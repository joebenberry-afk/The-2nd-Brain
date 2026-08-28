# P0.6 Final Project Attribution Runtime Proof

**Qualification:** `P0.6_PROVEN`
**Truthful decision authority:** `autoinject`
**Harness:** Hermes Agent
**Profile:** Brain-Integrator
**Repository:** `C:/Users/assas/Documents/The-Second-Brain`
**Branch:** `brain/v1-rc4-prime-074-compat`
**HEAD:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

This manifest was written while the fresh interactive Hermes session was still
live, before its session boundary. It indexes canonical telemetry and SQLite
read-backs for the selected second-turn injection interaction.

## Runtime identity

```text
Hermes session ID: 20260822_050720_57fbfb
Host session ID:   hermes:Brain-Integrator:20260822_050720_57fbfb
Brain session ID:  916573351736048942ca84d7e4f5aad04fcf8d578882a0dd5101ec8e55f080b8
bot_name:          Brain-Integrator
bot_role:          integrator
project_id:        second-brain
repo_root:         C:/Users/assas/Documents/The-Second-Brain
branch_id:         brain/v1-rc4-prime-074-compat
model:             gpt-5.6-luna
provider:          unknown (Hermes callback did not expose it)
```

## Selected real interaction

The selected interaction is the second user turn in this same persistent
session. The model-visible outcome was:

```text
P06_CONTEXT_PRESENT
```

This was produced after the user asked the model to inspect the context injected
for that turn and report whether it could see a Second Brain memory packet.

The exact response was captured in the live Hermes PTY transcript before the
session was terminated:

```text
P06_CONTEXT_PRESENT
```

The durable Hermes history confirms the corresponding second-turn prompt at
`2026-08-22 05:09:56.283470`; the PTY response above was captured by the live
session driver, not inferred from telemetry.

Correlation:

```text
task_sha256:           64c1fafba0f4918f8264afb5352cb16c619c0470dd1ad2f68a7776f166d18e8c
turn_id:               20260822_050720_57fbfb:20260822_050720_57fbfb:dacbd539
injection_decision_id: hermes-injection-0fa1b9779af2b6eba1eb001c
```

## Hermes pre-LLM / telemetry read-back

Canonical telemetry source:

```text
telemetry/agent-performance/hermes-Brain-Integrator-20260822_050720_57fbfb.jsonl
```

Relevant `hermes_pre_llm_call` record (line 8):

```text
decision:              INJECT
decision_source:       autoinject
injection_decision_id: hermes-injection-0fa1b9779af2b6eba1eb001c
profile:               integrator
reason_code:           INJECTED
mode:                  active
model_visible:         true
packet_tokens:         719
delivery_count:        6
candidate_count:       10
selected_routes:       []
routing_error:         false
project_id:            second-brain
bot_name:              Brain-Integrator
bot_role:              integrator
session:               hermes:Brain-Integrator:20260822_050720_57fbfb
task_sha256:           64c1fafba0f4918f8264afb5352cb16c619c0470dd1ad2f68a7776f166d18e8c
turn_id:               20260822_050720_57fbfb:20260822_050720_57fbfb:dacbd539
vmem_context_changed:  false
vmem_context_tokens:   6
vmem_resident_count:   0
vmem_evicted_count:    0
```

The preceding `brain_packet_delivered` telemetry record has the same project,
packet, selected-memory, and bounded delivery fields; its `model_visible=false`
means prepared-delivery bookkeeping, while the Hermes pre-LLM adapter record is
the host-visible action.

## Canonical ledger read-back

Canonical ledger source:

```text
state/sessions/916573351736048942ca84d7e4f5aad04fcf8d578882a0dd5101ec8e55f080b8/ledger.sqlite
```

The ledger was opened read-only with Python `sqlite3` URI `mode=ro` while the
session remained live. The matching event is `seq=3`:

```text
event_type:            brain_packet_delivered
surface_visibility:    model_visible_append
project_id:             second-brain
attribution.decision:  INJECT
attribution.source:    autoinject
attribution.id:        hermes-injection-0fa1b9779af2b6eba1eb001c
attribution.profile:   integrator
attribution.reason:    INJECTED
decision:               INJECT
mode:                   active
model_visible:          true
packet_tokens:          719
delivery_count:         6
selected_routes:        []
routing_error:          false
task_sha256:            64c1fafba0f4918f8264afb5352cb16c619c0470dd1ad2f68a7776f166d18e8c
turn_id:                20260822_050720_57fbfb:20260822_050720_57fbfb:dacbd539
vmem_context_changed:   false
vmem_context_tokens:    6
vmem_resident_count:    0
vmem_evicted_count:     0
```

The `session_started` ledger row has the same Hermes session, Brain session,
bot/role, project, repository, branch, model, and provider values as the
telemetry session-start record.

## Response / telemetry / ledger agreement

The Hermes plugin’s `pre_llm_call` contract returns the bounded `context` block
to Hermes; the adapter response that produced it carries the same decision,
project binding, and attribution fields recorded in the canonical event. The
real model acknowledged that returned context with `P06_CONTEXT_PRESENT`.

| Surface | Project | Decision ID | Decision/source | Visible | Bounded cost |
|---|---|---|---|---:|---:|
| Hermes model outcome | same injected Second Brain context | same turn interaction | context present | yes | host packet |
| Hermes pre-LLM telemetry | `second-brain` | `hermes-injection-0fa1b9779af2b6eba1eb001c` | `INJECT` / `autoinject` | true | 719 packet tokens |
| Canonical ledger `seq=3` | `second-brain` | `hermes-injection-0fa1b9779af2b6eba1eb001c` | `INJECT` / `autoinject` | true | 719 packet tokens |

No `governor.py` decision is claimed. The live authority is truthfully
`autoinject`; governor remains post-hoc telemetry analysis.

## Verification boundary

Focused tests and lint passed before this runtime:

```text
pytest tests/test_hermes_adapter.py -q                         19 passed
pytest tests/test_ledger.py tests/test_autoinject.py \
  tests/test_autoinject_writeback.py tests/test_autoinject_codex.py -q  64 passed
ruff check src tests                                           All checks passed
pytest tests/test_hermes_adapter.py -q                         19 passed
```

The independent Validator re-read this artifact, the telemetry JSONL, and the
canonical ledger after the session boundary. Final Validator session:
`20260822_052126_d9e086`.

Final gate result: `P0.6_PROVEN`.

The next unresolved frozen-roadmap requirement, read without modification, is
**P1.1 — Strict Driver/Worker Plane**. No P1.1 or later work was started.

No P1+, Lean, Prime, or roadmap work is included.

## Closure-task scope boundary

At the first inspection of this closure task, before Brain-Dev's fix, the
worktree already contained these pre-existing modifications/untracked files:

```text
M  brainstem/telemetry/SCHEMA.md
M  outputs/reports/rc2/01-frozen-roadmap-matrix.md
M  src/second_brain/cli.py
?? brainstem/adapters/hermes/
?? memory/semantic/mem-7ee245204a5e.md
?? outputs/reports/hermes/
?? outputs/reports/rc2/P0_4_VALIDATOR_RUNTIME_PROOF.md
?? outputs/reports/rc2/P0_6_GOVERNOR_ATTRIBUTION_RUNTIME_PROOF.md
?? outputs/reports/rc2/P0_6_INJECTION_TELEMETRY_PROOF.md
?? src/second_brain/hermes_adapter.py
?? tests/test_hermes_adapter.py
```

The only implementation/test changes made in this closure after that baseline
were:

```text
src/second_brain/hermes_adapter.py: add "project_id": binding.project_id
tests/test_hermes_adapter.py: assert ledger_payload["project_id"] == binding.project_id
```

No roadmap, CLI, schema, plugin, P1+, Lean, or Prime file was changed by this
closure task.
