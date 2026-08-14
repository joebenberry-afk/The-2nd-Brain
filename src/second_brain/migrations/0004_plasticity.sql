-- 0004_plasticity: shadow-learning tables (plan §40-45, Phase 13 §109)
CREATE TABLE predictions (
    prediction_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT,
    state                TEXT,
    expected_next_state  TEXT,
    actual_next_state    TEXT,
    prediction_error     INTEGER NOT NULL DEFAULT 0 CHECK (prediction_error IN (0, 1)),
    kind                 TEXT NOT NULL,
    created_at           TEXT NOT NULL
);

CREATE TABLE outcomes (
    outcome_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    task_id      TEXT,
    vector_json  TEXT NOT NULL,     -- plan §42 raw outcome vector, partial allowed
    created_at   TEXT NOT NULL
);

CREATE TABLE prediction_errors (
    error_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id  INTEGER REFERENCES predictions (prediction_id),
    kind           TEXT,
    salience       REAL NOT NULL DEFAULT 0.5,
    detail         TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE credit_events (
    credit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    subject_id   TEXT NOT NULL,
    subject_kind TEXT NOT NULL CHECK (subject_kind IN
                 ('skill', 'memory', 'policy', 'tool', 'scout', 'verification')),
    credit_level TEXT NOT NULL CHECK (credit_level IN
                 ('direct', 'contributory', 'correlated', 'unknown')),
    created_at   TEXT NOT NULL
);
