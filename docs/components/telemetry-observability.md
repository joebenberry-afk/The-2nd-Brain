# Telemetry & Observability (Python + Prime Extension)

## Purpose
Measure agent sessions (Phase 2) with zero behavior change; Python aggregates/validates the JSONL the Prime extension writes.

## Problem it solves
Real workload data (tools, tokens, context, errors) for later routing/efficiency decisions, with strict privacy.

## Responsibilities
- Python `telemetry.py`: `iter_records` (parse `<home>/telemetry/agent-performance/<session>.jsonl`, mark bad lines), `validate` (schema v2; required v/kind/session; 14 KNOWN_KINDS incl. `rtd_shadow` and `orchestrator_policy_violation`; ts), `report` (deterministic aggregates: sessions/kinds/tools/cwds/models/error results/bash calls/compactions/extension errors/max context %/result bytes; `--since`), `format_report`.
- TS extension:
  - `config.ts`: env gate `SECOND_BRAIN_OBSERVABILITY` in {off,0,false,no} or missing brain home → silently disabled;
  - `index.ts`: 11 lifecycle events; `safeHandler` never mutates `tool_call` input, try/catch → `extension_error`; `session_shutdown` sync `appendFinal`; anonymous fallback session id created ONCE per extension lifecycle (Phase 2 — one telemetry file per anonymous lifecycle instead of one per event); telemetry dir mkdir ATTEMPTED ONCE per factory (Phase 4, `createTelemetryDirEnsurer`);
  - `orchestrator-guard.ts` (Phase 1, commit 61c536a): pure decision logic — blocks `bash`/`edit`/`websearch` for orchestrator-model sessions (default substring `gpt-5.6-sol`; env `ORCHESTRATOR_MODELS` / `ORCHESTRATOR_BLOCKED_TOOLS`; `ipython` NOT blocked — RLM delegation path). Wired in `index.ts`: `tool_call` returns `{block:true, reason}` + appends `orchestrator_policy_violation` (`detected_by=runtime_guard`, `blocked=true`); `before_agent_start` injects the Sol contract as a `systemPrompt` patch for orchestrator sessions only. Other models/sessions remain measurement-only. Guard failures fail open (`extension_error`, never block).
  - `storage.ts`: fire-and-forget append chain (order preserved, first failure logged once), `sanitizeSessionStem`;
  - `sensors.ts`: privacy — counts/sizes only, bash command ≤500 chars, prompt_chars only;
  - `rtd.ts`: shadow RTD decision (Phase 5) — SHADOW MODE only, no substitution.

## Non-responsibilities
Never mutates sessions or tool input; no context mutation, auto cleanup, or routing; never stores message content or chain-of-thought. The ONLY behavioral patches are the Sol guard above (blocked execution tools + Sol contract injection for orchestrator-model sessions); everything else returns undefined.

## Inputs
Prime events; `SECOND_BRAIN_HOME`/`SECOND_BRAIN_OBSERVABILITY`; JSONL files.

## Outputs
JSONL v2 records (schema: `brainstem/telemetry/SCHEMA.md`); aggregate reports.

## State ownership
`telemetry/agent-performance/` (append-only, derived).

## Invariants
Measurement handlers always return undefined; the two guard-capable handlers (`tool_call`, `before_agent_start`) return patches ONLY for orchestrator-model sessions; `tool_call` input never mutated; storage never throws into the session; validation flags unknown kinds/missing fields/wrong version.

## Interactions
Extension writes → Python reads/validates/aggregates → `brainctl telemetry report|validate`; rtd_shadow flows through the same JSONL.

## Failure behavior
Extension errors → `extension_error` records; storage failure silent after one log; Python marks malformed lines without crashing.

## Verification
`tests/test_telemetry.py` (10); TS: `brainstem/prime-extension/tests/` — config (6), sensors (46, incl. privacy truncation), storage (19), wiring (33, no-mutation/error-swallow + Sol guard), rtd (19), orchestrator-guard (14); real-agent integration `tests/integration/run-integration.sh`; Pester `brainstem/tests/install-prime-extension.Tests.ps1`.

## Known limitations
No env snapshot (Phase 8); context % only when runtime exposes it; anonymous fallback id is stable per lifecycle but distinct across lifecycles. RTD is SHADOW MODE (no substitution). The Sol guard is deployed to `~/.prime` since 2026-08-15T06:45:44Z (8 files SHA-identical to repo); live census: 0 `orchestrator_policy_violation` in 22,615 records; Sol-specific acceptance blocked by model availability. The extension context exposes no rlmDepth, so a subagent spawned with an orchestrator model would also be guarded (acceptable: workers run cheaper models).

## Future extension
RTD substitution (active mode), environment steward, sleep/replay inputs.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #3 (hand-written ambient TS types, guarded by real integration test).

## Relevant tests
`tests/test_telemetry.py`; `brainstem/prime-extension/tests/*.test.ts`; `brainstem/tests/install-prime-extension.Tests.ps1`.
