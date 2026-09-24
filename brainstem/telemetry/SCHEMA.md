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
| prime_tool_surface | all_tools_count, active_tools_count, all_tools, active_tools (Phase R6; emitted alongside session_start only when the host exposes getAllTools/getActiveTools) |
| before_agent_start | prompt_chars |
| turn_start | turn |
| context | messages |
| tool_call | tool, id, command? (bash only), input_bytes; target_sha256? (read target hash only) |
| tool_result | tool, id, is_error, output_bytes |
| turn_end | turn, context_usage {used,total,percent} or null, tool_results |
| agent_end | messages |
| session_before_compact | branch_entries |
| session_compact | from_extension |
| vmem_compact_prep | evicted_at_compaction, pinned_preserved (Phase R3; null when the vmem call failed) |
| vmem_hot_context | resident_count, evicted_count, resident_tokens (Phase R3; null when the vmem call failed) |
| session_shutdown | reason |
| rtd_shadow | tool, id, size, threshold, would_trigger, reason, original_chars?, visible_chars?, saved_chars?, artifact_ref?, command_class?, error_status?, distilled? (P3-F additive) |
| lean_kernel | decision, reason, skill_status, mode, eval_source, kernel_chars, dedup_hit (v=2; approved Lean content only) |
| extension_error | error (string, truncated) |
| assistant_usage | provider, model, response_id?, input_tokens?, output_tokens?, cache_read_tokens?, cache_write_tokens?, total_tokens?, cost_total? (v=3; P3-B) |
| provider_request_meta | provider, model, request_seq, request_bytes, message_count, payload_keys, system_prefix_sha?, tool_surface_sha? (v=3; P3-B) |
| provider_response_meta | provider, model, status?, headers? [{key, value_sha256}] (v=3; P3-B) |
| quiet_skip | reason, candidates, vocab_terms, unique_terms, headline_terms, ubiquitous_headline_terms, capsule, vmem_objects, total_documents, precheck_ms, model_visible (v=2; V3 S2 quiet fast path, `src/quiet-precheck.ts` via the Prime adapter: one record per turn where the in-host precheck proved the Brain could not contribute a model-visible message, so the capsule/render/AutoInject phases ran no Python process on the critical path. reason is a fixed token (`no_evidence` is the only skip reason); counts describe the precheck's own tokenization/corpus statistics and never carry prompt text, terms, memory ids or packet content; model_visible = false because the turn deliberately added no Brain content. A turn that runs instead logs none of this — its evidence is the existing `autoinject_shadow_decision` / `brain_retrieval_attempt` / `active_state_delivery` records) |
| autoinject_shadow_decision | decision, reason, packet_tokens, latency_ms, candidate_count, selected_count, delivery_id, packet_sha256, mode, model_visible, result_patch, emit_index, cache_hit, handler_returned_message, cli_packet_chars, cli_stdout_chars (mode = resolved host mode; model_visible = true when this decision path is the model-visible custom-message injection path (advisory/active), false for shadow (decide+record only, never model-visible); result_patch = patch returned; emit_index = emit ordinal per session+task key, 1 = spawning emit; cache_hit = served from the emit cache without a new spawn; handler_returned_message = this run returned the patch; cli_packet_chars / cli_stdout_chars = parsed packet text length / raw CLI stdout length — Phase C5/C7 instrumentation) |
| codex_hook_shadow_decision | decision, reason, packet_tokens, delivery_id, candidate_count, selected_count (logged by brainstem/codex-hooks/run.ps1 to codex-hooks.jsonl) |
| brain_retrieval_attempt | task_sha256, candidate_count, eligible_count, contributing_count, noncontributing_count, recipient, role_profile, project_id, query_mode, is_delta (Python AutoInject pipeline, `second_brain/autoinject.py`; privacy-safe: counts and a task hash only, never query text. query_mode = which query the decision used: `idf` = the request itself, `idf_focused` = the request's question/indirect-question sentences, `idf_narrowed` = the request's own most discriminative terms; contribution counts separate *retrieved candidates* (candidate_count) from the candidates that survived the contribution decision (contributing_count)) |
| brain_packet_delivered | packet_id, item_count, packet_tokens, delivery_count, canonical_packet_hash, model_visible, delivery_prepared (Python AutoInject pipeline, `second_brain/autoinject.py`; model_visible = false and delivery_prepared = true — the Python event is the PREPARED/delivery-ledger state, NOT host insertion; actual model-visible injection happens via the host adapter custom-message path) |
| session_started | host, host_session_id (P3a Claude Code adapter, `_cmd_claude_code_hook` SessionStart branch; also emitted by Antigravity/Codex via `autoinject.BrainLifecycle.start_session`) |
| claude_code_stop_turn | host, project_id (P3a Claude Code adapter Stop branch — one record per assistant turn; Stop fires per-turn, not per-session, so this is NOT a session-completion signal; deliberately distinct from the pre-existing `turn_end` kind above, which carries a different Prime-specific field shape) |
| hermes_session_started | adapter_version, bot_name, bot_role, hermes_session_id, brain_session_id, project_id, repo_root, provider, model, branch_id (Hermes adapter; identity metadata only) |
| hermes_pre_llm_call | task_sha256, decision, reason, candidate_count, selected_ids, packet_tokens, mode, model_visible, delivery_count, project_id, bot_name, bot_role, attribution (object: injection_decision_id, decision_source, decision, profile, reason_code; bounded, no task text or packet body) (Hermes adapter) |
| hermes_post_tool_call | obj_id, object_kind, tool_name, tool_call_id?, turn_id?, status, result_sha256, result_chars, original_result_chars, original_result_bytes, original_result_sha256, artifact_ref, recovery_handle, visible_result_chars, visible_result_bytes, reduction_ratio, distilled, evicted_count, residency_state, vmem_budget_tokens, project_id, bot_name, bot_role, repo_root, branch_id; raw result content is never stored in telemetry (Hermes adapter) |
| hermes_writeback_candidate | memory_id, project_id, status, evidence_count, title_sha256, observation_sha256, bot_name, bot_role (Hermes adapter; canonical memory holds the explicit writeback) |
| hermes_session_finalized | brain_session_id, checkpoint_ok (Hermes adapter) |
| model_invocation_completed | lifecycle_event, turn_id, api_request_id, actual_identity, response_model, status, usage?, cost?; host-observed metrics only, never Brain model selection |
| model_invocation_failed | lifecycle_event, turn_id, api_request_id, actual_identity, response_model, status, failure_code?, usage?, cost?; host-observed error metadata |

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
behavior: substitution happens only when `[rtd] enabled=true` in
config/context.toml (P3-F; the legacy `SECOND_BRAIN_RTD=active` env is no
longer the substitution switch).

## Phase P3-F addition (RTD substitution, plan §11)

When `[rtd] enabled=true`, eligible large bash results (pytest/git/rg/grep,
text-only, size > threshold) are FIRST preserved byte-exactly through the
artifact store (`second_brain artifact store`, sha256 content-addressed) and
verified recoverable via `artifact expand`; only then is the model-visible
content replaced by the deterministic `[SECOND_BRAIN_RTD]` block (metadata +
bounded head/tail + command-class evidence + exact reopen instructions).
Preservation failure returns the ORIGINAL content unchanged (plan §11.4);
binary/non-text results are never distilled (§11.8). The `rtd_shadow` record
gains ADDITIVE fields (absent in shadow mode, never raw content):

- `original_chars` — exact raw result length;
- `visible_chars` — full model-visible block length (metadata + evidence + pointer);
- `saved_chars` — original − visible (≥ 0);
- `artifact_ref` — `[brain-artifact:sha256:<hex>]` recovery handle;
- `command_class` — pytest | git | rg | grep (first token);
- `error_status` — whether the tool result was an error (conservative §11.7);
- `distilled` — true = substitution applied; false = triggered but
  preservation/verification failed (original content kept).

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

## Historical execution telemetry (read-only vocabulary)

Older records may contain `orchestrator_policy_violation`, `stop_*`,
`omp_worker_*`, `hermes_worker_*`, `model_routing_decision`, or
`driver_contract_injected`. The current extension and adapters do not emit
those kinds or treat them as execution authority. They remain decodable
historical evidence; their presence is not proof of worker settlement or
model-visible delivery.


## Phase R3 addition — VMem compaction-boundary bookkeeping (2026-08-19)

`vmem_compact_prep` (emitted from `session_before_compact`, after the ledger
checkpoint succeeds) and `vmem_hot_context` (emitted from
`session_compact`, fire-and-forget) are advisory bookkeeping records for
Context Virtual Memory's own documented compaction-boundary integration
point (`src/second_brain/vmem.py` §6.7). Both are gated behind
`[vmem] enabled` in `config/context.toml` (default `false`). Nothing in
`session_before_compact` cancels compaction: a failed ledger checkpoint is
recorded as `ledger_degraded` and the host proceeds (V3 CTX-03).
See `outputs/reports/rc4/04-prime-vmem.md` for why this is bookkeeping only
and not yet a `context`-event message replacement.

## Phase R6 addition — Prime tool surface capture (2026-08-19)

`prime_tool_surface` is read-only measurement: it calls `pi.getAllTools()`/
`pi.getActiveTools()` (declared on `ExtensionAPI`,
`brainstem/prime-extension/types/prime.d.ts:306-309`, "modelled for Phase J
measurement, not consumed today" — this is the first place the codebase
ever calls them) once per `session_start`, when the host exposes them.
Never calls `setActiveTools` in this pass — see
`outputs/reports/rc4/06-tool-working-set-live.md` for why: the Python Tool
Working Set catalog's tool names don't match Prime's real tool names, and
`setActiveTools` takes a replacement list.

## Phase P3-B addition — economics instrumentation (2026-08-16)

## Approved Lean runtime context

`lean_kernel` records describe approved skill-content injection without
assigning a coordinator role or choosing a model. `decision` is `inject` or
`omit`; `reason` is a bounded state such as `active`, `advisory`, `off`,
`unsupported-profile`, or `skill-missing`. `skill_status` records the
resolved lifecycle, `mode`/`eval_source` the explicit evaluation setting,
`kernel_chars` the approved section length, and `dedup_hit` whether that
section was already present. No skill body or prompt content is persisted.
The exact approved canonical skill bytes are a separate consumption-time
authorization obligation; telemetry does not grant it.

Provider usage/response records below report observed native identity and
supported counters. They do not route a model, reserve agent capacity, or
authorize native execution.

Additive schema v3 records emitted by the Prime extension (`sensors.ts` /
`index.ts`) from the provider hooks proven live in Phase A:

### `assistant_usage` (v=3; per assistant message, `message_end`)

`response_id` carries the host's own identity for the billable response this usage belongs to
(`message.responseId`). It is what lets a reader tell a **repeated observation of one response**
apart from a **second billed request**:

* an identity is recorded only when the host reported one; an absent or empty value means
  *unidentified*, which is counted in full and reported, never treated as a duplicate (treating it
  as one would drop a genuinely billed retry);
* an identity longer than 256 units is recorded as `sha256:<hex of the full value>` rather than
  truncated — truncation could make two distinct responses share one recorded identity;
* readers deduplicate on response-scoped identities only (`response_id`, `api_request_id`, `uuid`),
  prefixed by field name. Routing-decision and turn identifiers are deliberately **not** accepted
  as response identity: they can cover more than one billed call.

Readers that must apply this rule: `governor.parse_telemetry_session`, `governor._session_total_tokens`
(the budget gate) and `telemetry.session_usage`.

Two gaps are recorded here rather than assumed away:

1. Cross-*field* equivalence is deliberately not attempted. An identity is `field:value`, so the
   same billable response observed once under `response_id` (Prime) and once under `api_request_id`
   (Hermes) counts twice. Merging the two id spaces would be a guess about host semantics, and a
   wrong guess drops a bill, so the gap is recorded instead. Note that Hermes records *are*
   identifiable: the usage allowlist (`hermes_adapter.py:_bounded_invocation_value`) filters nested
   usage keys, but `api_request_id` is carried at the record's top level and is accepted here. What
   remains unproven is whether those two names ever describe the same billable response.
2. Missing or malformed usage remains unknown, on every reader surface:
   - the strict `governor._session_total_tokens` reader raises on absent or
     unidentifiable usage rather than reporting a factual zero;
   - the aggregate reader `governor.parse_telemetry_session` leaves a counter
     the host never reported as `None` (`SessionTokens.input_tokens` etc.),
     keeps an explicit host `0` as `0`, and exposes coverage through
     `token_usage_seen` (observations that reported at least one counter) and
     `model_turns`; `attribute_roles` counts a session with an unknown total in
     `*_unknown_token_sessions` instead of adding a zero;
   - `brainctl governor report` prints `null` in JSON and `-` in the table for
     an unknown counter, never a fabricated `0`.
   No native task admission or agent-spend cap is advertised by this
   accounting path.

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
  prefix: messages preceding the FIRST user message (the stable system
  section; the whole messages array when no user message exists);
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

## Historical registry vocabulary and retained P4 operations

The Python registry accepts the following old and current kinds so archived
JSONL remains readable. Inclusion does not imply a current producer or any
execution authority. New runtime producers are the retained memory, context,
usage and maintenance events described above:

| kind | version | kind | version |
|---|---:|---|---:|
| OMP_SECOND_BRAIN_READY | 3 | active_state_delivery | 2 |
| agent_end | 2 | assistant_usage | 3 |
| autoinject_shadow_decision | 2 | before_agent_start | 2 |
| brain_no_injection | 2 | brain_packet_delivered | 2 |
| brain_retrieval_attempt | 2 | claude_code_stop_turn | 2 |
| codex_hook_shadow_decision | 2 | context | 2 |
| context_paging | 2 | context_structure | 2 |
| extension_error | 2 | hermes_model_decision | 2 |
| hermes_post_tool_call | 2 | hermes_pre_llm_call | 2 |
| hermes_session_finalized | 2 | hermes_session_started | 2 |
| hermes_worker_context_resolved | 2 | hermes_worker_lifecycle | 2 |
| hermes_worker_result_corrected | 2 | hermes_worker_result_correction_requested | 2 |
| hermes_worker_result_reviewed | 2 | hermes_writeback_candidate | 2 |
| lean_kernel | 2 | model_fallback_used | 2 |
| model_invocation_completed | 2 | model_invocation_failed | 2 |
| model_invocation_started | 2 | model_routing_decision | 2 |
| omp_routing_decision | 3 | omp_routing_handoff_failure | 3 |
| omp_routing_invocation | 3 | omp_routing_response | 3 |
| omp_visibility_plan | 3 | omp_worker_child_result | 3 |
| omp_worker_context_failure | 3 | omp_worker_context_handoff | 3 |
| orchestration_record | 2 | orchestrator_policy_violation | 2 |
| preinvocation | 2 | preinvocation_no_task | 2 |
| prime_tool_surface | 2 | provider_request_meta | 3 |
| provider_response_meta | 3 | quiet_skip | 2 |
| rtd_shadow | 2 | session_before_compact | 2 |
| session_compact | 2 | session_finalized | 2 |
| session_shutdown | 2 | session_start | 2 |
| session_started | 2 | simplification_review | 2 |
| stop_allowed | 2 |  |  |
| stop_blocked | 2 | stop_blocked_result | 2 |
| stop_boundary | 2 | stop_continue | 2 |
| stop_control_result | 2 | stop_finalization_error | 2 |
| stop_finalized | 2 | stop_not_triggered | 2 |
| tool_call | 2 | tool_result | 2 |
| turn_end | 2 | turn_start | 2 |
| vmem_compact_prep | 2 | vmem_fault_in | 2 |
| vmem_hot_context | 2 | writeback_candidate | 2 |
| heartbeat_pulse | 2 | bottleneck_fingerprint | 2 |
| optimization_proposal | 2 | optimization_evaluation | 2 |
| optimization_activation | 2 | optimization_rollback | 2 |

P4 field contracts are bounded and metadata-only:

- `heartbeat_pulse`: `mode`, `event`, `due`, `ran`, `healthy`, `db_ok`,
  `cache_pruned_count`, `git_dirty`, `issue_codes`, `latency_ms`,
  `model_tokens_used` (which must equal zero).
  `artifacts_gc_count` is an additive non-negative integer measurement when
  present; older version-2 producers are not required to supply it.
- `bottleneck_fingerprint`: `fingerprint_id`, `category`, `scope_id`,
  `occurrence_count`, `impact_score`, `evidence_count`, `evidence_hash`.
- `optimization_*`: `proposal_id`, `status`, `intervention_hash`,
  `evidence_hash`, `approval_state`, `rollback_state`.

P4 telemetry has no content or payload fields. Prompts, tool I/O, secrets, and
chain-of-thought are never admitted. Missing provider economics remain
missing; absent token counters are not rewritten as zero, and null provider
values are preserved.
