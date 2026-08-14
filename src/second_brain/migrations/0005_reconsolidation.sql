-- 0005_reconsolidation: activation/retrieval tracking + meta-memory heat
-- (plan §49-52/§15, Phase 15 §111)
CREATE TABLE memory_activations (
    activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id     TEXT NOT NULL,
    session_id    TEXT,
    outcome       TEXT CHECK (outcome IN ('correct', 'irrelevant', 'contradicted')),
    created_at    TEXT NOT NULL
);

CREATE TABLE memory_retrievals (
    retrieval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id    TEXT NOT NULL,
    session_id   TEXT,
    created_at   TEXT NOT NULL
);

ALTER TABLE memories
    ADD COLUMN heat TEXT NOT NULL DEFAULT 'WARM'
    CHECK (heat IN ('HOT', 'WARM', 'COLD', 'ARCHIVED'));
ALTER TABLE memories
    ADD COLUMN retrieval_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories
    ADD COLUMN successful_retrieval_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories
    ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories
    ADD COLUMN last_retrieved_at TEXT;
