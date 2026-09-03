-- 0014_worker_leases.sql: A2A-aligned worker tasks and leases (T4.1)

CREATE TABLE IF NOT EXISTS worker_tasks (
    task_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    packet_sha256 TEXT NOT NULL,
    accepted_at TEXT,
    settled_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_tasks_state ON worker_tasks(state);
CREATE INDEX IF NOT EXISTS idx_worker_tasks_lease ON worker_tasks(lease_expires_at);

CREATE TABLE IF NOT EXISTS worker_task_meta (
    task_id TEXT PRIMARY KEY,
    redeliveries INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    session_id TEXT,
    delivered_at TEXT,
    dispatch_payload TEXT,
    updated_at TEXT NOT NULL
);
