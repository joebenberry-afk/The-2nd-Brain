# Hermes Runtime Proof

**Date:** 2026-08-21
**Adapter version:** 0.1.0
**Repository HEAD during proof:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

## Real Brain path

The focused adapter suite exercised the real subprocess path:

```text
Hermes-shaped lifecycle JSON
  -> .venv/Scripts/python.exe -m second_brain
  -> autoinject hermes-hook
  -> existing BrainLifecycle / AutoInject / semantic / telemetry / ledger
```

The suite uses temporary initialized Brain homes, real SQLite/FTS storage, real
candidate memory files, real `state/sessions/*/ledger.sqlite` files, and real
JSONL telemetry. It does not replace the acceptance path with a fake memory
result.

Command and result:

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -q
11 passed
```

The proof includes:

- stable same-session identity and bot-scoped identity differences;
- idempotent session registration;
- real agent, telemetry, and ledger read-back;
- active-mode bounded packet retrieval;
- explicit candidate writeback with provenance;
- separate Brain-Integrator -> Brain-Dev/Brain-Validator adapter sessions;
- malformed-input fail-open behavior.

## Real Hermes plugin runtime

The installed Hermes Agent runtime loaded the repository plugin through its
actual `PluginManager`, invoked the registered lifecycle hooks, and called the
configured Second Brain venv. The controlled runtime used a temporary Brain
home with one real current memory; the plugin returned that memory through the
real `pre_llm_call` hook.

Observed output from the real Hermes runtime:

```json
{"brain_home":"C:\\Users\\assas\\AppData\\Local\\Temp\\hermes-runtime-proof-zdg6k8sb\\brain","context_contains_real_memory":true,"context_injected":true,"plugin":"second-brain-hermes","pre_llm_result_count":1,"registered_hooks":["on_session_finalize","on_session_start","pre_llm_call","pre_tool_call"],"registered_tools":["second_brain_writeback"],"session_finalize_callbacks":0,"session_start_callbacks":0}
```

The zero callback-result counts are expected: the start/finalize callbacks are
observers and return `None`; the `pre_llm_call` callback returned one context
result containing the real Brain memory.

Hermes Plugin Doctor passed against each persistent team profile copy:

```text
hermes -p integrator plugins doctor C:\Users\assas\AppData\Local\hermes\profiles\integrator\plugins\second-brain-hermes --ci
hermes -p dev       plugins doctor C:\Users\assas\AppData\Local\hermes\profiles\dev\plugins\second-brain-hermes --ci
hermes -p validator plugins doctor C:\Users\assas\AppData\Local\hermes\profiles\validator\plugins\second-brain-hermes --ci
Plugin Doctor: ...\second-brain-hermes (each profile)
  manifest: second-brain-hermes 0.1.0 (standalone)
  OK: runtime discovery, manifest parsing, import, and registration passed
  registrations: 1 tool(s), 4 hook(s)
```

The persistent profiles report the plugin as enabled and have these non-secret
settings read back through the nested Hermes plugin configuration keys:

```text
integrator: bot_name=Brain-Integrator bot_role=integrator
dev:       bot_name=Brain-Dev       bot_role=dev
validator: bot_name=Brain-Validator bot_role=validator
all: brain_home=C:/Users/assas/Documents/The-Second-Brain
all: brain_python=C:/Users/assas/Documents/The-Second-Brain/.venv/Scripts/python.exe
all: repo_root=C:/Users/assas/Documents/The-Second-Brain
all: timeout_seconds=10.0
```

The real persistent runtime sessions were then run after enablement:

```text
Brain-Integrator / integrator / 20260821_112315_c4ca8e
  writeback -> mem-7ee245204a5e
Brain-Dev / dev / 20260821_112604_21544d
  retrieval -> selected mem-7ee245204a5e, model-visible, 760 packet tokens
Brain-Validator / validator / 20260821_115008_dd0a99
  independent read-only proof -> HERMES_CONTINUATION_READY
```

## Verification gates

```text
ruff check src tests                         PASS
pyright                                      PASS (0 errors)
second_brain doctor                          PASS (16 checks, 0 failures)
pytest                                       PASS (1075 passed in 205.28s)
```

## Honest limits

Provider/cache economics remain unmeasured because the local Lemonade/Ornith
endpoint was unavailable; no provider values are inferred. This does not alter
the real bounded-packet, ledger, telemetry, provenance, or three-profile
identity proof. The final independent Brain-Validator result is
`HERMES_CONTINUATION_READY`.
