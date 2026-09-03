-- Guard inspection is performed by db.apply_migration before each ALTER.
PRAGMA table_info(memories);
ALTER TABLE memories ADD COLUMN origin_class TEXT NOT NULL DEFAULT 'MODEL_INFERENCE'
    CHECK (origin_class IN ('USER_AUTHORED', 'LOCAL_REPO', 'TRUSTED_TEST',
                            'TOOL_OBSERVATION', 'EXTERNAL_WEB', 'MODEL_INFERENCE',
                            'IMPORTED_FOREIGN'));
ALTER TABLE memories ADD COLUMN origin_root_sha TEXT;
ALTER TABLE memories ADD COLUMN authority_ceiling TEXT NOT NULL DEFAULT 'advisory'
    CHECK (authority_ceiling IN ('advisory', 'project_rule', 'policy'));
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
