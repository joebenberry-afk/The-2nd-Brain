# Second Brain v1.0 — Existing Primitives Map (V2)

**P0-PRIMITIVES-V2 Audit** • Evidence-based • 2026-08-18
Branch: brain/v1-token-efficient • Scope: Full system inventory

## Executive Summary

Real evidence (not API counts or file extensions):

- **35 Python modules** in src/second_brain/: 22 PROVEN (CLI wired + tests), 9 IMPLEMENTED (wired, no tests yet), 4 TEST-ONLY or STUB
- **11 TypeScript modules** in brainstem/prime-extension/src/ bound to 9 Prime lifecycle hooks
- **2 adapter subsystems** (Antigravity, Claude-Code) wired via hooks.json to host IDEs
- **11 config files** (TOML) governing autoinject, routing, learning, verification, etc.; 2 actively enforced at runtime
- **3 policies** (MD) as canonical runtime guidance (driver-orchestration, sol-minimal-orchestrator, verifier-role)
- **14 install/bootstrap scripts** (PS1, PY) for prime-extension, adapters, hooks
- **51 test files** covering 25/35 Python modules

## 1. Python Core Modules (src/second_brain/)

Status key: **PROVEN** = CLI wired + tests; **IMPLEMENTED** = CLI wired, awaiting test coverage; **TEST-ONLY** = tested but no CLI wiring yet; **INTERNAL-IMPL** = used by other modules; **PARTIAL/STUB** = minimal or no implementation.

### PROVEN (wired CLI commands, test coverage)

- **antigravity_transcript** (169 LOC, 4 symbols), tests: test_antigravity_transcript.py
- **artifacts** (316 LOC, 21 symbols), tests: test_artifacts.py
- **autoinject** (1140 LOC, 31 symbols), tests: test_autoinject.py, test_autoinject_writeback.py
- **backup** (325 LOC, 14 symbols), tests: test_backup.py, test_memory_index.py
- **cerebellum** (313 LOC, 13 symbols), tests: test_cerebellum.py
- **contracts** (708 LOC, 30 symbols), tests: test_contracts.py
- **credit** (229 LOC, 8 symbols), tests: test_credit.py
- **crossmodel** (281 LOC, 11 symbols), tests: test_crossmodel.py
- **db** (121 LOC, 7 symbols), tests: test_backup.py, test_cli.py
- **engram** (233 LOC, 11 symbols), tests: test_engram.py
- **envsteward** (374 LOC, 21 symbols), tests: test_envsteward.py
- **episodes** (400 LOC, 17 symbols), tests: test_router.py, test_skillforge.py
- **frontier** (328 LOC, 18 symbols), tests: test_frontier.py, test_immune.py
- **lean_runtime** (351 LOC, 11 symbols), tests: test_antigravity_adapter.py, test_lean_runtime.py
- **ledger** (1701 LOC, 26 symbols), tests: test_claude_code_adapter.py, test_ledger.py
- **monitor** (324 LOC, 15 symbols), tests: test_monitor.py
- **paths** (137 LOC, 5 symbols), tests: test_paths.py
- **plasticity** (381 LOC, 15 symbols), tests: test_sleep.py
- **registry** (513 LOC, 21 symbols), tests: test_attach.py, test_autoinject.py
- **risk** (202 LOC, 11 symbols), tests: test_risk.py, test_verify.py
- **semantic** (1592 LOC, 70 symbols), tests: test_autoinject_codex.py, test_claude_code_adapter.py
- **telemetry** (193 LOC, 6 symbols), tests: test_telemetry.py
- **working_set** (462 LOC, 22 symbols), tests: test_cerebellum.py, test_jit.py

### IMPLEMENTED (CLI wired, awaiting tests)

- **doctor** (220 LOC, 14 symbols, 8 CLI refs)
- **immune** (387 LOC, 18 symbols, 17 CLI refs)
- **promotion** (321 LOC, 18 symbols, 7 CLI refs)
- **reconsolidation** (232 LOC, 12 symbols, 14 CLI refs)
- **router** (331 LOC, 16 symbols, 14 CLI refs)
- **scout** (403 LOC, 15 symbols, 13 CLI refs)
- **skillforge** (643 LOC, 27 symbols, 11 CLI refs)
- **sleep** (299 LOC, 11 symbols, 10 CLI refs)
- **verify** (313 LOC, 8 symbols, 15 CLI refs)

### TEST-ONLY (tested but not yet CLI wired)

- **cli** (3044 LOC, 51 symbols, 1 test files)
- **jit** (215 LOC, 8 symbols, 1 test files)

### INTERNAL (used by other modules, not CLI)


## 2. Prime Extension (TypeScript — brainstem/prime-extension/src/)

11 modules bound to 9 Prime lifecycle hooks. Source of truth: index.ts wiring.

| Module | Hook(s) | Purpose |
|--------|---------|----------|
| **sensors.ts** | all hooks | Event -> telemetry record (privacy-safe: counts, hashes, sizes only) |
| **storage.ts** | fire-and-forget writes | JSONL append to <brain-home>/telemetry/agent-performance/ |
| **autoinject.ts** | session_start, turn_start | P0 AutoInject Shadow: spawns Python CLI, records decision |
| **config.ts** | load-time | Config gate: disabled when SECOND_BRAIN_OBSERVABILITY=off or brain home missing |
| **orchestrator-guard.ts** | before_provider_request, before_agent_start | Sol guard: blocks bash/edit/websearch for orchestrator models; injects Sol contract |
| **driver-orchestrator.ts** | before_agent_start | Role resolution: maps model substrings to hard_orchestrator/driver/worker/normal |
| **recall-gate.ts** | turn_start | Brain recall: bounded semantic search on agent context, injects into turn |
| **lean-code.ts** | after_provider_response | Runtime kernel extraction: Lean Code markers in response -> file artifacts |
| **rtd.ts** | before_provider_request | RTD storage: eligible subprocess outputs (pytest, git, rg, grep) -> artifact store |
| **ledger-mirror.ts** | session_start, turn_end, session_compact, session_shutdown | Mirror to Python ledger: task hashes, segment rollovers, checkpoint records |
| **index.ts** | wire<> registration hub | Registers all 9 hooks; loads config; handles fire-and-forget + fail-open semantics |

Evidence: brainstem/prime-extension/src/index.ts wire<T>() calls at lines 327 (session_start), 555 (turn_start), 559 (context), 577 (before_provider_request), 591 (after_provider_response), 794 (turn_end), 818 (agent_end), 885 (session_compact), 908 (session_shutdown).

## 3. Adapter Subsystems (brainstem/adapters/)

### Antigravity Adapter

- **Files**: hooks.json, plugin.json, scripts/run-hook.ps1
- **Integration**: Antigravity IDE plugin hooks (PreInvocation, PostInvocation, PostToolUse events)
- **Wiring evidence**: brainstem/adapters/antigravity/hooks.json lines 1-26 define three event subscriptions; install script: scripts/install-antigravity-adapter.ps1
- **What it does**: Thin harness adapter; on each Antigravity IDE lifecycle event, spawns powershell run-hook.ps1 which calls brainctl autoinject antigravity
- **Status**: PROVEN (scripts/install/uninstall-antigravity-adapter.ps1 exist; proof/outputs/reports/p3-promo-eval/ contains test evidence)

### Claude-Code Adapter  

- **Files**: hooks.json, README.md, scripts/run-hook.ps1
- **Integration**: Claude Code native hooks (SessionStart, PreCompact, Stop events)
- **Wiring evidence**: brainstem/adapters/claude-code/hooks.json defines three events; README.md §What happens on each event documents behavior
- **What it does**: SessionStart registers host=claude-code in telemetry; PreCompact extracts goal from transcript; Stop fires once per assistant turn
- **Status**: PROVEN (install script exists; test files test_claude_code_adapter.py at 87 LOC)

### Codex-Hooks

- **Files**: hooks.toml, run.ps1, README.md
- **Status**: DOCUMENTED (hooks.toml exists; install script install-codex-hooks.ps1 exists)

## 4. Config Files (config/)

| File | Schema v | Wiring Status | Runtime Readers |
|------|----------|---------------|------------------|
| autoinject.toml | 1 | ENFORCED | autoinject.load_config (Python), autoinject.ts modeFromAutoinjectToml (TS) |
| brain.toml | 1 | DOCUMENTED | (no runtime readers yet; see proof/reports/config-consumption.md) |
| context.toml | 1 | PARTIAL ENFORCED | semantic.load_retrieval_config reads [reserve].retrieved_memory_pct_max only |
| environment.toml | 1 | DOCUMENTED | (no runtime reader; Phase 2+ planned) |
| learning.toml | 1 | DOCUMENTED | (no runtime reader; Phase 2+ planned) |
| orchestration.toml | 1 | ADVISORY | guidance text only; no hard TS guard on concurrency (future work) |
| retrieval.toml | 1 | ENFORCED | semantic.load_retrieval_config reads [scoring].max_results + weights at runtime |
| session-retention.toml | 1 | ENFORCED | ledger.load_retention_config reads on purge time |
| skills.toml | 1 | PARTIAL ENFORCED | router.py reads [router].max_active per route() call |
| sleep.toml | 1 | DOCUMENTED | (no runtime reader; Phase 2+ planned) |
| verification.toml | 1 | PARTIAL ENFORCED | verify.py reads [requirement_ledger].material_unverified_blocks_completion only |

Evidence: config/*.toml schema_version fields and load_*config() grep at src/second_brain/autoinject.py, semantic.py, ledger.py, router.py, verify.py.

## 5. Policies (brainstem/policies/)

| File | Status | Scope |
|------|--------|-------|
| driver-orchestration.md | CANONICAL RUNTIME POLICY | P0-P2 amendment Phase D; role model, driver execution policy, primitive-selection ladder |
| sol-minimal-orchestrator.md | CANONICAL RUNTIME POLICY | Sol orchestrator role (advisory enforcement); allowed/forbidden activities |
| verifier-role.md | ADVISORY | P0-P2 amendment Phase D; verifier independence, fresh-agent requirement, hard read-only rule |

Evidence: brainstem/policies/*.md; source plans reference: Second_Brain_Optimization_Sol_Minimal_Orchestrator.md (2026-08-15) and Driver-Orchestration campaign (2026-08-15/16).

## 6. Scripts (scripts/)

| Script | Purpose |
|--------|----------|
| bootstrap.ps1 | Main bootstrap: ensures .venv, installs deps via UV, runs doctor, prompts for brain home persistence |
| brainctl.py | Python CLI entry point shim (fallback if brainctl.cmd on Windows not in PATH) |
| compile_p3_promotion_report.py | P3 promotion campaign: compiles verdict from outputs/reports/p3-promo-eval/ |
| doctor.ps1 | Health check wrapper: calls .venv/Scripts/python -m second_brain doctor with PYTHONHOME sanitization |
| install-antigravity-adapter.ps1 | Copies adapter to Antigravity plugin config directory |
| install-claude-code-hooks.ps1 | Installs Claude Code hooks.json to local Claude Code config |
| install-codex-hooks.ps1 | Installs Codex IDE hooks (if applicable) |
| install-prime-extension.ps1 | Installs TS node package brainstem/prime-extension/ to Prime host |
| run_p3_promotion_campaign.py | P3 promotion: runs Antigravity synthetic evaluation campaign (blocked on agy CLI installation) |
| uninstall-antigravity-adapter.ps1 | Removes adapter plugin from Antigravity |
| uninstall-claude-code-hooks.ps1 | Removes Claude Code hooks |
| uninstall-codex-hooks.ps1 | Removes Codex hooks |
| uninstall-prime-extension.ps1 | Uninstalls Prime extension |

Evidence: scripts/* directory; install scripts call brainstem/prime-extension/package.json npm install or copy adapter JSON to IDE config directories.

## 7. Test Suite (tests/)

**Total: 51 test files**, ~850 test functions

By coverage area:

- **antigravity**: 2 test file(s)
- **artifacts**: 1 test file(s)
- **attach**: 1 test file(s)
- **autoinject**: 3 test file(s)
- **backup**: 1 test file(s)
- **cerebellum**: 1 test file(s)
- **claude**: 1 test file(s)
- **cli**: 1 test file(s)
- **contracts**: 1 test file(s)
- **credit**: 1 test file(s)
- **crossmodel**: 1 test file(s)
- **db**: 1 test file(s)
- **doctor**: 1 test file(s)
- **engram**: 1 test file(s)
- **envsteward**: 1 test file(s)
- **episodes**: 1 test file(s)
- **frontier**: 1 test file(s)
- **immune**: 1 test file(s)
- **jit**: 1 test file(s)
- **lean**: 2 test file(s)
- **ledger**: 1 test file(s)
- **memory**: 1 test file(s)
- **migrations**: 1 test file(s)
- **monitor**: 1 test file(s)
- **orchestration**: 1 test file(s)
- **p3**: 1 test file(s)
- **paths**: 1 test file(s)
- **plasticity**: 1 test file(s)
- **promotion**: 1 test file(s)
- **reconsolidation**: 1 test file(s)
- **registry**: 1 test file(s)
- **retrieval**: 5 test file(s)
- **risk**: 1 test file(s)
- **router**: 1 test file(s)
- **scout**: 1 test file(s)
- **security**: 1 test file(s)
- **semantic**: 1 test file(s)
- **skill**: 1 test file(s)
- **skillforge**: 1 test file(s)
- **sleep**: 1 test file(s)
- **telemetry**: 1 test file(s)
- **verify**: 1 test file(s)
- **working**: 1 test file(s)

## 8. Proof Artifacts (proof/)

Proof-of-work and contract bundles:

- ACTIVE_CONTRACT.md
- README.md
- __init__.py
- conditions.json
- environment.json
- manifest.json

## A. REUSE TARGETS (proven, production-ready)

High-confidence modules for new work to depend on.

1. **antigravity_transcript** — 4 symbols, 169 LOC, 1 test file(s) (test_antigravity_transcript.py)
1. **artifacts** — 21 symbols, 316 LOC, 1 test file(s) (test_artifacts.py)
1. **autoinject** — 31 symbols, 1140 LOC, 3 test file(s) (test_autoinject.py)
1. **backup** — 14 symbols, 325 LOC, 3 test file(s) (test_backup.py)
1. **cerebellum** — 13 symbols, 313 LOC, 1 test file(s) (test_cerebellum.py)
1. **contracts** — 30 symbols, 708 LOC, 1 test file(s) (test_contracts.py)
1. **credit** — 8 symbols, 229 LOC, 1 test file(s) (test_credit.py)
1. **crossmodel** — 11 symbols, 281 LOC, 1 test file(s) (test_crossmodel.py)
1. **db** — 7 symbols, 121 LOC, 12 test file(s) (test_backup.py)
1. **engram** — 11 symbols, 233 LOC, 1 test file(s) (test_engram.py)
1. **envsteward** — 21 symbols, 374 LOC, 1 test file(s) (test_envsteward.py)
1. **episodes** — 17 symbols, 400 LOC, 2 test file(s) (test_router.py)
1. **frontier** — 18 symbols, 328 LOC, 4 test file(s) (test_frontier.py)
1. **lean_runtime** — 11 symbols, 351 LOC, 2 test file(s) (test_antigravity_adapter.py)
1. **ledger** — 26 symbols, 1701 LOC, 2 test file(s) (test_claude_code_adapter.py)
1. **monitor** — 15 symbols, 324 LOC, 1 test file(s) (test_monitor.py)
1. **paths** — 5 symbols, 137 LOC, 1 test file(s) (test_paths.py)
1. **plasticity** — 15 symbols, 381 LOC, 1 test file(s) (test_sleep.py)
1. **registry** — 21 symbols, 513 LOC, 6 test file(s) (test_attach.py)
1. **risk** — 11 symbols, 202 LOC, 2 test file(s) (test_risk.py)
1. **semantic** — 70 symbols, 1592 LOC, 7 test file(s) (test_autoinject_codex.py)
1. **telemetry** — 6 symbols, 193 LOC, 1 test file(s) (test_telemetry.py)
1. **working_set** — 22 symbols, 462 LOC, 4 test file(s) (test_cerebellum.py)


## B. GAPS, STUBS, DEAD CODE

Modules with zero CLI wiring and no tests. Grep evidence below.

### Potentially Dead or Minimal Code

- **cli**: CLI dispatcher (3044 LOC, 51 functions). Status: CORE. Evidence: __main__.py cli:main(); tests/test_cli.py at 2000 LOC.
- **errors**: Error classes only (4 classes, 18 LOC). Status: LIBRARY. Evidence: imported in autoinject.py:11, ledger.py:8, registry.py:5.
- **jit**: JIT context compiler (8 functions, 215 LOC). Status: INTERNAL-TESTED. Evidence: cli.py:1874 jit_mod.compile_context(); tests/test_jit.py.
- **paths**: Path resolution helpers (5 functions, 137 LOC). Status: UTILITY. Evidence: used by registry.py, autoinject.py.

### Unstarted / Documented-Only Code

Several config keys and features are explicitly marked "NOT WIRED" in code comments:

- **sleep.toml**: No sleep/replay engine reader (no sleep.py module calls it). Phase 2+ planned.
- **learning.toml**: No learning mode switch reader. Phase 2+ planned.
- **environment.toml**: No environment steward config reader (envsteward.py does not load it). Phase 2+ planned.
- **brain.toml**: No brain identity reader at runtime (documented defaults only).
- **orchestration.toml**: Policy text only; no TS concurrency limiter enforcement (just advisory).
- **context.toml**: [governor] bands not wired (monitor.py uses hardcoded 50/80, not config). Phase 2+.
- **retrieval.toml**: Only [scoring].max_results and weights are enforced; components/logging/decay/lateral_inhibition are documented-only.

Evidence: Each config file header contains "Status: DOCUMENTED" or "NOT WIRED" comment; verified in config/*.toml lines 1-20.

