# v1 Release Baseline — Second Brain v1.0.0

This is the frozen v1.0.0 baseline. It is the current release proof, generated fresh in this task, not a historical or stale capture.

## Source and qualification provenance

- Release candidate SHA: `07e506060914df468cbb4c5095d70eb74ab28340`.
- Manifest: [`outputs/reports/v1-p4/qualification-manifest.json`](v1-p4/qualification-manifest.json) — regenerated fresh in this task; recorded source SHA is byte-identical to the release candidate; 18/18 scenarios passed; 51 evidence references, all hash-matched.
- Independent verifier: [`outputs/reports/v1-p4/independent-verifier.json`](v1-p4/independent-verifier.json) — regenerated fresh in this task, `ok: true`, all ten checks `true`, including `git_currency` (`recorded_sha == fresh_sha`, exact match not merely ancestor).
- Detailed disposition: [`outputs/reports/v1-p4/qualification-report.md`](v1-p4/qualification-report.md).
- Authoritative 37-item status ledger: [`outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`](rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md) — P0.1 through P4.5, all `PROVEN`.
- P4.5 real Antigravity/Gemini pair: [`outputs/reports/p3-promo-eval/p4-5-fixed-b-1/evidence.json`](p3-promo-eval/p4-5-fixed-b-1/evidence.json) (baseline, Lean OFF, `VALID_COMPLETE`) and [`outputs/reports/p3-promo-eval/p4-5-fixed-c-1/evidence.json`](p3-promo-eval/p4-5-fixed-c-1/evidence.json) (candidate, Lean ON, `VALID_COMPLETE`).
- P4.5 governed lifecycle artifacts: [`outputs/audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json`](../audits/counterfactual/skill/lean-code-p4-5-e07-jsonc-config-lean-code-eval1.json), [`outputs/audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json`](../audits/optimization/proposal-9b1eabfe5e023d012b30aeaf-v3.json), [`skills/candidates/lean-code/candidate-binding.json`](../../skills/candidates/lean-code/candidate-binding.json).

## P4.5 result — read this correctly

```text
Baseline (Lean OFF) cumulative total tokens:  94,103
Candidate (Lean ON) cumulative total tokens:  94,476
Net saved (baseline - candidate):                -373
```

The evaluated Lean-code candidate had **measured negative ROI**. The governed optimization system correctly:

1. observed real behavior (`radar observe` → real `SEARCH_THRASH` fingerprint `fp-c4e5249a75e3`);
2. bound a real candidate (`skillforge.bind_candidate`, source=radar);
3. computed real economics (`credit.counterfactual_result`, from genuine cumulative session telemetry, not a single-call snapshot);
4. evaluated it (`optimize evaluate` — quality gates passed, ROI gate failed, `status: hold`);
5. refused activation (`optimize activate` → `{"activated": false, "reason": "evaluation_not_proven"}`).

**This is the qualifying evidence for P4.5.** It does not mean Lean-code saves tokens in this campaign, and the `lean-code` candidate remains `candidate / HOLD_SHADOW` — correctly not promoted.

## Economics baseline

| Key | Value | Evidence / limitation |
|---|---:|---|
| `v1_total_tokens` | `null` | not exposed by the qualification-scenario host; P4.5 real-provider pair reports 94,103 / 94,476 above |
| `v1_verified_tasks` | `18` | all 18 qualification scenarios passed |
| `v1_context_peak` | `null` | host did not expose peak |
| `v1_repeated_reads` | `null` | host did not expose metric |
| `v1_files_read` | `null` | host did not expose metric |
| `v1_tool_calls` | `0` | recorded scenario metrics (qualification host); real P4.5 pair recorded 14 (baseline) / 12 (candidate) |
| `v1_compactions` | `1` | compacted-session scenario |
| `v1_driver_tokens` | `null` | host did not expose metric |
| `v1_worker_tokens` | `null` | host did not expose metric |
| `v1_premium_model_turns` | `null` | host did not expose model tier |
| `v1_cache_behavior` | `miss=383.152 ms; hit=20.369 ms; hit_after_miss=true` | cache-sensitive raw artifacts |
| `v1_user_corrections` | `null` | host did not expose metric |
| `v1_rework` | `null` | host did not expose metric |
| `v1_p4_5_net_tokens_saved` | `-373` | real counterfactual result; governance correctly refused activation |

Additional exposed P4 measurements: active heartbeat `37 ms`, shadow heartbeat `42 ms`, off path `0 ms`, compact checkpoint `0.674 ms`, token-pressure input `156,000` bytes. Peak context, background model calls beyond the recorded `0`, and model/token economics beyond the P4.5 real pair above are unavailable; no economics should be inferred beyond what is stated.

## Gate status — all six canonical checks pass

Rerun from scratch in this task, at the exact release candidate:

| Check | Result |
|---|---|
| `ruff check src tests scripts` | **PASS** |
| `pyright` | **PASS** — 0 errors, 0 warnings, 0 informations |
| `pytest -q` | **PASS** — 90 files, 1,420 tests |
| `npm run lint` (`brainstem/prime-extension`) | **PASS** |
| `npm run typecheck` (`brainstem/prime-extension`) | **PASS** |
| `npm test -- --reporter=dot` (`brainstem/prime-extension`) | **PASS** — 26 files, 629 tests |

## P4.1–P4.5 disposition

All five rows are `PROVEN`. See [`outputs/reports/v1-p4/qualification-report.md`](v1-p4/qualification-report.md) for the full per-row evidence table and [`outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`](rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md) for the authoritative 37-item ledger.

## Root-cause fixes that unblocked P4.5

1. **Antigravity hook telemetry transport (`a74b285`)**: the PowerShell launcher closed the .NET `StreamWriter` wrapper instead of its raw `.BaseStream`, which flushed a stray UTF-8 BOM into the child Python process's stdin, breaking `json.loads()` on nearly every real invocation and silently degrading identity to the anonymous/no-task fallback. Fixed by driving the child process through explicit raw-byte `.BaseStream` I/O throughout, and by decoding stdin explicitly as `utf-8-sig` on the Python side instead of relying on the locale-dependent default (confirmed `cp1252` on this host absent `PYTHONIOENCODING`).
2. **Harness-neutral token schema (`cc3bfc1`)**: `credit.py`'s counterfactual economics schema mandated a `cache_write` counter that the real Gemini/Antigravity `agy` CLI usage schema never reports; made it nullable like the pre-existing `reasoning` field rather than fabricating `0`.

Both fixes were independently reviewed (APPROVE) and covered by new regression tests exercising the real subprocess/byte-transport path, not mocks.

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

Migration `0010_p4_operations.sql` creates the primary P4 tables in `db/brain.sqlite`: `goals`, `goal_events`, `bottleneck_fingerprints`, `heartbeat_state`, and `heartbeat_runs`. `db.migrate()` is idempotent and is called by initialization and P4 stores. The fresh `backup_restore_preservation` verifier check confirms a real goal and a real fingerprint both survive a genuine backup/restore round trip at this candidate.

## Scope boundary

`V2-A` and all later v2 behavior are **not started**. This baseline is the frozen boundary V2 work builds on top of, not replaces.

## Release commit and tag

- Release/freeze commit: recorded after this document was written; see `git log` for the exact SHA immediately following this file's commit.
- Tag: `v1.0.0`, annotated, created only after the independent verifier and all six gates above passed on this exact candidate.
