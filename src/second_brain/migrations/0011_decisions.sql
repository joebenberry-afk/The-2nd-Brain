-- 0011_decisions: append-only policy decision log with outcome updates.
CREATE TABLE IF NOT EXISTS decisions(
    decision_id TEXT PRIMARY KEY,
    session_id TEXT,
    task_id TEXT,
    kind TEXT,
    chosen_json TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    propensity REAL NOT NULL,
    randomized INTEGER NOT NULL DEFAULT 0,
    policy_version TEXT NOT NULL,
    rollout_stage TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    outcome_json TEXT,
    reward REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_kind_created ON decisions(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id);
