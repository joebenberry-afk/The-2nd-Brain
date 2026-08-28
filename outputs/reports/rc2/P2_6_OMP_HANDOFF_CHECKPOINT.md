# P2.6 Intelligent Model Routing — OMP Handoff Checkpoint

**Status:** IMPLEMENTED_BUT_RUNTIME_HANDOFF_INCOMPLETE
**Primary harness change:** OMP becomes primary; Hermes remains secondary validation target.
**Scope:** Preserve current P2.6 implementation and evidence before OMP integration.

## Verified implementation state

- `src/second_brain/model_routing.py` contains the bounded Brain-owned `ModelDecision` contract and deterministic selector.
- `src/second_brain/hermes_adapter.py` composes task, role, risk, capability, cost, availability, fallback, and identity inputs; records routing lifecycle through ledger/telemetry.
- `brainstem/adapters/hermes/hermes_plugin.py` registers the supported `llm_request` middleware bridge and post/error lifecycle observers.
- `brainstem/telemetry/SCHEMA.md` includes routing decision, fallback, invocation-started, invocation-completed, and invocation-failed kinds.

## Automated evidence preserved

- Ruff: clean on changed P2.6 Python files.
- Pyright: `0 errors, 0 warnings, 0 informations` on changed P2.6 Python files.
- `tests/test_model_routing.py`: 17 passed.
- `tests/test_hermes_adapter.py`: 28 passed.
- Relevant router/crossmodel/risk/worker/VMem regressions: 55 passed.
- Orchestration/delta/firewall/repository-intelligence regressions: 14 passed.
- Hermes plugin doctor: passed against repository plugin and installed validator plugin.

## Hermes runtime evidence

Persistent probe output:

- Process output: `P2_6_ROUTINE_OK`; session `20260823_233345_36fdd0`.
- Telemetry: `telemetry/agent-performance/hermes-Brain-Validator-20260823_233345_36fdd0.jsonl`.
- Actual provider/runtime identity: `openai-codex / gpt-5.6-luna`.
- Brain routing record: `model_routing_decision`, decision `model-decision-a066660555ec6de24034b04e`, status `failed`, failure `NO_ELIGIBLE_MODEL`.
- Cause: Hermes `pre_llm_call` did not expose provider metadata and the installed plugin had no configured candidate metadata, so Brain could not construct an eligible provider/model candidate.
- Provider completion telemetry still records actual `openai-codex / gpt-5.6-luna`; this does **not** prove selected==actual because Brain made no selected-model decision.

## Qualification boundary

Do not claim `P2.6_PROVEN`. Hermes runtime qualification is paused until the OMP primary integration is independently proven. The current Hermes implementation and evidence remain intact for secondary cross-harness validation after OMP qualification.

## Next gate

Implement and independently prove a thin OMP ↔ Second Brain lifecycle bridge using OMP-supported extension surfaces. Reuse Brain AutoInject, VMem, artifact, ledger, telemetry, worker-plane, context-reuse, and routing primitives. Then resume P2.6 with OMP as the primary live runtime.
