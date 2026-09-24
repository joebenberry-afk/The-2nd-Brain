# V3 S1 — fast, observable, non-interfering Brain (candidate report)

Date: 2026-09-24. Branch `brain/v3-s1` in `.worktrees/v3-s1`, parent `749e9cd` (the activated
M00 runtime). Not deployed: the live OMP extension, the production venv, the live database and
all live configuration are untouched. Requirements: `docs/intake/Second_Brain_V3_Requirements_2026-09-24/`
(bundle checksums verified against its `SHA256SUMS.txt`).

## 1. Baseline binding (PORT-02)

| Fact | Evidence |
|---|---|
| Installed runtime = `.worktrees/qualified-m00` @ `749e9cda8d55`, clean | `brainctl doctor` identity coherence; `second_brain.__file__` from `.venv` |
| Installed OMP extension = `749e9cd:brainstem/prime-extension/src` | all 16 `.ts` files byte-identical after CRLF normalization (`types/prime.d.ts` lives in `brainstem/prime-extension/types`) |
| Schema 28, 116 memories | `m00-activation-20260924/05-db-state.txt`; pilot corpus snapshot `db_sha256 738d4553…` |
| Root checkout is a stale branch (`brain/v1-rc4-prime-074-compat`, ahead 22 / behind 43) | its tests import removed modules against the installed runtime: 7 collection errors are a checkout/runtime mismatch, not a runtime defect |
| Health before S1 | `doctor` 21/21 PASS; M00 suite 2157 collected: all pass, 1 skip; ruff + pyright clean |

## 2. Requirement map (S1 scope)

Status words: SATISFIED (evidence below), CHANGED (S1 patch), PARTIAL, FAIL, NOT_RUN.

| ID | Status | Evidence / residual |
|---|---|---|
| ARCH-01 | CHANGED | Antigravity `Stop` returned `{"decision":"continue"}` on unresolved critical requirements (`adapters/antigravity.py` @749e9cd:229-232) — now always `{}` after memory finalization. OMP `session_before_compact` returned `{cancel:true}` on Brain checkpoint failure (`index.ts` 3 sites) — now records `ledger_degraded` and never vetoes (CTX-03). Hermes plugin registers only `second_brain_writeback` + `second_brain_handoff_read`; retired worker events refuse with `ORCHESTRATION_REMOVED` (static read, no gateway change needed). Python adapters: no remaining stop/continue/block/cancel outputs (grep). Residual: `verify.py` still reads requirement `blocks` for Brain's own CLI verification (not a host hook). Brain-on/off lifecycle exercise on Antigravity/Hermes hosts: NOT_RUN. |
| ARCH-02 | NOT_ASSESSED | Two-host core-fixture run is S5 work. |
| ARCH-03 | PARTIAL | Background environment assessment now returns a structured error on spawn failure (`environment-mirror.test.ts`). Pre-existing gaps kept: missing venv still maps to `ok:true` in `active-state-mirror.ts` / `environment-mirror.ts`; CLI `BrainError` prints to stderr, not JSON. Fault-injection matrix (missing interpreter, locked DB, broken index, slow encoder, malformed payload): NOT_RUN. |
| ARCH-04 | SATISFIED for S1 | Candidate adds no dependency, daemon, database, GPU or network service. Offline default-profile run: NOT_RUN. |
| PERF-01 | PARTIAL | Removed per-turn model-visible Brain text that carried no benefit: the prompt-echo `brain.active-state` message (577/117 chars) and the `[second-brain-prefix-extras] Project:` system-prompt line. **FAIL remains:** with the project resolved, a no-benefit prompt ("Reply with exactly: NB-OK-17. Do not use any tools.") still receives an unrelated packet in both M00 (1386 chars) and candidate (1267 chars) — lexical `tools`+`use` satisfy 2 of 3 IDF terms (`mem-d7311da506a7`). With the project unresolved (pilot 1, superseded), candidate input tokens equalled native exactly (9651 = 9651; M00 9704). Lean kernel (865 chars, live `advisory`) is config-governed; strict profile needs it off — production config not changed. |
| PERF-02 | PARTIAL | Pre-dispatch overhead vs inert roughly halved (table §4) but ~1.3–1.7 s remains against the 100 ms p95 target. |
| PERF-03 | PARTIAL | Harness sums host-reported usage per request and keeps provider `responseId`s; Brain-local CPU/spawn accounting not yet reconciled with it. |
| PERF-04 | CHANGED | Profiled: (a) synchronous `env assess` spawn ~1.4 s blocking the host event loop per new prompt and at session start → now background; (b) retrieval opened a connection and re-listed migrations per scored row (320 connects / 20 retrieves) → at-head cache + one batched activation query: miss 25.3 → 10.9 ms, hit 12.8 → 10.6 ms; (c) visibility planning serialized behind AutoInject → concurrent. Remaining cost is structural: ~130 ms package import per spawn × 3 serial spawns. E01 (reused interpreter / in-host) comparison: NOT_RUN. |
| RET-02 | CHANGED | Named live regression reproduced deterministically (full-prompt IDF top-8 picked boilerplate; `msm` 4/8 excluded the memory). Fix: when the full query returns nothing, retry with explicit question sentences, label and project-name words removed (whole words only; exact symbols such as `src/second_brain/x.py` kept). Host result: instruction-heavy prompt delivered `mem-a8d221e64549` in 3/3 candidate runs vs 0/3 M00. Limitation: when boilerplate matches some memory, the retry never runs (full query first by design, to keep appended constraints). |
| PORT-02 | PARTIAL | Harness records imported source identity per arm (module path, git sha, dirty flag, source-tree fingerprint) and an LF-normalized extension manifest. Hermes/Antigravity entrypoints do not record imported identity; no stale-plugin/gateway-restart detection exists (pre-existing). |
| VAL-01 | PARTIAL | `scripts/v3_matched_arms.py`: native / inert (`scripts/v3_inert_extension.ts`) / M00 / candidate, same model, thinking, prompt, corpus snapshot; fresh process + fresh home copy per run; seeded shuffled order; equal-length paths (cwd is model-visible). Pilot n=3 per cell — a fixture validation, not the held-out evaluation. Host native memory/skills control: not configured. |

## 3. Candidate patch

Python (`src/second_brain`):
- `adapters/antigravity.py` — Stop: finalize memory, emit `{}`.
- `autoinject.py` — `_focused_query_text` + full-then-focused retrieval; telemetry `query_mode=idf_focused`.
- `db.py` — `ensure_migrated` (per-process at-head cache keyed by path + dev/inode/size/mtime) and `forget_migration_state`; 13 modules migrated from `if pending_migrations: migrate` (14 sites); `backup.restore_backup` resets the cache after install and on rollback.
- `reconsolidation.py` — `base_level_activations` (one connection for many memories), `p_need_from_activation`; single-memory functions delegate. `semantic._rank_rows` batch-fills `_p_need`.

OMP extension (`brainstem/prime-extension/src`):
- `active-state-mirror.ts` — drop an `Objective:` line that only echoes the current prompt (including the re-stripped 512-char cut); no message when nothing remains.
- `environment-mirror.ts` — async `runEnvironmentAssessment`; sync variant kept only for shutdown.
- `index.ts` — background session-start/task-boundary assessments (mirrored as `environment_assessment` when done); no prefix-extras system-prompt text; concurrent visibility planning; no compaction veto.
- `injection-slots.ts` — `appendPrefixExtras` / marker removed.

Harness: `scripts/v3_matched_arms.py`, `scripts/v3_inert_extension.ts`. Docs: `brainstem/telemetry/SCHEMA.md` compaction note.

## 4. Tests and measurements

- Python: 2162 collected (M00: 2157); full run 2161 pass, 1 skip. New/changed: `test_stop_never_returns_lifecycle_decision` (×3), `test_instruction_heavy_prompt_recovers_same_memory_as_concise` (×2; the instruction-heavy case fails on M00 source with `NO_RELEVANT_MEMORY`, passes on candidate), `test_focused_query_keeps_exact_symbols_and_drops_boilerplate`, `test_appended_real_constraint_still_changes_retrieval`, `test_ensure_migrated_rechecks_a_database_replaced_in_place`. ruff, pyright: clean.
- TypeScript: 26 files, 606 tests pass; `tsc --noEmit`, `eslint` clean.

Matched pilot (`arms-pilot/`; OMP 18.3.0, `deepseek/deepseek-flash`, thinking `low`, project `second-brain`, seed 20260924, n=3 per cell, 0 failed runs; medians):

| case | arm | pre-dispatch ms | Δ vs inert | Brain chars | delivered |
|---|---|---|---|---|---|
| no_benefit | native / inert | 2149 / 2128 | — | 0 | — |
| no_benefit | M00 | 5391 | +3263 | 1386 | — |
| no_benefit | candidate | 3808 | +1680 | 1267 | — |
| memory_concise | inert | 2614 | — | 0 | 0/3 |
| memory_concise | M00 | 5486 | +2872 | 615 | 3/3 |
| memory_concise | candidate | 3910 | +1296 | 495 | 3/3 |
| memory_instruction_heavy | inert | 2144 | — | 0 | 0/3 |
| memory_instruction_heavy | M00 | 4540 | +2396 | 577 | **0/3** |
| memory_instruction_heavy | candidate | 3506 | +1362 | 495 | **3/3** |

Pre-dispatch = harness clock from process launch to the host's user `message_end` event. n=3 resolves second-scale effects only; sub-100 ms differences here are inconclusive. Hook-level numbers (§ RESOURCE_PROFILE.frozen.json): per-hook peak working set ~30 MiB both runtimes; spawn walls 162–175 ms, of which ~130 ms is package import.

`RESOURCE_PROFILE.frozen.json` freezes budgets and quality margins before any held-out evaluation.

## 5. Not done / NOT_RUN

- No deployment: extension install, venv repoint and OMP `/reload` are explicit owner actions. Hermes gateway restart not required by this patch (no Hermes file changed).
- PERF-01 no-benefit false injection (above) — precision work belongs to S2 (RET-03/RET-05, E02) with held-out cases; no stopword special-casing was added.
- E01 runtime comparison; ARCH-03 fault matrix; ARCH-01 live Antigravity/Hermes lifecycle exercise; offline profile run; Linux run.
- Held-out evaluation (margins are frozen; the pilot is not held-out).

## 6. Next slice (S2)

1. Retrieval precision and current state: source-backed record contracts (SourceRef/MemoryRecord minimum), a declared held-out set that includes short no-benefit prompts (the `tools`/`use` false injection is a seed case) and short memory-needing prompts; lexical baseline vs compact local encoder vs exact-vector hybrid (E02). USearch only if the measured corpus justifies ANN.
2. E01 fast path: one reused interpreter (or in-host read path) for the three serial per-prompt spawns, compared against the current path with the harness above; target the frozen PERF-02 margin.
3. Provenance/scope checks inside the same slice; ARCH-03 structured-unavailable results for missing interpreter.
