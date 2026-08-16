# Driver Orchestration Contract (canonical, P0-P2 amendment Phase D)

Source: Driver-Orchestration campaign (2026-08-15/16), updated for the
Maximum Prime-Agent Harness Amendment (§12/§13/§22/§31). This is the
canonical orchestration contract for the **driver role** in the Prime
extension (`brainstem/prime-extension`). It is a runtime policy, **not** part
of the protected `constitution/` change-control surface.

Status labels: **IMPLEMENTED** = wired and proven; **ADVISORY** = guidance
only, no hard enforcement; **NOT CONFIGURED / UNVERIFIED**; **PLANNED**.

## 1. Role model

Four roles, resolved on `before_agent_start` (`src/driver-orchestrator.ts`
`resolveAgentRole`; precedence hard_orchestrator > driver > worker > normal;
lowercased substring match):

| Role | Default model substrings | Source |
|---|---|---|
| `hard_orchestrator` | `gpt-5.6-sol` | `ORCHESTRATOR_MODELS` (Sol guard, unchanged) |
| `driver` | `deepseek-v4-pro`, `gpt-5.6-luna` | `DRIVER_MODELS` |
| `worker` | `deepseek-v4-flash`, `qwen3.5` | `WORKER_MODELS` |
| `normal` | anything else | — |

## 2. Driver execution policy (amendment §31 override)

The original plan forbade the driver from executing routine work. Per the
amendment the driver **MAY execute trivial deterministic work** and **must
not personally execute substantial work** when delegation is advantageous:

- **MAY (Tier 0/1):** read kernel/context state already held; run one-line
  deterministic commands (status reads, single greps, `git status`) when
  doing so is cheaper than delegation.
- **MUST NOT (default):** bulk repo exploration, multi-file inspection,
  editing, patch application, test-suite execution, builds, DB queries,
  trial-and-error debugging, broad review. These are delegated.
- **Emergency escape:** documented, explicit, and logged (counts toward
  `emergency_execution_actions`); never silent.

## 3. Primitive-selection ladder (Tier 0 -> Tier 6)

Choose the lowest tier that reliably solves the step:

1. **Tier 0 — held kernel state** (variables, prior results in context).
2. **Tier 1 — deterministic shell/python/project command** (one-liner,
   no model reasoning needed).
3. **Tier 2 — existing Python-backed skill** (stable, tested, bounded).
4. **Tier 3 — retained worker** (idle/completed child with usable context;
   prefer reuse over respawn — no duplicate fresh child for the same task).
5. **Tier 4 — fresh worker** (new task, no suitable retained child).
6. **Tier 5 — adaptive fan-out** (independent workstreams; width from
   `config/orchestration.toml [concurrency]`: default 1, ceiling 2, env
   `SECOND_BRAIN_CONCURRENCY_CEILING`; no swarm without decomposition).
7. **Tier 6 — recursion** (root -> worker -> specialist; this machine caps
   child recursion at `RLM_MAX_DEPTH=1` — depth-2 delegation is
   **BLOCKED**; record as `recursion_depth` telemetry; simple work never
   recurses gratuitously).

## 4. Delegation purity (comparative, not vanity)

Original plan target: **>= 99% delegation purity** (plan §19/20).
Amendment §22: purity is measured and compared (baseline vs candidate), not
worshipped. Formula (implemented in `brainctl orchestration record`):

```text
delegation_purity = 1 - (driver_execution_attempts + emergency_execution_actions) / driver_actions_total
```

A single trivial deterministic action is not a purity failure; repeated
unnecessary driver execution is.

## 5. Worker result contract (§12.8)

Workers return concise structured evidence: Conclusion / Evidence /
Files-symbols / Commands-tests / Changes / Uncertainty / Next action /
Artifacts. No giant raw transcripts unless requested; raw evidence lives in
files, kernel state, or the Brain artifact store (`state/artifacts`).

## 6. Driver review contract (§12.9)

The driver verifies the worker answered the real task, inspects evidence
quality, detects contradictions, asks targeted follow-ups, never blindly
trusts, never redoes all worker work, and integrates only when evidence is
sufficient.

## 7. Independent verification (§12.7)

For consequential changes: implementation owner -> artifacts/evidence ->
**fresh verifier** (see `verifier-role.md`) -> driver acceptance. Verifier
question: "If you did not know the original request, what problem would you
infer this patch solves?" Compare against the real requirement. A verifier
must not repeat the implementer's conclusion.

## 8. Shared-file safety (§23)

One writer per owned file/module at a time; explicit ownership + A2A
coordination; verifiers normally inspect, not write; no blind simultaneous
writers.

## 9. Telemetry

Per-turn orchestration counters recorded via
`brainctl orchestration record` (privacy-safe JSONL in
`telemetry/agent-performance/orchestration-<session>.jsonl`):
driver_actions_total, driver_execution_attempts, blocked_execution_attempts,
emergency_execution_actions, worker_tasks, worker_corrections,
worker_verifications, fan_out_width, recursion_depth; delegation_purity
computed and stored with each record.

## 10. Stop behavior (plan §15.4)

Once worker evidence + the Requirement Ledger prove completion and no
material gate remains, STOP — do not spawn "one more" verifier or worker
without a risk/evidence reason. (Wired into the driver contract:
`src/driver-orchestrator.ts` `DRIVER_ORCHESTRATOR_CONTRACT`.)
