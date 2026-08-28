# P0.4 Validator Runtime Proof

**Verdict status:** `P0.4_PROVEN`
**Harness:** Hermes Agent
**Profile:** `validator`
**Repository:** `C:/Users/assas/Documents/The-Second-Brain`
**Branch:** `brain/v1-rc4-prime-074-compat`
**HEAD:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

This manifest was written before the interactive Validator session was
terminated. It is an index of canonical read-backs, not a substitute for them.

## 1. Same-session identity

```text
Hermes session ID: 20260821_154649_d27020
Host session ID:   hermes:Brain-Validator:20260821_154649_d27020
Brain session ID:  af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49
bot_name:          Brain-Validator
bot_role:          validator
project_id:        second-brain
repo_root:         C:/Users/assas/Documents/The-Second-Brain
branch_id:         brain/v1-rc4-prime-074-compat
```

Identity is read from the session-start telemetry and the matching ledger row.

## 2. Real post-tool capture

The same persistent Validator session made one real terminal tool call. The
terminal output contained the bounded proof markers and 2400 `P` characters.

```text
tool_name:       terminal
tool_call_id:    call_b4d4OFzK4sgXCGyOhmIO6IOj
turn_id:         20260821_154649_d27020:20260821_154649_d27020:b1979b58
object_id:       obj-f9d646c21c53
object_kind:     TOOL_OBSERVATION
result_chars:    2517
result_sha256:   f9d646c21c53f438b1630defb84f72c687d191a1bde0cd35b5d1c2cca577983a
initial_state:   EVICTED
initial_evicted_count: 1
vmem_budget_tokens: 512
status:          ok
```

Primary source:

```text
telemetry/agent-performance/hermes-Brain-Validator-20260821_154649_d27020.jsonl
```

Relevant telemetry record: line 6, `kind=hermes_post_tool_call`.

## 3. Subsequent same-session pre-LLM turn

A second user turn in the same Hermes session explicitly referenced
`obj-f9d646c21c53`. The real `pre_llm_call` path then recorded:

```text
vmem_context_changed: true
vmem_faulted_in_ids:  ["obj-f9d646c21c53"]
vmem_resident_count:  1
vmem_resident_tokens: 629
vmem_context_chars:   2236
vmem_context_tokens:  559
packet_tokens:        603
model_visible:        true
bot_name:             Brain-Validator
bot_role:             validator
project_id:           second-brain
session:              hermes:Brain-Validator:20260821_154649_d27020
```

Primary source:

```text
telemetry/agent-performance/hermes-Brain-Validator-20260821_154649_d27020.jsonl
```

Relevant telemetry record: line 9, `kind=hermes_pre_llm_call`.

The installed plugin combines the existing AutoInject packet and the returned
bounded VMem block into the ordinary Hermes `pre_llm_call` `{"context": ...}`
response. The source path is:

```text
brainstem/adapters/hermes/hermes_plugin.py
```

## 4. Bounded model-visible faulted-in material

The same-session adapter read-back, after existing `vmem compact-prep` was used
to re-establish the documented cold state, returned:

```text
vmem_context.context_changed: true
vmem_context.faulted_in_ids: ["obj-f9d646c21c53"]
vmem_context.context_chars: 2236
vmem_context.context_tokens: 559
```

The returned `vmem_context.rendered_text` contained:

```text
[SECOND_BRAIN_FAULTED_IN]
HERMES_VALIDATOR_PERSISTED_BEGIN
...
HERMES_VALIDATOR_PERSISTED_END
```

The complete returned text is intentionally not duplicated into this manifest;
the canonical artifact backing and response were read from the same Brain
session via the existing adapter path. The content bound is the existing
512-token VMem budget plus the adapter’s bounded fault-in rendering.

## 5. Canonical VMem read-back

Command used:

```text
.venv/Scripts/python.exe -m second_brain --home C:/Users/assas/Documents/The-Second-Brain vmem list hermes:Brain-Validator:20260821_154649_d27020 --json
```

Canonical result for `obj-f9d646c21c53`:

```text
obj_id:             obj-f9d646c21c53
session_id:         hermes:Brain-Validator:20260821_154649_d27020
kind:               TOOL_OBSERVATION
content_sha256:     f9d646c21c53f438b1630defb84f72c687d191a1bde0cd35b5d1c2cca577983a
residency_state:    FAULTED_IN
token_estimate:     629
access_count:       2
metadata.tool_call_id: call_b4d4OFzK4sgXCGyOhmIO6IOj
metadata.turn_id:  20260821_154649_d27020:20260821_154649_d27020:b1979b58
```

## 6. Canonical ledger TOOL_COMPLETED read-back

Canonical ledger:

```text
state/sessions/af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49/ledger.sqlite
```

Read-only Python `sqlite3` URI used:

```python
sqlite3.connect(
  "file:C:/Users/assas/Documents/The-Second-Brain/state/sessions/"
  "af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49/ledger.sqlite"
  "?mode=ro",
  uri=True,
)
```

Matching row:

```text
seq:                3
event_type:         tool_completed
obj_id:             obj-f9d646c21c53
bot_name:           Brain-Validator
bot_role:           validator
brain_session_id:   af616602dd028c3b4c943a1d73b2eb03033debb95b7db9557272791e799e0d49
hermes_session_id:  20260821_154649_d27020
project_id:         second-brain
repo_root:          C:/Users/assas/Documents/The-Second-Brain
tool_name:          terminal
tool_call_id:       call_b4d4OFzK4sgXCGyOhmIO6IOj
residency_state:    EVICTED
evicted_count:      1
result_chars:       2517
result_sha256:      f9d646c21c53f438b1630defb84f72c687d191a1bde0cd35b5d1c2cca577983a
vmem_budget_tokens: 512
```

The ledger agent row is `hermes:Brain-Validator` with role profile `validator`
and the same Brain session ID.

## 7. Agreement index

| Evidence surface | Same session/object | Eviction | Fault-in | Bounded/model-visible context | Identity/project |
|---|---|---:|---:|---:|---:|
| `hermes_post_tool_call` telemetry | yes | 1 | pending next turn | n/a | yes |
| `hermes_pre_llm_call` telemetry | yes | read-back | `obj-f9d646c21c53` | 559 tokens / model-visible | yes |
| Canonical VMem | yes | prior state | `FAULTED_IN`, access 2 | 629 estimated tokens | yes |
| Canonical ledger | yes | 1 | matching object | metadata only | yes |
| Adapter response | yes | cold ref | exact object ID | `[SECOND_BRAIN_FAULTED_IN]` + proof markers | yes |

## 8. Final Validator read-back and roadmap boundary

After the interactive session boundary, fresh Validator session
`20260821_155343_90787a` independently re-read this manifest, the cited
telemetry JSONL, canonical VMem state, and the canonical SQLite ledger using
Python `sqlite3` URI `mode=ro`. All seven checks passed and the Validator
returned `P0.4_PROVEN`.

The frozen roadmap read-back confirms P0.5 remains proven by the existing
activity-capture/ledger evidence. The next unresolved qualified requirement is
**P0.6 — Injection Telemetry**: the existing telemetry/governor pieces are
implemented, but complete end-to-end governor/injection-attribution evidence
is still missing; `outputs/reports/rc2/02-token-fabric-live-wiring-audit.md`
classifies that integration as partial. No implementation task for P0.6 was
started here.

No source, test, plugin, configuration, or roadmap file was modified to create
this proof. Only this evidence manifest and the qualification addendum were
updated.
