# Current State

## Status (2026-08-14, milestone-19 committed)

- Phases 0-19: COMPLETE, each gated by the retained independent reviewer
  (phase1-verifier, REUSED per user policy) with all findings reconciled.
  Milestone reports: outputs/reports/milestone-01..19-*.md.
- Phase 19 verification in flight; Phase 20 (Cross-Model Memory) next.

## Live subsystems (dogfooded on the build itself)

- telemetry (Prime extension installed globally), artifacts/RTD (shadow),
  scout (advisory), working set + JIT + read ledger, requirement ledger
  (material gate), risk/verify (advisory), env/processes (advisory),
  episodes (9 real), semantic memory (3 curated + 1 superseded), sleep
  (consolidation applied once), reconsolidation (retrieval+activation
  recorded), plasticity (hindsight relabel + credit records), skill forge +
  router (1 shadow skill: sqlite-migration-verifier), credit (no-auto-
  reward), engrams (candidate-only, none real yet).

## Reused worker pool (user policy: NEVER spawn new; reuse)

- phase1-verifier: independent fresh-context reviewer (all phase gates).
- repowise-recon: implementation worker (phases 4-19 Python modules+tests).
- phase2-ts-worker: Prime extension TS (phase 2, 5, wiring tests).
- prime-api-recon: Prime API recon (phase 2 input).

## Key operating patterns (proven)

- Validation loop: ruff+format+pyright+pytest (Python); tsc+eslint+vitest+
  real integration (TS); Pester (PS). Explicit git add paths only (never
  git add -A while workers write). PYTHONHOME-sanitized subprocess env.
- Worker spec format: owned paths, API shape, acceptance assertions,
  validation loop, report file, done-reply. Integrate: validate loop, wire
  CLI (parent), live dogfood demo, milestone, verifier, reconcile, commit.
- Verifier tasks: requirements + scope + method + deliverable; it
  independently reruns tools and recomputes numbers; NEVER trust the
  milestone report; reconcile every finding (MAJOR/MINOR/NIT).

## Known gaps (honest records)

- rtd_shadow live trigger unproven (print-mode agents decline bash).
- Monitor/cerebellum fixtures hand-crafted (real calibration pending).
- No real multi-skill engram yet (one shadow skill exists).
- RepoWise index never initialized on this machine.
- Milestone-01/02/03 predate the v4.2 Dogfooding template (later reports
  use it).

## Next steps

1. Phase 19 verification reconciliation (when it returns).
2. Phase 20 (Cross-Model Memory): model_profiles table usage, model-scoped
   skill outcomes, transfer test across models (deepseek-v4-flash vs
   deepseek-v4-pro available).
3. Phases 21-23 (frontier, immune, policy promotion), then the §141-145
   real experiments and the final v4.2 self-hosting success-criteria
   checklist.
