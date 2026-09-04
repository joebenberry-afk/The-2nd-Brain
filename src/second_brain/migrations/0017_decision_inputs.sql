-- 0017_decision_inputs: replayable inputs for off-policy evaluation (T5.3)
ALTER TABLE decisions ADD COLUMN inputs_json TEXT;
