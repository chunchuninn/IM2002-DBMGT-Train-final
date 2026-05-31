"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
ph = PasswordHasher()


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# TODO: Implement the query_ and execute_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str = "",
    destination_id: str = "",
    travel_date: Optional[str] = None,
    **kwargs,  # Absorb unexpected parameters passed by the LLM
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.
    """
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.service_type,
            s.direction,
            s.origin_station_id,
            s.destination_station_id,
            s.stops_in_order,
            s.skip_stations,
            s.travel_time_from_origin_min,
            s.first_train_time::text,
            s.last_train_time::text,
            s.fare_classes,
            s.frequency_min,
            s.operates_on,
            orig.name  AS origin_name,
            dest.name  AS destination_name,
            -- Calculate number of stops between origin and destination
            (
                SELECT idx_dest.ord - idx_orig.ord
                FROM
                    jsonb_array_elements_text(s.stops_in_order)
                        WITH ORDINALITY AS idx_orig(station, ord)
                    ,
                    jsonb_array_elements_text(s.stops_in_order)
                        WITH ORDINALITY AS idx_dest(station, ord)
                WHERE idx_orig.station = %(origin_id)s
                  AND idx_dest.station = %(destination_id)s
            ) AS stops_travelled,
            -- Count seats already booked on the requested travel date
            COALESCE((
                SELECT COUNT(*)
                FROM national_rail_bookings b
                WHERE b.schedule_id  = s.schedule_id
                  AND b.travel_date  = %(travel_date)s::date
                  AND b.status IN ('confirmed', 'completed')
            ), 0) AS seats_booked
        FROM national_rail_schedules s
        JOIN national_rail_stations orig ON orig.station_id = s.origin_station_id
        JOIN national_rail_stations dest ON dest.station_id = s.destination_station_id
        WHERE
            -- origin must appear in stops_in_order
            s.stops_in_order @> %(origin_json)s::jsonb
            -- destination must appear in stops_in_order
            AND s.stops_in_order @> %(destination_json)s::jsonb
            -- origin index must come before destination index
            AND (
                SELECT ord FROM jsonb_array_elements_text(s.stops_in_order)
                    WITH ORDINALITY AS t(station, ord)
                WHERE t.station = %(origin_id)s
                LIMIT 1
            ) < (
                SELECT ord FROM jsonb_array_elements_text(s.stops_in_order)
                    WITH ORDINALITY AS t(station, ord)
                WHERE t.station = %(destination_id)s
                LIMIT 1
            )
        ORDER BY s.line, s.service_type, s.first_train_time
    """
    import json as _json
    params = {
        "origin_id":      origin_id,
        "destination_id": destination_id,
        "origin_json":    _json.dumps([origin_id]),
        "destination_json": _json.dumps([destination_id]),
        "travel_date":    travel_date or "9999-12-31",
    }
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """
    Calculate the fare for a national rail journey.
    fare_classes JSONB format: {"standard": {"base_fare_usd": 2.5, "per_stop_rate_usd": 1.5}, ...}
    """
    sql = """
        SELECT
            fare_classes -> %(fare_class)s ->> 'base_fare_usd'    AS base_fare_usd,
            fare_classes -> %(fare_class)s ->> 'per_stop_rate_usd' AS per_stop_rate_usd
        FROM national_rail_schedules
        WHERE schedule_id = %(schedule_id)s
          AND fare_classes ? %(fare_class)s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"schedule_id": schedule_id, "fare_class": fare_class})
            row = cur.fetchone()
            if not row:
                return None
            base      = float(row["base_fare_usd"])
            per_stop  = float(row["per_stop_rate_usd"])
            total     = round(base + per_stop * stops_travelled, 2)
            return {
                "fare_class":        fare_class,
                "base_fare_usd":     base,
                "per_stop_rate_usd": per_stop,
                "stops_travelled":   stops_travelled,
                "total_fare_usd":    total,
            }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.
    """
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.direction,
            s.origin_station_id,
            s.destination_station_id,
            s.stops_in_order,
            s.first_train_time::text,
            s.last_train_time::text,
            s.travel_time_from_origin_min,
            s.base_fare_usd,
            s.per_stop_rate_usd,
            s.frequency_min,
            s.operates_on,
            orig.name AS origin_name,
            dest.name AS destination_name,
            (
                SELECT idx_dest.ord - idx_orig.ord
                FROM
                    jsonb_array_elements_text(s.stops_in_order)
                        WITH ORDINALITY AS idx_orig(station, ord),
                    jsonb_array_elements_text(s.stops_in_order)
                        WITH ORDINALITY AS idx_dest(station, ord)
                WHERE idx_orig.station = %(origin_id)s
                  AND idx_dest.station = %(destination_id)s
            ) AS stops_travelled
        FROM metro_schedules s
        JOIN metro_stations orig ON orig.station_id = s.origin_station_id
        JOIN metro_stations dest ON dest.station_id = s.destination_station_id
        WHERE
            s.stops_in_order @> %(origin_json)s::jsonb
            AND s.stops_in_order @> %(destination_json)s::jsonb
            AND (
                SELECT ord FROM jsonb_array_elements_text(s.stops_in_order)
                    WITH ORDINALITY AS t(station, ord)
                WHERE t.station = %(origin_id)s LIMIT 1
            ) < (
                SELECT ord FROM jsonb_array_elements_text(s.stops_in_order)
                    WITH ORDINALITY AS t(station, ord)
                WHERE t.station = %(destination_id)s LIMIT 1
            )
        ORDER BY s.line, s.first_train_time
    """
    import json as _json
    params = {
        "origin_id":        origin_id,
        "destination_id":   destination_id,
        "origin_json":      _json.dumps([origin_id]),
        "destination_json": _json.dumps([destination_id]),
    }
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """Calculate the metro fare for a single-ticket journey."""
    sql = """
        SELECT base_fare_usd, per_stop_rate_usd
        FROM metro_schedules
        WHERE schedule_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return None
            base     = float(row["base_fare_usd"])
            per_stop = float(row["per_stop_rate_usd"])
            total    = round(base + per_stop * stops_travelled, 2)
            return {
                "base_fare_usd":     base,
                "per_stop_rate_usd": per_stop,
                "stops_travelled":   stops_travelled,
                "total_fare_usd":    total,
            }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.
    Expands all seats from the seat_layouts JSONB and excludes already-booked seats.
    """
    sql = """
        WITH layout AS (
            -- Retrieve the seat layout template for this schedule
            SELECT l.coaches
            FROM national_rail_schedules s
            JOIN national_rail_seat_layouts l ON l.layout_id = s.layout_id
            WHERE s.schedule_id = %(schedule_id)s
        ),
        all_seats AS (
            -- Expand coaches JSONB: coaches → each coach → seats array
            SELECT
                coach_obj ->> 'coach'      AS coach,
                coach_obj ->> 'fare_class' AS fare_class,
                seat ->> 'seat_id'         AS seat_id,
                (seat ->> 'row')::int      AS row,
                seat ->> 'column'          AS col
            FROM layout,
                 jsonb_array_elements(coaches)    AS coach_obj,
                 jsonb_array_elements(coach_obj -> 'seats') AS seat
        ),
        booked_seats AS (
            -- Seats already booked on this date (confirmed or completed)
            SELECT coach, seat_id
            FROM national_rail_bookings
            WHERE schedule_id = %(schedule_id)s
              AND travel_date = %(travel_date)s::date
              AND status IN ('confirmed', 'completed')
              AND coach   IS NOT NULL
              AND seat_id IS NOT NULL
        )
        SELECT
            a.coach,
            a.seat_id,
            a.row,
            a.col AS "column"
        FROM all_seats a
        LEFT JOIN booked_seats b
               ON b.coach = a.coach AND b.seat_id = a.seat_id
        WHERE a.fare_class = %(fare_class)s
          AND b.seat_id IS NULL          -- only seats not yet booked are available
        ORDER BY a.coach, a.row, a.col
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {
                "schedule_id": schedule_id,
                "travel_date": travel_date,
                "fare_class":  fare_class,
            })
            return [dict(row) for row in cur.fetchall()]


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.
    """
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT user_id, full_name, email, phone, date_of_birth, registered_at, is_active
        FROM users
        WHERE email = %s AND is_active = TRUE
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            return dict(row) if row else None


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).
    """
    nr_sql = """
        SELECT
            b.booking_id,
            b.travel_date,
            b.departure_time::text,
            b.ticket_type,
            b.fare_class,
            b.coach,
            b.seat_id,
            b.stops_travelled,
            b.amount_usd,
            b.status,
            b.booked_at,
            b.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name,
            s.line,
            s.service_type
        FROM national_rail_bookings b
        JOIN users u                    ON u.user_id   = b.user_id
        JOIN national_rail_stations orig ON orig.station_id = b.origin_station_id
        JOIN national_rail_stations dest ON dest.station_id = b.destination_station_id
        JOIN national_rail_schedules s   ON s.schedule_id   = b.schedule_id
        WHERE u.email = %s
        ORDER BY b.travel_date DESC, b.booked_at DESC
    """
    metro_sql = """
        SELECT
            t.trip_id,
            t.travel_date,
            t.ticket_type,
            t.stops_travelled,
            t.amount_usd,
            t.status,
            t.purchased_at,
            t.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name,
            s.line
        FROM metro_travels t
        JOIN users u              ON u.user_id   = t.user_id
        JOIN metro_stations orig  ON orig.station_id = t.origin_station_id
        JOIN metro_stations dest  ON dest.station_id = t.destination_station_id
        JOIN metro_schedules s    ON s.schedule_id   = t.schedule_id
        WHERE u.email = %s
        ORDER BY t.travel_date DESC, t.purchased_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(nr_sql, (user_email,))
            nr_rows = [dict(r) for r in cur.fetchall()]
            cur.execute(metro_sql, (user_email,))
            metro_rows = [dict(r) for r in cur.fetchall()]
    return {"national_rail": nr_rows, "metro": metro_rows}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT
            payment_id,
            national_rail_booking_id,
            metro_travel_id,
            amount_usd,
            method,
            status,
            paid_at
        FROM payments
        WHERE national_rail_booking_id = %(bid)s
           OR metro_travel_id          = %(bid)s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"bid": booking_id})
            row = cur.fetchone()
            return dict(row) if row else None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.
    """
    conn = _connect()
    conn.autocommit = False
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # 1. Fetch schedule info (stops_in_order, departure_time, fare_classes)
                cur.execute("""
                    SELECT stops_in_order, first_train_time, fare_classes
                    FROM national_rail_schedules
                    WHERE schedule_id = %s
                """, (schedule_id,))
                sched = cur.fetchone()
                if not sched:
                    return False, f"Schedule {schedule_id} not found."

                # 2. Calculate stops_travelled
                stops = sched["stops_in_order"]
                try:
                    orig_idx = stops.index(origin_station_id)
                    dest_idx = stops.index(destination_station_id)
                except ValueError:
                    return False, "Origin or destination not on this schedule."
                if orig_idx >= dest_idx:
                    return False, "Origin must come before destination on this schedule."
                stops_travelled = dest_idx - orig_idx

                # 3. Calculate fare
                fc = sched["fare_classes"].get(fare_class)
                if not fc:
                    return False, f"Fare class '{fare_class}' not available on this schedule."
                amount = round(
                    float(fc["base_fare_usd"]) + float(fc["per_stop_rate_usd"]) * stops_travelled,
                    2
                )

                # 4. Handle seat selection: auto-assign or specific seat
                coach_val = None
                seat_val  = None
                if seat_id and seat_id.lower() != "any":
                    # Verify the seat is not already booked
                    cur.execute("""
                        SELECT 1 FROM national_rail_bookings
                        WHERE schedule_id = %s
                          AND travel_date = %s::date
                          AND seat_id = %s
                          AND status IN ('confirmed', 'completed')
                    """, (schedule_id, travel_date, seat_id))
                    if cur.fetchone():
                        return False, f"Seat {seat_id} is already booked."
                    # Look up coach from seat layout
                    cur.execute("""
                        SELECT coach_obj ->> 'coach' AS coach
                        FROM national_rail_schedules s
                        JOIN national_rail_seat_layouts l ON l.layout_id = s.layout_id,
                             jsonb_array_elements(l.coaches) AS coach_obj,
                             jsonb_array_elements(coach_obj -> 'seats') AS seat
                        WHERE s.schedule_id = %s
                          AND seat ->> 'seat_id' = %s
                          AND coach_obj ->> 'fare_class' = %s
                    """, (schedule_id, seat_id, fare_class))
                    coach_row = cur.fetchone()
                    if not coach_row:
                        return False, f"Seat {seat_id} not found in {fare_class} class."
                    coach_val = coach_row["coach"]
                    seat_val  = seat_id
                else:
                    # auto-assign: find the first available seat
                    available = query_available_seats(schedule_id, travel_date, fare_class)
                    if not available:
                        return False, "No available seats for this journey."
                    chosen    = available[0]
                    coach_val = chosen["coach"]
                    seat_val  = chosen["seat_id"]

                # 5. Generate booking_id and insert
                booking_id = _gen_booking_id()
                cur.execute("""
                    INSERT INTO national_rail_bookings (
                        booking_id, user_id, schedule_id,
                        origin_station_id, destination_station_id,
                        travel_date, departure_time,
                        ticket_type, fare_class, coach, seat_id,
                        stops_travelled, amount_usd, status, booked_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s::date, %s,
                        %s, %s, %s, %s,
                        %s, %s, 'confirmed', NOW()
                    )
                """, (
                    booking_id, user_id, schedule_id,
                    origin_station_id, destination_station_id,
                    travel_date, sched["first_train_time"],
                    ticket_type, fare_class, coach_val, seat_val,
                    stops_travelled, amount_usd,
                ))

                # 6. Create payment record
                payment_id = _gen_payment_id()
                cur.execute("""
                    INSERT INTO payments (
                        payment_id, national_rail_booking_id,
                        amount_usd, method, status, paid_at
                    ) VALUES (%s, %s, %s, 'credit_card', 'paid', NOW())
                """, (payment_id, booking_id, amount_usd))

                return True, {
                    "booking_id":    booking_id,
                    "user_id":       user_id,
                    "schedule_id":   schedule_id,
                    "travel_date":   travel_date,
                    "fare_class":    fare_class,
                    "coach":         coach_val,
                    "seat_id":       seat_val,
                    "stops_travelled": stops_travelled,
                    "amount_usd":    amount_usd,
                    "status":        "confirmed",
                    "payment_id":    payment_id,
                }

    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.
    Refund policy:
      normal service  (RF001): >24h=100%, 3-24h=75%, 1-3h=50%, <1h=0%
      express service (RF002): >24h=100%, 1-24h=50%, <1h=0%
    """
    conn = _connect()
    conn.autocommit = False
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # 1. Fetch the booking
                cur.execute("""
                    SELECT b.booking_id, b.user_id, b.travel_date, b.departure_time,
                           b.amount_usd, b.status, s.service_type
                    FROM national_rail_bookings b
                    JOIN national_rail_schedules s ON s.schedule_id = b.schedule_id
                    WHERE b.booking_id = %s
                """, (booking_id,))
                booking = cur.fetchone()
                if not booking:
                    return False, f"Booking {booking_id} not found."
                if booking["user_id"] != user_id:
                    return False, "You can only cancel your own bookings."
                if booking["status"] == "cancelled":
                    return False, "This booking is already cancelled."
                if booking["status"] == "completed":
                    return False, "Cannot cancel a completed journey."

                # 2. Calculate refund percentage
                departure_dt = datetime.combine(
                    booking["travel_date"], booking["departure_time"]
                ).replace(tzinfo=timezone.utc)
                now          = datetime.now(timezone.utc)
                hours_until  = (departure_dt - now).total_seconds() / 3600

                svc = booking["service_type"]
                if svc == "normal":
                    if hours_until > 24:
                        pct, note = 1.00, "RF001: >24h before departure — 100% refund"
                    elif hours_until > 3:
                        pct, note = 0.75, "RF001: 3–24h before departure — 75% refund"
                    elif hours_until > 1:
                        pct, note = 0.50, "RF001: 1–3h before departure — 50% refund"
                    else:
                        pct, note = 0.00, "RF001: <1h before departure — no refund"
                else:  # express / limited_express
                    if hours_until > 24:
                        pct, note = 1.00, "RF002: >24h before departure — 100% refund"
                    elif hours_until > 1:
                        pct, note = 0.50, "RF002: 1–24h before departure — 50% refund"
                    else:
                        pct, note = 0.00, "RF002: <1h before departure — no refund"

                refund_amount = round(float(booking["amount_usd"]) * pct, 2)

                # 3. Update booking status to cancelled
                cur.execute("""
                    UPDATE national_rail_bookings
                    SET status = 'cancelled'
                    WHERE booking_id = %s
                """, (booking_id,))

                # 4. Update payment to refunded (if applicable)
                if pct > 0:
                    cur.execute("""
                        UPDATE payments
                        SET status  = 'refunded',
                            paid_at = NOW()
                        WHERE national_rail_booking_id = %s
                    """, (booking_id,))

                return True, {
                    "booking_id":       booking_id,
                    "status":           "cancelled",
                    "refund_amount_usd": refund_amount,
                    "refund_pct":       int(pct * 100),
                    "policy_note":      note,
                    "hours_until_departure": round(max(hours_until, 0), 1),
                }

    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    Returns (True, user_id) on success or (False, error_message) on failure.

    NOTE: passwords are stored as plain text here intentionally for teaching
    purposes. In production, replace with a salted hash (e.g. bcrypt).
    """
    # Hash passwords BEFORE opening a transaction to avoid holding DB locks
    # during CPU-intensive argon2 computation.
    stored_hash = ph.hash(password)
    secret_answer_hash = ph.hash(secret_answer.strip().lower())
    # secret_answer is lowercased for case-insensitive verification later.

    conn = _connect()
    conn.autocommit = False
    try:
        with conn:  # auto commit on success, rollback on exception
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # 1. Check if email already exists (including deactivated accounts)
                cur.execute(
                    "SELECT user_id, is_active FROM users WHERE email = %s",
                    (email,)
                )
                existing = cur.fetchone()
                if existing:
                    if existing["is_active"]:
                        return False, "This email is already registered."
                    else:
                        return False, "This account has been deactivated. Please contact support."

                # 2. Generate a thread-safe user_id using a PostgreSQL sequence.
                #    NEXTVAL is atomic — the database guarantees no two calls ever return
                #    the same number, even under high concurrency. No locks, no race conditions.
                cur.execute("SELECT NEXTVAL('user_id_seq')")
                new_num = cur.fetchone()["nextval"]
                user_id = f"RU{new_num:02d}"

                # 3. Insert basic profile into users table
                cur.execute("""
                    INSERT INTO users (user_id, full_name, email, date_of_birth, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                """, (
                    user_id,
                    f"{first_name} {surname}",
                    email,
                    f"{year_of_birth}-01-01",
                ))

                # 4. Insert hashed credentials into user_credential table.
                #    Passwords are hashed with argon2id — a memory-hard algorithm
                #    designed to resist brute-force attacks.
                cur.execute("""
                    INSERT INTO user_credential
                        (user_id, stored_hash, secret_question, secret_answer_hash)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, stored_hash, secret_question, secret_answer_hash))

        return True, user_id

    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # 1. Fetch user and their stored hash in one JOIN query
            cur.execute("""
                SELECT u.user_id, u.full_name, u.email, u.phone,
                       u.date_of_birth, u.is_active,
                       c.stored_hash
                FROM users u
                JOIN user_credential c ON u.user_id = c.user_id
                WHERE u.email = %s AND u.is_active = TRUE
            """, (email,))
            row = cur.fetchone()

            if not row:
                return None  # Email not found or account deactivated

            # 2. Verify password against stored argon2 hash
            try:
                ph.verify(row["stored_hash"], password)
            except VerifyMismatchError: # Catch specifically the "password mismatch" error
                return None  # Return None only if we are certain the password is wrong

            # 3. Split full_name into first_name and surname for the return dict
            parts = row["full_name"].split(" ", 1)
            first_name = parts[0]
            surname    = parts[1] if len(parts) > 1 else ""

            return {
                "user_id":       row["user_id"],
                "email":         row["email"],
                "full_name":     row["full_name"],
                "first_name":    first_name,
                "surname":       surname,
                "phone":         row["phone"],
                "date_of_birth": str(row["date_of_birth"]),
                "is_active":     row["is_active"],
            }

def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.secret_question
                FROM user_credential c
                JOIN users u ON c.user_id = u.user_id
                WHERE u.email = %s AND u.is_active = TRUE
            """, (email,))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.secret_answer_hash
                FROM user_credential c
                JOIN users u ON c.user_id = u.user_id
                WHERE u.email = %s AND u.is_active = TRUE
            """, (email,))
            row = cur.fetchone()
            if not row:
                return False

            # Verify against lowercased input for case-insensitive comparison
            try:
                ph.verify(row[0], answer.strip().lower())
                return True
            except Exception as e:
                print(f"[DEBUG verify_secret_answer] error: {e}")
                return False


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    with _connect() as conn:
        with conn.cursor() as cur:
            # 1. Look up user_id from email
            cur.execute(
                "SELECT user_id FROM users WHERE email = %s AND is_active = TRUE",
                (email,)
            )
            row = cur.fetchone()
            if not row:
                return False

            # 2. Hash new password and update credential table
            cur.execute("""
                UPDATE user_credential
                SET stored_hash = %s,
                    updated_at  = NOW()
                WHERE user_id = %s
            """, (ph.hash(new_password), row[0]))

            # 3. cur.rowcount tells us how many rows were actually updated by THIS cursor
            return cur.rowcount > 0


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]