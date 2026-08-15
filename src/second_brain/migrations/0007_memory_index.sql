-- 0007_memory_index: SQLite retrieval index for semantic memory (plan Phase 6).
-- Markdown stays canonical; this table is DERIVED index state, rebuildable via
-- `brainctl memory reindex` (never hand-edited).
--
-- The FTS5 virtual table (memory_fts) is NOT created here: FTS5 may be absent
-- from the SQLite build, and the migration framework must stay applicable on
-- every platform. semantic.py creates memory_fts lazily (IF NOT EXISTS) behind
-- an availability check and falls back to the linear scan when unavailable.
CREATE TABLE memory_index (
    memory_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',
    project_id      TEXT,
    scope           TEXT,
    status          TEXT,
    evidence_grade  TEXT,
    current_version INTEGER,
    created_at      TEXT,
    updated_at      TEXT,
    body_path       TEXT,
    tags            TEXT NOT NULL DEFAULT '',
    file_hash       TEXT NOT NULL,
    indexed_at      TEXT NOT NULL
);
