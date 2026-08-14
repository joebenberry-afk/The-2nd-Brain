-- 0001_init: project registry (plan §10)
CREATE TABLE projects (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    repo_path           TEXT,
    git_remote          TEXT,
    created_at          TEXT NOT NULL,
    last_seen_at        TEXT,
    brain_project_path  TEXT,
    default_mode        TEXT NOT NULL DEFAULT 'standard',
    repo_intelligence   TEXT NOT NULL DEFAULT 'repowise-preferred',
    verification_policy TEXT NOT NULL DEFAULT 'risk-adaptive',
    active              INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_projects_name ON projects (name);
CREATE INDEX idx_projects_repo_path ON projects (repo_path);
