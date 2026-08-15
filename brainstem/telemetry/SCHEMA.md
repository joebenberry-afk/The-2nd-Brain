# Second Brain Telemetry Schema (Phase 2)

Authoritative record shape for the Prime measurement extension. JSONL, one
record per line, in `<SECOND_BRAIN_HOME>/telemetry/agent-performance/<session-stem>.jsonl`.

`session` = basename of the Prime session file without `.jsonl`, else
`anon-<epochms>-<rand>`.

Common fields on every record: `v` (schema version, =2), `ts` (ISO-8601 UTC,
ms precision), `kind`, `session`.

Privacy rule (constitution/security-boundaries.md): never store message
content, prompts, tool I/O payloads, or chain-of-thought. Store only counts,
sizes, hashes, error flags, tool names, and (for `bash` only) the command text
truncated to 500 chars.

Kinds:

| kind | extra fields |
|---|---|
| session_start | reason, cwd, model |
| before_agent_start | prompt_chars, role?, driver_contract_injected? |
| turn_start | turn |
| context | messages |
| tool_call | tool, id, command? (bash only), input_bytes |
| tool_result | tool, id, is_error, output_bytes |
| turn_end | turn, context_usage {used,total,percent} or null, tool_results |
| agent_end | messages |
| session_before_compact | branch_entries |
| session_compact | from_extension |
| session_shutdown | reason |
| rtd_shadow | tool, id, size, threshold, would_trigger, reason |
| extension_error | error (string, truncated) |
| orchestrator_policy_violation | violation, model, detected_by, blocked |

Field names are snake_case and stable across schema versions; new fields are
additive.

## Clarifications (decided at Phase 2 gate, 2026-08-14)

- `turn_end.tool_results` = COUNT of tool results in that turn (integers only).
- `context_usage.used` maps the runtime token count and may be `null` when the
  runtime does not report tokens; `total` and `percent` are best-effort.
- Sessions without a persisted session file (`--no-session`) still write
  telemetry under a stable-in-process `anon-<epochms>-<4hex>` id; they carry
  no sensitive identity.
- No duration fields: durations derive from `ts` deltas (one clock, ms).
- Production note: Prime Agent routes sessions through a daemon that pins its
  startup environment. Set `SECOND_BRAIN_HOME` (and any gate vars) BEFORE
  starting prime-agent so the daemon inherits them; otherwise the extension
  silently disables itself (missing home) or writes elsewhere.

## Phase 5 addition (RTD shadow)

`rtd_shadow` records appear when a tool result would have triggered Reversible
Tool Distillation (size > threshold, whitelisted tool/command). They change no
behavior: substitution happens only when `SECOND_BRAIN_RTD=active`.

## Phase 3 clarification (2026-08-15, RTD hot path; corrected)

- `rtd_shadow.size` = legacy `JSON.stringify(content).length` (character
  length, including quotes/escaping; `0` when the content is not
  serializable). This is NOT the same as `tool_result.output_bytes`, which is
  the UTF-8 byte count (raw string bytes for strings; serialized JSON bytes
  for other content; `<unserializable>` fallback).
- RTD eligibility (tool = bash, command prefix) is decided BEFORE any content
  measurement (`rtdEligibility` in the real handler). Eligible results are
  measured once (`measureContent` full) and that measurement is shared
  between `tool_result.output_bytes` and `rtd_shadow` evaluation/recording —
  exactly one JSON.stringify attempt plus one byte count.
- Ineligible results perform ZERO RTD-specific serialization: primitive
  strings get only the raw UTF-8 byte count base telemetry already requires
  (no JSON.stringify at all); non-strings keep exactly the single
  serialization/fallback that base telemetry already requires
  (`measureContent(content, includeSerializedChars=false)`), and
  `serializedChars` is recorded as 0 (never consumed by RTD).

## Phase 1 addition (Sol minimal-orchestrator, 2026-08-15)

`orchestrator_policy_violation` records are a privacy-safe detection fallback
for the Sol minimal-orchestrator policy
(`brainstem/policies/sol-minimal-orchestrator.md`). Fields are **bounded and
enumerated only**:

- `violation` — one of `direct_execution`, `undue_context_gather`,
  `concurrency_overflow`, `wrong_tier`, `rediscovery`, `scope_drift`,
  `evidence_gap`;
- `model` — provider/id string or null (never a free-text label);
- `detected_by` — one of `manual`, `runtime_guard`, `telemetry_audit`;
- `blocked` — boolean.

No free-text fields (no action description, note, reason, prompt, command, or
payload). The pure sensor builder exists for future/manual use and is
**NOT WIRED**: no extension hook emits this kind yet, and no automatic prompt
inspection is performed.

## Driver-Orchestration addition (2026-08-15)

`before_agent_start` gains two OPTIONAL additive fields (absent when the
emitting extension does not provide them — old records and other emitters are
unaffected):

- `role` — agent role of the active model for the session, one of
  `hard_orchestrator` | `driver` | `worker` | `normal` (enumerated; resolution
  per `brainstem/policies/driver-orchestration.md`, precedence
  hard_orchestrator > driver > worker > normal);
- `driver_contract_injected` — driver-role sessions only: `true` when the
  driver-orchestration contract was appended to the system prompt for this
  turn, `false` when the base prompt already carried the contract marker (or
  no prompt patch was produced). Absent for every non-driver role.

Both fields are snake_case and additive under the schema rule "new fields are
additive"; the Python validator (`src/second_brain/telemetry.py`) requires no
change (unknown/extra fields are ignored; only `v`, `kind`, `session`, `ts`
are checked).
