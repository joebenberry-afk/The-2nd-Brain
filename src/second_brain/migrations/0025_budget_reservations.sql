-- Reserve-before-dispatch: capacity is checked and reserved atomically before a
-- budget-consuming worker admission. Unconsumed rows are durable and visible so a
-- restart can reconcile them, and a refusal writes nothing -- it therefore cannot
-- release or alter writer ownership.
CREATE TABLE IF NOT EXISTS budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    consumed_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_budget_reservations_task
ON budget_reservations(session_id, task_id);

CREATE INDEX IF NOT EXISTS idx_budget_reservations_outstanding
ON budget_reservations(session_id, consumed_at);
