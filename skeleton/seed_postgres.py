"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values
from argon2 import PasswordHasher

try:
    import psycopg2
    from psycopg2.extras import execute_values
    from argon2 import PasswordHasher
except ImportError as e:
    print(f"\n缺少必要套件 '{e.name}'")
    print("系統可能尚未啟動虛擬環境，請依照作業系統執行以下指令：")
    print("[macOS / Linux] source .venv/bin/activate")
    print("[Windows]       .venv\\Scripts\\Activate.ps1")
    print("若已啟動虛擬環境，請確認是否已安裝相依套件：")
    print("pip install -r requirements.txt\n")
    sys.exit(1)

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg

# 效能優化：開發環境播種專用的低成本雜湊參數 (加速 Seeding 過程)
ph = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows, pk_column, page_size=1000):
    if isinstance(rows, list) and len(rows) == 0:
        return 0

    update_cols = [col for col in columns if col != pk_column]
    
    if update_cols:
        update_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in update_cols])
        conflict_action = f"DO UPDATE SET {update_clause}"
    else:
        conflict_action = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT ({pk_column}) {conflict_action}"
    )
    
    execute_values(cur, sql, rows, page_size=page_size)
    
    return cur.rowcount

# 避免空值資料
def clean_val(val):
    if isinstance(val, str):
        val_stripped = val.strip()
        if val_stripped == "" or val_stripped.lower() in ("null", "none"):
            return None
    return val


# ── Batch A: Stations ────────────────────────────────────────────────────────
def seed_metro_stations(cur):
    data = load("metro_stations.json")
    
    cols = [
        'station_id', 'name', 'lines', 
        'is_interchange_metro', 'interchange_metro_lines', 
        'is_interchange_national_rail', 'interchange_national_rail_station_id',
        'adjacent_stations'
    ]

    def generate_rows(station_data):
        for row in station_data:
            
            station_id = row.get('station_id')
            if not station_id:
                raise ValueError(f"資料異常：缺少必要的 station_id 欄位。原始資料：{row}")
            
            adjacent_stations_json = json.dumps(row.get('adjacent_stations', []))
            
            yield (
                station_id,
                row.get('name'),
                row.get('lines') or [],
                row.get('is_interchange_metro', False),
                row.get('interchange_metro_lines') or [],
                False,  
                None,   
                adjacent_stations_json
            )

    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'station_id'])
    
    sql = f"""
        INSERT INTO metro_stations ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (station_id) DO UPDATE
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_rows(data), page_size=1000)
    
    print(f"  [OK]   metro_stations — {cur.rowcount} row(s) processed (UPSERT).")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    cols = [
        'station_id', 'name', 'lines', 
        'is_interchange_national_rail', 'interchange_national_rail_lines', 
        'is_interchange_metro', 'interchange_metro_station_id',
        'adjacent_stations'
    ]

    # 使用串流處理，避免資料過多記憶體溢出
    def generate_rows(station_data):
        for row in station_data:  
            
            # 提早失敗防護，避免沒有填 station_id 導致 PK 是 NULL
            station_id = row.get('station_id')
            if not station_id:
                raise ValueError(f"資料異常：缺少必要的 station_id 欄位。原始資料：{row}")
            
            # 序列化 JSONB 欄位
            adjacent_stations_json = json.dumps(row.get('adjacent_stations', []))
            
            yield (
                station_id,
                row.get('name'),
                row.get('lines') or [],  
                row.get('is_interchange_national_rail', False),
                row.get('interchange_national_rail_lines') or [],
                row.get('is_interchange_metro', False),
                clean_val(row.get('interchange_metro_station_id')),
                adjacent_stations_json
            )

    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'station_id'])
    
    sql = f"""
        INSERT INTO national_rail_stations ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (station_id) DO UPDATE
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_rows(data), page_size=1000)
    
    print(f"  [OK]   national_rail_stations — {cur.rowcount} row(s) processed (UPSERT).")

    cur.execute("""
        UPDATE metro_stations ms
        SET interchange_national_rail_station_id = nrs.station_id,
            is_interchange_national_rail = TRUE
        FROM national_rail_stations nrs
        WHERE ms.station_id = nrs.interchange_metro_station_id
        AND ms.interchange_national_rail_station_id IS NULL;
    """)
    print(f"  [OK]   metro_stations FK linked — {cur.rowcount} row(s) updated.")


# ── Batch B: Schedules & Layouts ─────────────────────────────────────────────
def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    
    # 安全的反向查表 (Reverse Lookup)
    schedule_to_layout = {}
    try:
        layouts_data = load("national_rail_seat_layouts.json")
        schedule_to_layout = {
            sl["schedule_id"]: sl["layout_id"]
            for sl in layouts_data
            if sl.get("schedule_id") and sl.get("layout_id")
        }
    except Exception as e:
        print(f"  [WARN] 無法載入 seat_layouts 建立對照表，將全數使用預設版型。原因: {e}")

    DEFAULT_LAYOUT_ID = "SL01"

    cols = [
        'schedule_id', 'line', 'service_type', 'direction',
        'origin_station_id', 'destination_station_id',
        'stops_in_order', 'skip_stations', 'travel_time_from_origin_min',
        'first_train_time', 'last_train_time',
        'fare_classes', 'frequency_min', 'operates_on',
        'layout_id'
    ]

    def generate_rows(schedule_data):
        for row in schedule_data:
            
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')
            
            if not schedule_id or not origin_id or not dest_id:
                raise ValueError(f"資料異常：缺少必要的排程或車站 ID。原始資料：{row}")

            # Layout 查找與 Fallback
            layout_id = schedule_to_layout.get(schedule_id)
            if not layout_id:
                layout_id = DEFAULT_LAYOUT_ID
                # 只有在明確缺漏時才印出警告，避免洗版
                # print(f"  [WARN] schedule_id='{schedule_id}' 無對應 layout，使用預設 '{DEFAULT_LAYOUT_ID}'。")

            # JSONB 安全序列化防護 (確保不會產生 "null" 字串)
            stops_json = json.dumps(row.get('stops_in_order') or [])
            skip_json = json.dumps(row.get('skip_stations') or [])
            travel_time_json = json.dumps(row.get('travel_time_from_origin_min') or {})
            fare_json = json.dumps(row.get('fare_classes') or {})

            yield (
                schedule_id,
                row.get('line'),
                row.get('service_type') or 'normal',  
                row.get('direction'),
                origin_id,
                dest_id,
                stops_json,
                skip_json,
                travel_time_json,
                clean_val(row.get('first_train_time')),  
                clean_val(row.get('last_train_time')),   
                fare_json,
                row.get('frequency_min'),
                row.get('operates_on') or [],            
                layout_id
            )

    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'schedule_id'])
    
    sql = f"""
        INSERT INTO national_rail_schedules ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (schedule_id) DO UPDATE
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_rows(data), page_size=1000)
    
    print(f"  [OK]   national_rail_schedules — {cur.rowcount} row(s) processed (UPSERT).")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    
    cols = ['layout_id', 'layout_name', 'coaches']

    def generate_rows(layout_data):
        for row in layout_data:
            
            layout_id = row.get('layout_id')
            if not layout_id:
                raise ValueError(f"資料異常：缺少必要的 layout_id 欄位。原始資料：{row}")
            
            coaches_raw = row.get('coaches') or []
            coaches_json = json.dumps(coaches_raw)
            
            yield (
                layout_id,
                row.get('layout_name', 'Standard Template'),  
                coaches_json
            )

    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'layout_id'])
    
    sql = f"""
        INSERT INTO national_rail_seat_layouts ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (layout_id) DO UPDATE
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_rows(data), page_size=100)
    
    print(f"  [OK]   national_rail_seat_layouts — {cur.rowcount} row(s) processed (UPSERT).")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")

    # ── 修正：national_rail_schedules.json 不含 layout_id，
    #    但 national_rail_seat_layouts.json 含有 schedule_id。
    #    從 layouts 反向建立對照字典：{ schedule_id → layout_id }
    layouts_data      = load("national_rail_seat_layouts.json")
    schedule_to_layout = {
        sl["schedule_id"]: sl["layout_id"]
        for sl in layouts_data
        if sl.get("schedule_id")
    }

    rows = []
    for row in data:
        schedule_id = row.get('schedule_id')

        # 查找對應的 layout_id
        # 若查無對應（如 NR_SCH05），fallback 至 SL01 預設標準車型
        # 這符合 1:N 共享佈局架構的設計意圖：多個班次可共用同一套車廂樣板
        DEFAULT_LAYOUT_ID = "SL01"
        layout_id = schedule_to_layout.get(schedule_id)
        if layout_id is None:
            layout_id = DEFAULT_LAYOUT_ID
            print(f"  [WARN] schedule_id='{schedule_id}' 無對應 layout，"
                f"自動 fallback 至預設佈局 '{DEFAULT_LAYOUT_ID}'。")

        stops_json       = json.dumps(row.get('stops_in_order', []))
        skip_json        = json.dumps(row.get('skip_stations', []))
        travel_time_json = json.dumps(row.get('travel_time_from_origin_min', {}))
        fare_json        = json.dumps(row.get('fare_classes', {}))

        rows.append((
            schedule_id,
            row.get('line'),
            row.get('service_type', 'normal'),
            row.get('direction'),
            row.get('origin_station_id'),
            row.get('destination_station_id'),
            stops_json,
            skip_json,
            travel_time_json,
            row.get('first_train_time'),
            row.get('last_train_time'),
            fare_json,
            row.get('frequency_min'),
            row.get('operates_on', []),
            layout_id,      # 從反向字典查找，不再依賴 JSON 中不存在的欄位
        ))

    cols = [
        'schedule_id', 'line', 'service_type', 'direction',
        'origin_station_id', 'destination_station_id',
        'stops_in_order', 'skip_stations', 'travel_time_from_origin_min',
        'first_train_time', 'last_train_time',
        'fare_classes', 'frequency_min', 'operates_on',
        'layout_id',
    ]
    count = insert_many(cur, "national_rail_schedules", cols, rows, "schedule_id")
    print(f"  [OK]   national_rail_schedules — {count} row(s) processed.")


# ── Batch A: Users & Credentials (安全解耦) ──────────────────────────────────
def seed_users(cur):
    data = load("registered_users.json")
    user_rows = []
    cred_rows = []

    for row in data:
        user_id     = row.get('user_id')
        raw_password = row.get('password')
        raw_answer   = row.get('secret_answer')

        hashed_password = ph.hash(raw_password) if raw_password else None
        hashed_answer   = ph.hash(raw_answer)   if raw_answer   else None

        # Bug 3 修正：users 表不含 secret_question / secret_answer
        user_rows.append((
            user_id,
            row.get('full_name'),
            row.get('email'),
            clean_val(row.get('phone')),
            clean_val(row.get('date_of_birth')),
            row.get('registered_at'),
            row.get('is_active', True),
        ))

        # ✅ Bug 3 修正：user_credential 需要 stored_hash + secret_question + secret_answer_hash
        if hashed_password:
            cred_rows.append((
                user_id,
                hashed_password,
                row.get('secret_question'),
                hashed_answer,
            ))

    u_cols = ['user_id', 'full_name', 'email', 'phone', 'date_of_birth',
              'registered_at', 'is_active']
    c_cols = ['user_id', 'stored_hash', 'secret_question', 'secret_answer_hash']

    u_count = insert_many(cur, "users", u_cols, user_rows, "user_id")
    print(f"  [OK]   users — {u_count} row(s) processed.")

    # ✅ Bug 3 修正：正確表名 user_credential（非 table_credential）
    c_count = insert_many(cur, "user_credential", c_cols, cred_rows, "user_id")
    print(f"  [OK]   user_credential — {c_count} row(s) processed.")


# ── Batch C: Transactions & Polymorphic ──────────────────────────────────────
def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    rows = []
    for row in data:
        # ✅ Bug 4 修正：使用 JSON 中實際存在的 key，對應 schema 正確欄位名稱
        rows.append((
            row.get('booking_id'),
            row.get('user_id'),
            row.get('schedule_id'),
            row.get('origin_station_id'),
            row.get('destination_station_id'),
            clean_val(row.get('travel_date')),
            clean_val(row.get('departure_time')),
            row.get('ticket_type'),                 # ✅ 補上 ticket_type
            row.get('fare_class'),
            clean_val(row.get('coach')),            # ✅ coach（非 coach_number）
            clean_val(row.get('seat_id')),          # ✅ seat_id（非 seat_number）
            row.get('stops_travelled'),             # ✅ 補上 stops_travelled
            row.get('amount_usd'),                  # ✅ amount_usd（非 price）
            row.get('status'),
            row.get('booked_at'),
            clean_val(row.get('travelled_at')),     # ✅ 補上 travelled_at
        ))
    cols = [
        'booking_id', 'user_id', 'schedule_id',
        'origin_station_id', 'destination_station_id',
        'travel_date', 'departure_time',
        'ticket_type', 'fare_class',
        'coach', 'seat_id',                         # ✅ 正確欄位名稱
        'stops_travelled',
        'amount_usd',                               # ✅ 正確欄位名稱
        'status', 'booked_at', 'travelled_at',
    ]
    count = insert_many(cur, "national_rail_bookings", cols, rows, "booking_id")
    print(f"  [OK]   national_rail_bookings — {count} row(s) processed.")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    rows = []
    for row in data:
        # ✅ Bug 5 修正：使用 JSON 中實際存在的 key，補齊所有 schema 欄位
        rows.append((
            row.get('trip_id'),
            row.get('user_id'),
            row.get('schedule_id'),                 # ✅ 補上 schedule_id
            row.get('origin_station_id'),           # ✅ origin（非 entry_station_id）
            row.get('destination_station_id'),      # ✅ destination（非 exit_station_id）
            clean_val(row.get('travel_date')),      # ✅ 補上 travel_date
            row.get('ticket_type', 'single'),
            clean_val(row.get('day_pass_ref')),     # ✅ 補上 day_pass_ref
            row.get('stops_travelled'),             # ✅ 補上 stops_travelled
            row.get('amount_usd'),                  # ✅ amount_usd（非 fare）
            row.get('status'),
            clean_val(row.get('purchased_at')),     # ✅ purchased_at（非 entry_time）
            clean_val(row.get('travelled_at')),     # ✅ travelled_at（非 exit_time）
        ))
    cols = [
        'trip_id', 'user_id', 'schedule_id',
        'origin_station_id', 'destination_station_id',
        'travel_date', 'ticket_type', 'day_pass_ref',
        'stops_travelled', 'amount_usd',
        'status', 'purchased_at', 'travelled_at',
    ]
    count = insert_many(cur, "metro_travels", cols, rows, "trip_id")
    print(f"  [OK]   metro_travels — {count} row(s) processed.")


def seed_payments(cur):
    data = load("payments.json")
    rows = []
    for row in data:
        booking_id = row.get('booking_id', '')
        nr_id, mt_id = None, None

        if booking_id.startswith('BK'):
            nr_id = booking_id
        elif booking_id.startswith('MT'):
            mt_id = booking_id
        else:
            raise ValueError(f"Payments 包含無法識別的訂單前綴: {booking_id}")

        rows.append((
            row.get('payment_id'),
            nr_id,
            mt_id,
            row.get('amount_usd'),          # ✅ Bug 6 修正：amount_usd（非 amount）
            row.get('method'),              # ✅ Bug 6 修正：method（非 payment_method）
            row.get('status'),              # ✅ Bug 6 修正：status（非 payment_status）
            clean_val(row.get('paid_at')),  # ✅ Bug 6 修正：paid_at（非 transaction_date）
        ))
    cols = [
        'payment_id', 'national_rail_booking_id', 'metro_travel_id',
        'amount_usd', 'method', 'status', 'paid_at',  # ✅ Bug 6 修正：正確欄位名稱
    ]
    count = insert_many(cur, "payments", cols, rows, "payment_id")
    print(f"  [OK]   payments — {count} row(s) processed.")


def seed_feedback(cur):
    data = load("feedback.json")
    rows = []
    for row in data:
        booking_id = row.get('booking_id', '')
        nr_id, mt_id = None, None
        
        # ✅ 多型關聯嚴格檢查
        if booking_id.startswith('BK'):
            nr_id = booking_id
        elif booking_id.startswith('MT'):
            mt_id = booking_id
        else:
            raise ValueError(f"Feedback 包含無法識別的訂單前綴: {booking_id}")
            
        rows.append((
            row.get('feedback_id'),
            nr_id,
            mt_id,
            row.get('user_id'),
            row.get('rating'),
            clean_val(row.get('comment')),
            row.get('submitted_at')
        ))
    cols = ['feedback_id', 'national_rail_booking_id', 'metro_travel_id', 
            'user_id', 'rating', 'comment', 'submitted_at']
    count = insert_many(cur, "feedback", cols, rows, "feedback_id")
    print(f"  [OK]   feedback — {count} row(s) processed.")


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("\nSeeding tables (dependency order):")

        # ── Batch A: Stations ─────────────────────────────────────────────
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)

        # ── Batch B: Schedules & Layouts ──────────────────────────────────
        seed_metro_schedules(cur)
        seed_seat_layouts(cur)
        seed_national_rail_schedules(cur)

        # ── Batch A: Users（與車站無關，可獨立）───────────────────────────
        seed_users(cur)

        # ── Batch C: Transactions ─────────────────────────────────────────
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)

        conn.commit()
        print("\nAll done. Database seeded successfully.")

    except Exception as e:
        conn.rollback()
        print(f"\nError during seeding — transaction rolled back.\n    {type(e).__name__}: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()