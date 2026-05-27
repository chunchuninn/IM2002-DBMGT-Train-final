"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: all inserts use ON CONFLICT DO NOTHING.

Console output style: bilingual (English headline + Chinese detail).
"""

import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values, Json
from argon2 import PasswordHasher

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg

# Argon2id hasher — defaults are already argon2id with sensible parameters.
# 用於 password 與 secret_answer 的 hashing。
_HASHER = PasswordHasher()


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


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns rows attempted (len)."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    # 回傳實際嘗試插入的列數，方便 log 顯示進度
    return len(rows)


def _hash(plain: str) -> str:
    """Argon2id hash. 對 secret_answer 之前會先 lower()。"""
    return _HASHER.hash(plain)


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_users(cur):
    """
    [USERS + CREDENTIALS]
    一筆 JSON 拆兩張表：
      - users          : 公開資料 (姓名、email、電話、生日、註冊時間、是否啟用)
      - user_credential: 機敏資料 (password hash、secret_question、secret_answer hash)
    """
    data = load("registered_users.json")

    user_rows = []
    cred_rows = []
    for u in data:
        user_rows.append((
            u["user_id"],
            u["full_name"],
            u["email"],
            u.get("phone"),
            u.get("date_of_birth"),
            u.get("registered_at"),
            u.get("is_active", True),
        ))
        # 密碼直接 hash；secret_answer 先 lowercase 再 hash，
        # 之後驗證時也要對輸入做相同處理 (大小寫不敏感)。
        cred_rows.append((
            u["user_id"],
            _hash(u["password"]),
            u["secret_question"],
            _hash(u["secret_answer"].strip().lower()),
        ))

    n1 = insert_many(
        cur, "users",
        ["user_id", "full_name", "email", "phone", "date_of_birth",
         "registered_at", "is_active"],
        user_rows,
    )
    n2 = insert_many(
        cur, "user_credential",
        ["user_id", "stored_hash", "secret_question", "secret_answer_hash"],
        cred_rows,
    )
    print(f"  [users]            inserted {n1:>3} rows  (使用者公開資料)")
    print(f"  [user_credential]  inserted {n2:>3} rows  (密碼/秘密問答 hash)")


def seed_metro_stations(cur):
    """
    [METRO STATIONS]
    每一筆 metro 站點：
      - lines / interchange_metro_lines  → 直接以 Python list 傳給 TEXT[]
      - adjacent_stations                → 用 Json() 包裝為 JSONB
      - interchange_national_rail_station_id 此刻先放著，
        national_rail_stations 表之後才會插入；
        因為循環 FK 在同一個 transaction 內最後才會驗證，
        所以這裡可以先填 ID，commit 時整體一致即可。
    """
    data = load("metro_stations.json")

    rows = []
    for s in data:
        rows.append((
            s["station_id"],
            s["name"],
            s.get("lines", []),                        # TEXT[]
            s.get("is_interchange_metro", False),
            s.get("interchange_metro_lines", []),      # TEXT[]
            s.get("is_interchange_national_rail", False),
            s.get("interchange_national_rail_station_id"),
            Json(s.get("adjacent_stations", [])),      # JSONB
        ))

    n = insert_many(
        cur, "metro_stations",
        ["station_id", "name", "lines",
         "is_interchange_metro", "interchange_metro_lines",
         "is_interchange_national_rail", "interchange_national_rail_station_id",
         "adjacent_stations"],
        rows,
    )
    print(f"  [metro_stations]               inserted {n:>3} rows  (捷運站點 + JSONB 鄰接資訊)")


def seed_national_rail_stations(cur):
    """
    [NATIONAL RAIL STATIONS]
    結構同 metro_stations，FK 反方向指回 metro_stations。
    """
    data = load("national_rail_stations.json")

    rows = []
    for s in data:
        rows.append((
            s["station_id"],
            s["name"],
            s.get("lines", []),
            s.get("is_interchange_national_rail", False),
            s.get("interchange_national_rail_lines", []),
            s.get("is_interchange_metro", False),
            s.get("interchange_metro_station_id"),
            Json(s.get("adjacent_stations", [])),
        ))

    n = insert_many(
        cur, "national_rail_stations",
        ["station_id", "name", "lines",
         "is_interchange_national_rail", "interchange_national_rail_lines",
         "is_interchange_metro", "interchange_metro_station_id",
         "adjacent_stations"],
        rows,
    )
    print(f"  [national_rail_stations]       inserted {n:>3} rows  (國鐵站點 + JSONB 鄰接資訊)")


def seed_seat_layouts(cur):
    """
    [SEAT LAYOUTS]
    schema 已把 schedule_id 從 layouts 移除，改由 schedules.layout_id 反向 FK。
    這裡只負責灌 layout 本體。`coaches` 整個 list 用 Json() 包成 JSONB。
    JSON 裡每筆 layout 有自帶 schedule_id 欄位，但因為 schema 不存它，
    暫時無視；等 seed_national_rail_schedules 時會再回頭讀這個檔案做對應。
    """
    data = load("national_rail_seat_layouts.json")

    rows = []
    for layout in data:
        rows.append((
            layout["layout_id"],
            layout.get("layout_name", "Standard Template"),
            Json(layout["coaches"]),
        ))

    n = insert_many(
        cur, "national_rail_seat_layouts",
        ["layout_id", "layout_name", "coaches"],
        rows,
    )
    print(f"  [national_rail_seat_layouts]   inserted {n:>3} rows  (座位車型樣板)")


def seed_metro_schedules(cur):
    """
    [METRO SCHEDULES]
    捷運班表：
      - stops_in_order                → JSONB (站序陣列)
      - travel_time_from_origin_min   → JSONB (站到時長字典)
      - operates_on                   → TEXT[]
    base_fare_usd / per_stop_rate_usd 為單一票價 (無艙等)。
    """
    data = load("metro_schedules.json")

    rows = []
    for s in data:
        rows.append((
            s["schedule_id"],
            s["line"],
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            Json(s["stops_in_order"]),
            s["first_train_time"],
            s["last_train_time"],
            Json(s["travel_time_from_origin_min"]),
            s["base_fare_usd"],
            s["per_stop_rate_usd"],
            s["frequency_min"],
            s.get("operates_on", []),
        ))

    n = insert_many(
        cur, "metro_schedules",
        ["schedule_id", "line", "direction",
         "origin_station_id", "destination_station_id",
         "stops_in_order", "first_train_time", "last_train_time",
         "travel_time_from_origin_min",
         "base_fare_usd", "per_stop_rate_usd",
         "frequency_min", "operates_on"],
        rows,
    )
    print(f"  [metro_schedules]              inserted {n:>3} rows  (捷運班表 + JSONB 站序/時長)")


def seed_national_rail_schedules(cur):
    """
    [NATIONAL RAIL SCHEDULES]
    要從 seat_layouts JSON 反查每個班次對應的 layout_id：
      layout 物件: { "layout_id": "SL01", "schedule_id": "NR_SCH01", ... }
      → 建一個 schedule_id → layout_id 的對照表
    若某個 schedule 找不到對應 layout，會 raise (schema 要求 NOT NULL)。
    fare_classes / stops_in_order / travel_time_from_origin_min / skip_stations
    皆為 JSONB。
    """
    schedules = load("national_rail_schedules.json")
    layouts   = load("national_rail_seat_layouts.json")

    # 反查表: schedule_id → layout_id
    sched_to_layout = {l["schedule_id"]: l["layout_id"] for l in layouts}

    rows = []
    for s in schedules:
        layout_id = sched_to_layout.get(s["schedule_id"], "SL01")
        if s["schedule_id"] not in sched_to_layout:
            print(f"    ↳ {s['schedule_id']} 無專屬 layout，fallback → SL01")
            
        rows.append((
            s["schedule_id"],
            s["line"],
            s["service_type"],
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            Json(s["stops_in_order"]),
            Json(s.get("skip_stations", [])),
            Json(s["travel_time_from_origin_min"]),
            s["first_train_time"],
            s["last_train_time"],
            Json(s["fare_classes"]),
            s["frequency_min"],
            s.get("operates_on", []),
            layout_id,
        ))

    n = insert_many(
        cur, "national_rail_schedules",
        ["schedule_id", "line", "service_type", "direction",
         "origin_station_id", "destination_station_id",
         "stops_in_order", "skip_stations",
         "travel_time_from_origin_min",
         "first_train_time", "last_train_time",
         "fare_classes", "frequency_min", "operates_on", "layout_id"],
        rows,
    )
    print(f"  [national_rail_schedules]      inserted {n:>3} rows  (國鐵班表 + 反查 layout_id)")


def seed_national_rail_bookings(cur):
    """
    [NATIONAL RAIL BOOKINGS]
    直灌 JSON 全部欄位。注意 schema 防雙重訂位的 unique partial index
    會在 (schedule_id, travel_date, coach, seat_id) 衝突時拋錯；
    mock data 應該不會有重複，若有則 ON CONFLICT DO NOTHING 會吞掉。
    """
    data = load("bookings.json")

    rows = []
    for b in data:
        rows.append((
            b["booking_id"],
            b["user_id"],
            b["schedule_id"],
            b["origin_station_id"],
            b["destination_station_id"],
            b["travel_date"],
            b["departure_time"],
            b["ticket_type"],
            b["fare_class"],
            b.get("coach"),
            b.get("seat_id"),
            b["stops_travelled"],
            b["amount_usd"],
            b["status"],
            b["booked_at"],
            b.get("travelled_at"),
        ))

    n = insert_many(
        cur, "national_rail_bookings",
        ["booking_id", "user_id", "schedule_id",
         "origin_station_id", "destination_station_id",
         "travel_date", "departure_time",
         "ticket_type", "fare_class", "coach", "seat_id",
         "stops_travelled", "amount_usd", "status",
         "booked_at", "travelled_at"],
        rows,
    )
    print(f"  [national_rail_bookings]       inserted {n:>3} rows  (國鐵訂單)")


def seed_metro_travels(cur):
    """
    [METRO TRAVELS]
    schema 設計了三種情境 (single / 買 day_pass / 用 day_pass)，
    目前 mock data 全部都是 single (有 stops_travelled、purchased_at)。
    若未來 JSON 出現 day_pass 紀錄，這裡需要再加分支：
      - ticket_type='day_pass' 且無 day_pass_ref → 購買當下，stops_travelled=NULL
      - ticket_type='day_pass' 且有 day_pass_ref → 使用紀錄，amount_usd=0, purchased_at=NULL
    現階段一律按 single 情境處理。
    """
    data = load("metro_travel_history.json")

    rows = []
    for t in data:
        ticket_type = t["ticket_type"]
        day_pass_ref = t.get("day_pass_ref")  # 未來才會有

        rows.append((
            t["trip_id"],
            t["user_id"],
            t["schedule_id"],
            t["origin_station_id"],
            t["destination_station_id"],
            t["travel_date"],
            ticket_type,
            day_pass_ref,
            t.get("stops_travelled"),
            t["amount_usd"],
            t["status"],
            t.get("purchased_at"),
            t.get("travelled_at"),
        ))

    n = insert_many(
        cur, "metro_travels",
        ["trip_id", "user_id", "schedule_id",
         "origin_station_id", "destination_station_id",
         "travel_date", "ticket_type", "day_pass_ref",
         "stops_travelled", "amount_usd", "status",
         "purchased_at", "travelled_at"],
        rows,
    )
    print(f"  [metro_travels]                inserted {n:>3} rows  (捷運搭乘紀錄)")


def seed_payments(cur):
    """
    [PAYMENTS]
    payments.json 只有單一 booking_id 欄位，需依前綴分流：
      - BK 開頭 → national_rail_booking_id
      - MT 開頭 → metro_travel_id
    schema 的 exclusive arc CHECK 會強制兩者只能填一個。
    paid_at 與 status 的對應由 schema 的 chk_payment_status_time 把關。
    """
    data = load("payments.json")

    rows = []
    for p in data:
        ref = p["booking_id"]
        if ref.startswith("BK"):
            nr_id, mt_id = ref, None
        elif ref.startswith("MT"):
            nr_id, mt_id = None, ref
        else:
            raise ValueError(
                f"payments: 無法判斷 booking_id 屬於哪個網絡 → {ref} "
                f"(預期前綴為 BK 或 MT)"
            )

        rows.append((
            p["payment_id"],
            nr_id,
            mt_id,
            p["amount_usd"],
            p["method"],
            p["status"],
            p.get("paid_at"),
        ))

    n = insert_many(
        cur, "payments",
        ["payment_id",
         "national_rail_booking_id", "metro_travel_id",
         "amount_usd", "method", "status", "paid_at"],
        rows,
    )
    print(f"  [payments]                     inserted {n:>3} rows  (金流；依前綴分流)")


def seed_feedback(cur):
    """
    [FEEDBACK]
    與 payments 同樣的分流邏輯：BK → national_rail_booking_id, MT → metro_travel_id。
    schema 用兩個 partial unique index 保證一張訂單最多只能一筆 feedback。
    """
    data = load("feedback.json")

    rows = []
    for f in data:
        ref = f["booking_id"]
        if ref.startswith("BK"):
            nr_id, mt_id = ref, None
        elif ref.startswith("MT"):
            nr_id, mt_id = None, ref
        else:
            raise ValueError(
                f"feedback: 無法判斷 booking_id 屬於哪個網絡 → {ref} "
                f"(預期前綴為 BK 或 MT)"
            )

        rows.append((
            f["feedback_id"],
            nr_id,
            mt_id,
            f["user_id"],
            f["rating"],
            f.get("comment"),
            f.get("submitted_at"),
        ))

    n = insert_many(
        cur, "feedback",
        ["feedback_id",
         "national_rail_booking_id", "metro_travel_id",
         "user_id", "rating", "comment", "submitted_at"],
        rows,
    )
    print(f"  [feedback]                     inserted {n:>3} rows  (旅客回饋)")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...  連線中")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("\nSeeding tables in dependency order:  依相依順序灌入資料\n")

        # Batch A — 獨立表 + 循環外鍵的兩張站點表
        seed_users(cur)
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)

        # Batch B — schedules + seat layouts
        # 注意：layouts 必須先於 national_rail_schedules，因為 schedules.layout_id FK 過來
        seed_seat_layouts(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)

        # Batch C — bookings / travels / payments / feedback
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)

        conn.commit()
        print("\n[OK] All done. Database seeded successfully.  全部資料灌入完成")
    except Exception as e:
        conn.rollback()
        print(f"\n[FAIL] Error during seeding: {e}")
        print("       已 rollback，資料庫狀態未變動")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()