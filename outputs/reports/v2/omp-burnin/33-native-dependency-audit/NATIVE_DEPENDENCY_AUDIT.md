# Native OMP Dependency Audit

**Question:** Does any mandatory v2 OMP path require the Prime Agent binary? **NO.**

## Evidence

Grounded in the Phase 2 static integration audit (`02-static-integration-audit/OMP_EVENT_MATRIX.md`, questions 9-11) plus this campaign's own live testing.

### Search performed

Every `execFile`/`execFileSync`/`spawn` call site across `brainstem/prime-extension/src/*.ts` was enumerated (active-state-mirror.ts, autoinject.ts, budget-bridge.ts, environment-mirror.ts, index.ts, ledger-mirror.ts, p4-mirror.ts, recall-gate.ts, routing-bridge.ts, rtd.ts, visibility-bridge.ts, vmem.ts, worker-context-bridge.ts, worker-result-bridge.ts). Every one resolves its executable as:

```text
options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe")
```

running `-m second_brain <subcommand>`. A repo-wide grep for `prime`, `prime-agent`, `prime.exe`, `sol` near any `spawn(`/`execFile`/`exec(` call returned zero hits referencing a Prime-branded binary.

### Prime-oriented filename vs. actual runtime dependency

`brainstem/prime-extension/src/index.ts:28-41` imports `AgentEndEvent, BeforeAgentStartEvent, ExtensionAPI, ExtensionContext, PrimeEvent, ...` via `import type {...} from "../types/prime"`. The `import type` keyword makes this a **TypeScript compile-time-only** import — erased entirely by the Bun/TS compiler, zero runtime code, zero runtime dependency on any Prime module or binary. No other file under `brainstem/prime-extension/src/` imports from `../types/prime`. This is a **Prime-oriented type/filename**, not an actual runtime dependency: the directory is named `prime-extension` and the type-declaration file is named `types/prime.ts` for historical reasons (this extension originated as a Prime Agent integration before OMP-first support was added), but at runtime the extension only needs the generic, duck-typed `pi`/`ExtensionAPI` object that any compliant OMP-family host injects into the exported factory function (`export default function(pi: ExtensionAPI, ...) {...}`).

### Per-capability verdict (live-tested this campaign, no Prime binary present on this machine)

| Capability | Runtime dependency chain | Prime required? |
|---|---|---|
| AutoInject (shadow + active injection) | `autoinject.ts` -> `python -m second_brain autoinject shadow\|advisory` -> Node/Bun + local Python venv | NO — live-proven Phase 8 |
| Model routing | `routing-bridge.ts` -> `python -m second_brain autoinject omp-routing` -> `model_routing.py` (harness-neutral by its own docstring) | NO |
| Worker context capsule | `worker-context-bridge.ts`, triggered by generic `tool_call` (host built-in `task` tool, not Prime-specific) | NO |
| Worker result | `worker-result-bridge.ts`, triggered by generic `tool_result` | NO |
| Skill visibility | `visibility-bridge.ts` -> `skills.py` build_plan/hydrate_plan | NO |

### Machine-level confirmation

This entire qualification campaign (Phases 0, 1, 6, 7, 8, and the AutoInject cache fix) was executed on a machine with **no Prime Agent binary installed or reachable** (`where prime-agent`, `where prime`, `where sol`, and npm global package listings all returned nothing), using only `omp -e ./brainstem/prime-extension/src/index.ts` directly. Every live capability proven so far (SessionStart identity delivery, AutoInject shadow decisions and real active-mode injection with a sentinel memory, project resolution across 5 scenarios including a live-found-and-fixed nested-directory bug, model routing decisions, skill visibility planning) worked with zero Prime process ever spawned.

## Conclusion

No actual runtime dependency on a Prime executable exists anywhere in the mandatory v2 OMP path. Per plan §33: **Prime Agent 0.9.1 is REMOVED from the v2 release blocker list.** The `prime-extension` directory/`types/prime.ts` naming is legacy nomenclature only and does not gate release; renaming it is optional future cleanup (Phase 3 packaging audit already classified analogous `package.json` naming as low-priority/deferred, same reasoning applies here).
