-- Durable result and terminal state share the worker lifecycle transaction.
-- Additive only: older readers ignore this table; rollback retains receipts.
CREATE TABLE IF NOT EXISTS worker_task_results (
    task_id TEXT PRIMARY KEY REFERENCES worker_tasks(task_id),
    packet_sha256 TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
