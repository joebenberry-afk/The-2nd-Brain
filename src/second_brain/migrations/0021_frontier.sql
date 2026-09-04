-- 0021_frontier: knowledge frontier, feature rollout events, and qualification ledger.
CREATE TABLE IF NOT EXISTS v2_frontier_items(
    frontier_id TEXT PRIMARY KEY,
    decision_ref TEXT NOT NULL,
    unknown TEXT NOT NULL,
    why_matters TEXT,
    scope TEXT NOT NULL DEFAULT 'project',
    stake_tokens REAL,
    p_flip REAL,
    expected_cost REAL,
    priority REAL,
    experiments_json TEXT,
    evidence_refs_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'INVESTIGATING', 'CLOSED', 'EXPIRED')),
    confidence REAL,
    provenance_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v2_frontier_status ON v2_frontier_items(status, priority DESC);

CREATE TABLE IF NOT EXISTS v2_rollout_events(
    event_id TEXT PRIMARY KEY,
    feature TEXT NOT NULL,
    from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v2_rollout_feature ON v2_rollout_events(feature, created_at);

CREATE TABLE IF NOT EXISTS v2_qualification(
    qualification_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    requirement TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PROVEN', 'CANARY', 'SHADOW', 'HELD', 'FAILED')),
    evidence_json TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v2_qualification_phase ON v2_qualification(phase, requirement);
