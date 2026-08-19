# Second Brain v1.0 — Harness Wiring Map

**P0-PRIMITIVES-V3** • Judgment layer • 2026-08-18
Evidence-based cross-system wiring: what binds to what, with file:line citations.

## A. Prime Extension TypeScript Modules (brainstem/prime-extension/src/)

All 11 modules are bound to Prime lifecycle hooks via index.ts wire<T>() calls.

### autoinject.ts
**Hooks**: session_start (line 330), turn_start (line 451)

**Purpose**: P0 AutoInject Shadow adapter: spawns Python CLI `second_brain autoinject shadow --json` on each hook, sends event JSON on stdin, records decision

**Data flow**: Session/turn event → stdin | stdout (JSON decision) → telemetry append via sensors.ts

**Evidence**: index.ts line 74 (import), lines 330/451 (runShadowAutoInject/runAdvisoryAutoInject calls)

### config.ts
**Hooks**: load-time (line 87)

**Purpose**: Config gate: checks SECOND_BRAIN_OBSERVABILITY env var and brain-home existence; disables extension if off

**Data flow**: Environment → bool disable flag → index.ts initialization

**Evidence**: index.ts line 87 (loadConfig call); config.ts lines 1-50 (disable logic)

### orchestrator-guard.ts
**Hooks**: before_provider_request (line 703), before_agent_start (line 340)

**Purpose**: Sol guard: blocks bash/edit/websearch tools for orchestrator models; injects Sol contract into systemPrompt on before_agent_start

**Data flow**: Model substring → ORCHESTRATOR_MODELS check → returns {block:true, reason} or {systemPrompt} patch

**Evidence**: index.ts line 25 (import), lines 497/703 (isOrchestratorModel/buildPolicyBlockRecord calls); orchestrator-guard.ts lines 1-50 (policy logic)

### driver-orchestrator.ts
**Hooks**: before_agent_start (line 340)

**Purpose**: Role resolver: maps model substrings to hard_orchestrator/driver/worker/normal; appends driver contract for non-Sol models

**Data flow**: Model name → role classification → optional systemPrompt contract injection

**Evidence**: index.ts line 76 (import), line 340 (resolveAgentRole call); driver-orchestrator.ts lines 1-50 (role model)

### recall-gate.ts
**Hooks**: after_provider_response (line 658)

**Purpose**: Brain recall on provider response: bounded semantic search of session context, injects results if found

**Data flow**: Response event → runBrainRecall → Python Brain search via CLI → results injected into turn context

**Evidence**: index.ts line 81 (import), line 658 (runBrainRecall call); recall-gate.ts lines 1-50 (config/threshold logic)

### lean-code.ts
**Hooks**: after_provider_response (line 478)

**Purpose**: Lean Code runtime kernel: extracts marked code blocks from response, writes to artifacts storage

**Data flow**: Response content → regex for `# Runtime Kernel` marker → artifact file write

**Evidence**: index.ts line 83 (import), line 478 (appendLeanKernel call); lean-code.ts lines 1-50 (LEAN_KERNEL_MARKER)

### rtd.ts
**Hooks**: before_provider_request (line 759)

**Purpose**: Real-time distillation: captures eligible subprocess outputs (pytest, git, rg, grep) that exceed RTD_DEFAULT_THRESHOLD (8000 bytes), stores as artifacts

**Data flow**: Bash commands → rtdEligibility check → large results → artifacts storage; reads config/context.toml [rtd] enabled

**Evidence**: index.ts line 86 (import), line 759 (runRtd call); rtd.ts lines 1-50 (eligibility logic, threshold config)

### ledger-mirror.ts
**Hooks**: session_start (line 340), agent_end (line 855), session_compact (line 894), session_shutdown (line 918)

**Purpose**: P2 session ledger mirror: spawns Python CLI to record task hashes, segment rollovers, checkpoints, session close events in canonical ledger

**Data flow**: Lifecycle event → runLedgerCheckpoint/runLedgerSegmentRollover → Python ledger.py API call

**Evidence**: index.ts lines 90 (import), 340/855/894/918 (runLedgerCheckpoint/runLedgerSegmentRollover calls); ledger-mirror.ts lines 1-50 (API contracts)

### sensors.ts
**Hooks**: all 9 hooks

**Purpose**: Pure event → telemetry record transformation (privacy-safe): counts, sizes, hashes, error flags, tool names, bash command text (truncated 500 chars)

**Data flow**: Every hook calls sensors.*() → returns telemetry record dict → appended to JSONL via storage.ts

**Evidence**: index.ts: every hook calls sensors.* or mirror() helper which calls sensors.*; sensors.ts lines 1-50 (privacy rules, byteLength, sensors.sessionStart, etc.)

### storage.ts
**Hooks**: all 9 hooks (fire-and-forget)

**Purpose**: Async JSONL telemetry storage: queues append operations on internal promise chain, writes to <brain-home>/telemetry/agent-performance/<session>.jsonl

**Data flow**: Telemetry record → getStore().append() → internal queue → filesystem write (never awaited on critical path)

**Evidence**: index.ts line 91 (import), every hook calls getStore().append(); storage.ts lines 1-30 (TelemetryStore, append, fire-and-forget)

### index.ts
**Hooks**: wire<T>() registration hub

**Purpose**: Extension entry point: loads config, registers all 9 hooks via wire<T>(), manages fail-open semantics

**Data flow**: activate() → loadConfig() → wire<SessionStartEvent>, wire<TurnStartEvent>, etc. → handlers call sensors/storage/submodules

**Evidence**: index.ts lines 1-100 (imports, activate signature), lines 327/555/559/577/591/794/818/885/908 (all wire<T>() calls)


## B. Claude-Code Adapter (brainstem/adapters/claude-code/)

Three native Claude Code lifecycle hooks via hooks.json, each spawning `brainctl autoinject claude-code-hook`.

| Event | Handler | What it does | Evidence |
|-------|---------|-------------|----------|
| **SessionStart** | hooks.json (line 3) | Registers host=claude-code in telemetry via autoinject.BrainLifecycle.start_session(); returns empty {} | run-hook.ps1 line 25+; README.md line 12 |
| **PreCompact** | hooks.json (line 12) | Extracts goal from transcript's last user message + git state; writes compaction_started ledger event; calls ledger.checkpoint_ledger | README.md line 13-14 |
| **Stop** | hooks.json (line 20) | Records claude_code_stop_turn telemetry on every turn; scans for optional `<!--second-brain-candidate ...-->` marker; writes candidate memory if present | README.md line 15 |

**Test coverage**: tests/test_claude_code_adapter.py (26 test functions at lines 1-1200+); verifies each hook event, session dedup, ledger integration, fail-open behavior.

**Reach to Brain**: Every hook spawns powershell run-hook.ps1 (brainstem/adapters/claude-code/scripts/run-hook.ps1 line 25+), which calls `brainctl autoinject claude-code-hook` with JSON on stdin; script exits 0 even on Brain errors (fail-open).


## C. Antigravity Adapter (brainstem/adapters/antigravity/)

Three event types via hooks.json, each spawning scripts/run-hook.ps1.

| Event | Matcher | Handler | What it does | Evidence |
|-------|---------|---------|-------------|----------|
| **PreInvocation** | (unconditional) | hooks.json lines 4-10 | Runs before tool invocation; calls brainctl autoinject antigravity with 'pre' event type | hooks.json line 5-7; run-hook.ps1 |
| **PostInvocation** | (unconditional) | hooks.json lines 11-16 | Runs after tool result; sends result to Brain for RTD eligibility / artifact store decision | hooks.json line 12-14 |
| **PostToolUse** | matcher: '*' (all tools) | hooks.json lines 17-26 | Runs on every tool use completion; thin event pass-through | hooks.json line 18 |

**Plugin metadata**: plugin.json line 2-4 (name: second-brain-adapter, description: thin harness adapter).

**Test coverage**: tests/test_antigravity_adapter.py (17 test functions); verifies hook event dispatch, session identity, Brain unavailability handling.

**Reach to Brain**: scripts/run-hook.ps1 (brainstem/adapters/antigravity/scripts/run-hook.ps1 line 4) calls `brainctl autoinject antigravity-hook --event $Event` with JSON payload; fail-open (exit 0).


## D. Codex-Hooks (brainstem/codex-hooks/)

Five native Codex IDE lifecycle hooks via hooks.toml, each spawning `brainctl autoinject codex-shadow`.

| Event | Handler | What it does |
|-------|---------|-------------|
| **SessionStart** | hooks.toml line 4 | Registers host=codex in telemetry via autoinject.BrainLifecycle |
| **UserPromptSubmit** | hooks.toml line 5 | Records user prompt; spawns Python shadow decision |
| **SubagentStart** | hooks.toml line 6 | Records subagent invocation event |
| **Stop** | hooks.toml line 7 | Records turn completion (shadow: {}, no injection) |
| **SessionEnd** | hooks.toml line 8 | Records session close event |

**Reach to Brain**: Every hook spawns run.ps1 (brainstem/codex-hooks/run.ps1 line 5-6), which calls `brainctl autoinject codex-shadow` with JSON on stdin; script exits 0 on all Brain errors (fail-open).

**Status**: IMPLEMENTED AT SHADOW LEVEL (decision recorded in telemetry, returns {}, no model-visible mutation). Corresponds to Phase 0C part 2 (plan §6.10).

**Test coverage**: tests/test_autoinject_codex.py (5 test functions: test_valid_stdin_deterministic_output, test_prompt_key_accepted_as_task, test_malformed_stdin_fails_open, test_no_argv_task_path_exists, test_wrong_project_stdin_no_injection).


## E. Config Files (config/*.toml)

Enforcement status per runtime reader. Schema versions all = 1.

| File | Wiring | Readers | Evidence |
|------|--------|---------|----------|
| autoinject.toml | ENFORCED | autoinject.load_config() reads [budget] and [delta_budget]; ... | autoinject.py:102-126, index.ts line 74 |
| brain.toml | DOCUMENTED-ONLY | No runtime reader exists (proof/reports/config-consumption.m... | (grep found no readers) |
| context.toml | PARTIAL ENFORCED | semantic.load_retrieval_config() reads [reserve].retrieved_m... | semantic.py:1094-1150 |
| environment.toml | DOCUMENTED-ONLY | envsteward.py mentions it (line 6 docstring) but does not re... | envsteward.py:6 (docstring only) |
| learning.toml | DOCUMENTED-ONLY | No runtime reader; plasticity.py does not load it... | (grep found no readers) |
| orchestration.toml | ADVISORY | Policy text only; orchestrator-guard.ts does not read concur... | (documented guidance, no enforcement code) |
| retrieval.toml | ENFORCED | semantic.load_retrieval_config() (line 1094) reads [scoring].max_results and weights; live call site: search_memories (line 1428). Stale TODOs at lines 974/1033 say "weights hardcoded" but config IS read at runtime. | semantic.py:1094-1163, :1428 |
| session-retention.toml | ENFORCED | ledger.load_retention_config() reads [retention]; reads on s... | ledger.py:61-74 |
| skills.toml | PARTIAL ENFORCED | router._router_max_active() reads [router].max_active per ro... | router.py:223-231 |
| sleep.toml | DOCUMENTED-ONLY | No runtime reader; sleep.py does not load it... | (grep found no readers) |
| verification.toml | PARTIAL ENFORCED | verify.load_verification_ladder() reads [ladder] per invocat... | verify.py:253-264 |


## F. Brainstem Policies & Supporting Documentation

### brainstem/policies/

| Policy | Status | Purpose | Enforcement |
|--------|--------|---------|-------------|
| driver-orchestration.md | CANONICAL RUNTIME POLICY | Role model (hard_orchestrator/driver/worker/normal), driver ... | Referenced by driver-orchestrator.ts line 1; implements role... |
| sol-minimal-orchestrator.md | CANONICAL RUNTIME POLICY | Sol orchestrator role (decision-maker, auditor, NOT executor... | Referenced by orchestrator-guard.ts line 1; implements tool-... |
| verifier-role.md | ADVISORY | Fresh-agent independence requirement, verifier duties (read-... | Referenced in Phase D amendment; no automatic enforcement (a... |

### brainstem/telemetry/

- **SCHEMA.md** (v=2): Formal specification of telemetry record schema (field names, types, privacy rules). Read by sensors.ts (line 10 reference) and storage.ts (JSONL writes conform to schema).
- **No code readers** — schema is normative documentation, not dynamically loaded.

### brainstem/tests/

Prime extension tests (Vitest):
- brainstem/prime-extension/src/__tests__/*.test.ts (verified in package.json scripts: `vitest`)
- Tests are ISOLATED (no Prime runtime needed): sensors.ts tests verify event→record transformation in pure JS.


## Critical Integration Paths

### Path 1: Session Lifecycle (session_start hook)
1. Prime sends SessionStartEvent to wire<SessionStartEvent>() handler (index.ts line 327)
2. Handler calls runShadowAutoInject() or runAdvisoryAutoInject() (autoinject.ts line 330)
3. AutoInject spawns Python: `second_brain autoinject shadow/advisory --json`
4. Python autoinject.load_config() reads config/autoinject.toml [budget] (autoinject.py line 109)
5. Python returns decision JSON → TS stores via sensors.sessionStart() → storage.append()
6. ledger-mirror.ts also called: runLedgerCheckpoint() mirrors session_started to Python ledger (index.ts line 340)

### Path 2: Response Processing (after_provider_response hook)
1. Prime sends AfterProviderResponseEvent (index.ts line 591)
2. Orchestrator guard checks model (isOrchestratorModel, line 703)
3. Recall gate runs if SECOND_BRAIN_RECALL enabled (runBrainRecall, line 658) → Python semantic search
4. RTD eligible outputs stored: runRtd() (line 759) checks context.toml [rtd] enabled, thresholds
5. Ledger mirror checkpoints response: runLedgerCheckpoint() (line 855)
6. All events recorded via sensors.afterProviderResponse() → telemetry file

### Path 3: Config Enforcement
- **autoinject.toml**: read EVERY CALL to autoinject.load_config() (not cached); mode also read by TS at hook time
- **retrieval.toml**: read EVERY semantic.search_memories() call; max_results and weights enforced at runtime
- **skills.toml**: read EVERY router.route() call; [router].max_active enforced unless CLI --max-active overrides
- **session-retention.toml**: read ONLY on session purge (ledger.SessionLifecycle.purge_inactive_sessions)
- **All others**: documented-only or future (Phase 2+ gates them behind unimplemented readers)

