-- 0013_routing_cascade: fast lookup for model/skill outcomes by model, skill, and timestamp.
CREATE INDEX IF NOT EXISTS idx_outcomes_model_skill ON model_skill_outcomes(model_id, skill_name, created_at);
