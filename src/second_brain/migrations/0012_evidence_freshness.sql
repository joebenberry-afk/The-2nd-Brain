-- Guard inspection is performed by db.apply_migration before each ALTER.
PRAGMA table_info(memory_sources);
ALTER TABLE memory_sources ADD COLUMN repo_id TEXT;
ALTER TABLE memory_sources ADD COLUMN path TEXT;
ALTER TABLE memory_sources ADD COLUMN symbol TEXT;
ALTER TABLE memory_sources ADD COLUMN commit_sha TEXT;
ALTER TABLE memory_sources ADD COLUMN blob_sha TEXT;
ALTER TABLE memory_sources ADD COLUMN range_start INTEGER;
ALTER TABLE memory_sources ADD COLUMN range_end INTEGER;
ALTER TABLE memory_sources ADD COLUMN range_sha TEXT;
ALTER TABLE memory_sources ADD COLUMN verified_at TEXT;
