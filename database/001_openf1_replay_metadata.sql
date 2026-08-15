-- Extension aditiva para fuentes historicas reproducidas por MQTT.
-- No altera valores existentes ni convierte CAN simulado en datos OpenF1.
ALTER TABLE telemetry_messages
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS telemetry_messages_source_session_driver_timestamp_idx
    ON telemetry_messages (source_type, session_id, driver_id, timestamp);

-- Contexto de carrera que no debe representarse como una muestra puntual.
CREATE TABLE IF NOT EXISTS racing_sessions (
    meeting_key INTEGER NOT NULL,
    session_key INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    session_name TEXT NOT NULL,
    session_type TEXT NOT NULL,
    circuit_key INTEGER,
    circuit_short_name TEXT,
    country_name TEXT,
    location TEXT,
    date_start TIMESTAMPTZ,
    date_end TIMESTAMPTZ,
    source_url TEXT NOT NULL,
    raw_payload_path TEXT NOT NULL,
    retrieved_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS racing_drivers (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    full_name TEXT,
    name_acronym TEXT,
    team_name TEXT,
    team_colour TEXT,
    source_url TEXT NOT NULL,
    raw_payload_path TEXT NOT NULL,
    retrieved_at_utc TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_key, driver_number)
);

CREATE TABLE IF NOT EXISTS racing_laps (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    date_start TIMESTAMPTZ,
    lap_duration_seconds DOUBLE PRECISION,
    duration_sector_1_seconds DOUBLE PRECISION,
    duration_sector_2_seconds DOUBLE PRECISION,
    duration_sector_3_seconds DOUBLE PRECISION,
    i1_speed_kph DOUBLE PRECISION,
    i2_speed_kph DOUBLE PRECISION,
    speed_trap_kph DOUBLE PRECISION,
    is_pit_out_lap BOOLEAN,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, lap_number)
);

CREATE TABLE IF NOT EXISTS racing_stints (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    stint_number INTEGER NOT NULL,
    compound TEXT,
    lap_start INTEGER,
    lap_end INTEGER,
    tyre_age_at_start INTEGER,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, stint_number)
);

CREATE TABLE IF NOT EXISTS racing_pit_stops (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    lap_number INTEGER,
    lane_duration_seconds DOUBLE PRECISION,
    stop_duration_seconds DOUBLE PRECISION,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, date)
);

CREATE TABLE IF NOT EXISTS racing_weather (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    date TIMESTAMPTZ NOT NULL,
    air_temperature_c DOUBLE PRECISION,
    track_temperature_c DOUBLE PRECISION,
    rainfall BOOLEAN,
    humidity_percent DOUBLE PRECISION,
    pressure_mbar DOUBLE PRECISION,
    wind_direction_degrees DOUBLE PRECISION,
    wind_speed_mps DOUBLE PRECISION,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, date)
);

CREATE TABLE IF NOT EXISTS racing_positions (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    position INTEGER NOT NULL,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, date)
);

CREATE TABLE IF NOT EXISTS racing_intervals (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    gap_to_leader_seconds DOUBLE PRECISION,
    gap_to_leader_text TEXT,
    interval_seconds DOUBLE PRECISION,
    interval_text TEXT,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, date)
);

CREATE TABLE IF NOT EXISTS racing_overtakes (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    date TIMESTAMPTZ NOT NULL,
    overtaking_driver_number INTEGER NOT NULL,
    overtaken_driver_number INTEGER NOT NULL,
    position INTEGER,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, date, overtaking_driver_number, overtaken_driver_number)
);

CREATE TABLE IF NOT EXISTS racing_team_radio (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    recording_url TEXT,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number, date)
);

CREATE TABLE IF NOT EXISTS racing_session_results (
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    driver_number INTEGER NOT NULL,
    position INTEGER,
    points DOUBLE PRECISION,
    number_of_laps INTEGER,
    duration_seconds DOUBLE PRECISION,
    gap_to_leader TEXT,
    dnf BOOLEAN,
    dns BOOLEAN,
    dsq BOOLEAN,
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (session_key, driver_number)
);

CREATE TABLE IF NOT EXISTS racing_events (
    event_id BIGSERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL REFERENCES racing_sessions(session_key),
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    driver_number INTEGER,
    related_driver_number INTEGER,
    lap_number INTEGER,
    raw_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS racing_events_session_time_idx
    ON racing_events (session_key, event_time);

CREATE INDEX IF NOT EXISTS racing_positions_session_driver_time_idx
    ON racing_positions (session_key, driver_number, date);

CREATE INDEX IF NOT EXISTS racing_intervals_session_driver_time_idx
    ON racing_intervals (session_key, driver_number, date);
