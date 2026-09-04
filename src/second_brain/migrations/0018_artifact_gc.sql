-- 0018_artifact_gc: artifact refcount table for GC (T6.3)
CREATE TABLE IF NOT EXISTS artifact_refs (
    sha TEXT NOT NULL,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sha, owner)
);
CREATE INDEX IF NOT EXISTS idx_artifact_refs_sha ON artifact_refs(sha);
