# v1 P4 Qualification Report — BLOCKED

**Decision:** BLOCKED. This report records the release gate exactly as observed; it does not authorize a v1.0.0 release and no tag was created. The current status ledger remains unchanged with P4.1–P4.5 `NOT QUALIFIED`.

## Candidate and evidence provenance

- Final source candidate for the checks below: `1e2db06028e4780c3b1a0c47c23dc4b58ff6c972`.
- Ruff remediation commits: `a659c34`, `23b0e4a`, `602abd3`, `04467be`; missing dataclass import repair: `07c8ab0`, `33b78e8`.
- Campaign hook project option: `2221972`; Prime wiring timing-test repair: `1e2db06`.
- Qualification manifest: [`qualification-manifest.json`](qualification-manifest.json)
  - stored source SHA: `db8944b6c31b23b6574d5b153408d62fe4f0b52e`
  - 18 required scenarios, all `passed`
  - 51 evidence references and matching hashes
- Independent verifier: [`independent-verifier.json`](independent-verifier.json)
  - stored top-level `ok: true`
  - all ten stored checks `ok: true`
  - 153 artifacts hashed; 119 artifacts privacy-scanned; zero stored hash/privacy/grounding failures
- The stored manifest/verifier is historical, not current release proof: subsequent source and test commits make its Git-currency window stale.
- Current real Antigravity pair attempt:
  [`../p3-promo-eval/p4-5-governed-b-1/evidence.json`](../p3-promo-eval/p4-5-governed-b-1/evidence.json) and
  [`../p3-promo-eval/p4-5-governed-c-1/evidence.json`](../p3-promo-eval/p4-5-governed-c-1/evidence.json).

The current pair used model `gemini-3.7-flash-medium`, deterministic acceptance passed in both arms, and each arm has a real conversation ID, wall time, and provider usage. Both were rejected by the campaign's validity guards because the CLI emitted no session-bound Brain hook payloads; the candidate arm additionally has no Lean injection proof. These raw captures are blocker evidence, not qualification evidence.

## P4 evidence disposition

The stored raw scenarios directly support P4.1–P4.4, but the stored manifest is not current at candidate `1e2db060...`; the failed P4.5 validity guards prevent release qualification and therefore the ledger is deliberately not changed. P4.5 remains unqualified because no current governed proposal/evaluation/activation record exists.

| Row | Evidence decision | Exact raw scenario references | Independent verifier checks | Release disposition |
|---|---|---|---|---|
| P4.1 Long-Running Goals | Direct scenario evidence supports the row: goal transitions `ACTIVE → BLOCKED → ACTIVE → COMPLETED`, with completion output. | `raw/long_running_goal/01-create.stdout`; `02-block.stdout`; `03-resume.stdout`; `04-complete-milestones.stdout` | `scenario_completeness`; `artifact_hash_integrity`; `database_integrity`; `backup_restore_preservation`; `claims_grounded`; `privacy_absence` | `NOT QUALIFIED` in current ledger; release blocked |
| P4.2 Schedules / Heartbeats | Direct active/off/shadow boundary evidence: active heartbeat ran and mutated maintenance; off did not run or mutate; shadow ran without maintenance mutation. | `raw/brain_on/02-pulse-active.stdout`; `raw/brain_off/02-pulse-off.stdout`; `raw/genuine_project_dogfood/03-p4-pulse-registered-project.stdout` | `off_shadow_boundaries`; `telemetry_validation`; `scenario_completeness`; `artifact_hash_integrity` | `NOT QUALIFIED` in current ledger; release blocked |
| P4.3 Operational Telemetry | Fresh qualification homes validate successfully, and P4 pulse outputs expose heartbeat latency/mode/mutation fields. Harness switch emits equivalent rows. | `raw/brain_on/02-pulse-active.stdout`; `raw/brain_off/02-pulse-off.stdout`; `raw/harness_switch/01-python-cli-pulse.stdout`; `raw/harness_switch/02-prime-bridge-direct-pulse.stdout` | `telemetry_validation`; `off_shadow_boundaries`; `scenario_completeness`; `artifact_hash_integrity`; `privacy_absence` | `NOT QUALIFIED` in current ledger; release blocked |
| P4.4 Bottleneck Fingerprinting | Direct Radar evidence observes and validates a candidate, then rejects tampered telemetry as `stale` with reason `telemetry_evidence_changed`. | `raw/stale_state/01-seed-telemetry.json`; `02-observe.stdout`; `03-validate-fresh.stdout`; `04-validate-stale.stdout` | `stale_and_unsafe_refusals`; `artifact_hash_integrity`; `claims_grounded`; `privacy_absence` | `NOT QUALIFIED` in current ledger; release blocked |
| P4.5 Controlled Self-Optimization | **Attempted, not qualified.** A real baseline/candidate Antigravity pair reached `agy_exit: 0` and deterministic `acceptance: PASS`, but both arms were rejected: no session-bound Brain hook telemetry or tool records; the candidate also lacks Lean injection proof. No `optimize propose`, `optimize evaluate`, or `optimize activate` artifact was created. | [`../p3-promo-eval/p4-5-governed-b-1/evidence.json`](../p3-promo-eval/p4-5-governed-b-1/evidence.json); [`../p3-promo-eval/p4-5-governed-c-1/evidence.json`](../p3-promo-eval/p4-5-governed-c-1/evidence.json); raw `agy-stream.jsonl` beside each record | No current verifier check can convert rejected arms into governed P4.5 evidence; rollback checks remain insufficient. | **`NOT QUALIFIED / BLOCKED`** |

## Current P4.5 attempt details

The real pair was executed after source stabilization at candidate `1e2db06028e4780c3b1a0c47c23dc4b58ff6c972` with `P3_AGY_MODEL=gemini-3.7-flash-medium`, `P3_AGY_PROJECT=second-brain`, and the `e07-jsonc-config` fixture:

| Arm | Session | Lean | Wall | Provider usage total | Acceptance | Validity |
|---|---|---|---:|---:|---|---|
| Baseline `b` | `e9bb9ba5-acda-4a8b-9f4b-5e4d6ebc3d26` | `OFF` | 73,362 ms | 16,152 | `PASS` | `REJECTED` |
| Candidate `c` | `c5523871-f6ca-4830-a4be-8202c069015c` | `ON` | 68,917 ms | 16,049 | `PASS` | `REJECTED` |

The raw `agy-stream.jsonl` files contain real model/tool events and usage. The installed hook transport appended only `preinvocation_no_task` records with the anonymous session `antigravity-anon`; no record matched either real conversation ID. The campaign therefore correctly refused both arms, and no token delta, radar fingerprint, candidate binding, proposal, evaluation, activation, or promotion was inferred.

Raw SHA-256: baseline evidence `4913801e33c06627da07f74db0c674398fc94506831921aed570e189d9018633`, baseline stream `8cb07f94f6030f98b552e7d9f2a5bb2faa0b0ec2c3a3f05e7f73d07623f95cf4`; candidate evidence `010d0fbf2b7468d21d1f5e1a5976c23e775f997647f2b8edd174e83ec854ce1f`, candidate stream `9bbf3086d25ba7d91c718234069c74ec93ea02aa90e7b13cd49f0cdbeef3aab3`.

## Independent verifier result

All stored checks are true: `scenario_completeness`, `artifact_hash_integrity`, `git_currency`, `database_integrity`, `telemetry_validation`, `backup_restore_preservation`, `stale_and_unsafe_refusals`, `off_shadow_boundaries`, `claims_grounded`, and `privacy_absence`. This is evidence integrity, not a substitute for a missing P4.5 lifecycle scenario.

## Final required checks

The latest complete gate was run against candidate `1e2db06028e4780c3b1a0c47c23dc4b58ff6c972` with the required sanitized Python environment and Prime-extension cwd. Every required command exited `0`.

| # | Exact command | CWD | Result |
|---|---|---|---|
| 1 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m ruff check src tests scripts` | repository root | **PASS** |
| 2 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pyright` | repository root | **PASS** — 0 errors, 0 warnings, 0 informations |
| 3 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q` | repository root | **PASS** |
| 4 | `npm run lint` | `brainstem/prime-extension` | **PASS** |
| 5 | `npm run typecheck` | `brainstem/prime-extension` | **PASS** |
| 6 | `npm test -- --reporter=dot` | `brainstem/prime-extension` | **PASS** — 26 files, 629 tests |

The first post-remediation Prime full-suite attempt exposed an asynchronous test wait race; isolated reproduction passed. Commit `1e2db06` raises only the two affected telemetry wait thresholds, after which the full Prime suite passed. This test repair does not qualify P4.5.

## P4 incremental measurements

These are measurements exposed by the qualification host; unavailable host metrics are explicitly null.

- Heartbeat latency: active `37 ms` (`brain_on`), shadow `42 ms` (`genuine_project_dogfood`), off `0 ms`; compact checkpoint `0.674 ms`.
- Cache-sensitive retrieval: miss `383.152 ms`, hit `20.369 ms`, a measured `362.783 ms` lower hit latency (no model token economics exposed).
- Model calls: `0` background model calls in every scenario; provider/model token fields are null.
- Tool calls: `0` in the recorded Brain scenario metrics.
- Context bytes: token-pressure input `156,000` original bytes; peak context is unavailable (`null`).
- Success: 18/18 qualification scenarios passed; this does not override failed final gates.
- Verification: independent verifier 10/10 checks true; 153 artifact hashes checked; 0 privacy offenders; 0 ungrounded claims.
- Rollback: Immune `recovery_rollback` passed with `rolled_back: true`, and unsafe rollback target refusal passed. This is rollback evidence, not P4.5 optimization activation evidence.

## Honest baseline keys

| Key | Value | Basis |
|---|---:|---|
| `v1_total_tokens` | `null` | provider token totals were unavailable |
| `v1_verified_tasks` | `18` | 18 qualification scenarios passed |
| `v1_context_peak` | `null` | not exposed by host |
| `v1_repeated_reads` | `null` | not exposed by host |
| `v1_files_read` | `null` | not exposed by host |
| `v1_tool_calls` | `0` | recorded scenario metrics |
| `v1_compactions` | `1` | compacted-session metric |
| `v1_driver_tokens` | `null` | not exposed by host |
| `v1_worker_tokens` | `null` | not exposed by host |
| `v1_premium_model_turns` | `null` | not exposed by host |
| `v1_cache_behavior` | `{"miss_latency_ms":383.152,"hit_latency_ms":20.369,"hit_after_miss":true}` | cache-sensitive scenario |
| `v1_user_corrections` | `null` | not exposed by host |
| `v1_rework` | `null` | not exposed by host |

## Historical telemetry issues

Historical reports remain historical and are not rewritten. The Task 8 qualification deliberately isolated `driver_worker` and `failed_worker` in dedicated Brain homes because of a pre-existing worker-plane telemetry schema gap. Fresh qualification telemetry validation itself passed across the three qualification homes (15 records total, zero issues), but that does not cleanse historical telemetry or prove the missing P4.5 lifecycle. The current ledger and README/current-state documents were not updated because this release gate failed.

## Migration and recovery surface (for a future gated release)

Migration `0010_p4_operations.sql` is applied by `db.migrate()` during `brainctl init` and on P4 stores. The primary state is `db/brain.sqlite`; migration 0010 stores goals, goal events, bottleneck fingerprints, heartbeat state, and heartbeat runs there. Existing backup/restore snapshots include these records through the primary database snapshot.

Guarded recovery commands (run against an isolated Brain home when validating):

```powershell
brainctl init
brainctl status                 # reopen/read the primary DB in a fresh process
brainctl backup --note v1-p4
brainctl restore <backup-dir> --force
brainctl telemetry validate
brainctl telemetry report --json
brainctl heartbeat run --event session_start --session release-smoke --force --json
brainctl immune rollback <policy-id> <trigger-id> --reason "verified recovery"
brainctl optimize rollback <proposal-id> <trigger-id> --reason "verified recovery" --json
```

No release tag was created, no post-tag smoke was run, and no V2-A or later v2 behavior was started.

## Remediation result

The declared Python development extras were installed into the linked worktree venv with `uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`, including Ruff, Pyright, and Hypothesis. The final checks above pass at the exact candidate SHA.

The baseline experiment proved 102 pre-existing Ruff findings in the two legacy campaign scripts at the P0–P3 checkpoint; the remaining 170 findings were introduced by the P4/P4.5 implementation surface. All 272 findings were repaired without changing scenario inputs, evidence values, verifier semantics, or gate policy. The production import regression found during review was repaired and import ordering then passed Ruff.

The earlier synthetic P4.5 extension was reviewed as unsafe and reverted (`a657a4f`); it is not evidence. The current real provider pair is also not qualification evidence because the Antigravity CLI supplied no session-bound hook payload. The release remains blocked rather than waiving the guard.
