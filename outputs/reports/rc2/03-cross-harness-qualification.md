# RC2 Cross-Harness Qualification Report

**Document ID**: `outputs/reports/rc2/03-cross-harness-qualification.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC1 → RC2 Repair & Qualification  
**Status**: QUALIFIED (with honest capability tier matrix)

---

## 1. Capability Negotiation Matrix

Rather than falsely claiming identical Level A parity across dissimilar host harnesses (Audit Finding F4), RC2 formally negotiates host capability contracts:

| Harness | Capability Level | AutoInject Recall | Tool Output Filtering | VMem Context Paging | Compaction Checkpoint | Structured Handoff | Live Proof Reference |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Prime Agent 0.7.3** | **Level A (Native)** | Pre-turn middleware | Observation Firewall | Virtual Memory Object Pager | Pre-compact hook | Native JSON | `tests/test_vmem_live_integration.py` |
| **Claude Code** | **Level B (Hook-Assisted)** | Session init / prompt | Firewall CLI adapter | Compact memory injection | Pre-compact checkpoint | Markdown handoff | `tests/test_p3_gaps_live_integration.py` |
| **Codex CLI** | **Level B (Shadow/Hook)** | Prompt prefix | Stdin/stdout pipe filter | Delta sync injection | Session state save | Structured packet | `tests/test_delta_sync_live_integration.py` |
| **Antigravity / AGY** | **Level A (Live Host)** | Pre-invocation system | Observation reducer | Active State Capsule | Pre-compact barrier | Artifact Markdown | `tests/test_firewall_live_integration.py` |

---

## 2. Harness-Specific Qualification Evidence

### 2.1 Prime Agent 0.7.3 (Level A)
- **Integration**: Full bi-directional middleware integration.
- **AutoInject Recall**: Tier 0-2 short-circuiting live in `autoinject.py`.
- **Tool Result Filter**: Raw tool stdout intercepted by `ObservationFirewall` before LLM context delivery.
- **Context Virtual Memory**: Resident memory capped at 4,000 tokens; bulky files paged out to `state/vmem/` and faulted in JIT.
- **Compaction**: Barrier snapshot saves session state prior to host compaction.

### 2.2 Claude Code (Level B)
- **Integration**: Hook and tool adapter wrapper.
- **Memory Injection**: Memory context supplied via session init and prompt injection.
- **Compaction Safety**: Writes checkpoint to `state/sessions/<id>/active-state.json` on pre-compact signal.
- **Honest Boundary**: Host does not allow dynamic in-flight context pointer mutation mid-turn; uses compact memory injection fallback.

### 2.3 OpenAI Codex CLI (Level B - Clarified from RC1 Finding F4)
- **Integration**: Transparent proxy and CLI wrapper (`brainctl`).
- **Prompt Shaping**: Prefix stability preserved via deterministic system prompt ordering.
- **Tool Execution**: Safe action cache check prior to shell command dispatch.
- **Correction**: Resolved Audit Finding F4 — documented as Level B hook wrapper, removing false claims of native kernel integration.

### 2.4 Google Antigravity / AGY (Level A Live)
- **Integration**: Native active host execution.
- **Artifact Generation**: Full markdown and structured artifact exchange under `.gemini/antigravity-cli/brain/`.
- **Tool Working Set**: Initial active tool schema footprint strictly maintained under ≤500 tokens.
- **Observation Reducer**: Live reductions verified across compiler, pytest, git, and search outputs.

---

## 3. Fail-Open Verification

Across all 4 harnesses, when the Second Brain daemon is terminated, corrupted, or unreachable:
1. Every hook catches exceptions and logs warnings to standard error.
2. The host harness proceeds with ordinary unaugmented execution without crashing or terminating user sessions.
3. Proven by: `tests/test_contracts.py` and `tests/test_immune.py`.
