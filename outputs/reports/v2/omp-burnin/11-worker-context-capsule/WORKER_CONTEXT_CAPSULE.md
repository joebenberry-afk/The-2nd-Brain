# Phase 11 — OMP Worker Context Capsule

## Prerequisite finding: driver-role authorization is required, and correctly enforced

The first live attempt (`/tmp/omp-p11-worker`, plain `claude-sonnet-5`, no role
override) was **rejected**:
```
{"kind":"omp_worker_context_failure","task_id":"omp-adf...","worker_agent":"task","failure_code":"UNAUTHORIZED_COORDINATOR"}
```
Traced to `src/second_brain/contracts.py:659-660` /
`src/second_brain/omp_adapter.py:65-67`:
`WorkerTaskPacket` validation requires
`driver_identity.role_profile in COORDINATOR_ROLES` (`{integrator, driver,
orchestrator, hard_orchestrator}`). The TS side (`driver-orchestrator.ts
resolveAgentRole`) classifies a model as `"driver"` only when its id matches
the `DRIVER_MODELS` env-configurable substring list (default
`["deepseek-v4-pro", "gpt-5.6-luna"]`); an unmatched model id (this
campaign's `anthropic/claude-sonnet-5`) resolves to role `"normal"`, which is
correctly NOT authorized to coordinate workers. Isolated with a control
experiment: `--no-extensions` (Second Brain unloaded entirely) let the exact
same prompt spawn a subagent immediately — proving the block is Second
Brain's own, intentional authorization gate, not an OMP-host restriction.
This is correct, designed behavior (preventing an unrecognized/ungoverned
model from posing as a coordinator), not a defect. Retested with
`DRIVER_MODELS=claude-sonnet-5` (the documented, intended extension point)
to exercise the capsule path itself.

## Live test 1 — trivial task, no relevant memory (`/tmp/omp-p11-worker2`)

Driver spawned worker `StiffCrocodile` (bundled `task` agent) with:
*"Reply with exactly: WORKER_CAPSULE_PROBE_OK"*.

`omp_worker_context_handoff` telemetry:
```
worker_role: worker, parent_role: driver
context_ref_count: 0, context_source_bytes: 0, context_source_tokens: 0
context_handoff_bytes: 426, context_handoff_tokens: 106
context_mode: full, context_reused: false, context_cache_hit: false
```
The child session's actual first user message (read directly from its
`.jsonl` transcript, not inferred) contains the literal embedded marker and
packet:
```
[SECOND_BRAIN_WORKER_TASK task_id=omp-b46f... packet_sha256=c5a9c4ba... parent_session_id=...]
[SECOND_BRAIN_WORKER_CONTEXT]
{"mode":"full","resolved_context":[],"context_delta":{...},"context_fingerprint":"854105...",
 "jit_context":"\n\nReply with exactly: WORKER_CAPSULE_PROBE_OK\n\n# Requirements\n\n(none)\n\n# Active State\n\n(none)\n\n# Project State\n\n(none)\n\n# Lexicon Matches\n\n(none)\n\n# Read Ledger Summary\n\ncount: 0\n(none)"}
[/SECOND_BRAIN_WORKER_CONTEXT]
```
Proves: (1) the capsule is genuinely embedded in the worker's own prompt, not
just telemetried; (2) correct `task_id`/`packet_sha256`/`parent_session_id`
attribution; (3) every section renders `(none)` rather than fabricating
content when nothing is relevant — bounded and honest; (4) the child's system
prompt is a fresh, generic worker-role prompt, not a copy of the driver's
conversation (child sessions do not inherit transcript history — confirmed
directly from the `.jsonl`, matching OMP's own documented `task` tool
contract). Worker completed and the driver's final answer correctly reported
`WORKER_CAPSULE_PROBE_OK`.

## Live test 2 — task relevant to an existing sentinel memory (`/tmp/omp-p11-worker3`)

Driver spawned worker `ConceptualHare` (auto-selected `scout` agent) with a
question semantically related to the campaign's `OMP_V2_SENTINEL`/`zzq-vault-7719`
sentinel memory (`mem-736677e29a1a`).

**Two independent delivery mechanisms observed, both bounded:**
1. `omp_worker_context_handoff` again showed `context_ref_count: 0` — the
   worker-context-bridge's own relevance computation found nothing to embed
   for this specific handoff.
2. The child session **independently ran its own `before_agent_start`
   AutoInject cycle** (every OMP session, including subagent children, goes
   through the same Second Brain lifecycle per Phase 2's audit) and received
   its own `brain.autoinject.packet` custom message — visible directly in
   `ConceptualHare.jsonl` line 6 — carrying the SAME sentinel memory
   (`packet_id: pkt-3ac0a9b982f45300`, 144 tokens, `authority: advisory`).

The worker correctly treated the injected claim as advisory-only (per the
packet's own embedded rule), went and verified against real repository files
(`pyproject.toml`, `package.json`, `.brain/project.toml`,
`src/second_brain/artifacts.py`, `gardener.py`), and reported the accurate
finding ("no canonical build artifact staging directory is configured"),
explicitly flagging the injected memory as unverified. **No secrets or raw
telemetry leaked** into either the capsule or the independent packet — both
are the same small, structured, advisory-labeled memory record already
proven safe in Phase 8.

**Architectural correction to the plan's assumption:** worker context does
NOT arrive through one single "worker capsule" channel. Two independent,
each-individually-bounded paths exist: (a) the explicit
`worker-context-bridge.ts` handoff embedded in the `tool_call` input (used
when the *driver's own already-resolved* context has something relevant to
forward), and (b) the child session's fully independent AutoInject retrieval
against *its own* task text once it starts (since a spawned child is a real,
first-class OMP session with the same lifecycle events as any other). Both
were exercised live in this phase; neither leaked unbounded content.

## Measurements

| | Test 1 (no relevant memory) | Test 2 (relevant memory) |
|---|---|---|
| Driver context (turn request bytes, `provider_request_meta`) | ~34KB (turn 0) | 89-93KB across turns 0-4 |
| Worker capsule handoff | 426 bytes / 106 tokens, `resolved_context: []` | 0 refs (bridge path); independent AutoInject packet 144 tokens (separate path) |
| Full driver-context-equivalent avoided | Worker never saw driver's turns/tool history | Worker never saw driver's turns/tool history |

Neither worker session's prompt approached the driver's cumulative context
size — no huge session replay in either path.

## Gate 11

**PASS.** Real OMP workers (not mocked) received bounded, correctly-attributed
context in both the "nothing relevant" and "something relevant" cases;
capsule generation fails closed on unauthorized coordinators rather than
silently fabricating authorization (a stricter, safer posture than "fails
open" for this specific gate — the failure mode here is refusing an
unauthorized spawn, not corrupting a legitimate one).
