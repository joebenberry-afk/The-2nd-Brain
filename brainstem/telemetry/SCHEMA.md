# Second Brain Telemetry Schema (Phase 2)

Authoritative record shape for the Prime measurement extension. JSONL, one
record per line, in `<SECOND_BRAIN_HOME>/telemetry/agent-performance/<session-stem>.jsonl`.

`session` = basename of the Prime session file without `.jsonl`, else
`anon-<epochms>-<rand>`.

Common fields on every record: `v` (schema version — =2 for pre-P3 kinds,
=3 for the P3-B economics kinds below; additive), `ts` (ISO-8601 UTC, ms
precision), `kind`, `session`.

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
| assistant_usage | provider, model, input_tokens?, output_tokens?, cache_read_tokens?, cache_write_tokens?, total_tokens?, cost_total? (v=3; P3-B) |
| provider_request_meta | provider, model, request_seq, request_bytes, message_count, payload_keys, system_prefix_sha?, tool_surface_sha? (v=3; P3-B) |
| provider_response_meta | provider, model, status?, headers? [{key, value_sha256}] (v=3; P3-B) |
| orchestrator_policy_violation | violation, model, detected_by, blocked |
| autoinject_shadow_decision | decision, reason, packet_tokens, latency_ms, candidate_count, selected_count, delivery_id, packet_sha256, mode, model_visible, result_patch, emit_index, cache_hit, handler_returned_message, cli_packet_chars, cli_stdout_chars (mode = resolved host mode; model_visible = true when this decision path is the model-visible custom-message injection path (advisory/active), false for shadow (decide+record only, never model-visible); result_patch = patch returned; emit_index = emit ordinal per session+task key, 1 = spawning emit; cache_hit = served from the emit cache without a new spawn; handler_returned_message = this run returned the patch; cli_packet_chars / cli_stdout_chars = parsed packet text length / raw CLI stdout length — Phase C5/C7 instrumentation) |
| codex_hook_shadow_decision | decision, reason, packet_tokens, delivery_id, candidate_count, selected_count (logged by brainstem/codex-hooks/run.ps1 to codex-hooks.jsonl) |
| brain_packet_delivered | packet_id, item_count, packet_tokens, delivery_count, canonical_packet_hash, model_visible, delivery_prepared (Python AutoInject pipeline, `second_brain/autoinject.py`; model_visible = false and delivery_prepared = true — the Python event is the PREPARED/delivery-ledger state, NOT host insertion; actual model-visible injection happens via the host adapter custom-message path) |

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


## Phase P3-B addition — economics instrumentation (2026-08-16)

Additive schema v3 records emitted by the Prime extension (`sensors.ts` /
`index.ts`) from the provider hooks proven live in Phase A:

### `assistant_usage` (v=3; per assistant message, `message_end`)

- Fields: `provider`, `model`, `input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `cost_total`.
- Uses the EXACT host values (`Usage.input/output/cacheRead/cacheWrite/
  totalTokens/cost.total`). A counter is **omitted** when the host did not
  report it — never invented. Zero is preserved as `0` where the host
  distinguishes zero from missing.
- `provider`/`model` come from the message itself when the host exposes them,
  else from the extension context model (provider/id split); null when
  unknown. No record is emitted when the host exposes no usage object.

### `provider_request_meta` (v=3; per provider request, `before_provider_request`)

Metadata ONLY — never payload content:

- `request_seq` — monotonic per-extension request sequence;
- `request_bytes` — UTF-8 byte size of the serialized payload;
- `message_count` — number of messages in the payload;
- `payload_keys` — sorted top-level payload key names;
- `system_prefix_sha` — sha256 of the JSON serialization of the stable
  prefix: the messages preceding the LAST user message (the provider-cache
  prefix portion; the whole messages array when no user message exists);
- `tool_surface_sha` — sha256 of the serialized `tools` surface; absent when
  the payload has no tools.

Purpose: detect stable-prefix epochs (system-prompt/tool-schema changes) and
correlate `cacheRead`/`cacheWrite` with prefix stability (plan §5.4).

### `provider_response_meta` (v=3; per provider response, `after_provider_response`)

- `status` — numeric HTTP status (absent when not reported);
- `headers` — ONLY known cache/rate-limit diagnostic header entries, each
  `{key, value_sha256}` (key lowercased; value stored as sha256, never raw):
  `x-ratelimit-*`, `ratelimit-*`, `rate-limit*`, `x-cache*`, `cache-control`,
  `cf-cache-status`, `retry-after`. No unrelated headers are ever stored and
  no specific header is ever assumed to exist (plan §5.5).

### Model-visibility reconciliation (plan §0A.8 / §5.2)

- Python `brain_packet_delivered` (v=2) = **prepared/delivery-ledger state**:
  `delivery_prepared: true`, `model_visible: false` — Python prepares/selects
  the packet and cannot observe host insertion.
- The Prime host-side mode-aware `autoinject_shadow_decision.model_visible`
  event is **authoritative** for actual model visibility (advisory/active =
  true, shadow = false).
