-- 0020_causal_learning: immutable interventions, observations, and prediction-error learning loop.
CREATE TABLE IF NOT EXISTS v2_interventions(
    intervention_id TEXT PRIMARY KEY,
    intervention_type TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    expected_json TEXT NOT NULL,
    baseline_ref TEXT NOT NULL,
    decision_ref TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'OBSERVED', 'RESOLVED', 'ABANDONED')),
    policy_version TEXT NOT NULL,
    provenance_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_observations(
    observation_id TEXT PRIMARY KEY,
    intervention_id TEXT NOT NULL REFERENCES v2_interventions(intervention_id),
    observed_json TEXT NOT NULL,
    prediction_error_json TEXT NOT NULL,
    surprise_score REAL NOT NULL,
    evidence_strength REAL NOT NULL,
    credit_class TEXT NOT NULL CHECK (credit_class IN ('DIRECT', 'CONTRIBUTORY', 'CORRELATED', 'UNRELATED_NEGATIVE')),
    evaluator_ref TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('telemetry', 'test_runner', 'acceptance_check', 'benchmark')),
    candidate_action_json TEXT NOT NULL,
    provenance_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_v2_interventions_target ON v2_interventions(target_ref, status);
CREATE INDEX IF NOT EXISTS idx_v2_observations_intervention ON v2_observations(intervention_id);
