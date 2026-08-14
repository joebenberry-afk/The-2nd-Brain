# ACTIVE integration contract (v4.3 Phase 0)

Status: **not ready for an autonomy claim**.

This contract records current runtime behavior. It is intentionally explicit
about the gap between a callable Brain API and automatic Prime integration.

1. **Targeted recall event:** none. The Prime extension observes lifecycle
   events, but it does not call semantic retrieval or JIT compilation. Recall
   currently requires an explicit `brainctl`/Python caller.
2. **Skill-routing event:** none. `brainctl router route` ranks skills and
   returns `shadow: true`; it does not execute or inject a selected skill.
3. **Injected context:** none in the official extension. `jit.compile_context`
   writes a capsule file; no Prime handler returns messages, a system prompt,
   a patch, or a tool-call change.
4. **Token budget:** not enforced by the official integration. The reserve and
   retrieval TOML values are policy descriptions; current JIT output has no
   configured retrieved-memory ceiling.
5. **Task outcome recorder:** caller-controlled. Prime telemetry records
   lifecycle counts and sizes only; success, verifier result, and task score
   require a caller or benchmark oracle.
6. **Episode creation:** caller-controlled. No Prime event automatically
   creates an episode from a task outcome.
7. **Automatic vs advisory learning:** the current Prime path is observability
   only. Memory curation, activation, credit, sleep, skill forging, and
   promotion are explicit/advisory APIs.
8. **Human/frontier approval:** frontier review and upward skill promotion
   require an approval record and immune checks; constitution changes remain
   protected by change control.
9. **Brain unavailable:** the observability extension disables itself when its
   environment gate or home is absent. It does not block or alter the agent.
   Explicit Brain API failures remain caller-visible errors.
10. **C0 OFF:** do not load the extension, do not invoke Brain APIs, and give
    the run a clean isolated state. Telemetry-only C1 may load the extension
    but must not alter model input.

## Proof consequence

An automatically orchestrated benchmark wrapper may measure mechanism value,
but it must not be labeled official Prime autonomy. Unless the official
integration gains a real recall/routing/injection path, C3 ACTIVE can support
mechanism evidence only and G16/P7 must fail as **autonomy unproven**.
