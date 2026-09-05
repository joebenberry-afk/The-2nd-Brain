-- Attempt-bound worktree-exclusive writer ownership and durable native receipts.
-- Additive only: legacy worker rows retain NULL attempt metadata and old readers
-- continue to use the original lifecycle columns.
ALTER TABLE worker_tasks ADD COLUMN attempt_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN access_intent TEXT;
ALTER TABLE worker_tasks ADD COLUMN project_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN worktree_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN worktree_root TEXT;
ALTER TABLE worker_tasks ADD COLUMN writer_ownership TEXT;
ALTER TABLE worker_tasks ADD COLUMN logical_outcome TEXT;
ALTER TABLE worker_tasks ADD COLUMN executor_settled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE worker_tasks ADD COLUMN cleanup_complete INTEGER NOT NULL DEFAULT 0;
ALTER TABLE worker_tasks ADD COLUMN host_session_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN callback_token_sha256 TEXT;
ALTER TABLE worker_tasks ADD COLUMN host_generation INTEGER;
ALTER TABLE worker_tasks ADD COLUMN native_attempt_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN native_job_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN agent_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN lifecycle_sequence INTEGER NOT NULL DEFAULT -1;
ALTER TABLE worker_tasks ADD COLUMN bound_at TEXT;
ALTER TABLE worker_tasks ADD COLUMN ownership_updated_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_attempt
ON worker_tasks(attempt_id) WHERE attempt_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_writer_worktree
ON worker_tasks(project_id, worktree_id)
WHERE access_intent = 'mutating'
  AND writer_ownership IN ('held', 'quarantined');

-- Receipts intentionally have no worker_tasks foreign key: task_id retries
-- replace the current attempt row while stale-attempt evidence must survive.
CREATE TABLE IF NOT EXISTS worker_attempt_results (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    packet_sha256 TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_lifecycle_receipts (
    attempt_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(attempt_id, sequence)
);

CREATE TABLE IF NOT EXISTS worker_dispatch_failures (
    attempt_id TEXT PRIMARY KEY,
    receipt_sha256 TEXT NOT NULL,
    failure_code TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
