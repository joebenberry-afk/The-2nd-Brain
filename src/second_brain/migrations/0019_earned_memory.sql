-- 0019_earned_memory: separate SHADOW-only earned-memory candidate state.
CREATE TABLE IF NOT EXISTS v2_candidates(
    candidate_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('project', 'domain', 'global')),
    project_id TEXT,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state = 'candidate'),
    trigger_set_json TEXT NOT NULL,
    source_event_refs_json TEXT NOT NULL,
    origin_class TEXT NOT NULL CHECK (origin_class IN (
        'USER_AUTHORED', 'LOCAL_REPO', 'TRUSTED_TEST', 'TOOL_OBSERVATION',
        'EXTERNAL_WEB', 'MODEL_INFERENCE', 'IMPORTED_FOREIGN'
    )),
    origin_root_sha TEXT,
    authority_ceiling TEXT NOT NULL CHECK (authority_ceiling IN ('advisory', 'project_rule', 'policy')),
    confidence TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    rollout_stage TEXT NOT NULL CHECK (rollout_stage = 'SHADOW'),
    decision_ref TEXT NOT NULL REFERENCES decisions(decision_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v2_candidates_project ON v2_candidates(project_id, updated_at);
