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
-- 依賴方（Batch C）優先 DROP，被依賴方（Batch A）最後 DROP
-- CASCADE 確保跨表的 FK 約束一併清除
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
-- password, secrect_answer 加上經由 argon2id ， hashing 後存於 user_credential
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id          VARCHAR(20)   PRIMARY KEY,
    full_name        VARCHAR(255)  NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE CHECK (email LIKE '%@%'),
    phone            VARCHAR(20),
    date_of_birth    DATE,
    registered_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE TABLE user_credential (
    user_id              VARCHAR(20)   PRIMARY KEY,
    stored_hash          VARCHAR(255)  NOT NULL,        -- 儲存完整的 argon2id 雜湊編碼字串
    secret_question      TEXT          NOT NULL,
    secret_answer_hash   VARCHAR(255)  NOT NULL,
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_credential_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE          -- 使用者刪除時，憑證自動連帶刪除
);


-- ------------------------------------------------------------
-- 1.2 metro_stations
-- 與 national_rail_stations 存在循環外鍵
-- adjacent_stations 在 Neo4j 中會被轉換為節點之間的邊
-- interchange_national_rail_station_id 的 FK 於兩表建立後補加
-- ------------------------------------------------------------
CREATE TABLE metro_stations (
    station_id                           VARCHAR(20)   PRIMARY KEY,
    name                                 VARCHAR(255)  NOT NULL,
    lines                                TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_metro                 BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_metro_lines              TEXT[]        NOT NULL DEFAULT '{}',
    is_interchange_national_rail         BOOLEAN       NOT NULL DEFAULT FALSE,
    interchange_national_rail_station_id VARCHAR(20),                            -- FK 見下方 ALTER TABLE
    adjacent_stations                    JSONB         NOT NULL DEFAULT '[]',   -- 將相鄰站點資訊以 JSONB 儲存，用以備份
    
    -- 只要 interchange_national_rail_station_id 不是 NULL，is_interchange_national_rail 就應該是 TRUE
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
-- 1.4 跨網路循環外鍵
-- ON DELETE SET NULL：轉乘站被刪除時，欄位設為 NULL 而非報錯，
--                    保留車站紀錄，避免連帶刪除整個車站資料。
-- ON UPDATE CASCADE：主鍵更新時自動同步子表。
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
-- coaches 為深層巢狀陣列（車廂 → 座位清單），使用 JSONB。
-- schedule_id UNIQUE：強制一個班次只能對應一套座位佈局。
-- ON DELETE CASCADE：班次撤銷時，對應佈局同步刪除。
-- ------------------------------------------------------------
CREATE TABLE national_rail_seat_layouts (
    layout_id    VARCHAR(20)  PRIMARY KEY,

    -- 移除 schedule_id，避免產生產生循環依賴
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
    
    -- 特快車跳過的車站紀錄，且不允許為 NULL，設預設空陣列 
    skip_stations                JSONB           NOT NULL DEFAULT '[]',

    travel_time_from_origin_min  JSONB           NOT NULL,
    first_train_time             TIME            NOT NULL,
    last_train_time              TIME            NOT NULL,
    fare_classes                 JSONB           NOT NULL,   
    frequency_min                SMALLINT        NOT NULL CHECK (frequency_min > 0),
    operates_on                  TEXT[]          NOT NULL DEFAULT '{}',

    -- 由班表引進外鍵指向 national_rail_seat_layouts ，使用 1:N 的共享車型架構
    layout_id                    VARCHAR(20)     NOT NULL,

    -- 起點站外鍵：限制必須存在於車站主檔，且營運中車站拒絕被輕易刪除 (RESTRICT)
    CONSTRAINT fk_nr_sch_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 終點站外鍵
    CONSTRAINT fk_nr_sch_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES national_rail_stations (station_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 座位佈局樣板外鍵：只要該座位車型仍有班次在使用，即拒絕刪除該樣板
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
    travelled_at            TIMESTAMPTZ,    -- 搭乘前為 NULL

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

    --使用 WHERE 條件排除了 'cancelled' 的訂單，若有人退票，該座位就能立刻被其他人重新買走
CREATE UNIQUE INDEX idx_prevent_double_booking 
ON national_rail_bookings (schedule_id, travel_date, coach, seat_id)
WHERE status IN ('confirmed', 'completed') AND coach IS NOT NULL AND seat_id IS NOT NULL;


-- ------------------------------------------------------------
-- 3.2 metro_travels
-- 無 departure_time / coach / seat_id / fare_class：
-- 捷運不預約座位，採統一計費制。
-- ------------------------------------------------------------
CREATE TABLE metro_travels (
    trip_id                 VARCHAR(20)     PRIMARY KEY,
    user_id                 VARCHAR(20)     NOT NULL,
    schedule_id             VARCHAR(20)     NOT NULL,
    origin_station_id       VARCHAR(20)     NOT NULL,
    destination_station_id  VARCHAR(20)     NOT NULL,
    travel_date             DATE            NOT NULL,
    ticket_type             VARCHAR(30)     NOT NULL CHECK (ticket_type IN ('single', 'day_pass')),

    -- 一日票的參照欄位
    day_pass_ref            VARCHAR(20),

    -- NULL 僅允許於 day_pass 使用紀錄情境（見 chk_metro_ticket_logic 情境 B/C）
    stops_travelled         SMALLINT        CHECK (stops_travelled > 0),
    amount_usd              NUMERIC(10,2)   NOT NULL CHECK (amount_usd >= 0),
    status                  VARCHAR(20)     NOT NULL CHECK (status IN ('confirmed', 'completed', 'cancelled')),

    -- NULL 僅允許於 day_pass 使用紀錄（情境 C），其餘情境由 chk_metro_ticket_logic 強制非 NULL
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

    -- 【自我參照外鍵】
    -- 確保 day_pass_ref 填入的 ID 必須是此表中真實存在的一筆交易
    CONSTRAINT fk_metro_day_pass_ref
        FOREIGN KEY (day_pass_ref)
        REFERENCES metro_travels (trip_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 嚴格規範不同票種與狀態下，欄位是該為 NULL 還是必須有值
    CONSTRAINT chk_metro_ticket_logic CHECK (
        -- 情境 A：單程票 (必須有站數、購買時間，且無 day_pass_ref)
        (ticket_type = 'single' AND day_pass_ref IS NULL AND stops_travelled IS NOT NULL AND purchased_at IS NOT NULL) 
        OR
        -- 情境 B：購買一日票當下 (無站數、無 day_pass_ref、必須有購買時間)
        (ticket_type = 'day_pass' AND day_pass_ref IS NULL AND stops_travelled IS NULL AND purchased_at IS NOT NULL) 
        OR 
        -- 情境 C：使用一日票搭乘 (必須有 day_pass_ref、金額必須是 0、無須再次紀錄購買時間)
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

    -- 確保這筆金流剛好只對應一種交通服務，不能兩個都有值，也不能兩個都是 NULL
    CONSTRAINT chk_payment_exclusive_arc CHECK (
        (national_rail_booking_id IS NOT NULL AND metro_travel_id IS NULL) OR
        (national_rail_booking_id IS NULL AND metro_travel_id IS NOT NULL)
    ),

    -- 如果狀態是 paid 或 refunded，就必須有時間戳記
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

    -- 將原本無法受保護的單一 booking_id，拆分為兩個獨立的外鍵欄位
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

    -- 確保這筆評價剛好只對應「一種」交通服務的訂單
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
CREATE INDEX IF NOT EXISTS idx_policy_documents_embedding ON policy_documents USING hnsw (embedding vector_cosine_ops);
