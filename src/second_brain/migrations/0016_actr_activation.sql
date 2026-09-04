-- 0016_actr_activation: ACT-R base-level activation, retrieval/storage strength
-- (plan T5.1)

ALTER TABLE memory_activations ADD COLUMN kind TEXT;

ALTER TABLE memories ADD COLUMN retrieval_strength REAL NOT NULL DEFAULT 1.0;

ALTER TABLE memories ADD COLUMN storage_strength REAL NOT NULL DEFAULT 1.0;

UPDATE memory_activations SET kind = 'used' WHERE outcome = 'correct' AND kind IS NULL;
