-- 0029_memory_supersessions: explicit cross-record supersession/invalidation (V3 MEM-03).
-- IF NOT EXISTS keeps a re-run after a lost version row idempotent.
CREATE TABLE IF NOT EXISTS memory_supersessions (
    old_memory_id TEXT PRIMARY KEY REFERENCES memories (memory_id),
    new_memory_id TEXT REFERENCES memories (memory_id),
    kind          TEXT NOT NULL CHECK (kind IN ('supersedes', 'corrects', 'invalidates')),
    reason        TEXT NOT NULL,
    effective_at  TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    source_ref    TEXT,
    CHECK ((kind = 'invalidates') = (new_memory_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_memory_supersessions_new
    ON memory_supersessions (new_memory_id);
