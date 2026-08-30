# v1 Release Baseline — BLOCKED / NOT FROZEN

This is the honest baseline captured after the final remediation checks. It is **not** a v1.0.0 release baseline: no release commit or tag exists because P4.5 lacks current governed optimization evidence. Do not use this document to claim release eligibility.

## Source and qualification provenance

- Final remediation candidate: `1e2db06028e4780c3b1a0c47c23dc4b58ff6c972`.
- Historical Task 8 manifest source SHA: `db8944b6c31b23b6574d5b153408d62fe4f0b52e`; subsequent source/test commits make it stale for release currency.
- Manifest: [`outputs/reports/v1-p4/qualification-manifest.json`](v1-p4/qualification-manifest.json); its 18-scenario evidence remains historical.
- Stored verifier: [`outputs/reports/v1-p4/independent-verifier.json`](v1-p4/independent-verifier.json), `ok: true`, all ten stored checks true at capture time.
- Detailed disposition: [`outputs/reports/v1-p4/qualification-report.md`](v1-p4/qualification-report.md).
- Current real pair captures: [`outputs/reports/p3-promo-eval/p4-5-governed-b-1/evidence.json`](p3-promo-eval/p4-5-governed-b-1/evidence.json) and [`outputs/reports/p3-promo-eval/p4-5-governed-c-1/evidence.json`](p3-promo-eval/p4-5-governed-c-1/evidence.json); both deterministic judges passed, both campaign validity checks rejected them for missing session-bound hook telemetry.

## Economics baseline

| Key | Value | Evidence / limitation |
|---|---:|---|
| `v1_total_tokens` | `null` | host did not expose provider totals |
| `v1_verified_tasks` | `18` | all 18 qualification scenarios passed |
| `v1_context_peak` | `null` | host did not expose peak |
| `v1_repeated_reads` | `null` | host did not expose metric |
| `v1_files_read` | `null` | host did not expose metric |
| `v1_tool_calls` | `0` | recorded Brain scenario metrics |
| `v1_compactions` | `1` | compacted-session scenario |
| `v1_driver_tokens` | `null` | host did not expose metric |
| `v1_worker_tokens` | `null` | host did not expose metric |
| `v1_premium_model_turns` | `null` | host did not expose model tier |
| `v1_cache_behavior` | `miss=383.152 ms; hit=20.369 ms; hit_after_miss=true` | cache-sensitive raw artifacts; token economics unavailable |
| `v1_user_corrections` | `null` | host did not expose metric |
| `v1_rework` | `null` | host did not expose metric |

Additional exposed P4 measurements: active heartbeat `37 ms`, shadow heartbeat `42 ms`, off path `0 ms`, compact checkpoint `0.674 ms`, and token-pressure input `156,000` bytes. Peak context, model calls beyond the recorded `0` background calls, and model/token economics are unavailable; no economics should be inferred.

## Gate status

The complete canonical checks pass at candidate `1e2db06028e4780c3b1a0c47c23dc4b58ff6c972`: repository Ruff, Pyright, full Python pytest, Prime lint, Prime typecheck, and Prime tests (`26` files / `629` tests) all exited `0`.

Release remains blocked for two evidence reasons:

1. The stored Task 8 manifest/verifier predates the remediation commits and is not current release proof under the verifier's conservative Git-currency rule.
2. P4.5 is `NOT QUALIFIED`: the current real Antigravity baseline/candidate pair passed deterministic acceptance but both arms were rejected because the CLI supplied no session-bound Brain hook telemetry; the candidate also lacks Lean injection proof. No proposal/evaluation/activation was inferred or recorded.

## Recovery and migration instructions

Use an isolated Brain home for validation. Never point these commands at user memory while testing recovery.

```powershell
# Fresh initialization; db.migrate() applies migration 0010.
brainctl init

# Fresh-process reopen and health check.
brainctl status
brainctl doctor --json

# Primary snapshot includes db/brain.sqlite and therefore P4 records.
brainctl backup --note v1-p4

# Restore a selected backup, with explicit operator intent.
brainctl restore <backup-dir> --force

# Validate records after restore.
brainctl telemetry validate
brainctl telemetry report --json

# Verify heartbeat mode and primary P4 state.
brainctl heartbeat run --event session_start --session release-smoke --force --json

# Guarded rollback only after trigger/policy evidence is present.
brainctl immune rollback <policy-id> <trigger-id> --reason "verified recovery"
brainctl optimize rollback <proposal-id> <trigger-id> --reason "verified recovery" --json
```

Migration `0010_p4_operations.sql` creates the primary P4 tables in `db/brain.sqlite`: `goals`, `goal_events`, `bottleneck_fingerprints`, `heartbeat_state`, and `heartbeat_runs`. `db.migrate()` is idempotent and is called by initialization and P4 stores. Existing backup/restore preserves these records through the primary database snapshot.

## Recovery gate for a future release

Resolve the Antigravity CLI hook-payload gap, obtain valid paired host/provider telemetry with Lean ON/OFF proof, regenerate Task 8 qualification/verifier evidence at the resulting commit, and rerun the six required final commands as a new gate. Only after all P4 rows, security/integrity, and economics gates pass may current documentation be updated and an annotated `v1.0.0` tag be created. Do not begin V2-A before that gate passes.
