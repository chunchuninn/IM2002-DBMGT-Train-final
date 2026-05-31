-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
--
--  Start from the mock data in train-mock-data/:
--    metro_stations.json, national_rail_stations.json
--    metro_schedules.json, national_rail_schedules.json
--    national_rail_seat_layouts.json
--    registered_users.json
--    bookings.json, metro_travel_history.json
--    payments.json, feedback.json
--
--  Think about:
--    - What tables do you need?
--    - What columns and data types?
--    - Which fields are primary keys? Which are foreign keys?
--    - What constraints make sense?
--
--  Apply your schema with:
--    docker-compose down -v && docker-compose up -d
-- ============================================================


-- ============================================================
-- SECTION 0 — DROP ALL TABLES
-- Dependent entities (Batch C) are dropped first, dependencies (Batch A) are dropped last.
-- CASCADE ensures that cross-table FK constraints are cleared together.
-- ============================================================

DROP TABLE IF EXISTS feedback                    CASCADE;
DROP TABLE IF EXISTS payments                    CASCADE;
DROP TABLE IF EXISTS metro_travels               CASCADE;
DROP TABLE IF EXISTS national_rail_bookings      CASCADE;
DROP TABLE IF EXISTS national_rail_seat_layouts  CASCADE;
DROP TABLE IF EXISTS national_rail_schedules     CASCADE;
DROP TABLE IF EXISTS metro_schedules             CASCADE;
DROP TABLE IF EXISTS national_rail_stations      CASCADE;
DROP TABLE IF EXISTS metro_stations              CASCADE;
DROP TABLE IF EXISTS table_credential            CASCADE;
DROP TABLE IF EXISTS users                       CASCADE;


-- ============================================================
-- SECTION 1 — BATCH A: Users & Stations
-- ============================================================

-- ------------------------------------------------------------
-- 1.1 users
-- password, secret_answer hashed via argon2id, stored in user_credential
-- ------------------------------------------------------------
-- User ID sequence: thread-safe auto-incrementing counter for generating unique user_ids.
-- NEXTVAL('user_id_seq') is atomic — the database guarantees no two concurrent
-- registrations ever receive the same number, eliminating race conditions entirely.
-- Unlike MAX(id)+1 in Python, sequences operate outside transaction boundaries,
-- so even a rolled-back registration will not reuse its number.
CREATE SEQUENCE IF NOT EXISTS user_id_seq START 21;

CREATE TABLE users (
    user_id          VARCHAR(20)   PRIMARY KEY,
    full_name        VARCHAR(255)  NOT NULL,
    email            VARCHAR(255) NOT NULL UNIQUE CHECK (email LIKE '%@%'),
    phone            VARCHAR(20),
    date_of_birth    DATE,
    registered_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE TABLE user_credential (
    user_id              VARCHAR(20)   PRIMARY KEY,
    stored_hash          VARCHAR(255)  NOT NULL,        -- Store the complete argon2id hash string
    secret_question      TEXT          NOT NULL,
    secret_answer_hash   VARCHAR(255)  NOT NULL,
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_credential_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE          -- Automatically delete credentials when user is deleted
);


-- ------------------------------------------------------------
-- 1.2 metro_stations
-- Circular foreign key with national_rail_stations
-- adjacent_stations will be converted to edges between nodes in Neo4j
-- The FK for interchange_national_rail_station_id is added after both tables are created
-- ------------------------------------------------------------
CREATE TABLE metro_stations (
    station_id                           VARCHAR(20)   PRIMARY KEY,
    name                                 VARCHAR(255)  NOT NULL,
    lines                                TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_metro                 BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_metro_lines              TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_national_rail         BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_national_rail_station_id VARCHAR(20),                            -- FK see ALTER TABLE below
    adjacent_stations                    JSONB         NOT NULL DEFAULT '[]',   -- Store adjacent stations info as JSONB for backup
    
    -- As long as interchange_national_rail_station_id is not NULL, is_interchange_national_rail should be TRUE
    CONSTRAINT chk_ms_interchange_consistency CHECK (
        (is_interchange_national_rail = TRUE AND interchange_national_rail_station_id IS NOT NULL) OR
        (is_interchange_national_rail = FALSE AND interchange_national_rail_station_id IS NULL)
    )
);


-- ------------------------------------------------------------
-- 1.3 national_rail_stations
-- ------------------------------------------------------------
CREATE TABLE national_rail_stations (
    station_id                       VARCHAR(20)   PRIMARY KEY,
    name                             VARCHAR(255)  NOT NULL,
    lines                            TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_national_rail     BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_national_rail_lines  TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_metro             BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_metro_station_id     VARCHAR(20),             
    adjacent_stations                JSONB         NOT NULL DEFAULT '[]',

    CONSTRAINT chk_nr_interchange_consistency CHECK (
        (is_interchange_metro = TRUE AND interchange_metro_station_id IS NOT NULL) OR
        (is_interchange_metro = FALSE AND interchange_metro_station_id IS NULL)
    )
);


-- ------------------------------------------------------------
-- 1.4 Cross-network circular foreign keys
-- ON DELETE SET NULL: When an interchange station is deleted, set the field to NULL instead of throwing an error,
--                    retaining station records and avoiding cascading deletion of the entire station data.
-- ON UPDATE CASCADE: Automatically sync child tables when the primary key is updated.
-- ------------------------------------------------------------
ALTER TABLE metro_stations
    ADD CONSTRAINT fk_metro_interchange_national_rail
    FOREIGN KEY (interchange_national_rail_station_id)
    REFERENCES national_rail_stations (station_id)
    ON DELETE SET NULL
    ON UPDATE CASCADE;

ALTER TABLE national_rail_stations
    ADD CONSTRAINT fk_national_rail_interchange_metro
    FOREIGN KEY (interchange_metro_station_id)
    REFERENCES metro_stations (station_id)
    ON DELETE SET NULL
    ON UPDATE CASCADE;


-- ============================================================
-- SECTION 2 — BATCH B: Schedules & Seat Layouts
-- ============================================================

-- ------------------------------------------------------------
-- 2.1 metro_schedules
-- ------------------------------------------------------------
CREATE TABLE metro_schedules (
    schedule_id                  VARCHAR(20)     PRIMARY KEY,
    line                         VARCHAR(20)     NOT NULL,
    direction                    VARCHAR(20)     NOT NULL CHECK (direction IN ('northbound', 'southbound', 'eastbound', 'westbound')),
    origin_station_id            VARCHAR(20)     NOT NULL,
    destination_station_id       VARCHAR(20)     NOT NULL,
    stops_in_order               JSONB           NOT NULL,   -- e.g. ["MS20","MS05",...]
    first_train_time             TIME            NOT NULL,
    last_train_time              TIME            NOT NULL,
    travel_time_from_origin_min  JSONB           NOT NULL,   -- e.g. {"MS20":0,"MS05":2,...}
    base_fare_usd                NUMERIC(10,2)   NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd            NUMERIC(10,2)   NOT NULL CHECK (per_stop_rate_usd >= 0),
    frequency_min                SMALLINT        NOT NULL CHECK (frequency_min > 0),
    operates_on                  TEXT[]          NOT NULL DEFAULT '{}',

    CONSTRAINT fk_metro_sch_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES metro_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_metro_sch_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES metro_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- ------------------------------------------------------------
-- 2.2 national_rail_seat_layouts
-- coaches is a deep nested array (coach -> seat list), using JSONB.
-- schedule_id UNIQUE: Forces a schedule to correspond to only one seat layout.
-- ON DELETE CASCADE: When a schedule is cancelled, the corresponding layout is deleted synchronously.
-- ------------------------------------------------------------
CREATE TABLE national_rail_seat_layouts (
    layout_id    VARCHAR(20)  PRIMARY KEY,

    -- Removed schedule_id to avoid creating circular dependencies
    layout_name  VARCHAR(100) NOT NULL DEFAULT 'Standard Template',
    coaches      JSONB        NOT NULL,

    CONSTRAINT chk_coaches_is_array 
        CHECK (jsonb_typeof(coaches) = 'array')
);


-- ------------------------------------------------------------
-- 2.3 national_rail_schedules
-- ------------------------------------------------------------
CREATE TABLE national_rail_schedules (
    schedule_id                  VARCHAR(20)     PRIMARY KEY,
    line                         VARCHAR(20)     NOT NULL,
    service_type                 VARCHAR(30)     NOT NULL CHECK (service_type IN ('normal', 'express', 'limited_express')),
    direction                    VARCHAR(20)     NOT NULL CHECK (direction IN ('northbound', 'southbound', 'eastbound', 'westbound')),
    origin_station_id            VARCHAR(20)     NOT NULL,
    destination_station_id       VARCHAR(20)     NOT NULL,
    stops_in_order               JSONB           NOT NULL,   
    
    -- Record of skipped stations for express trains, must not be NULL, default empty array 
    skip_stations                JSONB           NOT NULL DEFAULT '[]',

    travel_time_from_origin_min  JSONB           NOT NULL,
    first_train_time             TIME            NOT NULL,
    last_train_time              TIME            NOT NULL,
    fare_classes                 JSONB           NOT NULL,   
    frequency_min                SMALLINT        NOT NULL CHECK (frequency_min > 0),
    operates_on                  TEXT[]          NOT NULL DEFAULT '{}',

    -- Foreign key from schedule pointing to national_rail_seat_layouts, using 1:N shared train model architecture
    layout_id                    VARCHAR(20)     NOT NULL,

    -- Origin station foreign key: Requires existence in station master table, operating stations cannot be easily deleted (RESTRICT)
    CONSTRAINT fk_nr_sch_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- Destination station foreign key
    CONSTRAINT fk_nr_sch_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- Seat layout template foreign key: Refuses deletion of the template as long as schedules still use this seat model
    CONSTRAINT fk_nr_sch_layout
        FOREIGN KEY (layout_id)
        REFERENCES national_rail_seat_layouts (layout_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);


-- ============================================================
-- SECTION 3 — BATCH C: Bookings, Travels, Payments, Feedback
-- ============================================================

-- ------------------------------------------------------------
-- 3.1 national_rail_bookings
-- ------------------------------------------------------------
CREATE TABLE national_rail_bookings (
    booking_id              VARCHAR(20)     PRIMARY KEY,
    user_id                 VARCHAR(20)     NOT NULL,
    schedule_id             VARCHAR(20)     NOT NULL,
    origin_station_id       VARCHAR(20)     NOT NULL,
    destination_station_id  VARCHAR(20)     NOT NULL,
    travel_date             DATE            NOT NULL,
    departure_time          TIME            NOT NULL,
    ticket_type             VARCHAR(30)     NOT NULL CHECK (ticket_type IN ('single', 'return', 'season')),
    fare_class              VARCHAR(20)     NOT NULL CHECK (fare_class IN ('standard', 'first')),
    coach                   VARCHAR(10),
    seat_id                 VARCHAR(10),
    stops_travelled         SMALLINT        NOT NULL CHECK (stops_travelled > 0),
    amount_usd              NUMERIC(10,2)   NOT NULL CHECK (amount_usd >= 0),
    status                  VARCHAR(20)     NOT NULL CHECK (status IN ('confirmed', 'completed', 'cancelled')),
    booked_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    travelled_at            TIMESTAMPTZ,    -- NULL before travel

    CONSTRAINT fk_nr_booking_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_nr_booking_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES national_rail_schedules (schedule_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_nr_booking_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_nr_booking_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

    -- Using WHERE condition to exclude 'cancelled' orders, so if someone refunds, the seat can be re-purchased immediately
CREATE UNIQUE INDEX idx_prevent_double_booking 
ON national_rail_bookings (schedule_id, travel_date, coach, seat_id)
WHERE status IN ('confirmed', 'completed') AND coach IS NOT NULL AND seat_id IS NOT NULL;


-- ------------------------------------------------------------
-- 3.2 metro_travels
-- No departure_time / coach / seat_id / fare_class:
-- Metro does not reserve seats, uses a flat fare system.
-- ------------------------------------------------------------
CREATE TABLE metro_travels (
    trip_id                 VARCHAR(20)     PRIMARY KEY,
    user_id                 VARCHAR(20)     NOT NULL,
    schedule_id             VARCHAR(20)     NOT NULL,
    origin_station_id       VARCHAR(20)     NOT NULL,
    destination_station_id  VARCHAR(20)     NOT NULL,
    travel_date             DATE            NOT NULL,
    ticket_type             VARCHAR(30)     NOT NULL CHECK (ticket_type IN ('single', 'day_pass')),

    -- Reference field for day pass
    day_pass_ref            VARCHAR(20),

    -- NULL only allowed in day_pass usage record scenarios (see chk_metro_ticket_logic scenarios B/C)
    stops_travelled         SMALLINT        CHECK (stops_travelled > 0),
    amount_usd              NUMERIC(10,2)   NOT NULL CHECK (amount_usd >= 0),
    status                  VARCHAR(20)     NOT NULL CHECK (status IN ('confirmed', 'completed', 'cancelled')),

    -- NULL only allowed in day_pass usage record (scenario C), other scenarios forced non-NULL by chk_metro_ticket_logic
    purchased_at            TIMESTAMPTZ,
    travelled_at            TIMESTAMPTZ,

    CONSTRAINT fk_metro_travel_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_metro_travel_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES metro_schedules (schedule_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_metro_travel_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES metro_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_metro_travel_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES metro_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- [Self-referencing foreign key]
    -- Ensure the ID filled in day_pass_ref must be a genuinely existing transaction in this table
    CONSTRAINT fk_metro_day_pass_ref
        FOREIGN KEY (day_pass_ref)
        REFERENCES metro_travels (trip_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- Strictly specify whether fields should be NULL or must have values under different ticket types and statuses
    CONSTRAINT chk_metro_ticket_logic CHECK (
        -- Scenario A: Single ticket (must have stops travelled, purchase time, and no day_pass_ref)
        (ticket_type = 'single' AND day_pass_ref IS NULL AND stops_travelled IS NOT NULL AND purchased_at IS NOT NULL) 
        OR
        -- Scenario B: Point of purchasing day pass (no stops travelled, no day_pass_ref, must have purchase time)
        (ticket_type = 'day_pass' AND day_pass_ref IS NULL AND stops_travelled IS NULL AND purchased_at IS NOT NULL) 
        OR 
        -- Scenario C: Travelling using day pass (must have day_pass_ref, amount must be 0, no need to record purchase time again)
        (ticket_type = 'day_pass' AND day_pass_ref IS NOT NULL AND amount_usd = 0 AND purchased_at IS NULL)
    )
);


-- ------------------------------------------------------------
-- 3.3 payments
-- ------------------------------------------------------------
CREATE TABLE payments (
    payment_id               VARCHAR(20)     PRIMARY KEY,
    national_rail_booking_id VARCHAR(20),
    metro_travel_id          VARCHAR(20),
    amount_usd               NUMERIC(10,2)   NOT NULL CHECK (amount_usd >= 0),
    method                   VARCHAR(30)     NOT NULL CHECK (method IN ('credit_card', 'debit_card', 'ewallet')),
    status                   VARCHAR(20)     NOT NULL CHECK (status IN ('paid', 'pending', 'refunded', 'failed')),
    paid_at                  TIMESTAMPTZ,

    CONSTRAINT fk_payment_nr_booking
        FOREIGN KEY (national_rail_booking_id)
        REFERENCES national_rail_bookings (booking_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_payment_metro_travel
        FOREIGN KEY (metro_travel_id)
        REFERENCES metro_travels (trip_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- Ensure this payment exactly corresponds to only one transportation service, cannot both have values, nor both be NULL
    CONSTRAINT chk_payment_exclusive_arc CHECK (
        (national_rail_booking_id IS NOT NULL AND metro_travel_id IS NULL) OR
        (national_rail_booking_id IS NULL AND metro_travel_id IS NOT NULL)
    ),

    -- If status is paid or refunded, there must be a timestamp
    CONSTRAINT chk_payment_status_time CHECK (
        (status IN ('paid', 'refunded') AND paid_at IS NOT NULL) OR
        (status IN ('pending', 'failed') AND paid_at IS NULL)
    )
);


-- ------------------------------------------------------------
-- 3.4 feedback
-- ------------------------------------------------------------
CREATE TABLE feedback (
    feedback_id   VARCHAR(20)     PRIMARY KEY,

    -- Split the originally unprotected single booking_id into two independent foreign key fields
    national_rail_booking_id VARCHAR(20),
    metro_travel_id          VARCHAR(20),
    
    user_id       VARCHAR(20)     NOT NULL,
    rating        SMALLINT        NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment       TEXT,
    submitted_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_feedback_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_feedback_nr_booking
        FOREIGN KEY (national_rail_booking_id)
        REFERENCES national_rail_bookings (booking_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_feedback_metro_travel
        FOREIGN KEY (metro_travel_id)
        REFERENCES metro_travels (trip_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- Ensure this feedback exactly corresponds to an order of "one" transportation service
    CONSTRAINT chk_feedback_exclusive_arc CHECK (
        (national_rail_booking_id IS NOT NULL AND metro_travel_id IS NULL) OR
        (national_rail_booking_id IS NULL AND metro_travel_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX idx_feedback_unique_nr 
    ON feedback (national_rail_booking_id) 
    WHERE national_rail_booking_id IS NOT NULL;

CREATE UNIQUE INDEX idx_feedback_unique_metro 
    ON feedback (metro_travel_id) 
    WHERE metro_travel_id IS NOT NULL;



-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,  -- 'refund', 'booking', 'conduct'
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_policy_documents_embedding ON policy_documents USING hnsw (embedding vector_cosine_ops);git branch -D feature/queries.py'