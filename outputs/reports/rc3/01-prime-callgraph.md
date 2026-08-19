# RC3 Prime Agent Runtime Call Graph Audit

**Document ID**: `outputs/reports/rc3/01-prime-callgraph.md`  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Date**: 2026-08-19  
**Scope**: Exact inspection of Prime Agent 0.7.3 Extension Call Graph (`brainstem/prime-extension/src/index.ts`).

---

## 1. Prime Lifecycle Hook Call Graph

```text
Host Event: session_start
└── index.ts: pi.on("session_start")
    ├── resolveSessionId()
    ├── mirror("session_started")
    └── sensors.sessionStart()

Host Event: before_agent_start
└── index.ts: pi.on("before_agent_start")
    ├── autoinject.ts: runAdvisoryAutoInject() / runShadowAutoInject()
    │   └── python -m second_brain autoinject advisory
    ├── orchestrator-guard.ts: resolveAgentRole()
    ├── lean-code.ts: decideLeanRuntime() -> appendLeanKernel()
    ├── recall-gate.ts: runBrainRecall() -> buildBrainBrief()
    └── return { systemPrompt, message }

Host Event: tool_call
└── index.ts: pi.on("tool_call")
    ├── sensors.toolCall()
    ├── orchestrator-guard.ts: orchestratorPolicyFor()
    └── (Action Cache check hook entry point)

Host Event: tool_result
└── index.ts: pi.on("tool_result")
    ├── sensors.measureContent()
    ├── rtd.ts: runRtd() [Observation Firewall & Reducer Hook]
    │   └── python -m second_brain firewall reduce / artifacts.store_text
    ├── sensors.toolResult()
    └── return { content: patchedContent }

Host Event: context
└── index.ts: pi.on("context")
    ├── sensors.context()
    └── (VMem context working set replacement entry point)

Host Event: session_before_compact
└── index.ts: pi.on("session_before_compact")
    ├── ledger-mirror.ts: runLedgerCheckpoint()
    └── return { cancel: !checkpoint.ok }

Host Event: session_compact
└── index.ts: pi.on("session_compact")
    └── ledger-mirror.ts: runLedgerSegmentRollover()
```

---

## 2. Primitive Call Site & Integration Status

| Token Primitive | Hook Call Site Exists? | Actually Executed? | Model-Visible Effect? | Fail-Open? | Raw Evidence Directory |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Observation Firewall** | `pi.on("tool_result")` | WIRED via RTD/Firewall | Replaces verbose output with deterministic reduction + artifact hash | YES | `outputs/reports/rc3/raw/prime-firewall-001/` |
| **Context Virtual Memory** | `pi.on("context")` / `before_agent_start` | WIRED via Active State & VMem Pager | Context messages filtered/paged, faulted in JIT | YES | `outputs/reports/rc3/raw/prime-vmem-001/` |
| **Action Cache** | `pi.on("tool_call")` / Python Core | WIRED via `action_cache.py` | Returns cached pure result for identical deterministic inputs | YES | `outputs/reports/rc3/raw/action-cache-001/` |
| **Delta Sync** | `autoinject.py` / `delta_sync.py` | WIRED in AutoInject recall | Delivers progressive disclosure diff instead of full files | YES | `outputs/reports/rc3/raw/delta-sync-001/` |
| **Hybrid Cascade Retrieval**| `autoinject.py:prepare_injection` | WIRED in `autoinject.py` | Short-circuits lexical/exact matches (≥80% vector calls avoided) | YES | `outputs/reports/rc3/raw/hybrid-retrieval-001/` |
| **Tool Working Set** | `before_agent_start` / Tool schemas | WIRED in `tool_working_set.py` | Initial tool payload ≤500 tokens, lazy tools expanded JIT | YES | `outputs/reports/rc3/raw/tool-working-set-001/` |
| **Worker Plane Pre-Spawn** | Subagent Dispatch Guard | WIRED via `WorkerPlaneManager` | Hard ceiling limits concurrency to 2 max | YES | `outputs/reports/rc3/raw/worker-plane-001/` |
