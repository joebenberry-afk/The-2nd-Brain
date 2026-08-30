# v1 P4 Qualification Report — QUALIFIED

**Decision:** All P4.1–P4.5 rows are qualified with current, freshly regenerated evidence at the exact release candidate. This report was regenerated end-to-end (not hand-edited) by rerunning `scripts/run_v1_p4_qualification.py` and `scripts/verify_v1_p4_qualification.py` against the current working tree.

## Candidate and evidence provenance

- Candidate SHA: `07e506060914df468cbb4c5095d70eb74ab28340`.
- Prior remediation commits on this branch: Ruff/import repairs (`33b78e8`, `04467be`, `07c8ab0`), campaign hook option (`2221972`), Prime wiring timing fix (`1e2db06`), blocked-gate record (`6b5077b`), Antigravity hook BOM/StreamWriter fix (`a74b285`), harness-neutral `cache_write` token schema (`cc3bfc1`), P4.5 governed evaluation evidence (`07e5060`).
- Qualification manifest: [`qualification-manifest.json`](qualification-manifest.json), regenerated `2026-08-30T07:33:25Z`
  - recorded source SHA: `07e506060914df468cbb4c5095d70eb74ab28340` (identical to `HEAD`, not merely an ancestor)
  - 18/18 required scenarios `passed`, 0 failed
  - 51 evidence references, all with matching sha256 hashes
- Independent verifier: [`independent-verifier.json`](independent-verifier.json), regenerated in the same pass
  - top-level `ok: true`
  - all ten checks `ok: true`, including `git_currency` (`recorded_sha == fresh_sha`, 0 disallowed intervening paths)
  - `artifact_hash_integrity`: 153 artifacts checked, 0 mismatches, 0 missing, 0 unhashed
  - `privacy_absence`: 119 artifacts scanned, 0 offenders
  - `claims_grounded`: 0 failures
- P4.5 real Antigravity/Gemini pair (post BOM/StreamWriter fix):
  [`../p3-promo-eval/p4-5-fixed-b-1/evidence.json`](../p3-promo-eval/p4-5-fixed-b-1/evidence.json) and
  [`../p3-promo-eval/p4-5-fixed-c-1/evidence.json`](../p3-promo-eval/p4-5-fixed-c-1/evidence.json).
- P4.5 governed evaluation artifacts:
  [`../../audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json`](../../audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json),
  [`../../audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json`](../../audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json),
  [`../../../skills/candidates/lean-code/candidate-binding.json`](../../../skills/candidates/lean-code/candidate-binding.json).

## P4 evidence disposition

| Row | Evidence decision | Exact raw scenario references | Independent verifier checks | Release disposition |
|---|---|---|---|---|
| P4.1 Long-Running Goals | Fresh scenario evidence: goal transitions `ACTIVE → BLOCKED → ACTIVE → COMPLETED`, with completion output. | `raw/long_running_goal/01-create.stdout`; `02-block.stdout`; `03-resume.stdout`; `04-complete-milestones.stdout` | `scenario_completeness`; `artifact_hash_integrity`; `database_integrity`; `backup_restore_preservation`; `claims_grounded`; `privacy_absence` | `QUALIFIED` |
| P4.2 Schedules / Heartbeats | Fresh active/off/shadow boundary evidence: active heartbeat ran and mutated maintenance; off did not run or mutate; shadow ran without maintenance mutation. | `raw/brain_on/02-pulse-active.stdout`; `raw/brain_off/02-pulse-off.stdout`; `raw/genuine_project_dogfood/03-p4-pulse-registered-project.stdout` | `off_shadow_boundaries`; `telemetry_validation`; `scenario_completeness`; `artifact_hash_integrity` | `QUALIFIED` |
| P4.3 Operational Telemetry | Fresh qualification homes validate successfully; P4 pulse outputs expose heartbeat latency/mode/mutation fields; harness switch emits equivalent rows. | `raw/brain_on/02-pulse-active.stdout`; `raw/brain_off/02-pulse-off.stdout`; `raw/harness_switch/01-python-cli-pulse.stdout`; `raw/harness_switch/02-prime-bridge-direct-pulse.stdout` | `telemetry_validation`; `off_shadow_boundaries`; `scenario_completeness`; `artifact_hash_integrity`; `privacy_absence` | `QUALIFIED` |
| P4.4 Bottleneck Fingerprinting | Fresh Radar evidence observes and validates a candidate, then rejects tampered telemetry as `stale` with reason `telemetry_evidence_changed`. Also directly exercised for real by the P4.5 pair below (`radar observe` on the candidate session found a genuine `SEARCH_THRASH` fingerprint, `fp-c4e5249a75e3`). | `raw/stale_state/01-seed-telemetry.json`; `02-observe.stdout`; `03-validate-fresh.stdout`; `04-validate-stale.stdout` | `stale_and_unsafe_refusals`; `artifact_hash_integrity`; `claims_grounded`; `privacy_absence` | `QUALIFIED` |
| P4.5 Controlled Self-Optimization | **Qualified.** A real Antigravity/Gemini baseline/candidate pair (post BOM/StreamWriter transport fix) reached `agy_exit: 0`, deterministic `acceptance: PASS` in both arms, and **both arms are `validity: VALID_COMPLETE`** with real session-bound Brain hook telemetry (45 and 39 records respectively, all under the arm's own real `conversationId`) and real Lean ON/OFF proof (`lean_decision: omit`/`inject`, `lean_kernel_chars: 0`/`865` on every turn). The full governed lifecycle — Radar fingerprint → candidate binding → `credit.counterfactual_result()` computed from genuine cumulative session telemetry → `optimize propose` → `optimize evaluate` → `optimize activate` — was exercised end-to-end through the real CLI. The evaluated Lean candidate showed **negative** measured ROI (candidate used 373 more cumulative tokens than baseline) and the governance system **correctly refused activation** (`{"activated": false, "reason": "evaluation_not_proven"}`). This is qualification of the governed mechanism, not a promotion of this Lean candidate. | [`../p3-promo-eval/p4-5-fixed-b-1/evidence.json`](../p3-promo-eval/p4-5-fixed-b-1/evidence.json); [`../p3-promo-eval/p4-5-fixed-c-1/evidence.json`](../p3-promo-eval/p4-5-fixed-c-1/evidence.json); [`../../audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json`](../../audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json); [`../../audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json`](../../audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json) | Manual re-derivation from raw evidence performed in this task independently reproduced the same `net_tokens_saved: -373`, `status: hold`, and refused-activation result; `stale_and_unsafe_refusals`; `artifact_hash_integrity`; `claims_grounded`; `privacy_absence` | **`QUALIFIED`** |

## P4.5 governed lifecycle — exact chain

```text
radar observe <candidate session>          -> fp-c4e5249a75e3 (SEARCH_THRASH / RETRIEVAL_OVERLOAD)
skillforge.bind_candidate(source=radar)    -> skill-candidate-8845b97d4799c9c9eff7d26f
credit.counterfactual_result(...)          -> with(94,476 total tokens) vs without(94,103 total tokens)
optimize propose fp-c4e5249a75e3           -> proposal-9b1eabfe5e023d012b30aeaf (shadow)
optimize evaluate <proposal> --result-json -> quality gates PASS, ROI gate FAIL, status=hold
optimize activate <proposal>               -> {"activated": false, "reason": "evaluation_not_proven"}
```

No campaign script, test harness, or report ever wrote to `telemetry/agent-performance/antigravity-hooks.jsonl`; the campaign runner only reads it, filtered by the real session id (verified by inspection of `scripts/run_p3_promotion_campaign.py`). No hard-coded token economics, no forced activation, no manufactured session correlation.

## Critical interpretation — do not misread

```text
Baseline total tokens: 94,103
Candidate total tokens: 94,476
Net saved:              -373
```

The candidate had **negative measured ROI**. This is **not** a release blocker: the canonical P4.5 requirement is that the governed optimization mechanism can observe, bind, evaluate, and correctly refuse an unprofitable change — which it did. It is **not** evidence that Lean-code saves tokens in this campaign, and it must never be reported as a successful promotion.

## Independent verifier result

All ten checks are `true` on this fresh run: `scenario_completeness`, `artifact_hash_integrity`, `git_currency`, `database_integrity`, `telemetry_validation`, `backup_restore_preservation`, `stale_and_unsafe_refusals`, `off_shadow_boundaries`, `claims_grounded`, `privacy_absence`. `git_currency` reports the recorded manifest SHA and fresh `HEAD` SHA as byte-identical (not merely an ancestor), so this is current release proof, not historical evidence.

## Final required checks (fresh, this task)

Every command below was rerun from scratch in this task, after Task 8 regeneration, against the exact candidate commit.

| # | Exact command | CWD | Result |
|---|---|---|---|
| 1 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m ruff check src tests scripts` | repository root | **PASS** |
| 2 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pyright` | repository root | **PASS** — 0 errors, 0 warnings, 0 informations |
| 3 | `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q` | repository root | **PASS** — 90 files, 1,420 tests |
| 4 | `npm run lint` | `brainstem/prime-extension` | **PASS** |
| 5 | `npm run typecheck` | `brainstem/prime-extension` | **PASS** |
| 6 | `npm test -- --reporter=dot` | `brainstem/prime-extension` | **PASS** — 26 files, 629 tests |

## P4 incremental measurements

Measurements exposed by the qualification host; unavailable host metrics are explicitly null.

- Heartbeat latency: active `37 ms` (`brain_on`), shadow `42 ms` (`genuine_project_dogfood`), off `0 ms`; compact checkpoint `0.674 ms`.
- Cache-sensitive retrieval: miss `383.152 ms`, hit `20.369 ms`, a measured `362.783 ms` lower hit latency.
- P4.5 real-provider economics (Gemini `gemini-3.7-flash-medium`, `e07-jsonc-config` fixture): baseline 15 model calls / 94,103 cumulative total tokens / 14 tool calls / 48,838 ms wall time; candidate 13 model calls / 94,476 cumulative total tokens / 12 tool calls / 38,971 ms wall time. Candidate used fewer model calls, fewer tool calls, and less wall time, but slightly more cumulative tokens — reported exactly as measured, no averaging across a favorable subset.
- Success: 18/18 qualification scenarios passed; P4.5 real pair 2/2 arms `VALID_COMPLETE`.
- Verification: independent verifier 10/10 checks true; 153 artifact hashes checked, 0 mismatches; 0 privacy offenders; 0 ungrounded claims.
- Rollback: Immune `recovery_rollback` passed with `rolled_back: true`, and unsafe rollback target refusal passed.

## Honest baseline keys

| Key | Value | Basis |
|---|---:|---|
| `v1_total_tokens` | `null` | not exposed by the qualification-scenario host; the separate P4.5 real-provider pair reports 94,103 / 94,476 above |
| `v1_verified_tasks` | `18` | 18 qualification scenarios passed |
| `v1_context_peak` | `null` | not exposed by host |
| `v1_repeated_reads` | `null` | not exposed by host |
| `v1_files_read` | `null` | not exposed by host |
| `v1_tool_calls` | `0` | recorded scenario metrics (qualification-scenario host); real P4.5 pair recorded 14/12 above |
| `v1_compactions` | `1` | compacted-session metric |
| `v1_driver_tokens` | `null` | not exposed by host |
| `v1_worker_tokens` | `null` | not exposed by host |
| `v1_premium_model_turns` | `null` | not exposed by host |
| `v1_cache_behavior` | `{"miss_latency_ms":383.152,"hit_latency_ms":20.369,"hit_after_miss":true}` | cache-sensitive scenario |
| `v1_user_corrections` | `null` | not exposed by host |
| `v1_rework` | `null` | not exposed by host |
| `v1_p4_5_net_tokens_saved` | `-373` | real counterfactual result; candidate used more tokens, governance correctly refused activation |

## Migration and recovery surface

Migration `0010_p4_operations.sql` is applied by `db.migrate()` during `brainctl init` and on P4 stores. The primary state is `db/brain.sqlite`; migration 0010 stores goals, goal events, bottleneck fingerprints, heartbeat state, and heartbeat runs there. Existing backup/restore snapshots include these records through the primary database snapshot. The fresh `backup_restore_preservation` verifier check confirms a real goal and a real fingerprint both survive a genuine backup/restore round trip at this candidate.

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

## History

Prior report revisions in this file's history recorded genuinely blocked states (missing dev extras, 272 Ruff findings, then a P4.5 Antigravity telemetry transport bug) at earlier candidate SHAs. Those blockers were real at the time and are not retracted; they were resolved by the commits listed under Candidate and evidence provenance above, and this revision reflects the fully qualified state at the final candidate SHA.
