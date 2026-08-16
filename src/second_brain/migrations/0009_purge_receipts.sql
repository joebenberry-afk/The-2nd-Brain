-- 0009_purge_receipts: durable purge receipts (plan §12/§13, Phase G/T-G5).
-- Written ONLY after a session ledger directory has been fully purged
-- (extraction verified first when configured). The session row itself is
-- deleted with the ledger; the receipt is the durable tombstone.
CREATE TABLE IF NOT EXISTS purge_receipts (
    receipt_id           TEXT PRIMARY KEY,
    internal_session_id  TEXT NOT NULL,
    host_session_id      TEXT NOT NULL,
    status_before        TEXT NOT NULL,
    extracted_memory_ids TEXT NOT NULL DEFAULT '[]',
    purged_at            TEXT NOT NULL,
    reason               TEXT NOT NULL
);
