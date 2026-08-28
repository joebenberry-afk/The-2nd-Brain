# P0.6 Injection Telemetry / Governor Attribution Runtime Proof

**Qualification candidate:** `P0.6_IMPLEMENTATION_GAP`
**Truthful decision authority:** `autoinject`
**Harness:** Hermes Agent
**Profile:** Brain-Integrator
**Repository:** `C:/Users/assas/Documents/The-Second-Brain`
**Branch:** `brain/v1-rc4-prime-074-compat`
**HEAD:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

This artifact was persisted before ending the interactive runtime session. It
indexes canonical telemetry and SQLite read-backs; it does not fabricate a
`governor.py` decision. The live INJECT authority is the existing AutoInject
lifecycle, and the attribution explicitly says `decision_source=autoinject`.

## Runtime identity

```text
Hermes session ID: 20260821_164352_bf46d5
Host session ID:   hermes:Brain-Integrator:20260821_164352_bf46d5
Brain session ID:  6a0fcc44665d452d032ed00be56b15c0b2e3088bab8acec2585d0034d875f1d2
bot_name:          Brain-Integrator
bot_role:          integrator
project_id:        second-brain
repo_root:         C:/Users/assas/Documents/The-Second-Brain
branch_id:         brain/v1-rc4-prime-074-compat
model:             gpt-5.6-luna
provider:          unknown (callback did not expose provider)
```

## Real pre-LLM lifecycle

Telemetry source:

```text
telemetry/agent-performance/hermes-Brain-Integrator-20260821_164352_bf46d5.jsonl
```

The real Hermes `hermes_pre_llm_call` record contains:

```text
decision:              INJECT
decision_source:       autoinject
injection_decision_id: hermes-injection-6d0da3d0301d39795968d769
profile:               integrator
reason_code:           INJECTED
mode:                  active
model_visible:         true
packet_tokens:         760
delivery_count:        6
candidate_count:       10
selected_routes:       []
routing_error:         false
vmem_context_changed:  false
vmem_context_tokens:   6
vmem_resident_count:   0
vmem_evicted_count:    0
```

The attribution object is bounded, contains no task text, and is generated from
the existing host-session ID, task SHA-256, turn ID, and actual AutoInject
decision.

## Canonical ledger correlation

Ledger source:

```text
state/sessions/6a0fcc44665d452d032ed00be56b15c0b2e3088bab8acec2585d0034d875f1d2/ledger.sqlite
```

The ledger was opened with Python `sqlite3` URI `mode=ro`. Matching events:

```text
seq=1 event_type=session_started
  identity matches the runtime identity above

seq=2 event_type=brain_packet_delivered
  attribution.injection_decision_id=hermes-injection-6d0da3d0301d39795968d769
  attribution.decision_source=autoinject
  attribution.decision=INJECT
  attribution.profile=integrator
  attribution.reason_code=INJECTED
  decision=INJECT
  mode=active
  model_visible=true
  packet_tokens=760
  delivery_count=6
  project_id is NULL in the canonical brain_packet_delivered ledger payload
  (the corresponding hermes_pre_llm_call telemetry record has project_id=second-brain)
  routing_error=false
  task_sha256=351193a01e5b2f6cb02526d3a560e54baf799c363eb951a8ac4408a98952f7e2
  turn_id=20260821_164352_bf46d5:20260821_164352_bf46d5:fe73d21c

seq=3 event_type=tool_completed
  obj_id=obj-f9d3171a34f1
  tool_name=terminal
  result_chars=1295
  residency_state=RESIDENT
  evicted_count=0
  tool_call_id=call_eXsSwr1XZXKc2LogFfr4Tu1H
```

The `seq=2` attribution object is byte-identical to the response/telemetry
attribution object. The ledger agent row is `hermes:Brain-Integrator` with
role profile `integrator` and the same Brain session ID.

## Source truthfulness check

- `src/second_brain/hermes_adapter.py` obtains the actual decision from
  `BrainLifecycle.prepare_injection()`.
- The shared attribution object records `decision_source=autoinject` rather
  than falsely claiming that `governor.py` authorized the live decision.
- `src/second_brain/governor.py` remains a post-hoc telemetry parser/aggregator;
  it is not presented as a live decision authority.
- `brainstem/telemetry/SCHEMA.md` documents the additive attribution object.
- Existing routing, AutoInject, VMem, ledger, and identity fields remain in the
  same response/event paths.

## Qualification status

The live AutoInject attribution itself is truthful and correlated, but the
canonical ledger event is missing `project_id` while the matching telemetry
record contains `project_id=second-brain`. Therefore the complete P0.6
identity/project attribution requirement is not proven.

```text
Hermes runtime -> AutoInject decision authority -> bounded packet/context
  -> model_visible=true -> telemetry attribution
  -> ledger attribution with missing project_id
```

The exact implementation gap is to include `project_id: binding.project_id` in
the canonical `brain_packet_delivered` ledger event payload while preserving the
same shared attribution object. The telemetry path already adds the field;
the ledger path does not.

Final independent Validator session: `20260821_164729_df75e9`.
Final verdict: `P0.6_IMPLEMENTATION_GAP`.

No source, test, plugin, configuration, roadmap, or Prime file was modified by
this qualification. No implementation workaround was started.