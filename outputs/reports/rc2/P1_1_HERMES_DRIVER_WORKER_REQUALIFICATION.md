# P1.1 Hermes + Second Brain Driver/Worker Re-qualification

**Overall classification:** `PARTIAL`
**Hermes-boundary classification:** `MISSING`
**Prime implementation classification:** `IMPLEMENTED_BUT_NOT_PROVEN` for complete end-to-end worker execution
**Scope:** read-only qualification; no implementation, test, plugin, configuration, or roadmap changes

## Frozen contract

Canonical contract:

```text
brainstem/policies/driver-orchestration.md
brainstem/prime-extension/src/driver-orchestrator.ts
```

Required behavior:

- deterministic explicit roles: `hard_orchestrator`, `driver`, `worker`, `normal`;
- driver may execute trivial Tier 0/1 work but must delegate substantial work;
- primitive-selection ladder through retained/fresh workers and bounded fan-out;
- default one active worker, hard ceiling two, no 3+ fan-out;
- every worker task has a narrow objective, scope, constraints, required evidence,
  and completion condition;
- worker result is concise structured evidence, not a raw transcript;
- driver reviews results, rejects unsupported claims, requests targeted correction,
  and integrates only sufficient evidence;
- worker recursion is bounded (`RLM_MAX_DEPTH=1` on this machine);
- orchestration counters are observable: driver actions, execution attempts,
  blocked/emergency actions, worker tasks/corrections/verifications, fan-out,
  recursion depth, and delegation purity;
- worker failure must degrade deterministically rather than silently turn into
  uncontrolled driver execution.

The contract is Prime-extension-specific. It is not a Hermes plugin contract.

## Independent evidence sources

Static sources read:

```text
brainstem/policies/driver-orchestration.md
brainstem/prime-extension/src/driver-orchestrator.ts
brainstem/prime-extension/src/index.ts
brainstem/prime-extension/tests/driver-orchestrator.test.ts
brainstem/prime-extension/tests/wiring.test.ts
brainstem/prime-extension/src/orchestrator-guard.ts
config/orchestration.toml
tests/test_orchestration.py
src/second_brain/hermes_adapter.py
brainstem/adapters/hermes/hermes_plugin.py
brainstem/adapters/hermes/plugin.yaml
brainstem/telemetry/SCHEMA.md
outputs/reports/driver-orchestration-proof.md
outputs/reports/p1-orchestration-cache-gate.md
state/recon/driver-orchestration-evidence.md
state/recon/driver-orchestration-audit-runtime.md
```

Independent Brain-Dev evidence session:

```text
Read-only report: Brain-Dev
Prime role/wiring tests reported: 3 files, 110 tests passed
Brain/Hermes selected tests reported: all passed
No files modified; no writeback, A2A, Prime delegation, or Hermes-native delegation used
```

Independent real Hermes Brain-Integrator probe:

```text
Hermes session: 20260822_054745_762c75
Host session:   hermes:Brain-Integrator:20260822_054745_762c75
Brain session:  26ed9ccc47aecb85e6ac9781853d39dad54e02dd402231daedd331a5481e0448
Project:        second-brain
Repo:           C:/Users/assas/Documents/The-Second-Brain
Branch:         brain/v1-rc4-prime-074-compat
```

The probe explicitly prohibited A2A, Prime, and Hermes-native `delegate_task` and
asked whether the installed Second Brain Hermes plugin exposed a Brain worker
plane. It reported `MISSING`: no driver task creation, worker spawning,
assignment, completion, or worker-result return surface.

Persistence-session evidence written before session termination:

```text
Hermes session: 20260822_055021_ab48cb
Brain session:  88ad1db91a71c9eb7132b15327d176c9011b077122d1eaf2d9af773eba3c9492
Telemetry:      telemetry/agent-performance/hermes-Brain-Integrator-20260822_055021_ab48cb.jsonl
Ledger:         state/sessions/88ad1db91a71c9eb7132b15327d176c9011b077122d1eaf2d9af773eba3c9492/ledger.sqlite
```

## Runtime read-back

The live Integrator persistence session emitted only the existing lifecycle path:

```text
session_started
hermes_session_started
brain_retrieval_attempt
brain_packet_delivered
hermes_pre_llm_call
```

Canonical `hermes_pre_llm_call` values:

```text
bot_name:          Brain-Integrator
bot_role:          integrator
project_id:        second-brain
model:             gpt-5.6-luna
decision:          INJECT
decision_source:   autoinject
model_visible:     true
packet_tokens:     745
candidate_count:   10
delivery_count:    4
vmem_context_tokens: 6
vmem_resident_count: 0
```

The matching canonical ledger contains only:

```text
seq=1 session_started
seq=2 brain_packet_delivered
```

There is no task-assignment, worker-spawn, worker-completion, worker-result,
correction, verification, fan-out, recursion, or orchestration-counter event.

The installed Hermes plugin surface is:

```text
hooks:
  on_session_start
  pre_tool_call
  post_tool_call
  pre_llm_call
  on_session_finalize

tool:
  second_brain_writeback
```

The plugin delegates to the existing Brain CLI `autoinject hermes-hook`. It does
not expose the Prime RLM worker plane or a Brain worker-result callback.
Hermes' generic `delegate_task` catalog tool is a separate Hermes-native surface;
it was not used and is not evidence of the Second Brain worker plane.

## Requirement classification

| Requirement | Classification | Evidence / gap |
|---|---|---|
| Explicit driver/worker identities | **PROVEN** in Prime; **PROVEN** as bot identity in Hermes; **MISSING** Hermes model-role resolver | Prime `resolveAgentRole` and tests are deterministic. Hermes preserves `bot_name`/`bot_role`, but does not call `resolveAgentRole` or inject the driver contract. |
| Delegation through intended existing plane | **IMPLEMENTED_BUT_NOT_PROVEN** in Prime; **MISSING** in Hermes | Prime contract and historical C2 report prove a delegation decision/attempt, but depth-1 worker completion was blocked. Hermes has no Brain delegation hook. |
| Bounded worker task packets | **PARTIAL** | Prime policy and prompt require objective/scope/constraints/evidence/completion, but pure role logic does not construct or validate a packet. Hermes has bounded context/tool results, not worker packets. |
| Bounded worker results | **PARTIAL** | Prime policy defines the concise result shape, but no validator/schema was found. Hermes has no worker result callback. |
| Coordinator remains orchestration-focused | **IMPLEMENTED_BUT_NOT_PROVEN** in Prime; **MISSING** in Hermes | Prime contract/purity metric exist; no live Hermes coordinator/worker path exists to prove behavior. |
| Mechanical role constraints | **PARTIAL** | Prime role classification, driver-contract injection, and Sol tool guard are mechanical. Delegation purity and packet/result constraints are prompt/metric-level, not hard action enforcement. Hermes only mechanically propagates configured bot identity. |
| Delegation/result/session/Brain telemetry and ledger | **PARTIAL** overall; **MISSING** Hermes delegation/result records | Existing Prime role/orchestration telemetry and Brain Hermes lifecycle telemetry exist. Hermes emitted no worker assignment/result/orchestration records in the real probe. |
| Worker failure does not silently collapse | **PARTIAL** | Recursion depth and malformed orchestration-record fail-open paths are proven. Historical P1 report explicitly marks worker unavailable, child crash, and cancellation as NOT TESTED. Hermes has no worker failure path. |
| No Hermes-native plane mistaken for Brain plane | **PROVEN** | Plugin source and runtime surface show only lifecycle/context/VMem/writeback. Native Hermes `delegate_task` is separate and was not used as Brain evidence. |
| Current Hermes team satisfies P1.1 across harness boundary | **MISSING** | The three-profile Hermes integration proves identity and Brain context, not Brain-owned driver/worker delegation or result return. |

## Exact remaining seam

No existing generic `WorkerTaskPacket`/`WorkerResultPacket` interface was found in
the current repository. The Prime `driver-orchestrator.ts` module is pure role and
prompt logic; it is not a callable worker execution API and must not be imported
into Hermes as a second orchestration implementation.

The smallest future closure seam is an adapter-boundary design decision followed
by implementation, not a metadata-only patch:

1. expose or define a harness-neutral bounded task/result contract at the existing
   Brain orchestration boundary;
2. add a Hermes plugin/adapter delegation callback that translates a real Hermes
   coordinator-to-worker interaction into that contract while preserving the
   configured bot/session/project identity;
3. emit the existing canonical orchestration counters and task/result lifecycle
   records through Brain telemetry/ledger, rather than a Hermes-native store;
4. mechanically reject wrong-role dispatch, malformed/unbounded packets/results,
   and silent driver fallback; and
5. run a real persistent three-profile Hermes delegation, worker return, worker
   failure, and read-back proof.

Likely harness-owned surfaces, only after that interface decision:

```text
brainstem/adapters/hermes/hermes_plugin.py
src/second_brain/hermes_adapter.py
brainstem/telemetry/SCHEMA.md
src/second_brain/cli.py          (existing orchestration recorder seam)
tests/test_hermes_adapter.py
possibly a new harness-neutral packet/result contract module
```

Do not modify `driver-orchestrator.ts` to make it Hermes-aware. Do not create a
parallel Hermes orchestration database or telemetry store.

## Verdict

P1.1 is not PROVEN against the current Hermes + Second Brain runtime.

```text
Prime role/prompt implementation: IMPLEMENTED_BUT_NOT_PROVEN for full worker execution
Hermes Brain worker plane: MISSING
Overall P1.1: PARTIAL
```

This artifact was written before terminating the live persistence probe. No
implementation, test, plugin, configuration, or roadmap file was modified.
