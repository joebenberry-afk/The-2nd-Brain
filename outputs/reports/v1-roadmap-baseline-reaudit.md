# The Second Brain v1.0 — Phase 0 Re-Audit (Clean Re-Run)

**Plan governing this audit:** `second_brain_v1_0_token_efficient_one_shot_deepseek_plan.md`
(§2.1 Baseline truth, §2.2 Roadmap status matrix, §31 Frozen v1.0 priority checklist)

**Audit type:** Clean re-run. This report is derived exclusively from direct, fresh
inspection of source, tests, config, and `git` state performed in this session. No
conclusion in this report was inferred from, or relies on, any prior audit report —
including the dormant-campaign files explicitly excluded from this session (see
"Forbidden-file compliance" below).

---

## 1. Baseline truth (plan §2.1)

| Field | Value |
|---|---|
| Worktree path | `C:/Users/assas/Documents/The-Second-Brain-v1` |
| Branch | `brain/v1-token-efficient` |
| Git SHA at audit start | `a16b2d84d2be6e16021b2a58e5f7e192046e51c9` |
| Git SHA at audit write-time (see note) | `5457e95b48d86d42b09d87c9cedbd023116eee13` |
| VERSION file | `0.1.0` |
| `pyproject.toml` `[project].version` | `0.1.0` |
| `pyproject.toml` `requires-python` | `>=3.11` |
| Actual venv interpreter (`.venv/Scripts/python.exe --version`) | `Python 3.13.7` (satisfies `>=3.11`; not a 3.11 pin — no stricter interpreter pin found in `pyproject.toml`, `.python-version`, or CI config this session) |
| `git tag` v1.0.0 / "Production Ready" string in `src/` | Absent — confirmed via `git tag` and `grep` (final-release rule honored) |

**Note on the two SHAs:** a sibling worker committed
`5457e95 brain(core): phase 0 re-audit — existing primitives map (clean re-run, v1
campaign §2.3)` to this same branch/worktree while this audit was in progress (visible via
`git log`/`git reflog` during this session). That commit added exactly one new file,
`outputs/reports/v1-existing-primitives-map-reaudit.md` (confirmed via `git show --stat`
only — its content was not read, consistent with this audit's "derive fresh, don't read
other reports" instruction). It did not touch any forbidden path. `git status --short`
was re-verified immediately after noticing it and again at the end of this session; the
forbidden-file list was unaffected both times (see §6).

### Prime Agent 0.7.3 qualification verdict

Out of scope for direct verification from inside this worktree (Prime Agent
qualification is a host-level artifact, not a repo file). Not fabricated: not assessed
this session.

### Brain doctor result

Run via `.venv/Scripts/python.exe -m second_brain doctor` with `PYTHONHOME`,
`PYTHONPATH`, `UV_INTERNAL__PYTHONHOME` unset, per `AGENTS.md`.

```text
Brain home: C:\Users\assas\Documents\The-Second-Brain
[PASS] brain home
[PASS] brain marker
[PASS] layout — 70 major roots present
[PASS] config — all config files parse as TOML
[PASS] version — 0.1.0
[PASS] SECOND_BRAIN_HOME — C:\Users\assas\Documents\The-Second-Brain
[PASS] python env — no PYTHONHOME/PYTHONPATH pollution
[PASS] python — 3.13.7 at C:\Users\assas\Documents\The-Second-Brain-v1\.venv\Scripts\python.exe
[PASS] sqlite3 — SQLite 3.50.4
[PASS] git repo — git version 2.55.0.windows.3
[PASS] database — journal_mode=wal, foreign_keys=1
[PASS] migrations — current at version 9
[WARN] tool:rg — not found on PATH
[PASS] tool:ast-grep — ast-grep 0.45.1
[PASS] tool:repowise — repowise, version 0.41.0
[PASS] tool:uv — uv 0.11.6
16 checks: 0 failed, 1 warnings
```

**Important environmental caveat:** `second_brain doctor` and all DB/migration
inspection below operate against `SECOND_BRAIN_HOME` (`C:\Users\assas\Documents\The-Second-Brain`,
the shared canonical Brain home per `AGENTS.md`: "Canonical Brain: `%SECOND_BRAIN_HOME%`"),
**not** an isolated database inside this campaign worktree — the worktree itself has no
`db/` directory (confirmed: `ls db` fails in the worktree; derived state is gitignored
per the canonical-vs-derived doctrine). This is expected/correct architecture, not a
defect, but it means DB-level findings below reflect the single shared Brain instance,
not a worktree-isolated one.

### Full test suite

Command: `.venv/Scripts/python.exe -m pytest -v` (the `-q` invocation silently dropped
its own final summary line on this Windows/git-bash combination — confirmed by byte
inspection of the redirected output, which cut off cleanly after the last `[100%]`
progress line with no trailing bytes; `-v` reproduced the same test execution and
printed the summary correctly, so this is a `-q`-mode display quirk, not a suite
failure).

```text
886 passed, 2 skipped in 204.49s (0:03:24)
```

0 failed, 0 errors. The 2 skips were observed in `tests/test_scout.py` (`.....ss........` in
the `-v` output for that file); this session did not open `test_scout.py` to read the
skip reasons (not in the forbidden list — could be done in a follow-up, but was not
necessary to report the count honestly).

### ruff

Command: `.venv/Scripts/python.exe -m ruff check src tests`

```text
All checks passed!
```

### pyright

Command: `.venv/Scripts/python.exe -m pyright`

```text
3 errors, 0 warnings, 0 informations
```

All 3 errors are in `tests/test_memory_index.py` (lines 264, 278, 281): a test-only stub
class `StubConn` is not structurally assignable to the real `sqlite3.Connection` type
expected by `semantic._fts_available`. This is a test-fixture typing gap, not a
production-code type error — `src/second_brain/*.py` itself has 0 reported pyright
errors.

### Prime extension test / typecheck / lint

Commands run from `brainstem/prime-extension/`: `npm run test`, `npm run typecheck`,
`npm run lint`.

```text
test:      Test Files  15 passed (15)   Tests  378 passed (378)   Duration ~6.5s
typecheck: 0 errors (tsc --noEmit produced no output)
lint:      0 errors/warnings (eslint . produced no output)
```

One of the 15 passing test files is `tests/sensors.test.ts` (59 tests) — this file is
one of the 6 currently-modified-but-uncommitted tracked files this audit was ordered
not to open; only its contribution to the aggregate 378-passed count is reported here,
its content was not read.

### DB schema / migration level

```text
src/second_brain/migrations/: 0001_init.sql .. 0009_purge_receipts.sql (9 files)
doctor: "migrations — current at version 9"
schema_version table (direct SQLite query): 9 rows, versions 1..9, all applied
2026-08-14T04:37 .. 2026-08-16T02:36 (UTC)
```

### Memory index / FTS state

Direct SQLite inspection of the shared Brain home's `db/brain.sqlite`:

```text
24 tables/views present, including memory_fts, memory_fts_config,
memory_fts_content, memory_fts_data, memory_fts_docsize, memory_fts_idx
(FTS5 virtual table IS present and active — not merely configured)
memory_index rows: 18   memories rows: 18   (in sync)
```

`src/second_brain/migrations/0007_memory_index.sql`'s own comment confirms this is
intentionally derived/rebuildable state ("DERIVED index state, rebuildable via
`brainctl memory reindex`... never hand-edited"), and `semantic.reindex_all` is directly
tested (`tests/test_memory_index.py`).

### Current installed adapter state (this machine)

| Harness | Install location | State |
|---|---|---|
| Claude Code | `~/.claude/settings.json` `"hooks"` key | **INSTALLED** — `SessionStart`, `PreCompact`, `Stop` keys present, content references the Brain (confirmed by direct JSON parse this session) |
| Google Antigravity | `~/.gemini/config/plugins/second-brain-adapter/` | **INSTALLED** — `plugin.json`, `hooks.json`, `rules/second-brain-core.md`, `scripts/run-hook.ps1`, `skills/second-brain/` all present on disk |
| Codex | `~/.codex/config.toml` | **NOT INSTALLED** — no `# BEGIN second-brain-codex-hooks` marker (the exact idempotency marker `scripts/install-codex-hooks.ps1` writes) anywhere in `config.toml`; only an unrelated `[projects.'...the-second-brain']` trust entry exists |

---

## 2. Roadmap status matrix (plan §2.2 / §31)

Legend: ✅ PROVEN · ⚠️ IMPLEMENTED_BUT_NOT_PROVEN · 🟡 PARTIAL · ❌ MISSING

Summary counts this session: **8 PROVEN, 8 IMPLEMENTED_BUT_NOT_PROVEN, 15 PARTIAL, 6 MISSING** (37 checklist items).

### P0 — Autonomous Brain Activation / AutoInject
#### P0.1 Automatic Brain initialization — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/doctor.py (env/DB/tool checks), registry.py (project identity), brainstem/adapters/claude-code/hooks.json + brainstem/adapters/antigravity/hooks.json wire SessionStart. Prime extension config.ts gates the whole observability extension on SECOND_BRAIN_OBSERVABILITY + brain-home existence (fail-open).
- **integration:** PARTIAL — Claude Code hooks ARE installed in this machine's ~/.claude/settings.json (hooks.SessionStart/PreCompact/Stop present, confirmed live). Antigravity adapter IS installed at ~/.gemini/config/plugins/second-brain-adapter/ (hooks.json+plugin.json present). Codex hooks are NOT installed: ~/.codex/config.toml has no '# BEGIN second-brain-codex-hooks' marker (scripts/install-codex-hooks.ps1 never run on this machine) — only a [projects] trust entry exists.
- **evidence:** tests/test_claude_code_adapter.py (test_startup_records_exactly_one_session_started, test_repeated_startup_same_session_still_one), tests/test_antigravity_adapter.py (test_uninitialized_brain_fail_open, test_malformed_input_fail_open), src/second_brain/doctor.py run this session: 16 checks, 0 failed, 1 warning (tool:rg not on PATH).
- **real_use_confidence:** MEDIUM — fail-open + idempotent-session logic is unit-tested for 2 of 3 non-Prime harnesses, but only 2/3 target adapters are actually installed on this machine; Codex has zero live installation evidence, only autoinject-shadow-level Python tests.

#### P0.2 Automatic recall — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/autoinject.py (RetrievalIntent -> semantic.search_memories candidates -> validity gate), brainstem/prime-extension/src/recall-gate.ts (Phase 14 bounded recall + Brain Brief), brainstem/prime-extension/src/autoinject.ts (host adapter spawning `second_brain autoinject shadow --json`).
- **integration:** PARTIAL — config/autoinject.toml sets `mode = "active"` (autoinject.py pipeline decisions ARE returned to the host per autoinject.ts line ~400: `if (call.cfg.mode === "off" || call.cfg.mode === "shadow") return undefined;` else a live patch is returned). BUT recall-gate.ts (the separate Phase 14 'Brain Brief' path) is documented DEFAULT OFF (env SECOND_BRAIN_RECALL unset = no-op) — two overlapping recall mechanisms exist, only one (autoinject.ts) is enabled by default config in this repo state.
- **evidence:** tests: brainstem/prime-extension/tests/autoinject.test.ts (44 tests, passed), brainstem/prime-extension/tests/recall-gate.test.ts (23 tests, passed), tests/test_autoinject.py, tests/test_autoinject_codex.py, tests/test_autoinject_writeback.py (Python side, all pass per full-suite run).
- **real_use_confidence:** MEDIUM — mechanism is unit-proven and config-active, but two parallel recall code paths with different default states is a real ambiguity the plan's four-dimensional standard would flag; no end-to-end host-session transcript evidence was captured this session (out of scope for this audit's read-only mandate).

#### P0.3 Automatic routing — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/router.py implements deterministic SKILL routing (sparse top-K scoring: +1 positive trigger, -2 negative trigger, +1.5 adjacent bigram, capped selection). No equivalent deterministic router exists for the plan's broader P0.3 scope (project memory vs user memory vs repo intelligence vs rules vs session state vs skills vs decisions vs operational knowledge) — autoinject.py's RetrievalIntent classification is the closest analog but is memory-source-scoped, not the full 8-way store router the plan describes.
- **integration:** PARTIAL — router.py is wired into skill selection (tests/test_router.py, tests/test_skill_lifecycle.py) but is not general 'which knowledge store' routing.
- **evidence:** src/second_brain/router.py (330 lines, plan §56/§113), tests/test_router.py (16 tests, passed).
- **real_use_confidence:** LOW — the specific multi-store deterministic router the v1 checklist describes (project/user/repo/rules/session/skills/decisions/ops) was not found as a single component; only the skill-routing subset is proven.

#### P0.4 Automatic context injection — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/autoinject.py budgets (config/autoinject.toml: target_tokens=800, hard_cap_tokens=2000, delta target 400/1000), src/second_brain/contracts.py (shared packet schema, 'authority: advisory' separated from system/user instruction authority), src/second_brain/working_set.py (residency/active-state awareness).
- **integration:** IMPLEMENTED — mode='active' in config/autoinject.toml is read live by both autoinject.py (python) and autoinject.ts (`modeFromAutoinjectToml`); delivery dedupe implemented (autoinject.ts lines ~520-545 dedupe cache-hit-vs-active-mode logic).
- **evidence:** brainstem/prime-extension/tests/autoinject.test.ts (44 tests, passed), tests/test_autoinject.py, tests/test_autoinject_writeback.py, tests/test_retrieval_budget.py (8 tests), tests/test_retrieval_dedupe.py (7 tests) — all passed this session.
- **real_use_confidence:** MEDIUM-HIGH — budgets and dedupe are directly config-enforced and test-proven; no measured host-session token count was captured this audit session (would require a live harness turn, out of the read-only Phase-0 scope).

#### P0.5 Automatic activity capture — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/ledger.py (append-only session events, FTS index, content refs), src/second_brain/episodes.py (capture-only episodic memory, immutable markdown + episodes table row), brainstem/prime-extension/src/ledger-mirror.ts (mirrors ONE privacy-safe lifecycle event per turn via `second_brain ledger append`).
- **integration:** IMPLEMENTED — ledger-mirror.ts is a live fire-and-forget adapter (not shadow-gated the way autoinject/RTD are); tests/test_claude_code_adapter.py proves Stop-hook candidate-memory writing only when a marker+evidence exist (test_stop_with_marker_writes_one_candidate / test_stop_marker_without_evidence_is_not_written).
- **evidence:** brainstem/prime-extension/tests/ledger-mirror.test.ts (24 tests, passed), tests/test_ledger.py, tests/test_episodes.py, tests/test_claude_code_adapter.py (19 tests spanning SessionStart/PreCompact/Stop dedupe) — all in the 886-passed full-suite run.
- **real_use_confidence:** MEDIUM-HIGH — capture-only discipline (no chain-of-thought, sha256-only task text per ledger-mirror.ts privacy comment) is directly coded and tested; real production volume/noise was not measured this session.

#### P0.6 Injection telemetry — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — brainstem/prime-extension/src/sensors.ts (836 lines, pure event->telemetry mapping, schema v2, brainstem/telemetry/SCHEMA.md), src/second_brain/telemetry.py (deterministic read-only JSONL aggregation).
- **integration:** IMPLEMENTED — storage.ts writes JSONL fire-and-forget to <home>/telemetry/agent-performance/<session>.jsonl; index.ts wires all 11 lifecycle events to sensors + storage.
- **evidence:** brainstem/prime-extension/tests/sensors.test.ts (59 tests — NOTE: this test file is one of the 6 currently-modified-uncommitted tracked files; it was NOT opened/read this session per the hard-constraint forbidden list, only its pass count from the aggregate vitest run (378 passed / 15 files) is cited), tests/test_telemetry.py (11 tests, NOT read — forbidden modified file — aggregate pass count only).
- **real_use_confidence:** MEDIUM — schema and write path are solid; suppression-reason/eventual-reuse tracking (the richer §P0.6 fields the plan lists) was not independently confirmed this session because the two most relevant test files are in the forbidden untouched list.

### P1 — Agent Orchestration + Cache-Preserving Context
#### P1.1 Strict Driver/Worker Control Plane — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — brainstem/prime-extension/src/driver-orchestrator.ts (role resolution: hard_orchestrator/driver/worker/normal), brainstem/prime-extension/src/orchestrator-guard.ts (pure decision logic blocking bash/edit/websearch for the orchestrator role only), brainstem/policies/driver-orchestration.md + sol-minimal-orchestrator.md (canonical policy).
- **integration:** PARTIAL — config/orchestration.toml self-documents its own status as 'ADVISORY (policy text + telemetry today; no hard TS guard — the Sol tool-guard in orchestrator-guard.ts blocks only bash/edit/websearch and contains NO concurrency enforcement)'. default_active=1, hard_ceiling=2 are documented targets, not enforced fan-out limits.
- **evidence:** brainstem/prime-extension/tests/driver-orchestrator.test.ts (17 tests, passed), tests/orchestrator-guard.test.ts (14 tests, passed), config/orchestration.toml (read directly this session).
- **real_use_confidence:** MEDIUM — role classification and the Sol tool-block are real and tested, but the concurrency/adaptive-fan-out half of P1.1 is explicitly self-labeled non-enforced in config; do not conflate 'guard exists' with 'control plane enforces routing by complexity/risk/cost/capability'.

#### P1.2 Worker Communication — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/contracts.py (707 lines; shared event/protocol contracts, canonical JSON, sorted keys, stable string enum values, no timestamps in stable packet content).
- **integration:** PARTIAL — contracts.py defines packet shapes consumed by autoinject.py/autoinject.ts and ledger.py/ledger-mirror.ts; no direct evidence was found this session of a distinct 'assignment/status/findings/artifacts/evidence/blockers/dependencies/handoff' worker-packet schema separate from the AutoInject/ledger contracts already covered under P0.4/P0.5.
- **evidence:** tests/test_contracts.py (passed, part of 886), src/second_brain/contracts.py inspected directly.
- **real_use_confidence:** LOW-MEDIUM — the underlying serialization discipline is solid, but the plan's specific worker-communication packet taxonomy (distinct from AutoInject packets) was not independently located as a named, tested component this session.

#### P1.3 Cache-Preserving Context Architecture — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/jit.py (JIT Context Compiler: deterministic markdown capsule at outputs/context-capsules/<session-id>-<slug>.md; identical inputs -> identical body except compiled_at timestamp).
- **integration:** IMPLEMENTED — jit.py composes working_set.py (active-state/requirements/read-ledger) + optional project state into one compact packet; brainstem/prime-extension/tests/cache_stability.test.ts (3 tests) exercises stable-prefix behavior at the extension layer.
- **evidence:** tests/test_jit.py (passed, part of 886), brainstem/prime-extension/tests/cache_stability.test.ts (3 tests, passed).
- **real_use_confidence:** MEDIUM — determinism (same input -> same output) is directly proven; no host-reported cache-read/cache-write token metric was captured this session (would require a live paid-model turn, outside Phase-0 read-only scope).

### P2 — Durable State / Projection / Session Memory
#### P2.1 Deterministic Projections — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/semantic.py:reindex_all (derived memory_index/memory_fts rebuildable from canonical markdown, confirmed by migration 0007 comment 'DERIVED index state, rebuildable via brainctl memory reindex'), src/second_brain/ledger.py has a reindex()/`ledger reindex` CLI path and checkpoint_ledger's interrupted-compaction detector.
- **integration:** MISSING for the doctor-integration half — src/second_brain/doctor.py's actual check functions (check_home/layout/config/env/python/git/db/tools/version) do NOT include any divergence/stale-projection/corrupt-index/duplicate-state check; the plan's explicit requirement 'Brain Doctor must detect and report: divergence, stale projections, corrupt index...' is not implemented — confirmed by reading doctor.py's full function list and by this session's live `doctor` run (16 checks, all environment/DB-connectivity, none semantic-integrity).
- **evidence:** tests/test_memory_index.py (test_reindex_all_incremental_and_purge, test_supersede_reindexes_new_version), tests/test_ledger.py (test_fts_search_and_reindex), tests/test_doctor.py (passed, part of 886) — doctor tests cover only the 9 existing checks.
- **real_use_confidence:** LOW-MEDIUM — rebuild mechanisms exist and are unit-tested; the doctor-side automated divergence detection the plan explicitly calls for is absent.

#### P2.2 Lossless Session/Event Ledger + Compaction Recovery — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/ledger.py:checkpoint_ledger ('Pre-compaction durability barrier (plan §10.2): flush + integrity'), an interrupted-compaction-bracket detector (unclosed segments), compaction_id tracked on every event row.
- **integration:** IMPLEMENTED — brainstem/prime-extension/src/ledger-mirror.ts (P2 host event mirror, plan §16) wires PreCompact lifecycle to the Python ledger CLI; tests/test_claude_code_adapter.py proves PreCompact writes a bounded resume snapshot and does not store the full transcript.
- **evidence:** tests/test_ledger.py (passed, part of 886), tests/test_claude_code_adapter.py::test_precompact_writes_bounded_resume_snapshot, ::test_precompact_does_not_store_full_transcript, ::test_precompact_duplicate_invocation_is_deduplicated.
- **real_use_confidence:** MEDIUM-HIGH — flush/checkpoint/interrupted-bracket-detection code and PreCompact-hook tests both exist and pass; no live large-session compaction event was observed this session (read-only audit).

#### P2.3 Context Offloading — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/artifacts.py (RTD artifact store: content-addressed blobs at state/artifacts/blobs/<sha256>.bin + metadata, deterministic pure distillation, :func:`expand` for lossless drill-down).
- **integration:** PARTIAL — brainstem/prime-extension/src/rtd.ts implements the substitution surface, but config/context.toml [rtd] enabled=false (master switch OFF; the file's own comment: 'false = shadow measurement only'). Offloading exists and is wired but is NOT live by default in this repo state.
- **evidence:** tests/test_artifacts.py (NOT read this session — one of the 6 forbidden currently-modified tracked files; only its contribution to the aggregate 886-passed count is cited), brainstem/prime-extension/tests/rtd.test.ts (42 tests, passed).
- **real_use_confidence:** MEDIUM — mechanism, dedupe, and size caps are directly coded (artifacts.py) and the substitution path is unit-tested, but real_use_confidence is capped because the master enabled flag is off in the current committed config.

#### P2.4 Repository Intelligence — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/scout.py (isolated read-only Evidence Map builder: git state, RepoWise freshness, ripgrep term-match candidate pre-pass, prime-agent command builder for the actual spawn).
- **integration:** IMPLEMENTED — doctor.py confirms `tool:repowise` present (repowise 0.41.0) and `ast-grep 0.45.1`; scout.py leans on both as external tools rather than reimplementing a symbol index.
- **evidence:** tests/test_scout.py (passed, part of 886), doctor run this session: '[PASS] tool:repowise — repowise, version 0.41.0', '[PASS] tool:ast-grep — ast-grep 0.45.1'.
- **real_use_confidence:** MEDIUM — the isolated-process design and evidence-map template are real and tested; no measurement of 'invalidate incrementally' cache-hit-rate was captured this session.

#### P2.5 Risk-Adaptive Verification — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/risk.py (RISK_LEVELS LOW/MEDIUM/HIGH/CRITICAL, 9 weighted 0-2 signals, explainable verdict), src/second_brain/verify.py (verification_ladder_payload; ladder actions per level are strictly nested: LOW={targeted_test, typecheck_or_compile, diff_sanity} subset of MEDIUM subset of HIGH subset of CRITICAL, CRITICAL adds 'simplification_check' and an explicit-approval flag).
- **integration:** IMPLEMENTED — verify.py:ladder_from_toml reads config/verification.toml live; user-criticality can only RAISE risk, never lower it (tests/test_verify.py::test_override_raise_only_invariant_every_level, ::test_lean_never_lowers_existing_risk).
- **evidence:** tests/test_risk.py (21 tests, passed), tests/test_verify.py (22 tests: test_low_never_forces_independent_verifier, test_high_forces_fresh_independent_verifier_brief, test_critical_adds_explicit_approval_flag, all passed).
- **real_use_confidence:** HIGH — this is one of the most directly plan-matching, fully-tested items found this session: requirement->level->action-set mapping is explicit code with an explicit invariant test suite.

#### P2.6 Intelligent Model Routing — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/crossmodel.py (model_skill_report, transfer_test, global_policy_stats: aggregates PAST measured success/failure per model+skill, excludes low-success models from global policy) provides the historical-success SIGNAL the plan asks for, but no function anywhere in src/second_brain performs an actual 'select model for this task' decision (confirmed by grep for route_model/select_model/model_routing/choose_model across src + brainstem/prime-extension/src: zero matches).
- **integration:** PARTIAL — brainstem/prime-extension/src/driver-orchestrator.ts classifies the ALREADY-ACTIVE model into a role (hard_orchestrator/driver/worker/normal) by name-matching; this is coarse routing enforcement, not complexity/cost/modality-based selection.
- **evidence:** tests/test_crossmodel.py (passed, part of 886), brainstem/prime-extension/tests/driver-orchestrator.test.ts (17 tests, passed).
- **real_use_confidence:** LOW-MEDIUM — the data substrate for model routing decisions exists and is tested; the actual routing/selection decision engine the plan describes was not found as a distinct component.

### P3 — Brainstem / Skills / Self-Improvement
#### P3.1 Active State Capsule — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/working_set.py (active-state.json: objective/phase/repo/constraints/facts/hypotheses/decisions/blockers/next_action per the plan §17 schema); config/context.toml [capsule] min_update_interval_seconds=30.
- **integration:** IMPLEMENTED — jit.py composes the capsule into the JIT context packet (P1.3); config/context.toml [working_set] lists the 6 per-session files including active-state.json.
- **evidence:** tests/test_working_set.py (43 tests, passed), tests/test_jit.py (passed).
- **real_use_confidence:** HIGH — the capsule schema, update-interval throttling, and downstream JIT consumption are all directly coded and tested.

#### P3.2 Context Capsule — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/jit.py compiles exactly the fields the plan lists (task/project/working set/relevant memory/rules/repo state/skills/session refs/token budget) into one markdown capsule; no full parent transcript is included by construction (jit.py reads only working_set.py's three JSON files + optional project state).
- **integration:** IMPLEMENTED — scout.py's Evidence Map / prime-agent command builder is the worker-facing analog (isolated read-only subprocess, receives a scoped task, not the parent transcript).
- **evidence:** tests/test_jit.py (passed), tests/test_scout.py (passed).
- **real_use_confidence:** MEDIUM-HIGH — determinism and field-scoping are proven; whether a REAL spawned worker in this repo's harnesses receives only this capsule (vs. more) was not independently observed in a live session this audit.

#### P3.3 Reversible Tool Distillation — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/artifacts.py (RTD store) + brainstem/prime-extension/src/rtd.ts (602 lines: eligibility check BEFORE content work, byte-exact preservation via the artifact store THEN model-visible substitution, any preservation failure returns ORIGINAL content unchanged per the file's own §11.4 comment).
- **integration:** PARTIAL — config/context.toml [rtd] enabled=false (master switch off in the current committed config); threshold_chars=8000 and whitelist_tools=['bash'] / whitelist_commands=['pytest','git','rg','grep'] are configured but substitution does not fire by default.
- **evidence:** brainstem/prime-extension/tests/rtd.test.ts (42 tests, passed), tests/test_artifacts.py (NOT read — forbidden modified file; aggregate pass count only).
- **real_use_confidence:** MEDIUM — the reversibility guarantee (fail back to original on any preservation failure) is directly coded and unit-tested; real_use_confidence is capped by enabled=false in committed config, i.e. shadow-measurement-only in production today.

#### P3.4 Lean Code / Lean Build — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/lean_runtime.py (harness-neutral Python mirror of lean-code.ts decision semantics, single canonical source at skills/candidates/lean-code/SKILL.md '# Runtime Kernel' section), brainstem/prime-extension/src/lean-code.ts (426 lines).
- **integration:** PARTIAL — the lean-code skill itself currently lives under skills/candidates/lean-code/ (confirmed by directory listing this session), i.e. NOT yet promoted to skills/active/; lean-code.ts's own docstring states 'candidate -> no runtime influence by default (measurement only)'. Only code-capable driver/worker roles ever receive the kernel per lean-code.ts.
- **evidence:** tests/test_lean_runtime.py, tests/test_lean_canary.py (passed, part of 886), brainstem/prime-extension/tests/lean-code.test.ts (49 tests, passed), brainstem/prime-extension/tests/lean-cache.test.ts (4 tests, passed), brainstem/prime-extension/tests/lean-fixtures.test.ts + lean-opportunity-fixtures.test.ts (10 tests, passed).
- **real_use_confidence:** MEDIUM — decision logic is dual-implemented (TS+Python) and heavily tested, but the skill is still candidate-level, not promoted; real-use in production sessions is measurement-only per the code's own default state.

#### P3.5 Simplification Review — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/verify.py includes 'simplification_check' ('confirm no unrelated simplification') as one action in the CRITICAL-level verification ladder only; src/second_brain/defaults/templates/project/simplification-debt.md provides a durable deferred-simplification tracking template (plan §71).
- **integration:** PARTIAL — only wired at CRITICAL risk level, not as a standalone post-implementation review step for all risk levels.
- **evidence:** tests/test_verify.py::test_critical_adds_explicit_approval_flag (which also asserts simplification_check membership at CRITICAL), src/second_brain/defaults/templates/project/simplification-debt.md inspected directly.
- **real_use_confidence:** LOW-MEDIUM — a real hook exists but only at the top risk tier; no dedicated 'can this be simpler' reviewer component was found.

#### P3.6 STOP / Completion Discipline — ❌ MISSING
- **implementation:** MISSING as a dedicated component — no src/second_brain module, no test file (test_stop.py / test_completion*.py absent from the tests/ directory listing), and no brainstem/prime-extension source file implements a distinct STOP-discipline gate; the closest related code is verify.py's requirement/evidence-completeness ladder (P2.5/P3.7) and working_set.py's requirement ledger, which together could BACK a stop decision but do not themselves enforce 'stop when requirements+evidence are complete'.
- **integration:** MISSING — no lifecycle hook or CLI subcommand named for STOP discipline was found (cli.py itself could not be inspected — it is a forbidden modified-uncommitted file — so a stop-related CLI command cannot be ruled out with certainty, but no corroborating test file exists).
- **evidence:** Absence confirmed by: `ls tests/*.py` (37 files, none STOP/completion-named), grep for 'stop discipline|completion discipline|STOP_DISCIPLINE' across src/second_brain (zero matches).
- **real_use_confidence:** LOW — treat as MISSING pending direct cli.py inspection once that file is no longer in a dirty/forbidden state.

#### P3.7 Risk-Adaptive Accuracy Gate — ✅ PROVEN
- **implementation:** IMPLEMENTED — same mechanism as P2.5: src/second_brain/risk.py + src/second_brain/verify.py form requirement -> implementation -> evidence -> verification-strength; CRITICAL forces an explicit approval flag (fail-closed for unverified material requirements at the top tier).
- **integration:** IMPLEMENTED — verification_ladder_payload is compact/deterministic per test_ladder_payload_is_compact_and_deterministic.
- **evidence:** tests/test_verify.py (22 tests, passed), tests/test_risk.py (21 tests, passed) — same evidence base as P2.5.
- **real_use_confidence:** HIGH — this is effectively the same proven mechanism as P2.5; duplicated checklist concept, duplicated strong evidence.

#### P3.8 Independent Intent Verification — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/verify.py is explicitly titled 'Intent Verifier brief builder': builds a fresh-context brief from working-set requirements + capsule constraints + diff of touched files + validation evidence; solver reasoning (hypotheses/decisions/next_action/open questions) is DELIBERATELY EXCLUDED, and the diff is placed BEFORE requirements so the verifier must perform backward reconstruction rather than read the solver's narrative.
- **integration:** IMPLEMENTED — tests/test_verify.py::test_solver_reasoning_excluded and ::test_diff_section_precedes_requirements directly assert this separation.
- **evidence:** tests/test_verify.py::test_section_order_and_content, ::test_solver_reasoning_excluded, ::test_diff_section_precedes_requirements, ::test_determinism_identical_except_generated_at (all passed).
- **real_use_confidence:** HIGH — the anti-cheating-relevant design (verifier cannot see solver's self-narrated reasoning) is directly coded and directly tested, which is unusually strong evidence for this specific checklist item's real-use intent.

#### P3.9 Environment Steward — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/envsteward.py (exact-name match): snapshot() captures git state, language, package manager, lockfiles, tools, RepoWise freshness, brain version at session_start; every subprocess probe is error-graced.
- **integration:** IMPLEMENTED — writes to environment.toml [track] session_start per the module's own docstring; config/environment.toml exists in-repo.
- **evidence:** tests/test_envsteward.py (passed, part of 886), config/environment.toml present.
- **real_use_confidence:** HIGH — direct 1:1 name-and-scope match to the plan item, with dedicated config and test coverage.

#### P3.10 Improvement Radar — ❌ MISSING
- **implementation:** PARTIAL/MISSING as a dedicated component — no radar.py or equivalent module exists in src/second_brain (confirmed via full `ls src/second_brain/*.py` listing). The only direct textual hit repo-wide is a config flag `improvement_radar = true` inside src/second_brain/registry.py's embedded default-config template (line 321) — a settings toggle, not an implementation. Adjacent telemetry-driven signal detection exists piecemeal in src/second_brain/cerebellum.py (predicts stalled/looping workflows) and src/second_brain/plasticity.py (predicted-vs-actual bottleneck comparison), but neither implements the plan's specific list (repeated reads/searches, repeated failures, high worker retry, duplicate memory, poor cache hit rate, repeated permission friction, repeated manual sequences).
- **integration:** MISSING — no wiring from any of the above signals into an 'only invoke an LLM when a threshold indicates a real candidate' gate was found.
- **evidence:** grep across src/second_brain and brainstem/prime-extension/src for 'improvement.radar|improvement_radar': only the registry.py config-default-toggle line matched; no test_radar.py / test_improvement_radar.py exists in tests/.
- **real_use_confidence:** LOW — a settings flag exists but the feature behind it does not appear implemented as a distinct module.

#### P3.11 Skill Forge — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/skillforge.py (exact-name match, 642 lines): observed friction -> candidate -> isolated implementation -> eval -> shadow lifecycle; candidates live at skills/candidates/<name>/SKILL.md with the 10 §60 sections; nothing is installed/promoted automatically.
- **integration:** IMPLEMENTED — real candidates exist on disk: skills/candidates/lean-code/ (confirmed by directory listing this session).
- **evidence:** tests/test_skillforge.py (32 tests, passed).
- **real_use_confidence:** HIGH — direct 1:1 name match, real candidate artifacts on disk, comprehensive test coverage.

#### P3.12 Skill Verifier — ❌ MISSING
- **implementation:** MISSING as a dedicated component — no skill_verifier.py / SkillVerifier class exists anywhere in src/second_brain or brainstem/prime-extension/src (confirmed by grep for 'skill.verifier|skill_verifier|SkillVerifier': zero matches). skillforge.py's own evals ('deterministic and structural: trigger boundaries, a structural workflow smoke test, regression re-checks, and static security') provide the closest coverage but are internal to the Forge, not a separately-named candidate-vs-baseline evaluator across correctness/latency/token-usage/robustness/maintenance-burden as the plan specifies.
- **integration:** MISSING for the specific candidate-vs-baseline comparison the plan describes; skillforge.py evals are pass/fail structural checks, not comparative benchmarking.
- **evidence:** grep confirmed zero matches; no test_skill_verifier.py in tests/ (37-file listing).
- **real_use_confidence:** LOW — treat as MISSING; skillforge.py's internal evals are a different, narrower mechanism.

#### P3.13 Counterfactual Skill Evaluation — ✅ PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/credit.py:counterfactual_eval (paired with/without-skill task routing, deterministic, 'tasks_affected'/'tasks_unaffected' reporting; delta_tools honestly reported as 0 when unobservable per the module's own comment).
- **integration:** IMPLEMENTED — only invoked during candidate evaluation, not every normal invocation, per credit.py's design (counterfactual_eval takes an explicit skill_name + tasks list, is not wired into the hot AutoInject/ledger path).
- **evidence:** tests/test_credit.py::test_counterfactual_deterministic_and_report, ::test_counterfactual_unknown_skill (both passed).
- **real_use_confidence:** HIGH — direct 1:1 match, deterministic, honestly reports unobservable fields as 0 rather than fabricating — matches the plan's anti-cheating spirit.

#### P3.14 Skill ROI — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/credit.py:credit_report provides per-session credit-event aggregation (uses/outcomes), and src/second_brain/crossmodel.py:model_skill_report provides per-model success/failure stats, but neither tracks the plan's full ROI field set (tokens/time saved, model calls avoided, corrections avoided, context footprint, maintenance cost) as a single named 'Skill ROI' component — confirmed by grep for 'skill.roi|skill_roi|SkillROI': zero matches anywhere in src or brainstem.
- **integration:** PARTIAL — the raw ingredients (credit events, counterfactual deltas) exist and could feed an ROI report, but no such report generator was found.
- **evidence:** tests/test_credit.py::test_credit_report_aggregation (passed); grep confirmed no dedicated ROI module/test.
- **real_use_confidence:** LOW-MEDIUM — adjacent data exists; the specific ROI-tracking deliverable does not.

#### P3.15 Skill Gardener / Retirement — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/promotion.py:demote can move a skill to any lower level and ALWAYS writes a promotion record (reason-carrying); a real skills/retired/ directory exists on disk (confirmed by directory listing). 'retirement' as a STATE is real and enforced: brainstem/prime-extension/src/lean-code.ts line 14 comment 'retired -> no injection (plan §26.1: demotion/retirement disables the...)' and its test file (lean-code.test.ts:320,466 'retirement disables runtime behavior' / 'retirement beats advisory') prove retirement wins over advisory config for Lean Code specifically. No dedicated 'gardener' module performs the plan's PROACTIVE detection (unused/duplicated/superseded/low-ROI/harmful) anywhere in src/second_brain or brainstem/prime-extension/src (grep for 'gardener' found only the one Lean-Code-specific retirement-state comment above, not a scanning/detection component).
- **integration:** PARTIAL — demote() and the retired-state override are real, guarded, tested primitives; no scheduled/deterministic detection-and-demotion loop that decides WHEN to retire a skill exists.
- **evidence:** src/second_brain/promotion.py:demote (inspected directly), skills/retired/ directory confirmed present via `find skills -maxdepth 2 -type d`, brainstem/prime-extension/src/lean-code.ts:14, tests/lean-code.test.ts:320/466 (both passed), tests/test_promotion.py contribution NOT independently read this session (forbidden modified-uncommitted tracked file; counted only in the aggregate 886-passed figure).
- **real_use_confidence:** LOW-MEDIUM — demotion mechanics and one skill's retirement-override behavior are proven; proactive gardening/retirement candidate-detection does not exist as a general mechanism.

#### P3.16 Modular Skill Visibility — ⚠️ IMPLEMENTED_BUT_NOT_PROVEN
- **implementation:** IMPLEMENTED — src/second_brain/router.py implements sparse top-K deterministic/lexical routing (trigger-phrase scoring) BEFORE any semantic fallback, matching the plan's 'deterministic/lexical routing first, vector semantic fallback only if ambiguity remains'; skills/ directory structure itself enforces descriptor-only exposure at rest (active/candidates/shadow/staged/quarantine/retired/evals subdirectories, confirmed by listing).
- **integration:** IMPLEMENTED — router.py pool = active + candidate + shadow per its own docstring ('Phase 23: pool = active + candidate + shadow').
- **evidence:** tests/test_router.py (16 tests, passed), tests/test_skill_lifecycle.py (2 tests, passed).
- **real_use_confidence:** MEDIUM-HIGH — the routing algorithm and directory-based lifecycle segregation are both real and tested; whether full-skill-instruction JIT-loading (vs. descriptor-only at session start) is actually enforced end-to-end in a live harness turn was not independently observed.

#### P3.17 Brain Handoff — ❌ MISSING
- **implementation:** MISSING as a dedicated component — no handoff.py or equivalent module exists in src/second_brain; grep for 'handoff' repo-wide (src/second_brain, brainstem/prime-extension/src) only matched src/second_brain/paths.py and src/second_brain/working_set.py, both incidental/generic usages, not a deterministic cross-session/harness handoff builder producing objective/completed-work/evidence/unresolved-items/decisions/repo-state/hot-refs/next-action as the plan specifies.
- **integration:** MISSING — no test_handoff.py exists in tests/ (37-file listing); working_set.py's active-state capsule (P3.1) is the closest available substrate a handoff builder could consume but is not itself a handoff artifact.
- **evidence:** grep confirmed only 2 incidental matches, both non-implementing; `ls tests/*.py` confirmed no handoff test file.
- **real_use_confidence:** LOW — treat as MISSING; P3.1's Active State Capsule is necessary-but-not-sufficient raw material for this item.

### P4 — Long-Running Brain Operations
#### P4.1 Long-running goals — ❌ MISSING
- **implementation:** MISSING as a Brain-owned component — no goals.py or equivalent module exists in src/second_brain (confirmed via full `ls src/second_brain/*.py` listing); grep for 'goal' repo-wide (src/second_brain, brainstem/prime-extension/src) only matched src/second_brain/cli.py (forbidden — not read this session), brainstem/prime-extension/src/index.ts and ledger-mirror.ts (both informal English usages of the word 'goal', e.g. 'stop when the goal is satisfied' in a driver-contract prose block — not a tracked objective/milestones/blockers/dependencies/evidence/progress state machine).
- **integration:** UNKNOWN for cli.py's contribution — cli.py is a forbidden modified-uncommitted file this session could not open; test_cli.py (readable) has no goal-related test names among its visible test functions (checked test names up to the file's current extent this session).
- **evidence:** grep confirmed no dedicated goals module/state file layout under state/ or config/; `ls tests/*.py` confirmed no test_goals.py.
- **real_use_confidence:** LOW — the plan's local objective/milestone/blocker tracker was not found as a Brain-owned primitive; this task's own use of the Prime Agent platform's external `/goal` skill is a HOST feature, not evidence of a Brain-owned P4.1 component.

#### P4.2 Schedules / Heartbeats — ❌ MISSING
- **implementation:** MISSING — no heartbeat.py, schedule.py, or equivalent module exists anywhere in src/second_brain or brainstem/prime-extension/src (confirmed by grep for 'heartbeat': zero matches in either tree).
- **integration:** MISSING — no config file (config/*.toml, 12 files listed this session) references heartbeat/schedule cadence.
- **evidence:** grep confirmed zero matches; `ls tests/*.py` confirmed no test_heartbeat.py / test_schedule.py.
- **real_use_confidence:** LOW — this is a genuine gap; the plan's 'local deterministic health/delta checks -> no meaningful change = no model call' heartbeat path does not exist in this repository. (The Prime Agent platform's own rlm_heartbeat skill is an external host capability, not Brain-owned code.)

#### P4.3 Operational Telemetry — 🟡 PARTIAL
- **implementation:** IMPLEMENTED — src/second_brain/telemetry.py (deterministic read-only JSONL aggregation) + brainstem/prime-extension/src/sensors.ts (836 lines, pure event->record mapping) + storage.ts (fire-and-forget JSONL writer) cover a meaningful subset of the plan's field list: tool names/counts/sizes/hashes/error flags are captured (sensors.ts docstring), delegation/driver-worker split is available via driver-orchestrator role classification, action-cache hit/miss appears in autoinject.ts's dedupe-cache logic.
- **integration:** PARTIAL — no single module was found that assembles ALL of the plan's listed fields (retrieval hit rate, context size/peak, ledger size, memory growth, projection divergence, failed writes, latency, token economics) into one operational telemetry report; the fields exist scattered across several modules' own outputs rather than one unified surface.
- **evidence:** brainstem/telemetry/SCHEMA.md (schema v2, inspected reference only, not deep-read), tests/test_telemetry.py (NOT read — forbidden modified-uncommitted tracked file; aggregate pass-count only), brainstem/prime-extension/tests/sensors.test.ts (NOT read — same reason; 59 tests counted in the aggregate 378-passed vitest figure).
- **real_use_confidence:** MEDIUM — the write path and schema are real; whether the full plan field list is actually populated could not be confirmed this session because the two most relevant test files are forbidden to read.

#### P4.4 Bottleneck Fingerprinting — 🟡 PARTIAL
- **implementation:** PARTIAL — src/second_brain/plasticity.py implements 'predicted_bottleneck vs actual_bottleneck' comparison recording (plan §45: 'compare predicted vs actual bottleneck'), and src/second_brain/cerebellum.py predicts whether a workflow is progressing/stalled/looping from the read ledger + requirement ledger + capsule files_touched — but both are PER-TASK workflow-progress predictions, not the plan's cross-session 'recurring systemic waste' telemetry-clustering the checklist item describes.
- **integration:** PARTIAL — plasticity.py's bottleneck comparison feeds credit/prediction-error tracking (plan §45), not a fleet-wide waste-pattern detector.
- **evidence:** tests/test_plasticity.py (16 tests, passed), tests/test_cerebellum.py (passed, part of 886).
- **real_use_confidence:** LOW-MEDIUM — real per-task bottleneck-prediction machinery exists and is tested, but it answers a narrower question ('was this task's predicted stall point correct') than the plan's broader 'find recurring systemic waste across sessions'.

#### P4.5 Controlled Self-Optimization — ✅ PROVEN
- **implementation:** IMPLEMENTED as a DISTRIBUTED pipeline across multiple modules matching every stage of the plan's mandatory loop: Observe = src/second_brain/monitor.py + cerebellum.py + plasticity.py; Propose/Isolate = src/second_brain/skillforge.py (candidate -> isolated skills/candidates/<name>/); Test = skillforge.py's structural evals; Compare = src/second_brain/credit.py:counterfactual_eval; Review = src/second_brain/frontier.py ('CLEARED only by an approve verdict...reject is FINAL'); Promote = src/second_brain/promotion.py:promote (G1 evidence + G2 frontier-approve + G3 no-immune-rollback guards); Monitor = src/second_brain/immune.py:ingest_metric + check_triggers; Rollback = src/second_brain/immune.py:rollback (guarded, frontier-approval can block it).
- **integration:** IMPLEMENTED end-to-end mechanically, and exercised at least once for a REAL skill: skills/active/sqlite-migration-verifier/ exists on disk (confirmed by directory listing this session), proving at least one skill has traversed candidate->active. 'Never Brain notices issue -> silently edits production' is enforced structurally: promotion.promote requires an explicit frontier-approve review (G2) and immune.rollback checks 'frontier approved blocks rollback' (tests/test_immune.py::test_acceptance_frontier_approved_blocks_rollback).
- **evidence:** tests/test_promotion.py (NOT read — forbidden modified-uncommitted; aggregate pass-count only), tests/test_immune.py (15 tests, passed, all names inspected directly), tests/test_frontier.py, tests/test_skillforge.py (32 tests), tests/test_credit.py (9 tests) — all passed this session; skills/active/sqlite-migration-verifier, skills/candidates/lean-code, skills/shadow/delivery-integration confirmed present via directory listing.
- **real_use_confidence:** HIGH — every stage of the governed loop has a real, guarded, tested implementation, AND real skill artifacts on disk prove the pipeline has actually moved at least one skill through it, not just passed synthetic unit tests.


---

## 3. Cross-cutting release requirements (plan §31)

These are pass/fail gate items, assessed the same evidence-first way (not full four-field
rows, since the checklist itself does not ask for that here):

| Requirement | Status | Evidence |
|---|---|---|
| Token Efficiency Contract measured and satisfied | ❌ NOT SATISFIED | No live paid-model token measurement was captured this session (Phase-0 audit is read-only repo inspection, not a live harness run). A prior tracked artifact `outputs/reports/v1-token-baseline.md` exists in git history but was not read/relied on this session (fresh-evidence discipline) — its existence is noted, its content is not. |
| Token Governor / ablation evidence complete | 🟡 CANNOT ASSESS — EXCLUDED BY HARD CONSTRAINT | `src/second_brain/governor.py` and `config/governor.toml` are both on the explicit forbidden-file list (dormant-campaign in-progress work) and were not opened this session. Their existence (as untracked files) was confirmed via `git status` only — no content, no line count beyond what `git status` itself reports, was inspected. |
| Local-first / no-server requirement satisfied | ✅ SATISFIED | `grep` across `src/second_brain/*.py` for `asyncio.start_server`, `http.server`, `flask`, `fastapi`, `uvicorn`, `socketserver` returned zero matches. No always-on server process exists in the Brain core. (Note: the plan's optional "local stdio MCP adapter" transport, §10.4, was also not found — a cross-cutting-architecture nice-to-have, not itself a P0–P4 checklist item, so it does not affect this line's PASS.) |
| Prime Agent 0.7.3 integration proven | ⚠️ NOT ASSESSED THIS SESSION | Host-level qualification, outside this worktree's file surface. |
| Codex integration proven | ❌ NOT PROVEN | Hooks not installed on this machine (§1 above); only `tests/test_autoinject_codex.py` exists for Codex-specific logic, no full lifecycle-adapter test suite comparable to Claude Code's or Antigravity's `test_claude_code_adapter.py` / `test_antigravity_adapter.py`. |
| Claude Code integration proven | ⚠️ IMPLEMENTED_BUT_NOT_PROVEN | Hooks installed and live on this machine; `tests/test_claude_code_adapter.py` (19+ tests, all passed) proves unit-level behavior; no live production session transcript was captured this audit session. |
| Antigravity/agy integration proven | ⚠️ IMPLEMENTED_BUT_NOT_PROVEN | Adapter installed on this machine; `tests/test_antigravity_adapter.py` proves unit-level behavior including fail-open and Lean-kernel visibility; per this session's inherited context (BRAIN_CONTEXT_DELTA from parent), the real-agent Antigravity promotion campaign is independently reported HOLD/incomplete — this audit did not re-verify that claim directly (out of scope: it concerns `outputs/reports/p3-promo-eval*` and related P3 promotion artifacts, not re-read this session to keep this report's findings self-derived from Phase-0-scoped inspection only). |
| Cross-harness Brain Handoff proven | ❌ NOT PROVEN | P3.17 Brain Handoff itself is classified MISSING above (no dedicated module/tests found); nothing to prove. |
| Dogfooding proven | ⚠️ NOT ASSESSED THIS SESSION | Would require live harness session evidence outside this read-only Phase-0 audit's scope. |
| Backup/restore proven | ✅ PROVEN | `src/second_brain/backup.py` (sqlite3 backup API, sha256 manifest) + `tests/test_backup.py` (19 tests: roundtrip, consistent snapshot, force-restore, corrupt-hash refusal, byte-identity verification, hostile-manifest-entry rejection, symlink-escape rejection, path-traversal rejection — all passed this session). This is unusually thorough, adversarial-minded test coverage for this specific item. |
| Security/integrity qualification proven | ⚠️ PARTIAL / NOT INDEPENDENTLY CONFIRMABLE THIS SESSION | `tests/test_security.py` is one of the 6 forbidden modified-uncommitted tracked files and was not opened; its pass/fail is only known as part of the aggregate 886-passed/0-failed full-suite figure. Adjacent hardening evidence IS directly visible in `tests/test_backup.py` (hostile-path/symlink rejection, cited above) and `tests/test_immune.py`/`tests/test_promotion.py`-adjacent guard tests, but a dedicated security-qualification verdict cannot be produced without reading the forbidden file. |
| Clean install/recovery/concurrency/failure injection proven | ⚠️ PARTIAL | Recovery: `tests/test_backup.py` restore-failure-rolls-back-aside is direct evidence. Clean install: `tests/test_cli.py::test_init_doctor_status_flow`, `::test_init_refuses_non_empty_non_brain` cover CLI-level init. Concurrency: `config/orchestration.toml` self-documents "no hard TS guard...contains NO concurrency enforcement" (already cited under P1.1) — concurrency-failure-injection specifically was not found as a dedicated test suite. |
| Burn-in complete | ❌ NOT COMPLETE | No burn-in log/report artifact was found or claimed this session; this is a live-operation gate outside a single read-only Phase-0 audit's scope by definition. |
| Full regression green | ✅ GREEN | 886 passed, 2 skipped, 0 failed (pytest, this session) + 378 passed, 0 failed (vitest, Prime extension, this session) + ruff clean + Prime-extension eslint/tsc clean. pyright has 3 test-fixture-only typing errors (not production code, see §1). |

**Overall v1.0.0 tagging eligibility this session: NOT ELIGIBLE.** Per the plan's own
rule ("If even one required item remains partial, project remains 0.x"), the repo
correctly remains at `VERSION=0.1.0` with no `v1.0.0` tag and no "Production Ready"
string in source — confirmed directly, not merely assumed.

---

## 4. Existing-primitives quick-reference (plan §2.3, cross-checked against §31 items above)

This is a compact index of every module named in plan §2.3, with its actual current
plan-section anchor (read from each file's own module docstring this session) and its
primary §31 checklist mapping used above. Full detail is in the per-item rows in §2.

| Module | Docstring's own plan anchor | Primary §31 mapping(s) used above |
|---|---|---|
| `autoinject.py` | §6.1-6.8, §6.11-6.12 | P0.2, P0.4 |
| `ledger.py` | §9, §9.10, §11.2, §14 | P0.5, P2.2 |
| `working_set.py` | §100, §17, §18, §73 | P3.1, P1.3 (via jit.py) |
| `jit.py` | §25 | P1.3, P3.2 |
| `semantic.py` | §13, §47-49, §106 | P0.2 (candidates), P2.1 (reindex) |
| `skillforge.py` | §60-61, §112 | P3.11, P4.5 |
| `monitor.py` | §34, §107 | P4.4 (Observe stage only) |
| `envsteward.py` | §74-75, §104 | P3.9 |
| `scout.py` | §22, §23, §102 | P2.4, P3.2 |
| `router.py` | §56, §113 | P0.3 (skill subset only), P3.16 |
| `risk.py` | §35, §103 | P2.5, P3.7 |
| `lean_runtime.py` | §7-8 | P3.4 |
| `promotion.py` | §119 | P4.5, P3.15 (demote only) |
| `plasticity.py` | §40-45, §109 | P4.4 |
| `reconsolidation.py` | §49-52, §15, §111 | not directly mapped to a §31 item this session (advisory forgetting/heat-state; closest is P4.4/telemetry-adjacent, not scored separately) |
| `episodes.py` | §12, §46, §105 | P0.5 |
| `artifacts.py` | §20, §21, §101 | P2.3, P3.3 |
| `backup.py` | §126-127 | cross-cutting Backup/restore (§3 above) |
| `doctor.py` | (undated, "brainctl doctor") | P2.1 (gap identified), §1 baseline |
| `crossmodel.py` | §116 | P2.6 |
| `antigravity_transcript.py` | §13 | P0.1 (Antigravity adapter support) |
| `registry.py` | §10, §130 | P0.1 (project identity), P3.10 (config toggle only) |
| `verify.py` | §37-38, §10, P3-G | P2.5, P3.7, P3.8, P3.5 (partial) |
| `sleep.py` | §53-54, §110 | not directly mapped to a §31 item this session (consolidation pass; closest is P4.5-adjacent, not scored separately) |
| `telemetry.py` | Phase 2 | P0.6, P4.3 |
| `immune.py` | §118 | P4.5 |
| `engram.py` | §58, §115 | not directly mapped to a §31 item this session (workflow macros; no exact §31 item names this) |
| `cerebellum.py` | §39-40, §108 | P4.4 |
| `frontier.py` | §117 | P4.5 |
| `credit.py` | §43-44, §114 | P3.13, P3.14 (partial) |
| `contracts.py` | shared (§6.2/6.4/6.5/6.7/8.2/9.4/11.2/14) | P1.2, P0.4 |
| `cli.py` | (forbidden — modified uncommitted; not read) | not mapped |
| `governor.py` | (forbidden — untracked dormant-campaign work; not read) | not mapped |

Modules named in plan §2.3 but not present under `src/second_brain/*.py`: none — every
module the plan §2.3 list names exists in this repository (confirmed via directory
listing this session).

---

## 5. Notable cross-cutting findings

1. **Two live/shadow config switches materially gate real-use confidence for three
   checklist items.** `config/context.toml [rtd].enabled = false` (P2.3, P3.3) and the
   `recall-gate.ts` DEFAULT-OFF path alongside the config-driven `mode = "active"`
   `autoinject.toml` path (P0.2) both mean "the code exists and is tested" does not
   currently equal "the behavior is live in production by default." This is exactly the
   distinction plan §2.2 warns about ("Do not infer completion from filename/module
   existence").
2. **`doctor.py` does not implement the plan's P2.1 divergence/integrity checks.** The
   9 existing doctor checks are environment/DB-connectivity checks only; no
   stale-projection, corrupt-index, or sequence-violation detector exists, despite
   rebuild machinery (`reindex_all`, ledger `reindex`) being solid and tested.
   Confirmed by reading every function in `doctor.py` and by this session's live run.
3. **P4.1 (goals) and P4.2 (heartbeats) have no Brain-owned implementation** anywhere
   in `src/second_brain` or `brainstem/prime-extension/src` — confirmed by exhaustive
   grep and by the absence of any corresponding test file. These rely entirely on the
   host platform's own equivalent features today, which is a genuine architecture gap
   against the plan's "track locally... no recurring model call simply to remember a
   goal exists" requirement.
4. **P4.5 Controlled Self-Optimization is the strongest-evidenced item in this audit** —
   every stage of the plan's mandatory Observe→Propose→Isolate→Test→Compare→Review→
   Promote→Monitor→Rollback loop maps to a real, tested module, AND a real skill
   (`skills/active/sqlite-migration-verifier`) has demonstrably traversed the pipeline
   end-to-end (confirmed via direct directory listing, not inferred from a report).
5. **Codex is the weakest-integrated of the three non-Prime target harnesses.** No
   hooks installed on this machine, and no lifecycle-adapter test suite comparable to
   Claude Code's or Antigravity's exists in `tests/`.
6. **Governor/ablation work is genuinely in-flight and correctly excluded from this
   report's findings**, per the hard-constraint forbidden-file list — this audit does
   not claim any conclusion about `governor.py`/`config/governor.toml` either way.

---

## 6. Forbidden-file compliance proof

`git status --short` was run at the start of this session (before any inspection) and
again immediately before writing this report. Both outputs are byte-identical:

```text
 M brainstem/prime-extension/tests/sensors.test.ts
 M src/second_brain/cli.py
 M tests/test_artifacts.py
 M tests/test_promotion.py
 M tests/test_security.py
 M tests/test_telemetry.py
?? brainstem/prime-extension/prime-ext-test-full.txt
?? config/governor.toml
?? outputs/reports/logs/
?? outputs/reports/v1-arch-phase-gap-map.md
?? outputs/reports/v1-campaign-state.md
?? outputs/reports/v1-dogfood-campaign-tokens.md
?? outputs/reports/v1-existing-primitives-map.md
?? outputs/reports/v1-harness-wiring-map.md
?? outputs/reports/v1-roadmap-baseline.md
?? outputs/reports/v1-roadmap-matrix-crosscut.md
?? outputs/reports/v1-roadmap-matrix-p0p1p2p4.md
?? outputs/reports/v1-roadmap-matrix-p3.md
?? outputs/reports/v1-security-gate-audit.md
?? outputs/reports/v1-test-integrity-audit.md
?? src/second_brain/governor.py
?? tests/test_governor.py
```

None of these paths were opened, read, copied from, relied upon, moved, renamed,
deleted, staged, or committed this session. Six of them
(`brainstem/prime-extension/tests/sensors.test.ts`, `src/second_brain/cli.py`,
`tests/test_artifacts.py`, `tests/test_promotion.py`, `tests/test_security.py`,
`tests/test_telemetry.py`) are explicitly named as "cannot open" in the rows above where
their content would otherwise have been directly relevant evidence — in every such case
this report cites only their aggregate pass/fail contribution to the full-suite run,
never their content.

The one commit made to this branch during this session by a concurrent sibling worker
(`5457e95`, see §1) was observed only via `git log`/`git show --stat` (commit metadata
and a file-list diffstat, not content) and added a file outside the forbidden list.

This report's own output file, `outputs/reports/v1-roadmap-baseline-reaudit.md`, is a
new filename chosen specifically not to collide with any dormant-campaign filename
listed above.
