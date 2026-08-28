# Hermes Token / Context Evidence

**Status:** bounded adapter evidence PASS; provider-side cache-token metrics
remain unavailable and are not inferred.

## Measurement setup

A temporary initialized Brain contained one current, relevant memory. The
existing AutoInject mode was set to `active`. The adapter handled one
`session_start`, one first `pre_llm_call`, and the same `pre_llm_call` again
with the same session/turn identity.

The measurement used the real `hermes_adapter.handle_request()` path and the
same packet renderer used by the CLI/plugin bridge.

## Measured values

| Measurement | Result |
|---|---:|
| Startup request JSON | 240 chars |
| Startup response JSON | 250 chars |
| Targeted retrieval request JSON | 303 chars |
| First retrieval response JSON | 954 chars |
| Model-visible Brain packet | 508 chars |
| Existing Brain token estimate for packet | 127 tokens |
| First retrieval decision | `INJECT` |
| First retrieval model-visible | `true` |
| Second same-session decision | `NO_INJECTION` |
| Second same-session reason | `ALREADY_DELIVERED` |
| Second packet chars | 0 |
| Duplicate packet chars across first + second call | 508 chars |
| Provider/cache token metrics | `UNAVAILABLE_NOT_INFERRED` |

## Interpretation

- Hermes receives only the current user message as a retrieval query; raw task
  text is not persisted in Brain telemetry.
- The packet is the existing canonical Brain packet, not a Hermes memory copy.
- Existing delivery deduplication prevents repeating the same packet in the
  same Brain session/branch.
- Hermes `pre_llm_call` injection is ephemeral and is appended to the current
  user message, preserving the system-prompt cache prefix.
- The active retrieval packet remained far below the existing hard-cap path;
  the adapter did not enlarge Brain budgets for Hermes.
- No provider request was made by this measurement, so actual provider cache
  read/write tokens are correctly reported as unavailable rather than guessed.

## Limits

This is adapter/Brain payload measurement, not a paid-model economics
campaign. A fresh live Hermes session with provider usage metadata is still
needed for end-to-end provider cache and total-session token accounting.
