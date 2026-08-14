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
| before_agent_start | prompt_chars |
| turn_start | turn |
| context | messages |
| tool_call | tool, id, command? (bash only), input_bytes |
| tool_result | tool, id, is_error, output_bytes |
| turn_end | turn, context_usage {used,total,percent} or null, tool_results |
| agent_end | messages |
| session_before_compact | branch_entries |
| session_compact | from_extension |
| session_shutdown | reason |
| extension_error | error (string, truncated) |

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
