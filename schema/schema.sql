PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Import metadata
CREATE TABLE IF NOT EXISTS import_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    export_xml_path TEXT NOT NULL,
    records_parsed  INTEGER DEFAULT 0,
    workouts_parsed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    date_of_birth   TEXT,
    biological_sex  TEXT,
    blood_type      TEXT,
    export_date     TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    version         TEXT,
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS record_types (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hk_identifier   TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    category        TEXT NOT NULL CHECK (category IN ('quantity', 'category', 'workout', 'summary'))
);

-- Workouts
CREATE TABLE IF NOT EXISTS workouts (
    id              TEXT PRIMARY KEY,
    activity_type   TEXT NOT NULL,
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    start_date_local TEXT,
    local_date      TEXT NOT NULL,
    duration_sec    REAL,
    distance_m      REAL,
    energy_kcal     REAL,
    source_id       INTEGER REFERENCES sources(id),
    device          TEXT,
    route_file      TEXT,
    creation_date   TEXT
);

CREATE INDEX IF NOT EXISTS idx_workouts_start_at ON workouts(start_at);
CREATE INDEX IF NOT EXISTS idx_workouts_local_date ON workouts(local_date);
CREATE INDEX IF NOT EXISTS idx_workouts_activity ON workouts(activity_type);

CREATE TABLE IF NOT EXISTS workout_statistics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id      TEXT NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    stat_type       TEXT NOT NULL,
    start_at        TEXT,
    end_at          TEXT,
    sum_value       REAL,
    avg_value       REAL,
    min_value       REAL,
    max_value       REAL,
    unit            TEXT
);

CREATE INDEX IF NOT EXISTS idx_workout_stats_workout ON workout_statistics(workout_id);

CREATE TABLE IF NOT EXISTS workout_metadata (
    workout_id      TEXT NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,
    value           TEXT,
    PRIMARY KEY (workout_id, key)
);

-- Activity ring summaries
CREATE TABLE IF NOT EXISTS activity_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_components TEXT NOT NULL,
    local_date      TEXT NOT NULL,
    active_energy_kcal REAL,
    active_energy_goal REAL,
    exercise_min    REAL,
    exercise_goal   REAL,
    stand_hours     REAL,
    stand_goal      REAL,
    UNIQUE (local_date)
);

-- Selective health samples (VO2 max, RHR, HRV, weight)
CREATE TABLE IF NOT EXISTS health_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type     TEXT NOT NULL,
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    local_date      TEXT NOT NULL,
    value_num       REAL,
    value_text      TEXT,
    unit            TEXT,
    source_id       INTEGER REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_health_samples_type_date ON health_samples(record_type, local_date);

-- Sleep segments
CREATE TABLE IF NOT EXISTS sleep_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    local_date      TEXT NOT NULL,
    value           TEXT NOT NULL,
    source_id       INTEGER REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_sleep_local_date ON sleep_sessions(local_date);

-- GPX routes
CREATE TABLE IF NOT EXISTS routes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id      TEXT REFERENCES workouts(id),
    gpx_filename    TEXT NOT NULL UNIQUE,
    point_count     INTEGER,
    distance_m      REAL,
    elev_gain_m     REAL,
    duration_sec    REAL,
    avg_speed_mps   REAL,
    max_speed_mps   REAL
);

CREATE TABLE IF NOT EXISTS route_points (
    route_id        INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    elevation_m     REAL,
    recorded_at     TEXT,
    speed_mps       REAL,
    course_deg      REAL,
    PRIMARY KEY (route_id, seq)
);

-- Daily rollups (built after parse)
CREATE TABLE IF NOT EXISTS daily_metrics (
    local_date          TEXT PRIMARY KEY,
    resting_hr          REAL,
    hrv_sdnn            REAL,
    vo2_max             REAL,
    body_mass_kg        REAL,
    sleep_total_min     REAL,
    sleep_deep_min      REAL,
    sleep_rem_min       REAL,
    sleep_core_min      REAL,
    sleep_awake_min     REAL,
    steps               REAL,
    active_energy_kcal  REAL,
    workout_count       INTEGER DEFAULT 0,
    run_count           INTEGER DEFAULT 0,
    run_distance_m      REAL DEFAULT 0,
    run_duration_sec    REAL DEFAULT 0
);

-- Views for training analysis
CREATE VIEW IF NOT EXISTS v_workout_context AS
SELECT
    w.id,
    w.activity_type,
    w.local_date,
    w.start_at,
    w.end_at,
    w.duration_sec,
    w.distance_m,
    w.energy_kcal,
    w.route_file,
    d.resting_hr,
    d.hrv_sdnn,
    d.vo2_max,
    d.sleep_total_min,
    d.steps,
    d.run_distance_m AS day_run_distance_m
FROM workouts w
LEFT JOIN daily_metrics d ON d.local_date = w.local_date;

CREATE VIEW IF NOT EXISTS v_weekly_training AS
SELECT
    strftime('%Y-W%W', local_date) AS week,
    COUNT(*) AS workout_count,
    SUM(CASE WHEN activity_type = 'HKWorkoutActivityTypeRunning' THEN 1 ELSE 0 END) AS run_count,
    ROUND(SUM(CASE WHEN activity_type = 'HKWorkoutActivityTypeRunning' THEN distance_m ELSE 0 END), 1) AS run_distance_m,
    ROUND(SUM(CASE WHEN activity_type = 'HKWorkoutActivityTypeRunning' THEN duration_sec ELSE 0 END), 0) AS run_duration_sec
FROM workouts
GROUP BY week
ORDER BY week;
