/**
 * Pure sensors: event -> telemetry record.
 *
 * No fs, no process, no randomness — only data transformation, so Vitest can
 * test every mapping without a Prime runtime.
 *
 * Privacy (constitution/security-boundaries.md): never store message content,
 * prompts, tool I/O payloads, or chain-of-thought. Only counts, sizes,
 * hashes, error flags, tool names, and (for `bash` only) the command text
 * truncated to 500 chars.
 *
 * Schema: brainstem/telemetry/SCHEMA.md (v=2). Field names are snake_case.
 */
import { createHash } from "node:crypto";
import type { AgentRole } from "./driver-orchestrator";

/** Maximum length of stored bash command text (privacy rule). */
export const BASH_COMMAND_MAX_CHARS = 500;

/** Maximum length of stored error text. */
export const ERROR_MAX_CHARS = 500;

/** UTF-8 byte length of a string (TextEncoder is a global in Node 18+). */
export function byteLength(value: unknown): number {
  const text =
    typeof value === "string"
      ? value
      : safeJson(value);
  return new TextEncoder().encode(text).length;
}

/** JSON.stringify that never throws (returns "<unserializable>" on failure). */
export function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return "<unserializable>";
  }
}

/** Truncate a string to at most `max` characters. */
export function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max);
}

/**
 * Content measurement (Phase 3, corrected).
 *
 * One serialization attempt yields both metrics downstream, so RTD and
 * telemetry never serialize the same tool result twice:
 *
 * - `serializedChars`: legacy RTD metric — `JSON.stringify(content).length`
 *   (character length, including quotes/escaping; 0 when not serializable OR
 *   when the RTD char metric was not requested). Threshold decisions keep
 *   their historical semantics for Unicode, escaping, and boundary values.
 * - `outputBytes`: existing telemetry metric — UTF-8 bytes of the raw string
 *   for string content, UTF-8 bytes of the JSON serialization for anything
 *   else, with the current `<unserializable>` fallback (matches `byteLength`).
 *
 * `includeSerializedChars=false` requests the base-telemetry measurement
 * ONLY (ineligible tool results): primitive strings are measured with one
 * TextEncoder and ZERO JSON.stringify (no RTD-specific work); non-strings
 * keep exactly the single serialization/fallback that base telemetry already
 * required, and `serializedChars` is reported as 0.
 */
export interface ContentMeasurement {
  serializedChars: number;
  outputBytes: number;
}

/** Measure content exactly once; never throws. */
export function measureContent(content: unknown, includeSerializedChars = true): ContentMeasurement {
  if (!includeSerializedChars) {
    // Base telemetry only: no RTD serialization work at all.
    if (typeof content === "string") {
      return { serializedChars: 0, outputBytes: new TextEncoder().encode(content).length };
    }
    // Non-strings: the single serialization/fallback base telemetry already
    // required (byteLength semantics) — never an extra RTD path.
    let serialized: unknown;
    try {
      serialized = JSON.stringify(content);
    } catch {
      serialized = "<unserializable>";
    }
    return { serializedChars: 0, outputBytes: new TextEncoder().encode(serialized as string).length };
  }
  let serialized: unknown;
  let serializationFailed = false;
  try {
    serialized = JSON.stringify(content);
  } catch {
    serializationFailed = true;
    serialized = "<unserializable>";
  }
  const serializedChars = serializationFailed || typeof serialized !== "string" ? 0 : serialized.length;
  const text = typeof content === "string" ? content : serialized;
  return {
    serializedChars,
    outputBytes: new TextEncoder().encode(text as string).length,
  };
}

/** Common record fields (v, ts, kind, session). v=2 for pre-P3 kinds; v=3 for P3-B economics kinds (SCHEMA.md). */
export interface BaseRecord {
  v: 2 | 3;
  ts: string;
  kind: string;
  session: string;
}

function base(kind: string, session: string, extra: Record<string, unknown>): Record<string, unknown> {
  return {
    v: 2 as const,
    ts: new Date().toISOString(),
    kind,
    session,
    ...extra,
  };
}

/** v3 record base (P3-B economics kinds; additive schema version, SCHEMA.md). */
function baseV3(kind: string, session: string, extra: Record<string, unknown>): Record<string, unknown> {
  return {
    v: 3 as const,
    ts: new Date().toISOString(),
    kind,
    session,
    ...extra,
  };
}

/** Serialize a runtime model object as "provider/id". */
export function modelToString(model: unknown): string | null {
  if (model == null) return null;
  if (typeof model === "string") return model;
  const m = model as { id?: unknown; provider?: unknown };
  if (typeof m.id !== "string" || m.id.length === 0) return null;
  if (typeof m.provider === "string" && m.provider.length > 0) {
    return `${m.provider}/${m.id}`;
  }
  return m.id;
}

/** Map runtime context usage to schema shape {used,total,percent} or null. */
export function contextUsageToRecord(
  usage: { tokens: number | null; contextWindow: number; percent: number | null } | null | undefined,
): { used: number | null; total: number; percent: number | null } | null {
  if (usage == null) return null;
  return { used: usage.tokens, total: usage.contextWindow, percent: usage.percent };
}

/**
 * Redact credential-like values from a bash command (SEC-08 / INV-10).
 *
 * Runs BEFORE length truncation so a secret that straddles the truncation
 * boundary can never persist a partial value. Covers quoted `-H`/`--header`
 * payloads, Authorization/Bearer headers, `key=value` and `--flag value`
 * credential assignments (case-insensitive), common vendor environment
 * variables, and long credential-shaped tokens. Non-secret command
 * arguments are preserved so telemetry stays useful.
 */
export function redactSensitiveCommand(command: string): string {
  let text = command;

  // 1. Quoted header payloads that look sensitive: -H "Authorization: ..."
  text = text.replace(
    /(\s(?:-H|--header)\s+)(["'])([^"']*)\2/gi,
    (match: string, prefix: string, _quote: string, payload: string) =>
      /(?:authorization|bearer|api[-_]?key|token|password|passwd|secret|auth)/i.test(payload)
        ? `${prefix}"[REDACTED]"`
        : match,
  );

  // 2. Authorization header assignments: Authorization: Bearer SECRET
  text = text.replace(
    /(\b(?:authorization|proxy-authorization)\b\s*[:=]\s*(?:bearer\s+)?)(["']?)([^\s"']+)\2/gi,
    (_match: string, prefix: string) => `${prefix}[REDACTED]`,
  );

  // 3. Bare Bearer tokens: Bearer SECRET
  text = text.replace(
    /(\bBearer\s+)([A-Za-z0-9._~+\/=-]+)/g,
    (_match: string, prefix: string) => `${prefix}[REDACTED]`,
  );

  // 4. Exact secret-key assignments (any case): token=SECRET, api_key=SECRET
  text = text.replace(
    /(\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?key|client[_-]?secret|password|passwd|secret|token)\b\s*=\s*)(["']?)([^\s"']+)\2/gi,
    (_match: string, prefix: string) => `${prefix}[REDACTED]`,
  );

  // 5. Environment-style keys: OPENAI_API_KEY=SECRET, *_TOKEN=..., *_SECRET=...
  text = text.replace(
    /(\b[A-Za-z0-9]+_(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|TOKEN|SECRET|SECRET_ACCESS_KEY|PASSWORD|PASSWD|AUTH)\b\s*=\s*)(["']?)([^\s"']+)\2/gi,
    (_match: string, prefix: string) => `${prefix}[REDACTED]`,
  );

  // 6. CLI flags with a separate or inline value: --token SECRET, --token=SECRET
  text = text.replace(
    /(\s--(?:token|password|passwd|secret|api-key|apikey|api_key|access-token|refresh-token|auth-token|client-secret)\b)(\s*=\s*|\s+)(["']?)([^\s"']+)\3/gi,
    (_match: string, flag: string, separator: string) => `${flag}${separator}[REDACTED]`,
  );

  // 7. Credential-shaped tokens (conservative, long random-looking values).
  text = text.replace(
    /\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}\b|\bAKIA[0-9A-Z]{16}\b/g,
    "[REDACTED]",
  );

  // 8. Private key blocks.
  text = text.replace(
    /-----BEGIN [A-Z ]*PRIVATE KEY-----([\s\S]*?)-----END [A-Z ]*PRIVATE KEY-----/g,
    "[REDACTED]",
  );

  return text;
}

/**
 * Bash command text from a tool_call input: redacted FIRST, then truncated
 * to 500 chars (INV-10). Returns undefined for non-bash tools or
 * missing/empty command.
 */
export function bashCommand(input: Record<string, unknown>): string | undefined {
  if (input == null || typeof input !== "object") return undefined;
  const command = input.command;
  if (typeof command !== "string" || command.length === 0) return undefined;
  return truncate(redactSensitiveCommand(command), BASH_COMMAND_MAX_CHARS);
}

// ---------------------------------------------------------------------------
// Kind sensors. Each returns a full record with the schema's extra fields.
// ---------------------------------------------------------------------------

export interface SessionStartRecord extends BaseRecord {
  kind: "session_start";
  reason: string;
  cwd: string;
  model: string | null;
}

export function sessionStart(
  session: string,
  reason: string,
  cwd: string,
  model: unknown,
): SessionStartRecord {
  return base("session_start", session, {
    reason: typeof reason === "string" ? reason : String(reason),
    cwd,
    model: modelToString(model),
  }) as unknown as SessionStartRecord;
}

export interface BeforeAgentStartRecord extends BaseRecord {
  kind: "before_agent_start";
  prompt_chars: number;
  /**
   * Agent role of the active model for this session: hard_orchestrator |
   * driver | worker | normal (additive, schema v2; absent when not provided).
   */
  role?: AgentRole;
  /**
   * Driver role only: whether the driver-orchestration contract was appended
   * to the system prompt for this turn (additive; present for driver-role
   * sessions, absent otherwise).
   */
  driver_contract_injected?: boolean;
}

export function beforeAgentStart(
  session: string,
  prompt: unknown,
  role?: AgentRole,
  driverContractInjected?: boolean,
): BeforeAgentStartRecord {
  const record = base("before_agent_start", session, {
    prompt_chars: typeof prompt === "string" ? prompt.length : 0,
  }) as unknown as BeforeAgentStartRecord;
  if (role !== undefined) record.role = role;
  if (driverContractInjected !== undefined) record.driver_contract_injected = driverContractInjected;
  return record;
}

export interface TurnStartRecord extends BaseRecord {
  kind: "turn_start";
  turn: number;
}

export function turnStart(session: string, turnIndex: unknown): TurnStartRecord {
  return base("turn_start", session, {
    turn: typeof turnIndex === "number" ? turnIndex : 0,
  }) as unknown as TurnStartRecord;
}

export interface ContextRecord extends BaseRecord {
  kind: "context";
  messages: number;
}

export function context(session: string, messages: unknown): ContextRecord {
  return base("context", session, {
    messages: Array.isArray(messages) ? messages.length : 0,
  }) as unknown as ContextRecord;
}

export interface ToolCallRecord extends BaseRecord {
  kind: "tool_call";
  tool: string;
  id: string;
  /** bash only: command text truncated to 500 chars (privacy rule). */
  command?: string;
  input_bytes: number;
}

export function toolCall(
  session: string,
  toolName: unknown,
  toolCallId: unknown,
  input: Record<string, unknown>,
): ToolCallRecord {
  const name = typeof toolName === "string" ? toolName : "unknown";
  const id = typeof toolCallId === "string" ? toolCallId : "unknown";
  const inputObj = input && typeof input === "object" ? input : {};
  const record: ToolCallRecord = base("tool_call", session, {
    tool: name,
    id,
    input_bytes: byteLength(inputObj),
  }) as unknown as ToolCallRecord;
  if (name === "bash") {
    const command = bashCommand(inputObj);
    if (command !== undefined) record.command = command;
  }
  return record;
}

export interface ToolResultRecord extends BaseRecord {
  kind: "tool_result";
  tool: string;
  id: string;
  is_error: boolean;
  output_bytes: number;
}

/**
 * `outputBytes` is precomputed by the caller via `measureContent` (Phase 3)
 * so the real handler measures each result once and shares the byte count
 * with RTD shadow evaluation/recording.
 */
export function toolResult(
  session: string,
  toolName: unknown,
  toolCallId: unknown,
  isError: unknown,
  outputBytes: number,
): ToolResultRecord {
  return base("tool_result", session, {
    tool: typeof toolName === "string" ? toolName : "unknown",
    id: typeof toolCallId === "string" ? toolCallId : "unknown",
    is_error: isError === true,
    output_bytes: outputBytes,
  }) as unknown as ToolResultRecord;
}

export interface TurnEndRecord extends BaseRecord {
  kind: "turn_end";
  turn: number;
  context_usage: { used: number | null; total: number; percent: number | null } | null;
  tool_results: number;
}

export function turnEnd(
  session: string,
  turnIndex: unknown,
  usage: { tokens: number | null; contextWindow: number; percent: number | null } | null | undefined,
  toolResults: unknown,
): TurnEndRecord {
  return base("turn_end", session, {
    turn: typeof turnIndex === "number" ? turnIndex : 0,
    context_usage: contextUsageToRecord(usage),
    tool_results: Array.isArray(toolResults) ? toolResults.length : 0,
  }) as unknown as TurnEndRecord;
}

export interface AgentEndRecord extends BaseRecord {
  kind: "agent_end";
  messages: number;
}

export function agentEnd(session: string, messages: unknown): AgentEndRecord {
  return base("agent_end", session, {
    messages: Array.isArray(messages) ? messages.length : 0,
  }) as unknown as AgentEndRecord;
}

export interface SessionBeforeCompactRecord extends BaseRecord {
  kind: "session_before_compact";
  branch_entries: number;
}

export function sessionBeforeCompact(session: string, branchEntries: unknown): SessionBeforeCompactRecord {
  return base("session_before_compact", session, {
    branch_entries: Array.isArray(branchEntries) ? branchEntries.length : 0,
  }) as unknown as SessionBeforeCompactRecord;
}

export interface SessionCompactRecord extends BaseRecord {
  kind: "session_compact";
  from_extension: boolean;
}

export function sessionCompact(session: string, fromExtension: unknown): SessionCompactRecord {
  return base("session_compact", session, {
    from_extension: fromExtension === true,
  }) as unknown as SessionCompactRecord;
}

export interface PrimeToolSurfaceRecord extends BaseRecord {
  kind: "prime_tool_surface";
  all_tools_count: number | null;
  active_tools_count: number | null;
  all_tools: string[] | null;
  active_tools: string[] | null;
}

/** Phase R6: Prime's real tool surface (getAllTools/getActiveTools), captured
 * once per session_start. Read-only — never used to call setActiveTools in
 * this pass (see outputs/reports/rc4/06-tool-working-set-live.md). */
export function primeToolSurface(
  session: string,
  allTools: string[] | undefined,
  activeTools: string[] | undefined,
): PrimeToolSurfaceRecord {
  return base("prime_tool_surface", session, {
    all_tools_count: allTools ? allTools.length : null,
    active_tools_count: activeTools ? activeTools.length : null,
    all_tools: allTools ?? null,
    active_tools: activeTools ?? null,
  }) as unknown as PrimeToolSurfaceRecord;
}

export interface VmemCompactPrepRecord extends BaseRecord {
  kind: "vmem_compact_prep";
  evicted_at_compaction: number | null;
  pinned_preserved: number | null;
}

/** Phase R3: VMem compact-prep bookkeeping ahead of a real compaction event. */
export function vmemCompactPrep(
  session: string,
  evictedAtCompaction: number | undefined,
  pinnedPreserved: number | undefined,
): VmemCompactPrepRecord {
  return base("vmem_compact_prep", session, {
    evicted_at_compaction: typeof evictedAtCompaction === "number" ? evictedAtCompaction : null,
    pinned_preserved: typeof pinnedPreserved === "number" ? pinnedPreserved : null,
  }) as unknown as VmemCompactPrepRecord;
}

export interface VmemHotContextRecord extends BaseRecord {
  kind: "vmem_hot_context";
  resident_count: number | null;
  evicted_count: number | null;
  resident_tokens: number | null;
}

/** Phase R3: VMem hot-context render after a real compaction event. */
export function vmemHotContext(
  session: string,
  residentCount: number | undefined,
  evictedCount: number | undefined,
  residentTokens: number | undefined,
): VmemHotContextRecord {
  return base("vmem_hot_context", session, {
    resident_count: typeof residentCount === "number" ? residentCount : null,
    evicted_count: typeof evictedCount === "number" ? evictedCount : null,
    resident_tokens: typeof residentTokens === "number" ? residentTokens : null,
  }) as unknown as VmemHotContextRecord;
}

export interface SessionShutdownRecord extends BaseRecord {
  kind: "session_shutdown";
  reason: string;
}

export function sessionShutdown(session: string, reason: unknown): SessionShutdownRecord {
  return base("session_shutdown", session, {
    reason: typeof reason === "string" ? reason : String(reason),
  }) as unknown as SessionShutdownRecord;
}

/** Enumerated Sol orchestrator-policy violation codes (policy §13). */
export const ORCHESTRATOR_VIOLATIONS = [
  "direct_execution",
  "undue_context_gather",
  "concurrency_overflow",
  "wrong_tier",
  "rediscovery",
  "scope_drift",
  "evidence_gap",
] as const;

/** Enumerated detector identities for orchestrator violations. */
export const ORCHESTRATOR_DETECTORS = ["manual", "runtime_guard", "telemetry_audit"] as const;

export interface OrchestratorPolicyViolationRecord extends BaseRecord {
  kind: "orchestrator_policy_violation";
  /** Enumerated code; unknown values are coerced to "unknown", never free text. */
  violation: string;
  /** Provider/id string or null (see modelToString). */
  model: string | null;
  /** Enumerated detector id; unknown values are coerced to "unknown". */
  detected_by: string;
  /** Whether the action was blocked (hard enforcement) or only recorded (advisory). */
  blocked: boolean;
}

/**
 * Privacy-safe, report-only builder for orchestrator-policy violations.
 *
 * BOUNDED FIELDS ONLY: enumerated violation code, model id, enumerated
 * detector, blocked flag. No free text (no action description, prompt,
 * command, note, reason, or payload) ever enters the record.
 *
 * NOT WIRED: this sensor is available for manual/future use; no extension
 * hook emits it today and no automatic prompt inspection is performed.
 */
export function orchestratorPolicyViolation(
  session: string,
  violation: unknown,
  model: unknown,
  detectedBy: unknown,
  blocked: unknown,
): OrchestratorPolicyViolationRecord {
  const violationValue =
    typeof violation === "string" && (ORCHESTRATOR_VIOLATIONS as readonly string[]).includes(violation)
      ? violation
      : "unknown";
  const detector =
    typeof detectedBy === "string" && (ORCHESTRATOR_DETECTORS as readonly string[]).includes(detectedBy)
      ? detectedBy
      : "unknown";
  return base("orchestrator_policy_violation", session, {
    violation: violationValue,
    model: modelToString(model),
    detected_by: detector,
    blocked: blocked === true,
  }) as unknown as OrchestratorPolicyViolationRecord;
}

export interface ExtensionErrorRecord extends BaseRecord {
  kind: "extension_error";
  error: string;
}

export function extensionError(session: string, error: unknown): ExtensionErrorRecord {
  const message = error instanceof Error ? error.message : String(error);
  return base("extension_error", session, {
    error: truncate(message, ERROR_MAX_CHARS),
  }) as unknown as ExtensionErrorRecord;
}


// ---------------------------------------------------------------------------
// Phase 0C: P0 AutoInject SHADOW decision record (plan §6.12, SCHEMA.md).
// Privacy-safe: decision/reason/tokens/latency/counts/ids/hash only — never
// task text or packet content.
// ---------------------------------------------------------------------------

export interface AutoInjectShadowDecisionRecord extends BaseRecord {
  kind: "autoinject_shadow_decision";
  decision: string | null;
  reason: string | null;
  packet_tokens: number | null;
  latency_ms: number;
  candidate_count: number;
  selected_count: number;
  delivery_id: string | null;
  packet_sha256: string | null;
  /** Resolved host mode at decision time (Phase C4 instrumentation). */
  mode: string | null;
  /** True when this decision path is the model-visible custom-message
   * injection path (advisory/active); false for shadow (decide+record only,
   * never model-visible). Unambiguous visibility marker (SCHEMA.md). */
  model_visible: boolean;
  /** True when the advisory/active path returned a custom_message patch. */
  result_patch: boolean;
  /** Emit ordinal for this (session, task) key (1 = the spawning emit). */
  emit_index: number;
  /** True when served from the emit cache (no new spawn). */
  cache_hit: boolean;
  /** True when this run actually returned the custom_message patch. */
  handler_returned_message: boolean;
  /** Length of the parsed packet text (null when no packet). */
  cli_packet_chars: number | null;
  /** Length of the raw CLI stdout that was parsed. */
  cli_stdout_chars: number;
}

export function autoinjectShadowDecision(
  session: string,
  fields: {
    decision: string | null;
    reason: string | null;
    packet_tokens: number | null;
    latency_ms: number;
    candidate_count: number;
    selected_count: number;
    delivery_id: string | null;
    packet_sha256: string | null;
    mode: string | null;
    model_visible: boolean;
    result_patch: boolean;
    emit_index: number;
    cache_hit: boolean;
    handler_returned_message: boolean;
    cli_packet_chars: number | null;
    cli_stdout_chars: number;
  },
): AutoInjectShadowDecisionRecord {
  return {
    ...base("autoinject_shadow_decision", session, {}),
    decision: fields.decision,
    reason: fields.reason,
    packet_tokens: fields.packet_tokens,
    latency_ms: fields.latency_ms,
    candidate_count: fields.candidate_count,
    selected_count: fields.selected_count,
    delivery_id: fields.delivery_id,
    packet_sha256: fields.packet_sha256,
    mode: fields.mode,
    model_visible: fields.model_visible,
    result_patch: fields.result_patch,
    emit_index: fields.emit_index,
    cache_hit: fields.cache_hit,
    handler_returned_message: fields.handler_returned_message,
    cli_packet_chars: fields.cli_packet_chars,
    cli_stdout_chars: fields.cli_stdout_chars,
  } as unknown as AutoInjectShadowDecisionRecord;
}

// ---------------------------------------------------------------------------
// P3-D lean runtime adapter sensor (plan §8, SCHEMA.md `lean_kernel`).
// Privacy-safe: enumerated decisions/reasons/roles/status + mode value +
// character counts only — never kernel text or prompt content.
// ---------------------------------------------------------------------------

export interface LeanKernelRecord extends BaseRecord {
  kind: "lean_kernel";
  /** inject = kernel patch produced; omit = no patch. */
  decision: "inject" | "omit";
  /** Enumerated: active | advisory | off | role | skill-missing. */
  reason: "active" | "advisory" | "off" | "role" | "skill-missing";
  /** Agent role at decision time (driver-orchestration vocabulary). */
  role: string;
  /** Resolved skill lifecycle status (null when the file is missing). */
  skill_status: string | null;
  /** Resolved eval gate value (env advisory/off, else file [lean] eval) or null. */
  mode: string | null;
  /** Where the resolved mode came from: "env" | "file" | null. */
  eval_source: "env" | "file" | null;
  /** Character length of the canonical kernel section (0 when unavailable). */
  kernel_chars: number;
  /** True when the base prompt already carried the marker (no re-injection). */
  dedup_hit: boolean;
}

export function leanKernel(
  session: string,
  fields: {
    decision: "inject" | "omit";
    reason: "active" | "advisory" | "off" | "role" | "skill-missing";
    role: string;
    skill_status: string | null;
    mode: string | null;
    eval_source: "env" | "file" | null;
    kernel_chars: number;
    dedup_hit: boolean;
  },
): LeanKernelRecord {
  return {
    ...base("lean_kernel", session, {}),
    decision: fields.decision,
    reason: fields.reason,
    role: fields.role,
    skill_status: fields.skill_status,
    mode: fields.mode,
    eval_source: fields.eval_source,
    kernel_chars: fields.kernel_chars,
    dedup_hit: fields.dedup_hit,
  } as unknown as LeanKernelRecord;
}

// ---------------------------------------------------------------------------
// P3-B economics sensors (plan §5.1/§5.4/§5.5; schema v3, SCHEMA.md).
// Privacy (plan §25): counts, sizes, keys, and sha256 hashes ONLY — never
// prompt text, source/tool output, provider payloads, auth data, or raw
// header values.
// ---------------------------------------------------------------------------

/** sha256 hex digest (privacy: only the hash ever leaves this module). */
export function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** JSON serialization that never throws; undefined when not serializable. */
function stableJson(value: unknown): string | undefined {
  try {
    const text = JSON.stringify(value);
    return typeof text === "string" ? text : undefined;
  } catch {
    return undefined;
  }
}

/** True when a provider-payload message has role "user". */
function isUserMessage(message: unknown): boolean {
  if (message == null || typeof message !== "object") return false;
  return (message as { role?: unknown }).role === "user";
}

/** Split a "provider/id" model string into its parts (null-safe). */
export function splitProviderModel(value: string | null): {
  provider: string | null;
  model: string | null;
} {
  if (value == null) return { provider: null, model: null };
  const slash = value.indexOf("/");
  if (slash > 0) return { provider: value.slice(0, slash), model: value.slice(slash + 1) };
  return { provider: null, model: value };
}

/** Numeric usage counter when the host reported one; undefined otherwise
 * (zero vs missing preserved — never invent values). */
function usageCounter(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

export interface AssistantUsageRecord extends BaseRecord {
  v: 3;
  kind: "assistant_usage";
  provider: string | null;
  model: string | null;
  /** Each counter present ONLY when the host reported it (zero preserved). */
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  total_tokens?: number;
  cost_total?: number;
}

/**
 * Per-assistant-message provider usage (plan §5.1, message_end). Uses the
 * EXACT host values; absent counters are omitted, zeros are preserved.
 * Returns null when the host exposed no usage object (no record emitted).
 */
export function assistantUsage(
  session: string,
  provider: string | null,
  model: string | null,
  usage: unknown,
): AssistantUsageRecord | null {
  if (usage == null || typeof usage !== "object") return null;
  const u = usage as Record<string, unknown>;
  const extra: Record<string, unknown> = { provider, model };
  const input = usageCounter(u.input);
  if (input !== undefined) extra.input_tokens = input;
  const output = usageCounter(u.output);
  if (output !== undefined) extra.output_tokens = output;
  const cacheRead = usageCounter(u.cacheRead);
  if (cacheRead !== undefined) extra.cache_read_tokens = cacheRead;
  const cacheWrite = usageCounter(u.cacheWrite);
  if (cacheWrite !== undefined) extra.cache_write_tokens = cacheWrite;
  const total = usageCounter(u.totalTokens);
  if (total !== undefined) extra.total_tokens = total;
  if (u.cost != null && typeof u.cost === "object") {
    const costTotal = usageCounter((u.cost as Record<string, unknown>).total);
    if (costTotal !== undefined) extra.cost_total = costTotal;
  }
  return baseV3("assistant_usage", session, extra) as unknown as AssistantUsageRecord;
}

export interface ProviderRequestMetaRecord extends BaseRecord {
  v: 3;
  kind: "provider_request_meta";
  provider: string | null;
  model: string | null;
  request_seq: number;
  request_bytes: number;
  message_count: number;
  payload_keys: string[];
  /** sha256 of the stable prefix (messages before the last user message). */
  system_prefix_sha?: string;
  /** sha256 of the serialized tool surface; absent when the payload has no tools. */
  tool_surface_sha?: string;
}

/**
 * Provider-request fingerprint (plan §5.4): metadata only — top-level payload
 * keys (sorted), serialized byte size, message count, and sha256 fingerprints
 * of the stable system/messages prefix and the tool surface. NEVER the
 * payload content itself.
 *
 * `system_prefix_sha` = sha256 of the JSON serialization of the messages
 * preceding the LAST user message (the stable provider-cache prefix); when
 * there is no user message the whole messages array is fingerprinted. This
 * detects stable-prefix epochs busted by system-prompt/tool-schema changes.
 */
export function providerRequestMeta(
  session: string,
  provider: string | null,
  model: string | null,
  requestSeq: number,
  payload: unknown,
): ProviderRequestMetaRecord {
  const obj =
    payload != null && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const keys = Object.keys(obj).sort();
  const messages = Array.isArray(obj.messages) ? (obj.messages as unknown[]) : [];
  const extra: Record<string, unknown> = {
    provider,
    model,
    request_seq: requestSeq,
    request_bytes: byteLength(obj),
    message_count: messages.length,
    payload_keys: keys,
  };
  let prefix = messages;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (isUserMessage(messages[i])) {
      prefix = messages.slice(0, i);
      break;
    }
  }
  const prefixJson = stableJson(prefix);
  if (prefixJson !== undefined) extra.system_prefix_sha = sha256Hex(prefixJson);
  if (obj.tools !== undefined) {
    const toolsJson = stableJson(obj.tools);
    if (toolsJson !== undefined) extra.tool_surface_sha = sha256Hex(toolsJson);
  }
  return baseV3("provider_request_meta", session, extra) as unknown as ProviderRequestMetaRecord;
}

/** Header entries permitted into telemetry: cache/rate-limit diagnostics only. */
export const RESPONSE_HEADER_ALLOWLIST: readonly RegExp[] = [
  /^x-ratelimit-/i,
  /^ratelimit-/i,
  /^rate-limit/i,
  /^x-cache/i,
  /^cache-control$/i,
  /^cf-cache-status$/i,
  /^retry-after$/i,
];

export interface ResponseHeaderMeta {
  key: string;
  value_sha256: string;
}

export interface ProviderResponseMetaRecord extends BaseRecord {
  v: 3;
  kind: "provider_response_meta";
  provider: string | null;
  model: string | null;
  /** Present only when the host reported a numeric status. */
  status?: number;
  /** Present only when at least one allowlisted header was found. */
  headers?: ResponseHeaderMeta[];
}

/**
 * Provider-response metadata (plan §5.5): status plus ONLY known
 * cache/rate-limit diagnostic header KEYS with sha256-hashed values. Never
 * depends on a specific header existing; unrelated headers are never stored.
 */
export function providerResponseMeta(
  session: string,
  provider: string | null,
  model: string | null,
  status: unknown,
  headers: unknown,
): ProviderResponseMetaRecord {
  const extra: Record<string, unknown> = { provider, model };
  if (typeof status === "number") extra.status = status;
  const headerEntries: ResponseHeaderMeta[] = [];
  if (headers != null && typeof headers === "object") {
    for (const [key, value] of Object.entries(headers as Record<string, unknown>)) {
      if (typeof value !== "string") continue;
      if (!RESPONSE_HEADER_ALLOWLIST.some((re) => re.test(key))) continue;
      headerEntries.push({ key: key.toLowerCase(), value_sha256: sha256Hex(value) });
    }
  }
  if (headerEntries.length > 0) extra.headers = headerEntries;
  return baseV3("provider_response_meta", session, extra) as unknown as ProviderResponseMetaRecord;
}
