-- db.apply_migration refuses unresolved pre-cutover holders before any DDL.
-- Terminal history and its original callback identity remain unchanged.
DROP INDEX IF EXISTS idx_worker_tasks_writer_worktree;

CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_writer_physical
ON worker_tasks(worktree_id)
WHERE access_intent = 'mutating'
  AND writer_ownership IN ('held', 'quarantined');

-- A replacement directory cannot acquire a still-reserved execution path.
CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_writer_root
ON worker_tasks(worktree_root)
WHERE access_intent = 'mutating'
  AND writer_ownership IN ('held', 'quarantined');

CREATE TRIGGER IF NOT EXISTS worker_tasks_physical_identity_insert
BEFORE INSERT ON worker_tasks
WHEN NEW.access_intent = 'mutating'
  AND NEW.writer_ownership IN ('held', 'quarantined')
  AND (NEW.worktree_id IS NULL OR typeof(NEW.worktree_id) != 'text'
       OR length(NEW.worktree_id) != 64
       OR NEW.worktree_id GLOB '*[^0-9a-f]*'
       OR NEW.worktree_root IS NULL OR typeof(NEW.worktree_root) != 'text'
       OR length(trim(NEW.worktree_root)) = 0)
BEGIN
    SELECT RAISE(ABORT, 'invalid physical worktree identity');
END;

CREATE TRIGGER IF NOT EXISTS worker_tasks_physical_identity_update
BEFORE UPDATE ON worker_tasks
WHEN NEW.access_intent = 'mutating'
  AND NEW.writer_ownership IN ('held', 'quarantined')
  AND (NEW.worktree_id IS NULL OR typeof(NEW.worktree_id) != 'text'
       OR length(NEW.worktree_id) != 64
       OR NEW.worktree_id GLOB '*[^0-9a-f]*'
       OR NEW.worktree_root IS NULL OR typeof(NEW.worktree_root) != 'text'
       OR length(trim(NEW.worktree_root)) = 0)
BEGIN
    SELECT RAISE(ABORT, 'invalid physical worktree identity');
END;
