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
    print(f"\nMissing required package: '{e.name}'")
    print("The virtual environment may not be activated. Run the appropriate command below:")
    print("[macOS / Linux] source .venv/bin/activate")
    print("[Windows]       .venv\\Scripts\\Activate.ps1")
    print("If the virtual environment is already active, ensure dependencies are installed:")
    print("pip install -r requirements.txt\n")
    sys.exit(1)

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg

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


def clean_val(val):
    if isinstance(val, str):
        val_stripped = val.strip()
        if val_stripped == "" or val_stripped.lower() in ("null", "none"):
            return None
    return val


def build_upsert_sql(table, cols, pk_col):
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk_col)
    return (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT ({pk_col}) DO UPDATE SET {update_clause}"
    )


def upsert_execute(cur, sql, rows, label, page_size=1000):
    execute_values(cur, sql, rows, page_size=page_size)
    print(f"  [OK]   {label} — {cur.rowcount} row(s) processed (UPSERT).")


def route_booking_id(booking_id, context):
    if booking_id.startswith('BK'):
        return booking_id, None
    elif booking_id.startswith('MT'):
        return None, booking_id
    else:
        raise ValueError(f"{context} contains unrecognised booking_id prefix: {booking_id}")


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
                raise ValueError(f"Data error: missing required station_id field. Raw data: {row}")

            yield (
                station_id,
                row.get('name'),
                row.get('lines') or [],
                row.get('is_interchange_metro', False),
                row.get('interchange_metro_lines') or [],
                False,
                None,
                json.dumps(row.get('adjacent_stations', []))
            )

    upsert_execute(cur, build_upsert_sql('metro_stations', cols, 'station_id'), generate_rows(data), 'metro_stations')


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")

    cols = [
        'station_id', 'name', 'lines',
        'is_interchange_national_rail', 'interchange_national_rail_lines',
        'is_interchange_metro', 'interchange_metro_station_id',
        'adjacent_stations'
    ]

    def generate_rows(station_data):
        for row in station_data:
            station_id = row.get('station_id')
            if not station_id:
                raise ValueError(f"Data error: missing required station_id field. Raw data: {row}")

            yield (
                station_id,
                row.get('name'),
                row.get('lines') or [],
                row.get('is_interchange_national_rail', False),
                row.get('interchange_national_rail_lines') or [],
                row.get('is_interchange_metro', False),
                clean_val(row.get('interchange_metro_station_id')),
                json.dumps(row.get('adjacent_stations', []))
            )

    upsert_execute(cur, build_upsert_sql('national_rail_stations', cols, 'station_id'), generate_rows(data), 'national_rail_stations')

    cur.execute("""
        UPDATE metro_stations ms
        SET interchange_national_rail_station_id = nrs.station_id,
            is_interchange_national_rail = TRUE
        FROM national_rail_stations nrs
        WHERE ms.station_id = nrs.interchange_metro_station_id
        AND ms.interchange_national_rail_station_id IS NULL;
    """)
    print(f"  [OK]   metro_stations FK linked — {cur.rowcount} row(s) updated.")


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

    def generate_rows(schedule_data):
        for row in schedule_data:
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')

            if not schedule_id or not origin_id or not dest_id:
                raise ValueError(f"Data error: missing required schedule or station ID. Raw data: {row}")

            yield (
                schedule_id,
                row.get('line'),
                row.get('direction'),
                origin_id,
                dest_id,
                json.dumps(row.get('stops_in_order', [])),
                clean_val(row.get('first_train_time')),
                clean_val(row.get('last_train_time')),
                json.dumps(row.get('travel_time_from_origin_min', {})),
                row.get('base_fare_usd'),
                row.get('per_stop_rate_usd'),
                row.get('frequency_min'),
                row.get('operates_on') or [],
            )

    upsert_execute(cur, build_upsert_sql('metro_schedules', cols, 'schedule_id'), generate_rows(data), 'metro_schedules')


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")

    cols = ['layout_id', 'layout_name', 'coaches']

    def generate_rows(layout_data):
        for row in layout_data:
            layout_id = row.get('layout_id')
            if not layout_id:
                raise ValueError(f"Data error: missing required layout_id field. Raw data: {row}")

            yield (
                layout_id,
                row.get('layout_name', 'Standard Template'),
                json.dumps(row.get('coaches') or [])
            )

    upsert_execute(cur, build_upsert_sql('national_rail_seat_layouts', cols, 'layout_id'), generate_rows(data), 'national_rail_seat_layouts', page_size=100)


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")

    schedule_to_layout = {}
    try:
        layouts_data = load("national_rail_seat_layouts.json")
        schedule_to_layout = {
            sl["schedule_id"]: sl["layout_id"]
            for sl in layouts_data
            if sl.get("schedule_id") and sl.get("layout_id")
        }
    except Exception as e:
        print(f"  [WARN] Could not load seat_layouts for lookup table; all schedules will use the default layout. Reason: {e}")

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
                raise ValueError(f"Data error: missing required schedule or station ID. Raw data: {row}")

            yield (
                schedule_id,
                row.get('line'),
                row.get('service_type') or 'normal',
                row.get('direction'),
                origin_id,
                dest_id,
                json.dumps(row.get('stops_in_order') or []),
                json.dumps(row.get('skip_stations') or []),
                json.dumps(row.get('travel_time_from_origin_min') or {}),
                clean_val(row.get('first_train_time')),
                clean_val(row.get('last_train_time')),
                json.dumps(row.get('fare_classes') or {}),
                row.get('frequency_min'),
                row.get('operates_on') or [],
                schedule_to_layout.get(schedule_id) or DEFAULT_LAYOUT_ID
            )

    upsert_execute(cur, build_upsert_sql('national_rail_schedules', cols, 'schedule_id'), generate_rows(data), 'national_rail_schedules')


def seed_users(cur):
    data = load("registered_users.json")

    u_cols = ['user_id', 'full_name', 'email', 'phone', 'date_of_birth', 'registered_at', 'is_active']

    def generate_users(user_data):
        for row in user_data:
            user_id = row.get('user_id')
            email = row.get('email')
            full_name = row.get('full_name')

            if not user_id or not email or not full_name:
                raise ValueError(f"Data error: missing user_id, full_name, or email. Raw data: {row}")

            yield (
                user_id,
                full_name,
                email,
                clean_val(row.get('phone')),
                clean_val(row.get('date_of_birth')),
                clean_val(row.get('registered_at')),
                row.get('is_active', True)
            )

    upsert_execute(cur, build_upsert_sql('users', u_cols, 'user_id'), generate_users(data), 'users')

    c_cols = ['user_id', 'stored_hash', 'secret_question', 'secret_answer_hash']

    def generate_credentials(user_data):
        for row in user_data:
            user_id = row.get('user_id')
            raw_password = row.get('password')
            secret_question = row.get('secret_question')
            raw_answer = row.get('secret_answer')

            if not user_id or not raw_password or not secret_question or not raw_answer:
                continue

            yield (
                user_id,
                ph.hash(raw_password),
                secret_question,
                ph.hash(raw_answer.strip().lower())# Normalise the answer to lowercase before hashing so that verification, the same hash and will all pass verification.
            )

    c_sql = build_upsert_sql('user_credential', c_cols, 'user_id') + ', updated_at = NOW()'
    upsert_execute(cur, c_sql, generate_credentials(data), 'user_credential', page_size=500)


def seed_national_rail_bookings(cur):
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

    def generate_bookings(booking_data):
        for row in booking_data:
            booking_id = row.get('booking_id')
            user_id = row.get('user_id')
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')

            if not all([booking_id, user_id, schedule_id, origin_id, dest_id]):
                raise ValueError(f"Data error: missing core booking or foreign key ID. Raw data: {row}")

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
                clean_val(row.get('coach')),
                clean_val(row.get('seat_id')),
                row.get('stops_travelled'),
                row.get('amount_usd'),
                row.get('status'),
                row.get('booked_at'),
                clean_val(row.get('travelled_at'))
            )

    upsert_execute(cur, build_upsert_sql('national_rail_bookings', cols, 'booking_id'), generate_bookings(data), 'national_rail_bookings')


def seed_metro_travels(cur):
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
            trip_id = row.get('trip_id')
            user_id = row.get('user_id')
            schedule_id = row.get('schedule_id')
            origin_id = row.get('origin_station_id')
            dest_id = row.get('destination_station_id')

            if not all([trip_id, user_id, schedule_id, origin_id, dest_id]):
                raise ValueError(f"Data error: missing primary key or foreign key ID in metro travel record. Raw data: {row}")

            yield (
                trip_id,
                user_id,
                schedule_id,
                origin_id,
                dest_id,
                clean_val(row.get('travel_date')),
                row.get('ticket_type', 'single'),
                clean_val(row.get('day_pass_ref')),
                row.get('stops_travelled'),
                row.get('amount_usd'),
                row.get('status'),
                clean_val(row.get('purchased_at')),
                clean_val(row.get('travelled_at'))
            )

    upsert_execute(cur, build_upsert_sql('metro_travels', cols, 'trip_id'), generate_travels(data), 'metro_travels')


def seed_payments(cur):
    data = load("payments.json")

    cols = [
        'payment_id', 'national_rail_booking_id', 'metro_travel_id',
        'amount_usd', 'method', 'status', 'paid_at'
    ]

    def generate_payments(payment_data):
        for row in payment_data:
            payment_id = row.get('payment_id')
            booking_id = row.get('booking_id')

            if not payment_id or not booking_id:
                raise ValueError(f"Data error: missing payment_id or corresponding booking_id. Raw data: {row}")

            nr_id, mt_id = route_booking_id(booking_id, 'Payments')

            yield (
                payment_id,
                nr_id,
                mt_id,
                row.get('amount_usd'),
                row.get('method'),
                row.get('status'),
                clean_val(row.get('paid_at'))
            )

    upsert_execute(cur, build_upsert_sql('payments', cols, 'payment_id'), generate_payments(data), 'payments')


def seed_feedback(cur):
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

            if not feedback_id or not user_id or not booking_id:
                raise ValueError(f"Data error: missing feedback_id, user_id, or booking_id. Raw data: {row}")

            nr_id, mt_id = route_booking_id(booking_id, 'Feedback')

            yield (
                feedback_id,
                nr_id,
                mt_id,
                user_id,
                row.get('rating'),
                clean_val(row.get('comment')),
                clean_val(row.get('submitted_at'))
            )

    upsert_execute(cur, build_upsert_sql('feedback', cols, 'feedback_id'), generate_feedback(data), 'feedback')


def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("\nSeeding tables (dependency order):")

        seed_metro_stations(cur)
        seed_national_rail_stations(cur)

        seed_metro_schedules(cur)
        seed_seat_layouts(cur)
        seed_national_rail_schedules(cur)

        seed_users(cur)

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