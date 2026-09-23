-- 0028_runtime_lineage: IF NOT EXISTS keeps a re-run after a lost version row idempotent.
CREATE TABLE IF NOT EXISTS runtime_lineage (
    episode_id TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    parent_runtime_id TEXT,
    root_runtime_id TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    issuer_generation INTEGER NOT NULL,
    runtime_generation INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    PRIMARY KEY (episode_id, runtime_id)
);
CREATE TABLE IF NOT EXISTS episode_roots (
    episode_id TEXT PRIMARY KEY,
    runtime_id TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    issuer_generation INTEGER NOT NULL,
    active_runtime_id TEXT NOT NULL,
    active_generation INTEGER NOT NULL
);
