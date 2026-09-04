-- 0015_harness_capabilities.sql: harness capability profiles and tiers (T4.3)

CREATE TABLE IF NOT EXISTS harness_capabilities (
    harness_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    supported INTEGER NOT NULL,
    version TEXT,
    observed_at TEXT NOT NULL,
    evidence_json TEXT,
    PRIMARY KEY(harness_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_harness_capabilities_harness ON harness_capabilities(harness_id);
