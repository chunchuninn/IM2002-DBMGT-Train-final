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
def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    
    cols = [
        'schedule_id', 'line', 'direction',
        'origin_station_id', 'destination_station_id',
        'stops_in_order', 'first_train_time', 'last_train_time',
        'travel_time_from_origin_min',
        'base_fare_usd', 'per_stop_rate_usd',   
        'frequency_min', 'operates_on'
    ]

    # 使用串流處理，避免班次過多導致記憶體溢出
    def generate_rows(schedule_data):
        for row in schedule_data:
            
            # 提早失敗防護，避免沒有填 station_id 導致 PK 是 NULL
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')
            
            if not schedule_id or not origin_id or not dest_id:
                raise ValueError(f"資料異常：缺少必要的排程或車站 ID。原始資料：{row}")
            
            # 序列化 JSONB 欄位
            stops_json = json.dumps(row.get('stops_in_order', []))
            travel_time_json = json.dumps(row.get('travel_time_from_origin_min', {}))

            yield (
                schedule_id,
                row.get('line'),
                row.get('direction'),
                origin_id,
                dest_id,
                stops_json,
                clean_val(row.get('first_train_time')),  # 防護空字串導致的 TIME 型態轉換錯誤
                clean_val(row.get('last_train_time')),   # 防護空字串
                travel_time_json,
                row.get('base_fare_usd'),        
                row.get('per_stop_rate_usd'),    
                row.get('frequency_min'),
                row.get('operates_on') or [],            # 防護明確的 null 導致違反 NOT NULL
            )

    # 確保 JSON 修改能覆寫舊資料 (UPSERT)
    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'schedule_id'])
    
    sql = f"""
        INSERT INTO metro_schedules ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (schedule_id) DO UPDATE
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_rows(data), page_size=1000)
    
    print(f"  [OK]   metro_schedules — {cur.rowcount} row(s) processed (UPSERT).")


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
    
    # ---------------------------------------------------------
    # 安全的反向查表 (Reverse Lookup)
    # ---------------------------------------------------------
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

    # 導入 Generator 串流處理，保護記憶體
    def generate_rows(schedule_data):
        for row in schedule_data:
            
            # 提早失敗防護：確保 PK 與 FK 存在
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


# ── Batch A: Users & Credentials (安全解耦) ──────────────────────────────────
def seed_users(cur):
    """
    匯入使用者與憑證資料。
    包含 OOM 防護 (Generator)、UPSERT 覆寫、嚴謹的憑證完整性檢查與 Fail-Fast 驗證。
    """
    data = load("registered_users.json")
    
    # ==========================================
    # 階段 1：處理 users 表 (一般個資)
    # ==========================================
    u_cols = ['user_id', 'full_name', 'email', 'phone', 'date_of_birth', 'registered_at', 'is_active']

    def generate_users(user_data):
        for row in user_data:
            user_id = row.get('user_id')
            email = row.get('email')
            full_name = row.get('full_name')
            
            # 提早失敗防護：絕對不允許缺少主鍵或核心個資
            if not user_id or not email or not full_name:
                raise ValueError(f"資料異常：缺少 user_id, full_name 或 email。原始資料：{row}")
                
            yield (
                user_id,
                full_name,
                email,
                clean_val(row.get('phone')),
                clean_val(row.get('date_of_birth')),
                clean_val(row.get('registered_at')),
                row.get('is_active', True)
            )

    # 組裝 users 的 UPSERT 語句
    u_update_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in u_cols if col != 'user_id'])
    u_sql = f"""
        INSERT INTO users ({', '.join(u_cols)})
        VALUES %s
        ON CONFLICT (user_id) DO UPDATE SET {u_update_clause}
    """
    execute_values(cur, u_sql, generate_users(data), page_size=1000)
    print(f"  [OK]   users — {cur.rowcount} row(s) processed (UPSERT).")


    # ==========================================
    # 階段 2：處理 user_credential 表 (高敏感資料)
    # ==========================================
    c_cols = ['user_id', 'stored_hash', 'secret_question', 'secret_answer_hash']

    def generate_credentials(user_data):
        for row in user_data:
            user_id = row.get('user_id')
            raw_password = row.get('password')
            secret_question = row.get('secret_question')
            raw_answer = row.get('secret_answer')

            # 嚴格的憑證完整性檢查：這三個欄位在 schema 中皆為 NOT NULL
            if not user_id or not raw_password or not secret_question or not raw_answer:
                # 缺乏任一憑證資料，則視為「無密碼使用者」(如 SSO)，安全跳過
                continue

            # 只有在此筆資料準備寫入時，才即時耗用 CPU 進行雜湊運算
            yield (
                user_id,
                ph.hash(raw_password),
                secret_question,
                ph.hash(raw_answer)
            )

    # 組裝 user_credential 的 UPSERT 語句
    c_update_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in c_cols if col != 'user_id'])
    # 加上 updated_at = NOW() 確保密碼更新時能留下紀錄
    c_sql = f"""
        INSERT INTO user_credential ({', '.join(c_cols)})
        VALUES %s
        ON CONFLICT (user_id) DO UPDATE 
        SET {c_update_clause}, updated_at = NOW()
    """
    execute_values(cur, c_sql, generate_credentials(data), page_size=500)
    print(f"  [OK]   user_credential — {cur.rowcount} row(s) processed (UPSERT).")


# ── Batch C: Transactions & Polymorphic ──────────────────────────────────────
def seed_national_rail_bookings(cur):
    """
    匯入台鐵訂單交易資料。
    包含 OOM 防護 (Generator)、UPSERT 狀態同步更新，以及嚴謹的核心鍵值 Fail-Fast 驗證。
    """
    data = load("bookings.json")
    
    cols = [
        'booking_id', 'user_id', 'schedule_id',
        'origin_station_id', 'destination_station_id',
        'travel_date', 'departure_time',
        'ticket_type', 'fare_class',
        'coach', 'seat_id',
        'stops_travelled',
        'amount_usd',
        'status', 'booked_at', 'travelled_at'
    ]

    # 使用 Generator 串流處理，避免交易資料庫過大導致記憶體溢出
    def generate_bookings(booking_data):
        for row in booking_data:
            
            # 提早失敗防護：訂單的主鍵與所有關聯外鍵絕對不能遺失
            booking_id = row.get('booking_id')
            user_id = row.get('user_id')
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')
            
            # 若任一核心 ID 缺失，立刻阻擋，避免拋出難以追蹤的 Foreign Key Violation
            if not all([booking_id, user_id, schedule_id, origin_id, dest_id]):
                raise ValueError(f"交易資料異常：缺少核心訂單或關聯 ID。原始資料：{row}")
            
            yield (
                booking_id,
                user_id,
                schedule_id,
                origin_id,
                dest_id,
                clean_val(row.get('travel_date')),
                clean_val(row.get('departure_time')),
                row.get('ticket_type'),
                row.get('fare_class'),
                clean_val(row.get('coach')),            # 退票或自由座可能為 null
                clean_val(row.get('seat_id')),          # 退票或自由座可能為 null
                row.get('stops_travelled'),
                row.get('amount_usd'),
                row.get('status'),
                row.get('booked_at'),
                clean_val(row.get('travelled_at'))      # 尚未搭乘或取消的訂單為 null
            )

    # 組裝 UPSERT 語句，確保 JSON 中的狀態改變 (如 confirmed -> cancelled) 能夠正確更新至 DB
    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'booking_id'])
    
    sql = f"""
        INSERT INTO national_rail_bookings ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (booking_id) DO UPDATE 
        SET {update_set_clause}
    """

    # 執行批次寫入，page_size=1000 確保無論幾十萬筆訂單，都會以 1000 筆為單位穩定寫入
    execute_values(cur, sql, generate_bookings(data), page_size=1000)
    
    print(f"  [OK]   national_rail_bookings — {cur.rowcount} row(s) processed (UPSERT).")


def seed_metro_travels(cur):
    """
    匯入捷運搭乘紀錄。
    包含 OOM 記憶體防護、核心 ID 的 Fail-Fast 驗證，以及 UPSERT 狀態同步更新。
    """
    data = load("metro_travel_history.json")
    
    cols = [
        'trip_id', 'user_id', 'schedule_id',
        'origin_station_id', 'destination_station_id',
        'travel_date', 'ticket_type', 'day_pass_ref',
        'stops_travelled', 'amount_usd',
        'status', 'purchased_at', 'travelled_at'
    ]

    def generate_travels(travel_data):
        for row in travel_data:
            # 提早失敗防護：確保所有的主鍵與關聯外鍵皆存在
            trip_id = row.get('trip_id')
            user_id = row.get('user_id')
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')
            
            if not all([trip_id, user_id, schedule_id, origin_id, dest_id]):
                raise ValueError(f"捷運搭乘紀錄異常：缺少核心主鍵或外鍵 ID。原始資料：{row}")

            yield (
                trip_id,
                user_id,
                schedule_id,
                origin_id,
                dest_id,
                clean_val(row.get('travel_date')),
                row.get('ticket_type', 'single'),
                clean_val(row.get('day_pass_ref')),     # 一日票參照可能為 null
                row.get('stops_travelled'),             # 購買一日票當下可能為 null
                row.get('amount_usd'),
                row.get('status'),
                clean_val(row.get('purchased_at')),     # 使用一日票搭乘時為 null
                clean_val(row.get('travelled_at'))      # 尚未搭乘或取消時為 null
            )

    # 組裝 UPSERT 語句，確保 status (如 completed / cancelled) 能覆寫更新
    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'trip_id'])
    sql = f"""
        INSERT INTO metro_travels ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (trip_id) DO UPDATE 
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_travels(data), page_size=1000)
    print(f"  [OK]   metro_travels — {cur.rowcount} row(s) processed (UPSERT).")


def seed_payments(cur):
    """
    匯入付款紀錄。
    包含多型關聯 (Polymorphic) 的嚴謹防護，確保絕對符合 Exclusive Arc 限制。
    """
    data = load("payments.json")
    
    cols = [
        'payment_id', 'national_rail_booking_id', 'metro_travel_id',
        'amount_usd', 'method', 'status', 'paid_at'
    ]

    def generate_payments(payment_data):
        for row in payment_data:
            payment_id = row.get('payment_id')
            booking_id = row.get('booking_id')
            
            # Fail-Fast 防護：付款 ID 與對應的訂單 ID 絕對不可少
            if not payment_id or not booking_id:
                raise ValueError(f"付款資料異常：缺少 payment_id 或對應的 booking_id。原始資料：{row}")

            nr_id, mt_id = None, None
            # 多型外鍵拆分路由
            if booking_id.startswith('BK'):
                nr_id = booking_id
            elif booking_id.startswith('MT'):
                mt_id = booking_id
            else:
                raise ValueError(f"Payments 包含無法識別的訂單前綴: {booking_id}")

            yield (
                payment_id,
                nr_id,
                mt_id,
                row.get('amount_usd'),
                row.get('method'),
                row.get('status'),
                clean_val(row.get('paid_at')) # pending/failed 狀態時可能為 null
            )

    # UPSERT 保證如果訂單退費 (status: paid -> refunded)，能即時更新資料庫狀態
    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'payment_id'])
    sql = f"""
        INSERT INTO payments ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (payment_id) DO UPDATE 
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_payments(data), page_size=1000)
    print(f"  [OK]   payments — {cur.rowcount} row(s) processed (UPSERT).")


def seed_feedback(cur):
    """
    匯入意見回饋紀錄。
    允許使用者修改回饋內容，重跑腳本即可自動套用 UPSERT 更新。
    """
    data = load("feedback.json")
    
    cols = [
        'feedback_id', 'national_rail_booking_id', 'metro_travel_id', 
        'user_id', 'rating', 'comment', 'submitted_at'
    ]

    def generate_feedback(feedback_data):
        for row in feedback_data:
            feedback_id = row.get('feedback_id')
            user_id = row.get('user_id')
            booking_id = row.get('booking_id')
            
            # 確保評價具有追溯性
            if not feedback_id or not user_id or not booking_id:
                raise ValueError(f"評價資料異常：缺少 feedback_id, user_id 或 booking_id。原始資料：{row}")

            nr_id, mt_id = None, None
            if booking_id.startswith('BK'):
                nr_id = booking_id
            elif booking_id.startswith('MT'):
                mt_id = booking_id
            else:
                raise ValueError(f"Feedback 包含無法識別的訂單前綴: {booking_id}")
                
            yield (
                feedback_id,
                nr_id,
                mt_id,
                user_id,
                row.get('rating'),
                clean_val(row.get('comment')),       # comment 允許為 null
                clean_val(row.get('submitted_at')) 
            )

    # UPSERT 保證使用者若修改了評價分數 (rating) 或是留下了新的評論 (comment)，皆能同步至 DB
    update_set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'feedback_id'])
    sql = f"""
        INSERT INTO feedback ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (feedback_id) DO UPDATE 
        SET {update_set_clause}
    """

    execute_values(cur, sql, generate_feedback(data), page_size=1000)
    print(f"  [OK]   feedback — {cur.rowcount} row(s) processed (UPSERT).")


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