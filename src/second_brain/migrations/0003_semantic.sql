-- 0003_semantic: semantic memory cortex (plan §13, Phase 10 §106)
CREATE TABLE memories (
    memory_id        TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    scope            TEXT NOT NULL DEFAULT 'project'
                     CHECK (scope IN ('project', 'domain', 'global')),
    project_id       TEXT,
    status           TEXT NOT NULL DEFAULT 'candidate'
                     CHECK (status IN ('candidate', 'current', 'labile', 'superseded', 'archived')),
    evidence_grade   TEXT NOT NULL DEFAULT 'OBSERVED'
                     CHECK (evidence_grade IN ('OBSERVED', 'TESTED', 'VERIFIED',
                                               'INFERRED', 'HISTORICAL', 'REJECTED')),
    current_version  INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_verified_at TEXT,
    strength         REAL NOT NULL DEFAULT 0.5,
    stability        REAL NOT NULL DEFAULT 0.5,
    summary          TEXT,
    body_path        TEXT
);

CREATE TABLE memory_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   TEXT REFERENCES memories (memory_id),
    source_ref  TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'evidence'
                CHECK (source_kind IN ('evidence', 'episode', 'test', 'decision', 'import')),
    added_at    TEXT NOT NULL
);

CREATE TABLE memory_versions (
    memory_id   TEXT,
    version     INTEGER,
    created_at  TEXT NOT NULL,
    title       TEXT,
    body_path   TEXT,
    change_note TEXT,
    PRIMARY KEY (memory_id, version)
);
