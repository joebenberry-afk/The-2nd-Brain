# Optimization Proof Package (v4.3)

Date: 2026-08-15 (UTC). Campaign: Second Brain optimization (Sol
Minimal-Orchestrator pass). Branch: `brain/optimization-sol-orchestrator`.

Every claim cites a commit hash, a test name, or an artifact path. Where the
plan requires evidence that does not exist, the section says **NOT PROVEN —
gap** instead of papering over it.

## 1. Sol Orchestration

- **Policy location**: `brainstem/policies/sol-minimal-orchestrator.md`
  (committed `b5acf83` "documentation truth pass (Phase 5)").
- **Enforcement**: `brainstem/prime-extension/src/orchestrator-guard.ts`
  (pure decision logic, 159 lines) + host wiring in `src/index.ts` — commit
  `61c536a` "brain(adapter): enforce Sol minimal-orchestrator guard"
  (also adds `docs/orchestration/SOL_MINIMAL_ORCHESTRATOR.md`).
- **Allowed tools for orchestrator models**: `ipython` (deliberately NOT
  blocked — it is the `rlm(...)` subagent delegation path),
  `agent_message`/`agent_observe`; **blocked**: `bash`, `edit`, `websearch`
  (`orchestrator-guard.ts:25-26` `DEFAULT_BLOCKED_TOOLS`).
- **Behavioral tests**: `brainstem/prime-extension/tests/orchestrator-guard.test.ts`
  decision-matrix tests — "defaults match the policy contract: bash/edit/websearch
  blocked, ipython NOT listed", "orchestrator model + ipython -> allow (delegation
  path)", "orchestrator model + bash -> block with reason", "non-orchestrator model
  + any tool -> never blocked", "is deterministic", "emits the
  orchestrator_policy_violation kind with bounded enumerated fields"; plus
  wiring tests in `tests/wiring.test.ts`: "tool_call: Sol model + bash ->
  {block:true} with reason and a violation record", "tool_call: Sol model +
  ipython -> NOT blocked, no violation", "before_agent_start: Sol model ->
  systemPrompt contains the delegation rule".
- **Violation count**: **0 live** — the guard is NOT deployed yet (installed
  extension copy at `~/.prime/agent/extensions/second-brain` predates
  `61c536a`); a census of live telemetry (`telemetry/agent-performance/*.jsonl`,
  20,874 records, 2026-08-15) finds **zero** `orchestrator_policy_violation`
  records. Sensor exists end-to-end: schema kind (`brainstem/telemetry/SCHEMA.md`,
  committed `1f2c843`), Python aggregation (`src/second_brain/telemetry.py`
  `orchestrator_violations`/`violation_codes`, `1f2c843`, tests
  `tests/test_telemetry.py::test_report_counts_orchestrator_violations`).

## 2. Telemetry

- **Anonymous session-ID fix (Phase 2)**: one stable `anon-<epochms>-<4hex>`
  id per extension lifecycle — `src/index.ts:156-161` closure; explicit Prime
  session-file stems always win (`resolveSessionId`, `index.ts:60-76`).
  Commit `1f2c843`. Tests: `tests/wiring.test.ts` "reuses ONE stable anonymous
  id for every event without a session file", "appends all anonymous lifecycle
  events to ONE telemetry file, not one per event", "separate extension
  lifecycles get distinct anonymous ids (deterministic)", "explicit Prime
  session file stem still overrides the fallback, byte-for-byte".
- **mkdir-once (Phase 4)**: `tests/storage.test.ts` "establishes the directory
  exactly ONCE per store lifecycle, never per append", "attempts mkdir exactly
  once across ANY number of calls", "a FAILED first attempt is permanently
  marked attempted"; `tests/wiring.test.ts` "two distinct session stores from
  ONE factory share exactly ONE mkdir attempt". Commit `1f2c843`.
- **File-count comparison (pre-fix vs post-fix expectation)**:
  - Pre-fix census (measured in `outputs/reports/optimization-phase0-baseline.md`
    §1, 2026-08-15): **360 files, 304 `anon-*` files each with exactly 1 record,
    310 files with <= 2 records, 13,032 records** — the one-tiny-file-per-event
    fragmentation signature.
  - Post-fix expectation: zero new anon files (one file per anonymous
    lifecycle). Live census 2026-08-15 (this package): **374 files, 304 anon
    1-record files (all pre-fix; newest anon mtime 2026-08-14T16:05Z), 308
    files <= 2 records, 20,874 records, largest session file 4,686 records**.
    No new anon files since the fix landed in the tree — but the fix is NOT
    deployed yet, so the on-disk signature is unchanged until the extension is
    installed and Prime restarted.
- **Overhead measurements**: `proof/results/raw/overhead-paired.jsonl` and
  `overhead-paired-v2.jsonl` (60 rows each; 30 C1_OBSERVABILITY vs 30 C0_OFF):
  C1 peak context percent 1.0624-1.0645% (baseline has none), wall_seconds
  12.32-13.56 both arms, zero failed tool calls / zero regressions on both
  arms — telemetry-on is behaviorally indistinguishable in the harness.

## 3. RTD (real-time distillation, shadow)

- **Eligibility-order fix (Phase 3)**: tool + command eligibility decided
  BEFORE any content measurement (`index.ts:216-218` -> `rtd.ts:50-67`);
  ineligible primitive strings get ZERO JSON.stringify (raw TextEncoder only);
  eligible results are serialized EXACTLY once, shared by
  `tool_result.output_bytes` and `rtd_shadow.size` (`sensors.ts`
  `measureContent`). Commit `1f2c843`.
- **Tests**: `tests/wiring.test.ts` "ineligible tool/command: no RTD shadow
  record, telemetry still measured once", "ineligible primitive-string result:
  ZERO JSON.stringify of the content", "eligible result: content serialized
  exactly once, output_bytes and rtd_shadow.size share the same measurement";
  `tests/rtd.test.ts` "rejects non-bash tools (reason tool) without reading
  any content", "eligibility is checked BEFORE the measurement is used",
  "rtdShadowRecord with precomputed eligibility never re-reads the input
  command"; `tests/sensors.test.ts` measureContent byte-parity suite.
- **Threshold wiring**: `rtd.threshold_chars` from `config/context.toml` now
  feeds the threshold ladder — commit `3848ec8` "brain(adapter): wire
  context.toml rtd threshold_chars into RTD threshold ladder" (tests
  `tests/rtd.test.ts` threshold tests); env `SECOND_BRAIN_RTD_THRESHOLD`
  still overrides; `SECOND_BRAIN_RTD=active` logs intent without substituting
  (`rtd.ts:140-146`, wiring test "SECOND_BRAIN_RTD=active logs intent without
  substituting").

## 4. Retrieval

- **FTS5 engine (Phases 6-9)**: `semantic.search_memories`
  (`src/second_brain/semantic.py`) — FTS5 word/prefix tokens + bm25 primary
  (`_search_fts`), linear Markdown fallback (`_search_linear`, FTS-consistent
  token-AND matching + frontmatter-stripped bodies), Phase 7 hard filters
  (rejected/archived/superseded), Phase 8 canonical-first dedupe, Phase 9
  deterministic scoring (relevance x trust x scope x freshness x decision -
  token penalty). Commit `2ce8c0f`; Phase 10/11/12 (contradiction surfacing,
  top_k/budget, config weights) commit `1b698cf`.
- **Migration 0007 idempotency proof**: `src/second_brain/migrations/0007_memory_index.sql`
  (derived `memory_index` table; `memory_fts` created lazily);
  `tests/test_memory_index.py::test_migration_0007_fresh_create` and
  `::test_migrate_idempotent_reopen` (fresh temp home: 1-7 applied, re-apply
  no-op); fresh-home end-to-end verified in `2ce8c0f` (FTS index built,
  search returns the memory). **Live reindex (this package)**: before — 6
  memories, schema v6, `memory_fts` absent (live path = linear scan); after —
  schema v7, `memory_index` 6/6, `memory_fts` 6/6, `_fts_available=True`,
  `search_memories("brain")` returns 3 rows in ~5 ms with the FTS branch
  taken (`indexed > 0`). Derived data only; `memory/` canonical files
  untouched; `git status` clean.
- **Fresh quality metrics** (harness `proof/runner/retrieval_bench.py`, seed
  20260815; full tables in `proof/reports/retrieval-bench.md` §Phase 9):
  FTS filters+dedupe+full scoring — Recall@1 **0.9375 / 0.96 / 0.98** at
  100 / 1k / 10k; Recall@3 0.9375 / 0.96 / 0.98; dup rate 0.0, stale rate 0.0
  (Phase 6 recorded: R@1 0.0, dup/stale 0.33); **10k p95 = 9.96 ms** (plan
  target <= 200 ms). Post-Phase-12 sanity (100 corpus): R@1 0.9375, p95
  6.34 ms (default `top_k=3` now caps rows, so R@5/P@5 read lower — a
  reporting artifact of the budget, not a quality regression).
- **Quality tests**: `tests/test_retrieval_filters.py` (filters/history),
  `test_retrieval_dedupe.py` (canonical-first), `test_retrieval_ranking.py`
  (scoring + benchmark-fixture R@1), `test_memory_index.py` (FTS fallback +
  parity), `test_retrieval_budget.py` (contradiction markers, top_k, token
  budget, config weights, pct ceiling, invalid-config defaults).

## 5. Configuration

- **Enforced (operative, tested)**:
  - `skills.toml` `router.max_active` — commit `b4f0a47`; tests
    `tests/test_router.py::test_router_max_active_honors_skills_toml` and
    `::test_router_max_active_explicit_override_beats_config`.
  - `context.toml` `rtd.threshold_chars` — commit `3848ec8`.
  - `retrieval.toml` `scoring.max_results` + all `scoring.weights.*` keys
    (13 scalars + grade_scores/status_scores tables) — commit `1b698cf`;
    tests `tests/test_retrieval_budget.py::test_retrieval_toml_weights_reorder_results`
    and `::test_top_k_trims_to_highest_scoring_rows`.
  - `context.toml` `reserve.retrieved_memory_pct_max` — commit `1b698cf`;
    test `::test_retrieved_memory_pct_max_caps_token_budget`.
  - Absent/invalid values fall back to hardcoded defaults (fail open) —
    `::test_absent_or_invalid_config_keeps_defaults`.
- **Informational / planned (NOT WIRED)**: full key-by-key matrix with
  readers and operative flags in `proof/reports/config-consumption.md`
  (e.g. `governor.*`, `lateral_inhibition.*`, `decay.*`,
  `scoring.components`, `sleep.*`, `learning.*`, `environment.toml`
  `track.*` — documented defaults only).

## 6. Router

- **Cache behavior**: SKILL.md metadata parsed at most once per route call
  and cached across calls with mtime-based invalidation — commit `b4f0a47`
  (+ `8d2fe05` Windows mtime fix). Tests: `tests/test_router.py`
  "test_route_reads_each_skill_md_at_most_once_per_call",
  "test_route_second_call_unchanged_files_zero_reads",
  "test_route_cache_invalidates_on_skill_md_change",
  "test_route_conservative_routing_unchanged_with_cache".
- **Conservative routing results**: milestone-17
  (`outputs/reports/milestone-17-skill-router.md`): trigger noise 1 vs
  natural baseline 3; recall 5/5 vs 3/5; F1 0.417 vs 0.250.
  Experiment-143 (`outputs/reports/experiment-143-repeated-workflow-skill.md`):
  fresh unseen task routes to the correct shadow skill (score 4.0 vs 0.0),
  trigger recall 6/6 with zero noise.

## 7. Prime Recall

**NOT PROVEN — gap.** No recall path exists in the committed tree:
- `proof/ACTIVE_CONTRACT.md:1-3` — "Targeted recall event: none ... Recall
  currently requires an explicit `brainctl`/Python caller."
- No env-gated recall hook (`SECOND_BRAIN_RECALL` or equivalent), no trigger
  rules, no injected-token limits: grep of `brainstem/`, `src/`, `docs/` finds
  none. The sibling's Phase 14 commits (`0e49262`, `6ef579a`, `f5c173a`) are
  sleep/replay-clustering work (`src/second_brain/sleep.py`), not Prime recall
  integration.
- The only hook remains the advisory AGENTS.md marker ("use targeted Brain
  recall") written into managed projects (`registry.py` MARKER_BODY, Phase 3)
  plus the guard's `before_agent_start` systemPrompt delegation rule
  (`61c536a`) — neither retrieves Brain memory.


## 7b. Phases 15-17 (conservative no-op)

Per the plan, Phases 15-17 intentionally make NO changes this campaign —
each was reviewed and deferred with a recorded reason:

- **Phase 15 (learning/plasticity)**: no change. The campaign's retrieval
  work must be proven in live use before automatic learning signals feed
  credit/utility updates; `learning.toml` modes remain documented-only
  (config-consumption.md rows "none / no / no").
- **Phase 16 (skill forging)**: no change. `skillforge.py` constants and
  lifecycle stages stay as-is; routing/retrieval quality gates are not yet
  strong enough to auto-forge skills (router is report-only, `shadow: true`).
- **Phase 17 (sleep/replay + compaction)**: no change. Sibling Phase 14
  sleep/replay commits (`0e49262`, `6ef579a`, `f5c173a`) are
  reconciliation/verifier fixes to existing `sleep.py` behavior, not new
  campaign features; compaction/lean-profile behavior in the Prime extension
  (`session_before_compact`/`session_compact` telemetry) is measurement-only
  and unchanged. `sleep.toml` engine/replay keys remain documented-only.
- No lean-profile or systemPrompt-compaction changes were made by this
  campaign beyond the guard contract + recall brief (both default-off for
  non-Sol sessions).

## 8. Remaining Risks

1. **Deployment pending**: the extension at `~/.prime/agent/extensions/second-brain`
   predates `1f2c843` + `61c536a` + `a8c6acb`; the anon-session fix,
   mkdir-once, RTD ordering, threshold wiring, the Sol guard, AND the recall
   hook are NOT live until `scripts/install-prime-extension.ps1` runs and
   Prime restarts. Recall is additionally gated off by default
   (`SECOND_BRAIN_RECALL` unset), so even after deployment it changes
   nothing until explicitly enabled.
2. **Guard live trial not run**: 0 violations is a property of "not
   deployed", not of live enforcement; the decision matrix is unit-proven only.
3. **`contradiction_count` column never written** (read by scoring, no
   writer); contradiction surfacing is title/body-based, file-free.
4. **`_CONTEXT_WINDOW_TOKENS = 200_000` hardcoded** (the pct ceiling is wired,
   the window is not configurable yet).
5. **One transient full-suite flake** observed once (2026-08-15) and never
   reproduced across three subsequent full runs — watch next run.
6. **Bench R@5/P@5 now reflect the `top_k=3` cap** (default budget), not
   engine quality; compare pre/post-Phase-11 tables with the cap in mind.
7. **Recall hook unexercised in production**: unit/wiring-proven only; the
   one-spawn-per-session cost, brief injection quality, and interaction with
   the guard contract need a live trial with `SECOND_BRAIN_RECALL=1`.
7. Live Brain holds only 6 memories — FTS-vs-linear latency at scale is
   proven by the synthetic 10k corpus (p95 9.96 ms vs 1,426 ms linear),
   not by live data.

## 9. Recommendation

Limited rollout, in order:
1. Run `scripts/install-prime-extension.ps1` (pre-install backup) and restart
   Prime Agent; re-census `telemetry/agent-performance/` after a few sessions
   — expect zero new `anon-*` files and (once a Sol model runs) the first
   `orchestrator_policy_violation` records proving the guard fires.
2. Run a live Sol trial with the guard enabled and audit the decision matrix
   against real sessions; measure telemetry overhead on live sessions.
3. Re-census the proof numbers (this document's section 2/3) from live data
   and refresh this file with a dated addendum.
4. Trial the recall hook (now implemented, default off) on a live session
   with `SECOND_BRAIN_RECALL=1` after deployment, audit the injected briefs,
   then decide whether it becomes a default-on feature.
5. Close the gaps: wire `_CONTEXT_WINDOW_TOKENS`, write `contradiction_count`.


---

# Live Rollout Addendum — 2026-08-15

Appended per plan Phase 11 (live validation evidence). Evidence sources:
driver/worker live runs 2026-08-15 (timestamps below), commits `a2be626`
(baseline), `42bf8a3` (flake fix), plus this addendum commit. Quotes are the
recorded live evidence; nothing re-derived.

## 11.1 Deployment (live, 2026-08-15T06:45:44Z)

- Installer `scripts/install-prime-extension.ps1` ran 2026-08-15T06:45:44Z,
  exit 0. Pre-install backup: `backups/20260815-064544-293-prime-extension-pre-install`
  (4 old `.ts` files + settings.json copy; old `index.ts` sha `b0108ac9…`).
- 8 installed files SHA-identical to repo `brainstem/prime-extension/src`:
  `config.ts`, `index.ts`, `rtd.ts`, `sensors.ts`, `storage.ts`,
  `orchestrator-guard.ts`, `recall-gate.ts`, + `types/prime.d.ts`.
- `~/.prime/agent/settings.json` untouched (mtime pre-install) — installer
  never edits settings (script header, verified in `a2be626` baseline).
- Baseline: `proof/reports/live-rollout-baseline.md` (`a2be626`, + re-census
  append) documents pre-deploy installed copy (4 files, mtimes 08-14) vs
  repo, process topology, and restart mechanics.

## 11.2 New code loaded live (recall hook observed in production)

- Recall-hook spawn caught via process polling in a live headless session:
  at **+6.11 s** after session start the session worker spawned
  `C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe -m
  second_brain memory search restore db sqlite stale wal sidecars moved rows`
  (9 sightings ~20 ms apart). Only the NEW extension contains the recall
  hook → **new code demonstrably active in new sessions** (no restart
  needed; per-session loader, `a2be626` §3b).

## 11.3 Recall — relevant live test

- Env `SECOND_BRAIN_RECALL=1`, model `deepseek/deepseek-v4-flash`, prompt
  "restore db sqlite stale wal sidecars moved rows" (42 chars / 8 words):
  spawn fired with the EXACT query; session telemetry **0 `extension_error`
  records**. Headless transcripts do not persist the systemPrompt, so the
  injection itself is unit-proven (23 recall-gate + 6 recall-wiring vitest
  tests, `a8c6acb`) with the live spawn + CLI chain confirmed.

## 11.4 Recall — irrelevant live test

- Prompt "bake sourdough bread at high altitude with rye starter": spawn
  fired (20 sightings, exact query), **0 rows → no injection**; model
  answered from own knowledge; no hallucinated memory; **0
  `extension_error`**.

## 11.5 Recall bounds (live-confirmed contract)

- Exactly ONE spawn per `before_agent_start`; single query; defaults
  `MAX_ROWS=3`, `MIN_CHARS=40`, `TIMEOUT_MS=5000`, brief ≤1000 words
  (`recall-gate.ts`, `a8c6acb`); full vitest suite 177/177 green.

## 11.6 Guard — live status (Pass Condition B)

- Headless print sessions AND the RLM harness expose ONLY the `ipython`
  tool (verified by two live sessions reporting "no tool literally named
  bash"; `websearch` absent too). `bash`/`edit`/`websearch` therefore
  **cannot be invoked live** → negative tests A–C cannot trigger the block
  path; plan Pass Condition B applies.
- **Zero `orchestrator_policy_violation` records** in the 22,615-record
  census — no false positives.
- Sol model unavailable per handoff → Sol-specific acceptance is
  **explicitly blocked by model availability** (not by the guard).
- Unit-level enforcement proof: 14 orchestrator-guard + 7 guard-wiring
  vitest tests (decision matrix incl. block + violation record), `61c536a`.

## 11.7 Test D — allowed path (live)

- The campaign itself ran on the live system (driver `deepseek/deepseek-v4-pro`
  + 2 `deepseek-v4-flash` workers, ≤2 concurrent) with **zero violations and
  no deadlocks** — delegation/reading works live.

## 11.8 FTS5 live

- Schema v7, `memory_fts` 6/6 rows, FTS branch taken (`semantic.py:1172-1190`);
  live query "sqlite restore" → 1 row `[current/VERIFIED]`.

## 11.9 Telemetry re-census (2026-08-15T~12:00Z, post-deploy)

- 387 files (+27), anon 304 (**0 new**; newest anon pre-deploy),
  ≤2-record files 308 (all pre-deploy), 22,615 records (+9,583);
  `orchestrator_policy_violation` 0 / `rtd_shadow` 0 / `extension_error` 0;
  1 pre-deploy malformed line (01a003e2, NUL byte) only; all post-deploy
  records valid `v=2` bounded schema; all 20 post-deploy sessions use UUID
  stems. (Full tables in `proof/reports/live-rollout-baseline.md` append.)

## 11.10 Realistic task (Phase 5)

- Flake investigation → real mechanism: `tests/test_migrations_property.py`
  was the only Hypothesis file without `deadline=None`; git-init subprocess
  + 200 ms deadline under two-worker contention → minimal test-only fix
  `42bf8a3` → full suite **655 passed / 2 skipped** pre and post.

## 11.11 Phase 9 gaps (re-confirmed non-blocking)

- `_CONTEXT_WINDOW_TOKENS = 200_000` hardcoded; `contradiction_count` column
  unwritten. Both NON-BLOCKING (no effect on rollout; recall/retrieval
  budgets observed fine). No changes made.

## 11.12 Automated regression state (re-run this campaign)

- pytest **655 passed / 2 skipped** (post-fix); vitest **177/177**; ruff
  clean; pyright clean.

## 11.13 Final status

**PARTIALLY VALIDATED** — SOL-SPECIFIC ACCEPTANCE BLOCKED (Sol-specific
guard block-path trial still blocked solely by Sol model unavailability;
guard machinery live-proven model-independent). All model-independent
machinery (deployment, per-session loading, recall hook, telemetry health,
FTS5, campaign delegation) is live-proven. The daemon restart step
(graceful `shutdown --force`, per §11.14) is EXECUTED — 2026-08-15T12:11Z,
recorded in §11.15; the Sol trial can run when a Sol model is available.

## 11.14 Graceful daemon shutdown (driver restart step)

- Command: `prime-agent shutdown [--force] [--json]` (command-registry
  "shutdown"; `cli/public-command.ts:261-266` → `cli/daemon-command.ts:254-263`
  sends `{type:"shutdown", force}`) → supervisor `case "shutdown"`
  (`daemon-supervisor.ts:1575-1577`) → graceful `shutdown()`: requests each
  worker to archive+shut down (4720-4723, 5 s grace, SIGKILL fallback),
  then `process.exit`; log: "shutdown command received over socket; N active
  session(s) will be closed". Use `--force` for headless (skips interactive
  confirmation; unresponsive workers are the only force-kill target).
  On this machine (no `prime-agent` on PATH):
  `node C:/Tools/prime-agent/node_modules/tsx/dist/cli.mjs --tsconfig
  C:/Tools/prime-agent/tsconfig.json
  C:/Tools/prime-agent/packages/coding-agent/src/cli.ts shutdown --force`
  Clients auto-relaunch the cold daemon on next run (cli-main/daemon-launch
  probe). EXECUTED by this campaign on 2026-08-15: old supervisor pid 26652
  last logged 12:07:34.870Z; the next client run auto-relaunched the cold
  daemon — new supervisor pid 26456 id `b9da0028-ed7e-4ae0-a01f-e14ca9d68e30`
  listening 12:11:43.579Z, fresh session worker pid 31216 id
  `d7208ad5ffea` 12:11:45.750Z, fresh kernels 12:11:48Z. Full sequence and
  load verification in §11.15.

## 11.15 Post-restart load verification (2026-08-15T12:11–12:20Z)

Restart sequence (daemon log `~/.prime/agent/logs/agent.jsonl` and
`prime-agent-daemon.2245fa1c.log`; process census via
`Get-CimInstance Win32_Process`):

- Old supervisor pid 26652: last log line 2026-08-15T12:07:34.870Z
  ("Supervisor command get_session_stats failed: Error: Session worker is
  stopping" — session teardown underway); process gone post-restart.
- New supervisor pid 26456, id `b9da0028-ed7e-4ae0-a01f-e14ca9d68e30`:
  "listening on \\.\pipe\prime-agent-daemon" at
  2026-08-15T12:11:43.579Z. All `node.exe` CLI processes (daemon chain)
  created 12:11:37–43Z.
- Fresh session worker pid 31216, id `d7208ad5ffea`: "listening on
  \\.\pipe\prime-agent-worker-2245fa1c0e38-d7208ad5ffea" at
  2026-08-15T12:11:45.750Z; descriptor `d7208ad5ffea.json` valid
  (workerId/pid 31216/socketPath).
- Fresh Python kernels pids 12836 + 26912 (`ipykernel_launcher`),
  CreationDate 2026-08-15T12:11:48Z.
- Startup hygiene: the new supervisor discarded two stale zero-filled
  worker-descriptor files left by the pre-restart daemon's hard stop
  ("Ignoring invalid worker descriptor ... not valid JSON",
  12:11:41.858Z/.860Z) and continued; no extension error / crash /
  missing-dependency lines in any log since 12:11:40Z
  (`client-errors.log`: none).

Extension identity post-restart (SHA-256, live vs repo
`brainstem/prime-extension/src` + `types/prime.d.ts`):

- 8/8 installed files byte-identical to repo: `config.ts`
  `3ceb6dc5…`, `index.ts` `4405af2e…`, `orchestrator-guard.ts`
  `c2950b86…`, `recall-gate.ts` `4b8253ae…`, `rtd.ts` `ac7820ee…`,
  `sensors.ts` `e70f288e…`, `storage.ts` `3dad5234…`, `types/prime.d.ts`
  `8feab2d6…`.
- `~/.prime/agent/settings.json` untouched: LastWriteTimeUtc
  2026-08-15T05:01:00Z (pre-restart).

Restarted-session telemetry (this session
`telemetry/agent-performance/01a00555-d423-721b-9545-ad54c630260e.jsonl`):

- All lines valid JSON `v=2`; `session_start` at
  2026-08-15T12:11:46.990Z (model `deepseek/deepseek-v4-pro`, reason
  `startup`); **0 `extension_error`** records.
- Anon census unchanged: 304 files matching `^anon`, none modified after
  2026-08-15T12:11:40Z.

Result: daemon restart fully executed; extension loads and telemetry
records identically in the restarted daemon; no startup errors.
