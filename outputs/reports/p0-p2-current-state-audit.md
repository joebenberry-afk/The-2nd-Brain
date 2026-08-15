# P0→P2 Current-State Audit (Phase 0A)

- **Date:** 2026-08-16 (session run)
- **Campaign:** P0→P2 DeepSeek OneShot per `Second_Brain_P0_P2_DeepSeek_OneShot_Implementation_Plan.md` (sec 16 PHASE 0A, sec 15 STAGE D0, sec 23 STOP, sec 26/27 read only)
- **Repo:** `C:/Users/assas/Documents/The-Second-Brain`
- **Branch/HEAD:** `brain/optimization-sol-orchestrator` @ `a94cba0` (brain(adapter): driver orchestration contract)
- **Role:** EXPLORER — read-only. Only file written: this report.

## 1. Scope & method

- Read only plan sections 15 (STAGE D0), 16 (PHASE 0A), 23 (STOP), 26/27; the full plan was NOT read.
- Ran baseline commands (pytest, ruff, pyright, npm lint/typecheck/test, codex detection).
- Mapped 12 required components via targeted grep/head of repo + installed Prime/Codex/RLM APIs.
- No code modified. Untracked `memory/semantic/mem-ae7a34f105c5.md` pre-existed; noted, untouched.
- All Python runs stripped `PYTHONHOME`/`PYTHONPATH` (corrupted uv tree on this machine).
- No installs performed.

## 2. Classification table (12 required components)

| # | Component | Class | Evidence (exact path) |
|---|---|---|---|
| 1 | Brain retrieval | **REUSE** | `src/second_brain/semantic.py:1379 search_memories` — FTS5 bm25 primary + linear fallback, fail-open; `working_set.py` session capsules (init/update/requirements/evidence); `router.py:239 route` skill routing with `[router] max_active`; `migrations/0007_memory_index.sql` derived index table |
| 2 | Packet/context compiler | **EXTEND** | `src/second_brain/jit.py:139 compile_context` writes task-context capsule (`active-state.json` etc.); `cli.py:1645 cmd_context` + `context compile` subcommand. No canonical "injection packet" renderer with budget/NO_INJECTION today → P0C packet renderer is an extension |
| 3 | Prime extension lifecycle hooks | **EXTEND** | `brainstem/prime-extension/src/index.ts` — 11 events wired: session_start, before_agent_start, turn_start, context, tool_call, tool_result, turn_end, agent_end, session_before_compact, session_compact, session_shutdown; plus rtd_shadow, orchestrator_policy_violation. Already injects Sol orchestrator contract as systemPrompt addendum and blocks direct execution tools for Sol sessions. No memory AutoInject today (`recall-gate.ts` is env-gated, SHADOW-like brief injection) |
| 4 | Telemetry | **REUSE** | `src/second_brain/telemetry.py` (iter/validate/report/format_report); `brainstem/telemetry/SCHEMA.md` (JSONL v2, privacy rule: counts/sizes/hashes only, bash cmd ≤500 chars); `prime-extension/src/sensors.ts` (measureContent, redaction, record builders) |
| 5 | Session/artifact storage | **REUSE + EXTEND** | `src/second_brain/artifacts.py` — content-addressed blobs `state/artifacts/blobs/<sha256>.bin` + meta JSON; `db.py` migration framework (0001–0007); `state/` layout: artifacts, cache, experiments, locks, ownership, projections, promotions. No per-root session ledger / branch lineage / flush barrier yet (P2A work) |
| 6 | Security helpers | **REUSE** | `src/second_brain/security/paths.py` — `resolve_under` (symlink-safe, drive-letter aware), `assert_safe_recursive_delete`, `validated_project_dir`; `security/identifiers.py` — `validate_identifier` + 8 typed validators (project/skill/engram/frontier/proof_task/policy/trigger) |
| 7 | FTS/index | **REUSE** | `migrations/0007_memory_index.sql` — derived `memory_index`; `memory_fts` FTS5 created lazily in `semantic.py` behind `_fts_available` (IF NOT EXISTS) with linear-scan fallback; `brainctl memory reindex` rebuild path. No FTS over session events (no ledger yet) |
| 8 | Compaction behavior | **EXTEND (observe→control)** | Prime native: `/compact` + auto at `contextWindow - reserve(16k)`, keepRecent 20k, `CompactionEntry{type,id,parentId,timestamp,summary,firstKeptEntryId,tokensBefore,fromHook,details,customInstructions}`, split-turn handling, branch summarization (`C:/Tools/prime-agent/packages/coding-agent/docs/compaction.md`). Extension today only RECORDS session_before_compact/session_compact (index.ts:456,460); no pre-compaction flush barrier/checkpoint → P2D work |
| 9 | Installed Prime/Pi exact API | **REUSE** | Hook types in `src/core/extensions/types.ts`: SessionStart, BeforeAgentStart, AgentStart, AgentEnd, TurnStart, TurnEnd, Context, ToolCall, ToolResult, SessionBeforeCompact, SessionCompact, SessionShutdown (+CustomMessage at messages.ts). `setActiveTools` exists (loader.ts:285, runner.ts:282); custom-message API at types.ts:366/999/1127 + custom renderer registration (1118). Session tree: entries have `id`/`parentId` (session-manager.ts:248; entry types include compaction/branch_summary/custom_message) |
| 10 | Codex API | **MISSING (seam exists)** | `codex-cli 0.147.0` installed (C:\Users\assas\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe). `~/.codex/config.toml` has `[hooks.state]` trusted hashes ONLY (plugins: security-guidance, superpowers, ponytail) — no active `[hooks]` commands. Plugin manifests verify event names: PreToolUse, PostToolUse, SessionStart, Stop, UserPromptSubmit, SubagentStart, SubagentStop. 6 custom agent profiles exist in `~/.codex/agents/` (doc-writer, end_of_session, executor_luna, executor_sol, explorer, tester); `wire_api="responses"`, model gpt-5.6-luna; deepseek-pro/flash profiles exist. No Brain-managed Codex hook today |
| 11 | RLM subagent API | **REUSE** | `skills/agent-message/SKILL.md` — `agent_message.send(receiver_role=parent|sibling|child, receiver_name=…)` via daemon, family roster; `agent-observe` — read-only family status + recent messages; `compact` — `compact.status()/run("instructions")`; `goal` — `goal.get()/create()/complete()` with token budget. Harness: `rlm('sub-task')` spawn, `rlm.list_subagents()`, harness CRUD for memories/skills/subagents/prompt notes, child replies via agent_message |
| 12 | Tests | **REUSE** | `tests/` 39 pytest files → 657 collected (655 passed, 2 skipped); retrieval budget/dedupe/filters/ranking, memory_index, migrations-property, security paths covered. `brainstem/prime-extension/tests/` 8 files → 201 vitest tests pass (config, driver-orchestrator, orchestrator-guard, recall-gate, rtd, sensors, storage, wiring, integration) |

## 3. BASELINE / STAGE D0 evidence

### Git state
- Branch `brain/optimization-sol-orchestrator`, HEAD `a94cba0` (clean).
- Only uncommitted item: `?? memory/semantic/mem-ae7a34f105c5.md` — pre-existing untracked file (per campaign brief); left untouched.

### Command results (exact)
| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` (pytest 9.1.1, addopts=-q) | **655 passed, 2 skipped, 0 failed** — 139.15s, exit 0 (summary hidden by CR-progress; re-run with `-o addopts=''`) |
| `.venv/Scripts/python.exe -m ruff check src tests` | **2 errors**, exit 1 — both E501 line-too-long: `tests/test_router.py:243:101`, `tests/test_router.py:264:101` (pre-existing, trivial) |
| `.venv/Scripts/python.exe -m pyright` | **3 errors, 0 warnings** — `tests/test_memory_index.py:278/281` (+1) `StubConn` not assignable to `Connection` in `_fts_available` (test-only typing) |
| `npm run lint` (eslint) | exit 0, no findings |
| `npm run typecheck` (tsc --noEmit) | exit 0 |
| `npm run test` (vitest run) | **8 files, 201 tests passed**, 4.89s |
| `where.exe codex` | `C:\Users\assas\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe` (+ npm shims) |
| `codex --version` | `codex-cli 0.147.0` |
| `ls ~/.codex` | exists: config.toml, agents/ (6 profiles), plugins/, auth.json, deepseek-pro/flash configs, backups |
| Codex hooks config | `[hooks.state]` trusted plugin hashes only; no active `[hooks]` command table |

### Config switch modes (`config/*.toml`)
- `config/learning.toml`: `shadow = true`, `advisory = false`, `active = false` — learning is SHADOW (would-trigger only).
- `config/skills.toml`: `[router] max_active = 3` — ENFORCED (router.py reads it per `route()`); `stages = [candidate, shadow, staged, approved, retired]`, `adoption = [shadow, advisory, active]`.
- `config/context.toml`: `[rtd] threshold_chars` — RTD is SHADOW MODE (measure only, no substitution); env `SECOND_BRAIN_RTD_THRESHOLD` > file > default 8000; eligibility fixed in `rtd.ts RTD_COMMAND_PREFIXES` (`pytest`, `git`, `rg`, `grep`).
- `config/environment.toml`: shutdown checks (owned_process_leak, untracked_junk, active_children, …).

## 4. STOP-condition checklist (plan sec 23)

| # | Condition | Verdict | Evidence |
|---|---|---|---|
| 1 | Dirty repo w/ unexplained user work | **OK** | Tree clean except pre-existing untracked mem file (documented, not ours) |
| 2 | Security remediation missing/regressed | **OK** | security/paths.py + identifiers.py present with tests; no regression (655 green) |
| 3 | Prime live API differs, no safe injection/tool-enforcement seam | **OK** | Seam proven: extension already injects systemPrompt addendum + blocks tools via orchestrator-guard; 11 events wired |
| 4 | Codex hook API differs, no supported AutoInject seam | **RISK** | Hooks system exists (plugin events verified), but no Brain-managed hook configured yet; seam unexercised → smoke-test before P0 ACTIVE |
| 5 | Only way to inject = silent high-authority system policy | **OK** | No memory injection today; recall-gate is env-gated and injects as brief (low authority); Sol contract already low-authority addendum |
| 6 | Raw user prompt interpolated through shell | **OK** | No such path; rtd.ts measures only, never substitutes |
| 7 | P2 cannot identify safe internal session path | **RISK** | No per-root session ledger path identified yet; extension writes to `<brain>/telemetry/agent-performance/` + `sanitizeSessionStem` exists — safe path design pending P2A |
| 8 | Session purge cannot prove path containment | **RISK** | No purge exists yet; `resolve_under`/`assert_safe_recursive_delete` primitives ready — proof pending P2E |
| 9 | Compaction cannot be blocked / ledger flush unreliable | **RISK** | Extension observes `session_before_compact` only; no flush barrier/block path — P2D must add; if unachievable → downgrade P2 guarantee per plan |
| 10 | Request snapshots require persisting API credentials | **OK** | Telemetry privacy rule prohibits credentials; snapshot design must preserve |
| 11 | Exact replay claimed without proof | **OK** | No replay claimed yet; replayer is P2C work |
| 12 | SQLite migration unsafe/non-idempotent | **OK** | Migration framework + `test_migrations_property.py`; 7 migrations applied cleanly |
| 13 | Dogfood P1 runaway fan-out / instability | **OK** | Not active yet; policy = default 1 worker, max 2 |
| 14 | Cache opt changes provider request semantics unproven | **OK** | Not attempted; `wire_api="responses"` noted for later |
| 15 | New dependency/service/vector DB "convenient" | **OK** | Nothing added; FTS5 lazy + fallback already in place |
| 16 | Violates Constitution/security policy | **OK** | Injection/telemetry respects privacy boundaries; no constitution edits |
| 17 | Meaningful regression with unknown root cause | **OK** | All suites green; ruff/pyright findings are trivial pre-existing style/typing with known cause |

**No STOP conditions currently fire. 3 RISKs (#4, #7, #9) are design/implementation items for P0/P2, not blockers to Phase 0A.**

## 5. Adapter fidelity notes

### Prime (Pi)
- Extension = measurement + orchestrator-role enforcement today. 11 lifecycle events + 2 derived kinds (rtd_shadow, orchestrator_policy_violation) recorded as JSONL under `telemetry/agent-performance/<session>.jsonl`.
- `recall-gate.ts` is the closest thing to P0 AutoInject: env-gated (`SECOND_BRAIN_RECALL`, `_MAX_ROWS`=3, `_MIN_CHARS`=40, `_TIMEOUT_MS`=5000), side-effect-free decision/format split, injects a compact Brain Brief — a SHADOW-ready foundation.
- `driver-orchestrator.ts` + `orchestrator-guard.ts` + `storage.ts` exist (Sol contract injection, tool blocking, extension state) — P1 partial groundwork already shipped.
- API surface confirmed: `setActiveTools`, custom messages (customType/content/display/details), custom renderer registration, compaction events, session entries with `id`/`parentId` tree.
- Fidelity gap: extension cannot see final provider request envelope (cache-key material) — P1C metrics are best-effort; `context` event provides messages/usage only.

### Codex
- CLI 0.147.0 with plugin-hook infrastructure; event names verified from plugin manifests: PreToolUse, PostToolUse, SessionStart, Stop, UserPromptSubmit, SubagentStart, SubagentStop.
- No Brain-owned hooks installed; `[hooks.state]` contains only third-party plugin hashes. Adding Brain hooks = new config table + trusted hash or command path (unverified mechanics on this version).
- Custom agent profiles already present (`~/.codex/agents/*.toml` — executor_luna, executor_sol, explorer, tester, doc-writer, end_of_session) → P1A Codex side is partially pre-built.
- Providers: default OpenAI (`gpt-5.6-luna`, `wire_api=responses`), DeepSeek opt-in profiles (deepseek-pro/deepseek-flash).

## 6. UNKNOWNs (honest)

1. **docs/session.md does not exist** in `C:/Tools/prime-agent/packages/coding-agent` — session-tree fields (id/parentId) confirmed via `session-manager.ts:248` and `docs/compaction.md`, but a dedicated session doc was not found; deeper field semantics (segment boundaries, replay) unverified.
2. **Codex hook installation mechanics** (adding a Brain hook command to this exact 0.147.0 config, trusted-hash requirements, whether hooks fire for desktop-app sessions) unverified — must smoke-test in P0C.
3. **Prime extension env-var surface** beyond recall/RTD gates not fully enumerated (config.ts `loadConfig` not exhaustively read).
4. **`state/` stray dirs** (`p0-audit-dkaqfth7`, `p0manual`, `pytest-cache-p0`, `projections`, `promotions`) — origin/purpose not verified in this audit; may be leftovers from prior campaigns.
5. **Provider cache metrics** (P1C Cache Doctor inputs) — availability on OpenAI responses API from Prime session state unverified.
6. **Exact Prime session file layout** (where session JSONL lives under `~/.prime/agent/sessions/…`) not verified beyond extension's `sanitizeSessionStem` usage.
7. pytest's default `-q` suppresses the terminal summary line in this environment (CR-progress only); counts obtained via `-o addopts=''` rerun — cosmetic, no behavioral impact.

## 7. Bottom line for Phase 0B+

- **REUSE-heavy start:** retrieval, telemetry, security helpers, artifact store, migration framework, RLM messaging, tests all mature.
- **First EXTEND targets:** canonical packet renderer (P0C), recall-gate → AutoInject shadow (P0C), compaction control + session ledger (P2A/2D), Codex hooks (P0C adapter).
- **MISSING:** Codex Brain hooks (seam exists), per-root session ledger/branch lineage, pre-compaction flush barrier, replay/invariant checker, rehydration store.
- **Baseline is green** except 2 ruff E501 + 3 pyright test-typing errors (pre-existing, known cause, non-blocking).
