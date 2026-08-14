---
name: delivery-integration
status: candidate
source_episodes:
- success-20260814-fdf27e46
- success-20260814-95e17baf
- success-20260814-8c6aad35
transfer_evidence: experiment-5 (2026-08-14): deepseek-v4-pro -> deepseek-v4-flash
  verdict=transfers (same task, both succeeded) => global scope (no model restriction)
created_at: 2026-08-14T10:40:19.271706+00:00
---

# Purpose

- Worker delivery integration (Phase 17): validated delivery, wired router CLI, live eval exposed fixture/real-trigger mismatch, scoring redesigned, gate met (noise 1 vs 3)
- Worker delivery integration (Phase 20): baseline-committed delivery, crossmodel CLI wired, live DB migration path fixed (read paths ensure migration), contamination guard demoed
- Worker delivery integration (Phase 23): promotion CLI wired, real shadow->candidate->active promotion ran under its own gates, router pool upgraded, gate numbers unchanged

# Positive Triggers

- worker delivery
- wire the cli
- integrate a delivery
- validate the delivery
- baseline commit
- milestone report

# Negative Triggers

- no worker delivery
- without integration

# Inputs

- worker-delivered module + tests
- repo validation loop (ruff/pyright/pytest)

# Procedure

1. Commit the worker delivery as a baseline (explicit paths)
2. Run the validation loop (ruff check/format, pyright, pytest)
3. Wire the CLI subcommand and fix response-shape mismatches
4. Live dogfood the subsystem; record honest measurements
5. Write the milestone report with requirement-to-evidence + dogfooding sections
6. Commit explicit paths; dispatch the independent verifier
7. Reconcile every verifier finding; re-run the validation loop

# Tools

- brainctl
- git
- ruff
- pyright
- pytest

# Safety

- never git add -A while workers write; explicit paths only

# Verification

- validation loop green
- live CLI command returns 0
- verifier findings reconciled

# Output

- committed milestone + reconciled findings

# References

- episode success-20260814-fdf27e46
- episode success-20260814-95e17baf
- episode success-20260814-8c6aad35
- evidence milestone-17-skill-router.md|tests/test_router.py
- evidence milestone-20-cross-model-memory.md|src/second_brain/crossmodel.py
- evidence milestone-23-policy-promotion.md|src/second_brain/promotion.py
