# Telemetry & Observability (Python + Prime Extension)

## Purpose
Measure agent sessions (Phase 2) with zero behavior change; Python aggregates/validates the JSONL the Prime extension writes.

## Problem it solves
Real workload data (tools, tokens, context, errors) for later routing/efficiency decisions, with strict privacy.

## Responsibilities
- Python `telemetry.py`: `iter_records` (parse `<home>/telemetry/agent-performance/<session>.jsonl`, mark bad lines), `validate` (schema v2; required v/kind/session; 13 KNOWN_KINDS incl. `rtd_shadow`; ts), `report` (deterministic aggregates: sessions/kinds/tools/cwds/models/error results/bash calls/compactions/extension errors/max context %/result bytes; `--since`), `format_report`.
- TS extension:
  - `config.ts`: env gate `SECOND_BRAIN_OBSERVABILITY` in {off,0,false,no} or missing brain home → silently disabled;
  - `index.ts`: 11 lifecycle events; `safeHandler` never returns patches, never mutates `tool_call` input, try/catch → `extension_error`; `session_shutdown` sync `appendFinal`;
  - `storage.ts`: fire-and-forget append chain (order preserved, first failure logged once), `sanitizeSessionStem`;
  - `sensors.ts`: privacy — counts/sizes only, bash command ≤500 chars, prompt_chars only;
  - `rtd.ts`: shadow RTD decision (Phase 5).

## Non-responsibilities
Never blocks/mutates sessions; no context mutation, auto cleanup, or routing; never stores message content or chain-of-thought.

## Inputs
Prime events; `SECOND_BRAIN_HOME`/`SECOND_BRAIN_OBSERVABILITY`; JSONL files.

## Outputs
JSONL v2 records (schema: `brainstem/telemetry/SCHEMA.md`); aggregate reports.

## State ownership
`telemetry/agent-performance/` (append-only, derived).

## Invariants
Handlers always return undefined; `tool_call` input never mutated; storage never throws into the session; validation flags unknown kinds/missing fields/wrong version.

## Interactions
Extension writes → Python reads/validates/aggregates → `brainctl telemetry report|validate`; rtd_shadow flows through the same JSONL.

## Failure behavior
Extension errors → `extension_error` records; storage failure silent after one log; Python marks malformed lines without crashing.

## Verification
`tests/test_telemetry.py` (8); TS: `brainstem/prime-extension/tests/` — config (6), sensors (23, incl. privacy truncation), storage (13), wiring (18, no-mutation/error-swallow), rtd (14); real-agent integration `tests/integration/run-integration.sh`; Pester `brainstem/tests/install-prime-extension.Tests.ps1`.

## Known limitations
No env snapshot (Phase 8); context % only when runtime exposes it; anonymous fallback session ids.

## Future extension
RTD substitution (active mode), environment steward, sleep/replay inputs.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #3 (hand-written ambient TS types, guarded by real integration test).

## Relevant tests
`tests/test_telemetry.py`; `brainstem/prime-extension/tests/*.test.ts`; `brainstem/tests/install-prime-extension.Tests.ps1`.
