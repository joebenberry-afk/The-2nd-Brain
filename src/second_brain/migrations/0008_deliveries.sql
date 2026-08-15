-- 0008_deliveries: P0 AutoInject delivery ledger (plan §6.5, Phase 0C).
-- One row per delivered memory item on an active lineage (root session +
-- branch). The dedupe key is (root_session_id, branch_id, memory_id,
-- memory_version); canonical_hash pins the exact delivered content so a
-- content change without a version bump is detected. superseded_by_delivery_id
-- points at the delivery that replaced this one (a later memory version);
-- old host messages are never rewritten, only the ledger pointer moves.
-- IF NOT EXISTS: lazy-migration brains may already hold the table while
-- forgetting the version row; re-running must stay idempotent.
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id             TEXT PRIMARY KEY,
    root_session_id         TEXT NOT NULL,
    agent_session_id        TEXT NOT NULL,
    branch_id               TEXT NOT NULL,
    memory_id               TEXT NOT NULL,
    memory_version          INTEGER NOT NULL,
    canonical_hash          TEXT NOT NULL,
    packet_id               TEXT NOT NULL,
    delivered_event_id      TEXT NOT NULL,
    delivered_at            TEXT NOT NULL,
    superseded_by_delivery_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_deliveries_dedupe
    ON deliveries (root_session_id, branch_id, memory_id, memory_version);
