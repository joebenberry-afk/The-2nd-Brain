# Milestone 22 — Immune System (Phase 22)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-21 (Frontier Memory) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Rollback trigger detectors with GUARDED auto-rollback: a policy guard
matches metric triggers in a rolling window; rollback moves the target file
aside only under four simultaneous conditions.

### Exact files

- `src/second_brain/immune.py` — register_policy/register_trigger/ingest_metric/check_triggers/rollback/rollback_log
- `src/second_brain/cli.py` — `immune policy|trigger|ingest|check|rollback|log`
- `tests/test_immune.py` — 14 tests + Hypothesis trigger cross-check
- `outputs/reports/milestone-22-immune-system.md` (this file)

## Requirement-to-evidence (Phase 22 acceptance, plan §118)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Detected regressions get rolled back when the trigger matches | live: f1_delta -0.3 over window 3 matched `router-regression` (computed=-0.3, matched=True); rollback moved the target aside + wrote a record |
| 2 | Auto-rollback only in guarded situations | four guards test-asserted: trigger matched / not frontier-approved / target differs from backup / not already rolled back; refusals are explicit reasons with NO mutation (live: unchanged target -> `no_change` refusal) |
| 3 | Window semantics | only last N samples per metric count (tested; stale samples ignored) |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (424 tests, verifier collect)
live: trigger+policy registered -> ingests -> check matched -> refusal on
unchanged target -> rollback on mutated target -> log record
(demo artifacts removed afterwards; the demo is documented here, not kept)
```

## Deviations

1. Metrics are caller-ingested (no live auto-capture yet; the telemetry
   extension feed is a later wiring item).
2. Frontier-approve blocks auto-rollback by design (human review wins).
3. rollback_log record uses ts/policy_id/reason/restored_from_sha.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: immune system, frontier memory (as the blocking guard),
  requirement ledger (gate record).
- How they were used: a real guard was registered for the router scoring
  policy, synthetic regressions were ingested, and the complete
  refuse/rollback lifecycle was exercised against the real router.py.
- Observed benefit: rollbacks now have an auditable trigger->action trail
  and cannot fire without evidence.
- Observed overhead: <5ms per operation.
- Token/context effect: none.
- Failures or friction: CLI log command crashed mid-demo because the
  rollback had moved router.py aside (import failure) — expected artifact,
  restored from git.
- Knowledge captured: n/a (demo records removed as synthetic).
- Memory/episode IDs: n/a.
- Candidate improvements: wire telemetry metrics into ingest_metric
  automatically; add success-rate guards per skill.
- Promotion decision: immune -> ACTIVE for policy-file guards only;
  triggers remain inert until metrics are fed.

## Rollback

- Git: revert this milestone's commits. Immune records are canonical files;
  a performed rollback is recorded and its .bak is preserved by design.

## Next gate

**Phase 23 — Policy Promotion** (plan §119): shadow -> candidate -> active
promotion with all guards (router evidence + frontier approve + immune
guard + credit history). Acceptance: a policy activates ONLY when all
guards pass.


## Phase 22 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase22-independent-verification.md):
1. NIT — test count corrected to 424 (15 immune tests; verifier collect is
   ground truth).
2. NIT — _write_json used a fixed .tmp name (same-file writer race); now
   uses a pid+timestamp-unique tmp name before os.replace.
