# P0.6 Injection Telemetry Proof

**Qualification:** `P0.6_IMPLEMENTATION_GAP`
**Harness:** Hermes Agent
**Profile:** Brain-Validator
**Repository:** `C:/Users/assas/Documents/The-Second-Brain`
**Branch:** `brain/v1-rc4-prime-074-compat`
**HEAD:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

This artifact records one fresh persistent Hermes pre-LLM lifecycle and the
canonical telemetry/ledger read-back. It is an evidence manifest, not a claim
that the missing governor attribution exists.

## Runtime identity

```text
Hermes session ID: 20260821_161508_d1c8a5
Host session ID:   hermes:Brain-Validator:20260821_161508_d1c8a5
Brain session ID:  02940ab12884d129b43ac71919957baac2dc8aac1d24f5258b298634b2030906
bot_name:          Brain-Validator
bot_role:          validator
project_id:        second-brain
repo_root:         C:/Users/assas/Documents/The-Second-Brain
branch_id:         brain/v1-rc4-prime-074-compat
model:             gpt-5.6-luna
provider:          unknown (Hermes callback did not expose it)
```

## Real lifecycle read-back

Telemetry source:

```text
telemetry/agent-performance/hermes-Brain-Validator-20260821_161508_d1c8a5.jsonl
```

The fresh session recorded:

```text
hermes_session_started:
  bot_name=Brain-Validator
  bot_role=validator
  brain_session_id=02940ab12884d129b43ac71919957baac2dc8aac1d24f5258b298634b2030906
  project_id=second-brain
  repo_root=C:/Users/assas/Documents/The-Second-Brain
  model=gpt-5.6-luna

hermes_pre_llm_call:
  decision=INJECT
  mode=active
  model_visible=true
  packet_tokens=760
  candidate_count=10
  delivery_count=6
  selected_routes=[]
  routing_error=false
  vmem_context_changed=false
  vmem_context_tokens=6
  vmem_resident_count=0
  vmem_evicted_count=0
```

The real terminal tool call in the same session produced:

```text
tool_name=terminal
tool_call_id=call_jcV3IQjhZRymfTHxcZhYF9L0
object_id=obj-9e34353b1fb1
object_kind=TOOL_OBSERVATION
result_chars=1685
result_sha256=9e34353b1fb1b451cedcae7d8ecc86485a0b3ed9d53dee0dfe13896a8afc7f5b
residency_state=RESIDENT
evicted_count=0
vmem_budget_tokens=512
status=ok
```

## Canonical ledger read-back

Ledger source:

```text
state/sessions/02940ab12884d129b43ac71919957baac2dc8aac1d24f5258b298634b2030906/ledger.sqlite
```

Read-only Python `sqlite3` query found:

```text
agents:
  agent_id=hermes:Brain-Validator
  host_agent_id=Brain-Validator
  role_profile=validator

seq=1 event_type=session_started
  bot_name=Brain-Validator
  bot_role=validator
  brain_session_id=02940ab12884d129b43ac71919957baac2dc8aac1d24f5258b298634b2030906
  hermes_session_id=20260821_161508_d1c8a5
  project_id=second-brain
  repo_root=C:/Users/assas/Documents/The-Second-Brain

seq=2 event_type=brain_packet_delivered
  decision=INJECT
  mode=active
  model_visible=true
  packet_tokens=760
  delivery_count=6
  selected_routes=[]
  routing_error=false
  vmem_context_changed=false
  vmem_context_tokens=6
  vmem_resident_count=0
  vmem_evicted_count=0

seq=3 event_type=tool_completed
  obj_id=obj-9e34353b1fb1
  object_kind=TOOL_OBSERVATION
  bot_name=Brain-Validator
  bot_role=validator
  brain_session_id=02940ab12884d129b43ac71919957baac2dc8aac1d24f5258b298634b2030906
  hermes_session_id=20260821_161508_d1c8a5
  project_id=second-brain
  repo_root=C:/Users/assas/Documents/The-Second-Brain
  tool_call_id=call_jcV3IQjhZRymfTHxcZhYF9L0
  result_chars=1685
  result_sha256=9e34353b1fb1b451cedcae7d8ecc86485a0b3ed9d53dee0dfe13896a8afc7f5b
  residency_state=RESIDENT
  evicted_count=0
  vmem_budget_tokens=512
```

## Attribution qualification

The current implementation provides these P0.6 attribution links:

- Hermes session → Brain session → bot/role/project/repository
- routing result (`selected_routes`, `routing_error`)
- AutoInject decision (`INJECT`), mode (`active`), and model visibility
- packet/delivery token counts
- VMem/AutoInject state fields
- telemetry and matching ledger events

The required governor attribution is absent:

- `src/second_brain/hermes_adapter.py` does not invoke `governor.py`.
- `hermes_pre_llm_call` has no `governor_decision`, `governor_profile`,
  `governor_source`, or equivalent attribution field.
- The ledger event has no governor attribution either.
- The existing `governor.py` is a telemetry parser/aggregator and is not a
  live decision source on this Hermes path.
- Therefore the record can explain that AutoInject decided `INJECT`, but cannot
  prove which governor decision/profile produced that injection.

**Smallest exact implementation gap:** wire the existing governor decision
source into the Hermes pre-LLM attribution path and add one bounded, correlated
governor attribution object/field to the existing `hermes_pre_llm_call` response,
telemetry record, and matching ledger payload. Do not create a second governor
or telemetry store.

No implementation was made during this qualification. P0.6 remains
`P0.6_IMPLEMENTATION_GAP`.
