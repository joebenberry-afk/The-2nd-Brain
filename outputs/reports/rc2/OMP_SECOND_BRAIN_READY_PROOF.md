# OMP ↔ Second Brain Readiness Proof

**Verdict:** `OMP_SECOND_BRAIN_READY`
**Primary harness:** Oh My Pi (OMP)
**Secondary harness retained:** Hermes, with P2.6 runtime qualification paused at `P2_6_OMP_HANDOFF_CHECKPOINT.md`.

## Architecture

OMP uses the existing `brainstem/prime-extension` extension. It does not create memory, VMem, artifact, ledger, worker, context-reuse, or routing state of its own.

- OMP lifecycle registration: `brainstem/prime-extension/src/index.ts`.
- Thin bounded subprocess transport: `brainstem/prime-extension/src/routing-bridge.ts`.
- Brain CLI command: `src/second_brain/cli.py` (`autoinject omp-routing`).
- Brain-owned selector: `src/second_brain/omp_adapter.py` -> `model_routing.route_model`.
- Existing AutoInject/VMem/artifact/ledger/context paths remain in the same extension.
- Behavior-changing control seam: direct OMP `before_provider_request` handler returns a replacement payload; `wire()` is not used for this path because it intentionally discards return values.

## Independent validator result

Brain-Validator independently reviewed the changed files, readiness gate, runtime evidence, and focused verification. Verdict:

```text
OMP_SECOND_BRAIN_READY
```

Validator confidence: 0.91.

## Automated evidence

- `npm test -- --run tests/omp-routing.test.ts`: **5 passed**.
- `npm test -- --run tests/wiring.test.ts`: **79 passed**.
- Existing OMP lifecycle/Brain regressions (`wiring`, `autoinject`, `vmem`, `ledger-mirror`, `context-paging`): **226 passed**.
- `npm run typecheck`: passed.
- `.venv/Scripts/python.exe -m pytest -q -o addopts= tests/test_omp_adapter.py`: **4 passed**.
- Ruff on OMP Python changes: clean.
- Pyright on OMP Python changes: `0 errors, 0 warnings, 0 informations`.
- `py_compile` for `omp_adapter.py` and `cli.py`: passed.

## Real OMP runtime proof

Command surface:

```text
omp --no-tools --no-lsp --model openai-codex/gpt-5.6-luna \
  --extension brainstem/prime-extension/src/index.ts \
  --max-time 60 -p "P2.6 OMP role-tier runtime probe..."
```

Observed output: `OMP_P2_6_RUNTIME_OK`, exit code 0.

Canonical telemetry:

```text
telemetry/agent-performance/2026-08-24T03-55-41-757Z_01a031e8-e53d-7314-8592-67fcda2de3ec.jsonl
```

Read-back facts:

- `omp_routing_decision`: decision `model-decision-c943b1528e948377059f330a`, status `selected`, reason `LOWEST_COST_ELIGIBLE`, selected `openai-codex / gpt-5.6-luna`, tier `balanced`.
- `OMP_SECOND_BRAIN_READY` follows that selected decision in the same session.
- `omp_routing_invocation`: selected `openai-codex / gpt-5.6-luna`; effective request `openai-codex / gpt-5.6-luna`; `handoff_failure=null`.
- `provider_request_meta`: effective provider/model `openai-codex / gpt-5.6-luna`.
- `assistant_usage`: actual provider/model `openai-codex / gpt-5.6-luna`, with real token/cost fields.
- Existing AutoInject evidence is present in the same session (`autoinject_shadow_decision`, packet hash, bounded packet metrics).
- No provider cache counters are claimed; actual counters were not exposed.

## Fixed defects retained as evidence

Earlier real OMP probes are preserved, not discarded:

- `...03-52-03-589Z...jsonl`: empty candidate metadata caused `NO_ELIGIBLE_MODEL`; unsupported ledger mirror event and non-string prompt-base error were recorded.
- `...03-54-17-684Z...jsonl`: unsupported defects were fixed, but role `driver` required balanced tier while the default host candidate was efficient.
- The final probe proves all three defects are corrected without hiding failures.

## Readiness boundary

OMP is now the primary live harness for resumed P2.6 qualification. Hermes remains a secondary cross-harness regression target. P2.6 itself is not yet `P2.6_PROVEN`; its remaining runtime probes and independent final qualification resume using OMP primary evidence.
