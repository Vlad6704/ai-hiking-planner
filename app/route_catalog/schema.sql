CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY,
    route_id TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    parse_status TEXT NOT NULL,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS route_variants (
    variant_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(route_id),
    variant_key TEXT NOT NULL,
    name TEXT NOT NULL,
    distance_m INTEGER CHECK(distance_m IS NULL OR distance_m > 0),
    duration_minutes INTEGER CHECK(duration_minutes IS NULL OR duration_minutes > 0),
    ascent_m INTEGER CHECK(ascent_m IS NULL OR ascent_m >= 0),
    descent_m INTEGER CHECK(descent_m IS NULL OR descent_m >= 0),
    difficulty TEXT NOT NULL,
    layout TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS route_filter ON route_variants(active, difficulty, duration_minutes);
CREATE INDEX IF NOT EXISTS route_distance ON route_variants(distance_m);
CREATE INDEX IF NOT EXISTS route_ascent ON route_variants(ascent_m);
CREATE VIRTUAL TABLE IF NOT EXISTS routes_fts USING fts5(
    route_id UNINDEXED, name, description, instructions, points_of_interest, cautions,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS catalog_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    last_attempt_day TEXT,
    last_success_at TEXT,
    last_outcome TEXT,
    owner TEXT,
    lease_until TEXT,
    run_id TEXT
);
INSERT OR IGNORE INTO catalog_state(id) VALUES(1);
CREATE TABLE IF NOT EXISTS catalog_refresh_runs (
    run_id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL,
    report TEXT NOT NULL
);
PRAGMA user_version=1;
