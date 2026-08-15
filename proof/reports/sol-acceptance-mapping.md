# Sol minimal-orchestrator — acceptance mapping (A–G)

Maps the acceptance scenarios of the Sol optimization plan (canonical:
`brainstem/policies/sol-minimal-orchestrator.md` §14) to existing automated
evidence, and states which scenarios still require a live Sol trial.

Status labels:

- **AUTOMATED** — proven by committed tests (repo state @ 2026-08-15;
  commits 1f2c843, 61c536a, b4f0a47c, b5acf83, Phase 12 RTD wiring).
- **POLICY-ONLY** — encoded as guidance (policy doc / injected Sol contract);
  no runtime mechanism enforces it.
- **LIVE TRIAL REQUIRED** — needs a running Sol session; deferred because the
  Sol guard is NOT deployed to `~/.prime` yet (deployment pending campaign
  end; the installed extension predates commit 61c536a).

## 0. Deployment caveat (applies to every row)

All "guard" evidence below is automated and committed, but the LIVE runtime
still runs the pre-guard extension. Until deployment, the operative
enforcement on real Sol sessions is **advisory policy + detection telemetry**,
not the hard guard (policy §12).

## Evidence base (files)

| Evidence | Location |
|---|---|
| Guard decision matrix (pure) | `brainstem/prime-extension/src/orchestrator-guard.ts` |
| Guard wiring (tool_call / before_agent_start) | `brainstem/prime-extension/src/index.ts` |
| Guard unit tests | `brainstem/prime-extension/tests/orchestrator-guard.test.ts` |
| Guard wiring tests | `brainstem/prime-extension/tests/wiring.test.ts` (`minimal-orchestrator guard (src/index.ts)`) |
| Violation record schema | `brainstem/telemetry/SCHEMA.md` (`orchestrator_policy_violation`) |
| Sol contract (injected systemPrompt) | `docs/orchestration/SOL_MINIMAL_ORCHESTRATOR.md`; embedded `SOL_ORCHESTRATOR_CONTRACT` in `src/index.ts` |
| Telemetry/retrieval baselines | `outputs/reports/optimization-phase0-baseline.md` |

## A — Missing repository fact → Sol delegates inspection

- **AUTOMATED (enforcement half):** Sol-model sessions cannot run repository
  inspection tools. `orchestrator-guard.test.ts` → "orchestrator model +
  blocked tool -> block with reason" (bash/edit/websearch); "non-orchestrator
  model + any tool -> never blocked". Wiring: `wiring.test.ts` → "tool_call:
  Sol model + bash -> {block:true} with reason and a violation record";
  "tool_call: Sol model blocks edit and websearch too".
- **AUTOMATED (delegation path open):** `orchestrator-guard.test.ts` →
  "orchestrator model + ipython -> allow (delegation path)"; "orchestrator
  model + other tools -> allow" (agent_message/agent_observe/rlm allowed —
  Sol can delegate and read returned results).
- **LIVE TRIAL REQUIRED:** verify Sol's voluntary behavior — that it
  *chooses* delegation (policy §3) rather than attempting blocked tools.

## B — Missing telemetry fact → Sol delegates telemetry analysis

- **AUTOMATED (enforcement half):** same guard rows as A (no direct
  telemetry inspection tool is exposed to Sol).
- **AUTOMATED (detection):** every blocked attempt emits
  `orchestrator_policy_violation` (`detected_by=runtime_guard`,
  `blocked=true`, `violation=direct_execution`) — `wiring.test.ts` →
  "tool_call: Sol model + bash -> {block:true} with reason and a violation
  record" (asserts the exact 8-field bounded record shape).
- **LIVE TRIAL REQUIRED:** telemetry-analysis delegation behavior.

## C — Simple provided evidence → Sol audits without spawning

- **POLICY-ONLY:** audit-without-spawn is guidance (policy §2, §10); no
  runtime mechanism counts spawns against a task.
- **AUTOMATED (contract delivery):** the contract instructing this is
  injected every turn — `wiring.test.ts` → "before_agent_start: Sol model ->
  systemPrompt contains the delegation rule" (asserts "MUST delegate",
  "WORKER RETURN CONTRACT", <1500 words); "before_agent_start: non-Sol model
  -> undefined, no systemPrompt".
- **LIVE TRIAL REQUIRED:** observe no unnecessary worker spawn on a
  simple-evidence task.

## D — Worker returns weak proof → narrow correction, no self-reproduce

- **POLICY-ONLY:** correction loop is guidance (policy §10; contract section
  "CORRECTION LOOP"); the blocked tools make self-reproduction impossible at
  the guard level (D's "does not reproduce the test itself" is enforced for
  bash/ipython-adjacent flows only via policy — note ipython is unblocked so
  Sol *could* run Python; the contract forbids it).
- **LIVE TRIAL REQUIRED:** two-round correction behavior.

## E — Cheap task → Qwen/DeepSeek, not Luna

- **POLICY-ONLY:** worker ladder is guidance (policy §5-6; contract
  "WORKER SELECTION"); Prime's subagent spawn takes any model
  (`agent-session.ts _resolveRlmSubagentModel`) with no tier gate.
- **LIVE TRIAL REQUIRED:** observe model choice on a cheap task.

## F — Complex critical change → Luna escalation when justified

- **POLICY-ONLY:** same ladder (policy §6; contract). No automated selector.
- **LIVE TRIAL REQUIRED:** observe escalation on a critical task.

## G — Parallelism → never 3+ simultaneous workers

- **POLICY-ONLY:** ceiling is guidance (policy §7: default 1, hard ceiling 2);
  Prime exposes `rlmMaxDepth` (depth, not breadth) and no concurrent-child
  cap (recon: `agent-session.ts` RLM spawn path).
- **AUTOMATED (audit-ready):** `concurrency_overflow` is an enumerated
  violation class in SCHEMA.md, but no emitter exists — detection today is
  manual/telemetry-audit only (`detected_by` enum includes `telemetry_audit`).
- **LIVE TRIAL REQUIRED:** observe spawn counts on a dependent-step task.

## Cross-cutting automated evidence

- Guard determinism: `orchestrator-guard.test.ts` → "is deterministic:
  identical inputs produce identical outputs"; random-task determinism in
  `tests/test_router.py` (campaign router work, separate concern).
- Env configurability: `orchestrator-guard.test.ts` → "env override changes
  which tools/models the matrix blocks"; `wiring.test.ts` → "ORCHESTRATOR_*
  env overrides change the wired guard behavior".
- Non-Sol isolation: `wiring.test.ts` → "tool_call: non-Sol model + bash ->
  NOT blocked, no violation (measurement only)".
- Record-shape privacy: `orchestrator-guard.test.ts` → "emits the
  orchestrator_policy_violation kind with bounded enumerated fields" (no
  free-text tool/reason/command fields).

## Bottom line

A and B have hard automated evidence for the **enforcement layer** (blocked
tools, open delegation path, violation records). Their behavioral half —
Sol actually choosing to delegate — plus C–G are **policy-only guidance**
delivered via the injected contract and require a **live Sol trial** after the
guard is deployed to `~/.prime` (deferred). Until then the honest status is
policy §12: advisory + detection, not hard enforcement.
