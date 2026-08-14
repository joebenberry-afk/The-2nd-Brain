-- 0002_episodes: episodic memory vault (plan §12, Phase 9 §105)
CREATE TABLE episodes (
    episode_id       TEXT PRIMARY KEY,
    project_id       TEXT,
    session_id       TEXT,
    task_id          TEXT,
    episode_type     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    summary          TEXT NOT NULL,
    evidence_refs    TEXT,             -- JSON array of provenance refs, stored verbatim
    prediction_error REAL,             -- 0..1
    salience         REAL,
    status           TEXT NOT NULL DEFAULT 'raw',
    confidence       TEXT,
    scope            TEXT NOT NULL DEFAULT 'project'
);

CREATE INDEX idx_episodes_type_created ON episodes (episode_type, created_at);
