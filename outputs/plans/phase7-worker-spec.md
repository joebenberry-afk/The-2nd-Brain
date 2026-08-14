# Phase 7 worker spec (to repowise-recon when free)

YOU OWN: src/second_brain/risk.py, src/second_brain/verify.py,
tests/test_risk.py, tests/test_verify.py, state/recon/phase7-python-results.md.
Parent wires CLI + runs the planted-mismatch eval.

risk.py (deterministic, explainable):
- RISK_LEVELS = LOW MEDIUM HIGH CRITICAL
- assess_risk(repo, files_touched, task_text="", user_criticality=None) -> {level, score, signals[]}
  - signals (plan §35) with weights, all EXPLAINABLE: blast_radius (files count),
    centrality (paths under db/, registry, constitution, config, src/second_brain),
    concurrency (paths mentioning locks/process/daemon), persistence (db/migrations),
    security_boundary (constitution/immune/secrets), public_api (cli.py/prime-extension),
    data_loss (backup/restore/delete), config_scope (config/ + defaults sync),
    hotspot (file churn via git log -n 20 --format= commit count? use `git log --oneline -20 -- <file>` count)
  - each signal -> 0/1/2; score sum -> thresholds: <3 LOW, <6 MEDIUM, <9 HIGH, else CRITICAL
  - user_criticality override forces at least that level
  - every subprocess probe error-graced
verify.py (Intent Verifier brief, plan §37-38):
- build_verifier_brief(home, session_id, repo) -> Path (outputs/verification/<session-id>.md):
  sections in order: BACKWARD RECONSTRUCTION (instruction: infer intent from the
  diff FIRST), DIFF (git diff of files_touched from capsule), REQUIREMENTS (ledger,
  placed AFTER the diff section), CONSTRAINTS (capsule), VALIDATION EVIDENCE (ledger
  evidence entries), VERIFIER QUESTIONS (§37's 8 questions).
  - diff section must come BEFORE requirements (anti-confirmation-bias per §38)
  - never includes capsule's hypotheses/decisions (solver reasoning excluded)
- tests: brief structure ordering (diff index < requirements index), exclusions
  (no hypothesis text present), missing repo/git errors graced, deterministic
  (same inputs -> same brief except diff).
risk tests: signal math deterministic; file lists; overrides; missing repo graced.
Validation loop as usual. Report + reply done.