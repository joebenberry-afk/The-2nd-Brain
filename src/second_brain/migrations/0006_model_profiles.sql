-- 0006_model_profiles: cross-model memory (plan §116, Phase 20)
CREATE TABLE model_profiles (
    model_id       TEXT PRIMARY KEY,
    family         TEXT NOT NULL DEFAULT '',
    capabilities   TEXT NOT NULL DEFAULT '',
    first_seen_at  TEXT NOT NULL
);

CREATE TABLE model_skill_outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id   TEXT NOT NULL REFERENCES model_profiles (model_id),
    skill_name TEXT NOT NULL,
    task_hash  TEXT NOT NULL,
    success    INTEGER NOT NULL,
    noise      INTEGER NOT NULL DEFAULT 0,
    f1         REAL NOT NULL DEFAULT 0,
    session_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
