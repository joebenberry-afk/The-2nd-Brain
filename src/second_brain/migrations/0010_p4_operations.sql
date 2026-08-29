-- 0010_p4_operations: canonical P4 state in the primary Brain database.
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','BLOCKED','COMPLETED','ABANDONED')),
    milestones_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target_date TEXT,
    completed_at TEXT,
    blocker_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_goals_status_updated ON goals(status, updated_at);
CREATE TABLE IF NOT EXISTS goal_events (
    event_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    milestone_id TEXT,
    evidence_ref TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goal_events_goal_created ON goal_events(goal_id, created_at);
CREATE TABLE IF NOT EXISTS bottleneck_fingerprints (
    fingerprint_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    signal_key TEXT NOT NULL,
    scope_id TEXT NOT NULL DEFAULT '',
    impact_score REAL NOT NULL CHECK (impact_score >= 0 AND impact_score <= 10),
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    description TEXT NOT NULL,
    mitigation TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(category, signal_key, scope_id)
);
CREATE INDEX IF NOT EXISTS idx_bottleneck_rank ON bottleneck_fingerprints(impact_score DESC, occurrence_count DESC);
CREATE TABLE IF NOT EXISTS heartbeat_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_run_at TEXT
);
INSERT OR IGNORE INTO heartbeat_state(singleton, last_run_at) VALUES (1, NULL);
CREATE TABLE IF NOT EXISTS heartbeat_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    issue_codes_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_started ON heartbeat_runs(started_at);
