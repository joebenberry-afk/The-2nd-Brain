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

/**
 * Count-only, never-throws occurrence counter for an exact literal
 * substring in an already-serialized string. RC4 CVM closure repair:
 * `providerRequestMeta` reuses this against the SAME serialized payload
 * string it already computes `request_bytes` from — counts only, the
 * marker text and surrounding content are never stored or logged.
 */
export function countOccurrences(haystack: string, marker: string): number {
  if (marker.length === 0) return 0;
  try {
    return haystack.split(marker).length - 1;
  } catch {
    return 0;
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

export interface ContextPagingRecord extends BaseRecord {
  kind: "context_paging";
  paged_count: number;
  // Defect B (RC4 proactive-paging-repair pass) additive fields — counts/
  // kinds/state-labels/local deterministic estimates only, NEVER content,
  // NEVER an obj_id/delivery_id/tool_call_id. null when not supplied
  // (matches every other additive-field sensor in this file).
  candidate_count: number | null;
  eligible_count: number | null;
  pressure_estimated_tokens: number | null;
  resident_budget: number | null;
  requested_page_count: number | null;
  claimed_page_count: number | null;
  // RC4 CVM closure repair (Repair B) additive fields: `newly_claimed_count`
  // is Path A's real state-transition count (the SAME real count
  // `claimed_page_count` already meant); `reprojected_page_count` is Path
  // B's already-EVICTED, zero-DB-write pointerization count this event.
  // `paged_count` above continues to mean "total replacements this event"
  // = newly_claimed_count + reprojected_page_count.
  newly_claimed_count: number | null;
  reprojected_page_count: number | null;
  estimated_tokens_before: number | null;
  estimated_tokens_after: number | null;
  estimated_tokens_removed: number | null;
  object_kinds: string[] | null;
  state_before: string[] | null;
  state_after: string[] | null;
}

/** Defect B additive detail (context-paging.ts `PageContextResult`'s
 * telemetry fields, camelCase source -> snake_case record). */
export interface ContextPagingDetails {
  candidateCount?: number;
  eligibleCount?: number;
  pressureEstimatedTokens?: number;
  residentBudget?: number;
  requestedPageCount?: number;
  claimedPageCount?: number;
  newlyClaimedCount?: number;
  reprojectedPageCount?: number;
  estimatedTokensBefore?: number;
  estimatedTokensAfter?: number;
  objectKinds?: string[];
  stateBefore?: string[];
  stateAfter?: string[];
}

/** Part B/E (extended by the Defect B proactive-paging-repair pass):
 * privacy-safe telemetry for a successful paging patch. `details` is
 * OPTIONAL and additive — omitting it (existing call shape) still records
 * `paged_count` exactly as before. Appended ONLY when `pageContext`
 * actually returned a patch (zero-mutation calls append nothing here,
 * matching context_structure's additive-only convention). Object kinds and
 * residency-state labels are short recognized tokens only (`recognizedToken`
 * — same privacy discipline as `vmemFaultIn`'s `obj_kind`); estimated token
 * counts are the SAME local ~4-chars/token estimate already used for the
 * resident_token_budget check — never a real provider usage figure, and
 * never presented as a savings claim (see `estimated_tokens_removed`,
 * simply `before - after` for the elements actually paged). No obj_id/
 * delivery_id/tool_call_id/content ever appears here. */
export function contextPaging(
  session: string,
  pagedCount: unknown,
  details?: ContextPagingDetails,
): ContextPagingRecord {
  const before = details?.estimatedTokensBefore;
  const after = details?.estimatedTokensAfter;
  const removed =
    typeof before === "number" && typeof after === "number" ? Math.max(0, before - after) : null;
  const tokens = (values: unknown): string[] | null =>
    Array.isArray(values)
      ? values.map((v) => recognizedToken(v)).filter((v): v is string => v !== null)
      : null;
  return base("context_paging", session, {
    paged_count: typeof pagedCount === "number" ? pagedCount : 0,
    candidate_count: typeof details?.candidateCount === "number" ? details.candidateCount : null,
    eligible_count: typeof details?.eligibleCount === "number" ? details.eligibleCount : null,
    pressure_estimated_tokens:
      typeof details?.pressureEstimatedTokens === "number" ? details.pressureEstimatedTokens : null,
    resident_budget: typeof details?.residentBudget === "number" ? details.residentBudget : null,
    requested_page_count:
      typeof details?.requestedPageCount === "number" ? details.requestedPageCount : null,
    claimed_page_count:
      typeof details?.claimedPageCount === "number" ? details.claimedPageCount : null,
    newly_claimed_count:
      typeof details?.newlyClaimedCount === "number" ? details.newlyClaimedCount : null,
    reprojected_page_count:
      typeof details?.reprojectedPageCount === "number" ? details.reprojectedPageCount : null,
    estimated_tokens_before: typeof before === "number" ? before : null,
    estimated_tokens_after: typeof after === "number" ? after : null,
    estimated_tokens_removed: removed,
    object_kinds: tokens(details?.objectKinds),
    state_before: tokens(details?.stateBefore),
    state_after: tokens(details?.stateAfter),
  }) as unknown as ContextPagingRecord;
}

// ---------------------------------------------------------------------------
// [context_structure] structural telemetry (privacy-safe schema capture,
// gated by config/context.toml [context_structure] enabled=false by
// default). Learns the real per-element SHAPE of Prime's `context` event
// `messages` array WITHOUT ever storing prompt/tool text. Pilot 1
// (outputs/reports/rc4/11-real-prime-pilot.md) confirmed `event.messages`
// is a real Array but deliberately never captured the per-element shape.
//
// Privacy: only JS value types, an object's OWN top-level key NAMES
// (Object.keys, never values), a short recognized role/kind TOKEN (never an
// arbitrary string), and sizes/lengths ever leave this module. See
// `RECOGNIZED_TOKEN_RE` below for the enum-like shape a role/kind token
// must match; anything else is omitted, never stored verbatim.
// ---------------------------------------------------------------------------

/** Short enum-like token shape for role/type/kind fields (never free text). */
export const RECOGNIZED_TOKEN_RE = /^[a-z_]{1,24}$/i;

/** A string value ONLY when it matches the short recognized-token shape. */
function recognizedToken(value: unknown): string | null {
  return typeof value === "string" && RECOGNIZED_TOKEN_RE.test(value) ? value : null;
}

export interface ContextBlockShape {
  /** `.type`/`.kind` field VALUE, only when it is itself a recognized token. */
  kind: string | null;
  /** Size proxy only: JSON.stringify(block).length (never the string itself). */
  length: number;
}

/** Shape (never content) of one content block inside an element's content array. */
function contextBlockShape(block: unknown): ContextBlockShape {
  let length = 0;
  try {
    const serialized = JSON.stringify(block);
    length = typeof serialized === "string" ? serialized.length : 0;
  } catch {
    length = 0;
  }
  let kind: string | null = null;
  if (block !== null && typeof block === "object" && !Array.isArray(block)) {
    const b = block as Record<string, unknown>;
    kind = recognizedToken(b.type) ?? recognizedToken(b.kind);
  }
  return { kind, length };
}

export interface ContextElementShape {
  /** typeof element (e.g. "object", "string", "undefined"). */
  type: string;
  /** Object.keys(element) — key NAMES only, never present for non-plain-objects. */
  keys?: string[];
  /** element.role, only when it is a recognized short token; omitted otherwise. */
  role?: string;
  /** typeof element.content (e.g. "array"/"string"/"object"/"undefined"). */
  content_type: string;
  /** element string length, ONLY when the whole element is a string. */
  length?: number;
  /** content array length, ONLY when element.content is an array. */
  content_length?: number;
  /** Per-block shapes, ONLY when element.content is an array. */
  blocks?: ContextBlockShape[];
}

/** Structural (never content) shape of one `messages[i]` element. */
function contextElementShape(element: unknown): ContextElementShape {
  const type = typeof element;
  if (type === "string") {
    return { type, content_type: "undefined", length: (element as string).length };
  }
  if (element !== null && type === "object" && !Array.isArray(element)) {
    const obj = element as Record<string, unknown>;
    const shape: ContextElementShape = { type, keys: Object.keys(obj), content_type: typeof obj.content };
    const role = recognizedToken(obj.role);
    if (role !== null) shape.role = role;
    if (Array.isArray(obj.content)) {
      shape.content_length = obj.content.length;
      shape.blocks = obj.content.map((block) => contextBlockShape(block));
    }
    return shape;
  }
  return { type, content_type: "undefined" };
}

export interface ContextStructureRecord extends BaseRecord {
  kind: "context_structure";
  count: number;
  elements: ContextElementShape[];
}

/**
 * Structural (privacy-safe) shape of the `context` event's `messages` array.
 * Non-array input safely no-ops to `{count: 0, elements: []}` — same
 * fallback as `context()` above. Never throws, never stores prompt/tool
 * text, thinking text, or any field value beyond a short recognized token
 * or a number.
 */
export function contextStructure(session: string, messages: unknown): ContextStructureRecord {
  const arr = Array.isArray(messages) ? messages : [];
  return base("context_structure", session, {
    count: arr.length,
    elements: arr.map((element) => contextElementShape(element)),
  }) as unknown as ContextStructureRecord;
}

export interface ToolCallRecord extends BaseRecord {
  kind: "tool_call";
  tool: string;
  id: string;
  /** bash only: command text truncated to 500 chars (privacy rule). */
  command?: string;
  /** Hash of a read target; raw paths never enter telemetry. */
  target_sha256?: string;
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
  if (name === "read") {
    const target = inputObj.path ?? inputObj.AbsolutePath ?? inputObj.file;
    if (typeof target === "string" && target.length > 0) {
      record.target_sha256 = createHash("sha256").update(target, "utf8").digest("hex");
    }
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

export interface ActiveStateDeliveryRecord extends BaseRecord {
  kind: "active_state_delivery";
  capsule_sha256: string | null;
  capsule_bytes: number | null;
  rendered_chars: number;
  changed: boolean;
  model_visible: boolean;
}

export function activeStateDelivery(
  session: string,
  capsuleSha256: string | undefined,
  capsuleBytes: number | undefined,
  renderedChars: number,
  changed: boolean,
): ActiveStateDeliveryRecord {
  return base("active_state_delivery", session, {
    capsule_sha256: capsuleSha256 ?? null,
    capsule_bytes: typeof capsuleBytes === "number" ? capsuleBytes : null,
    rendered_chars: renderedChars,
    changed,
    model_visible: true,
  }) as unknown as ActiveStateDeliveryRecord;
}

export interface VmemFaultInRecord extends BaseRecord {
  kind: "vmem_fault_in";
  /** SessionObjectKind (short enum token) or null — never obj_id, never content. */
  obj_kind: string | null;
  /** "memory" | "artifact" | "raw" | null — vmem.resolve_object's resolution path. */
  resolution: string | null;
  ok: boolean;
}

/** Part D: explicit fault-in telemetry (runVmemResolve call sites). Counts/
 * kind/ok only, same privacy-safe style as vmemCompactPrep/vmemHotContext —
 * never the resolved content, obj_id, delivery_id, or artifact_ref. */
export function vmemFaultIn(
  session: string,
  objKind: unknown,
  resolution: unknown,
  ok: unknown,
): VmemFaultInRecord {
  return base("vmem_fault_in", session, {
    obj_kind: recognizedToken(objKind),
    resolution: recognizedToken(resolution),
    ok: ok === true,
  }) as unknown as VmemFaultInRecord;
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
  reason: string;
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
    reason: string;
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
export function usageCounter(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

export interface AssistantUsageRecord extends BaseRecord {
  v: 3;
  kind: "assistant_usage";
  provider: string | null;
  model: string | null;
  /**
   * The host's identity for the response this usage belongs to (`message.responseId`, present on
   * every assistant message in the live transcript). It is what lets an accounting reader
   * recognise a *repeated observation of the same billable request* instead of summing it twice;
   * absent when the host did not report one, which must never be read as "a duplicate".
   */
  response_id?: string;
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
  responseId?: unknown,
): AssistantUsageRecord | null {
  if (usage == null || typeof usage !== "object") return null;
  const u = usage as Record<string, unknown>;
  const extra: Record<string, unknown> = { provider, model };
  if (typeof responseId === "string" && responseId.length > 0) {
    // Bounded without becoming lossy: truncating a long identity could map two distinct host
    // responses onto one recorded identity, and the accounting reader would then drop the second
    // genuinely billed request. A digest of the full value keeps distinct identities distinct.
    extra.response_id =
      responseId.length <= 256
        ? responseId
        : `sha256:${createHash("sha256").update(responseId, "utf8").digest("hex")}`;
  }
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
  /**
   * RC4 CVM closure repair: a COUNT ONLY of the exact literal substring
   * `"[SECOND_BRAIN_VMEM]"` in the already-serialized outgoing payload —
   * proves the live provider request actually contained one or more real
   * VMem pointers, without ever storing the pointer text, surrounding
   * content, or the payload itself. Reuses the SAME serialized string
   * `request_bytes` already computes (no second `JSON.stringify`).
   */
  vmem_pointer_count: number;
  /** Same technique, counting `"[SECOND_BRAIN_RTD]"` occurrences. */
  rtd_pointer_count: number;
  /** Count of the stable Lean marker in the serialized provider payload. */
  lean_kernel_marker_count?: number;
  /** Count of exact canonical Lean kernel strings in provider string fields. */
  lean_kernel_content_count?: number;
  /** Hash of the canonical kernel expected for this session, never its text. */
  lean_kernel_sha256?: string;
  /** Canonical kernel character length expected for this session. */
  lean_kernel_chars?: number;
  /** Bounded non-sensitive path/placement metadata for the marker. */
  lean_kernel_placement?: string;
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
export interface LeanProviderEvidence {
  marker: string;
  kernel?: string;
}

function countValueOccurrences(value: unknown, needle: string, seen = new Set<object>(), depth = 0): number {
  if (depth > 8 || needle.length === 0) return 0;
  if (typeof value === "string") return countOccurrences(value, needle);
  if (value === null || typeof value !== "object") return 0;
  if (seen.has(value)) return 0;
  seen.add(value);
  if (Array.isArray(value)) {
    return value.reduce((total, item) => total + countValueOccurrences(item, needle, seen, depth + 1), 0);
  }
  return Object.values(value).reduce(
    (total, item) => total + countValueOccurrences(item, needle, seen, depth + 1),
    0,
  );
}

function findValuePath(
  value: unknown,
  needle: string,
  path = "$",
  seen = new Set<object>(),
  depth = 0,
): string | undefined {
  if (depth > 8 || needle.length === 0) return undefined;
  if (typeof value === "string") return value.includes(needle) ? path : undefined;
  if (value === null || typeof value !== "object" || seen.has(value)) return undefined;
  seen.add(value);
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findValuePath(value[index], needle, `${path}[${index}]`, seen, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  for (const [key, item] of Object.entries(value)) {
    const found = findValuePath(item, needle, `${path}.${key}`, seen, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

export function providerRequestMeta(
  session: string,
  provider: string | null,
  model: string | null,
  requestSeq: number,
  payload: unknown,
  leanEvidence?: LeanProviderEvidence,
): ProviderRequestMetaRecord {
  const obj =
    payload != null && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const keys = Object.keys(obj).sort();
  const messages = Array.isArray(obj.messages) ? (obj.messages as unknown[]) : [];
  // RC4 CVM closure repair: serialize ONCE, reuse the SAME string for both
  // request_bytes (via byteLength's string branch, which never re-serializes)
  // and the pointer-marker counts below — never a second JSON.stringify of
  // the payload, counts only, never the string itself stored/logged.
  const serializedPayload = safeJson(obj);
  const extra: Record<string, unknown> = {
    provider,
    model,
    request_seq: requestSeq,
    request_bytes: byteLength(serializedPayload),
    message_count: messages.length,
    payload_keys: keys,
    vmem_pointer_count: countOccurrences(serializedPayload, "[SECOND_BRAIN_VMEM]"),
    rtd_pointer_count: countOccurrences(serializedPayload, "[SECOND_BRAIN_RTD]"),
  };
  if (leanEvidence?.marker) {
    const markerCount = countOccurrences(serializedPayload, leanEvidence.marker);
    const contentCount =
      leanEvidence.kernel === undefined
        ? 0
        : countValueOccurrences(obj, leanEvidence.kernel);
    extra.lean_kernel_marker_count = markerCount;
    extra.lean_kernel_content_count = contentCount;
    extra.lean_kernel_chars = leanEvidence.kernel?.length ?? 0;
    extra.lean_kernel_placement =
      markerCount > 0
        ? findValuePath(obj, leanEvidence.marker) ?? "provider_payload"
        : "absent";
    if (leanEvidence.kernel !== undefined) {
      extra.lean_kernel_sha256 = sha256Hex(leanEvidence.kernel);
    }
  }
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

export interface ModelRouteTransitionRecord extends BaseRecord {
  v: 3;
  kind: "MODEL_ROUTE_TRANSITION";
  current_provider: string | null;
  current_model: string | null;
  target_provider: string | null;
  target_model: string | null;
  target_capacity: number;
  cache_scope: string;
  cache_cold: boolean;
  load_before: number;
  load_after: number;
  reclaimed_count?: number;
}

export function modelRouteTransition(
  session: string,
  extra: Omit<ModelRouteTransitionRecord, "v" | "ts" | "kind" | "session">,
): ModelRouteTransitionRecord {
  return baseV3("MODEL_ROUTE_TRANSITION", session, extra as Record<string, unknown>) as unknown as ModelRouteTransitionRecord;
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

// ---------------------------------------------------------------------------
// P4 sensors (Task 7; plan §3 P4, SCHEMA.md). Bounded mirrors of p4-mirror.ts's
// `P4PulseResult` fields. Privacy: enumerated strings, booleans, bounded
// non-negative numbers, 64-hex hashes, and bounded issue-code lists only —
// candidate summaries, proposal bodies, command text, and raw tool payloads
// (present on the raw Python dicts p4-mirror.ts relays) never reach a
// sensor here.
// ---------------------------------------------------------------------------

const P4_SHA256_HEX_RE = /^[0-9a-fA-F]{64}$/;
const P4_TOKEN_RE = /^[A-Za-z0-9_.:-]{1,128}$/;

/** Bounded non-negative integer, clamped to `max`; malformed input -> 0. */
function boundedCount(value: unknown, max: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return 0;
  return Math.min(value, max);
}

/** Bounded token (proposal ids, status/state enums), or null when malformed
 * (never free text) — three-plus call sites below, per project convention. */
function boundedToken(value: unknown): string | null {
  return typeof value === "string" && P4_TOKEN_RE.test(value) ? value : null;
}

/** Bounded sha256 hex digest, or null when absent/malformed. */
function boundedHash(value: unknown): string | null {
  return typeof value === "string" && P4_SHA256_HEX_RE.test(value) ? value : null;
}

export const HEARTBEAT_MODES = ["off", "shadow", "active"] as const;

export interface HeartbeatPulseRecord extends BaseRecord {
  kind: "heartbeat_pulse";
  mode: "off" | "shadow" | "active";
  event: string;
  due: boolean;
  ran: boolean;
  healthy: boolean;
  db_ok: boolean;
  cache_pruned_count: number;
  git_dirty: boolean;
  issue_codes: string[];
  latency_ms: number;
  model_tokens_used: number;
}

/**
 * Bounded telemetry mirror of one `p4.pulse()` heartbeat result (Task 3's
 * `HeartbeatCoordinator.run_if_due()` output, relayed through p4-mirror.ts).
 * Only the fixed heartbeat_pulse field set ever leaves this builder;
 * `model_tokens_used` is always zero (the heartbeat is zero-token by design).
 */
export function heartbeatPulse(
  session: string,
  result: Record<string, unknown> | undefined,
): HeartbeatPulseRecord {
  const value = result ?? {};
  const mode =
    typeof value.mode === "string" && (HEARTBEAT_MODES as readonly string[]).includes(value.mode)
      ? (value.mode as "off" | "shadow" | "active")
      : "shadow";
  const issueCodes = Array.isArray(value.issue_codes)
    ? value.issue_codes
        .filter((code): code is string => typeof code === "string" && code.length >= 1 && code.length <= 64)
        .slice(0, 32)
    : [];
  return base("heartbeat_pulse", session, {
    mode,
    event: typeof value.event === "string" ? truncate(value.event, 128) : "",
    due: value.due === true,
    ran: value.ran === true,
    healthy: value.healthy === true,
    db_ok: value.db_ok === true,
    cache_pruned_count: boundedCount(value.cache_pruned_count, 1_000_000),
    git_dirty: value.git_dirty === true,
    issue_codes: issueCodes,
    latency_ms: boundedCount(value.latency_ms, 86_400_000),
    model_tokens_used: 0,
  }) as unknown as HeartbeatPulseRecord;
}

export const BOTTLENECK_CATEGORIES = [
  "PROMPT_BLOAT",
  "TOOL_CHAIN_THRASH",
  "UNCOMPRESSED_PAYLOAD",
  "RETRIEVAL_OVERLOAD",
] as const;

export interface BottleneckFingerprintRecord extends BaseRecord {
  kind: "bottleneck_fingerprint";
  fingerprint_id: string;
  category: string;
  scope_id: string;
  occurrence_count: number;
  impact_score: number;
  evidence_count: number;
  evidence_hash: string | null;
}

/**
 * Bounded telemetry mirror of one Radar fingerprint (Task 5's
 * `ImprovementRadar.observe_session()` fingerprint dict, relayed through
 * p4-mirror.ts's `fingerprints[]`). Only fingerprint_id/category/scope_id/
 * counts/impact_score/evidence_hash ever leave this builder — the raw
 * dict's `description`, `mitigation`, `metadata`, and `evidence_refs` are
 * never read.
 */
export function bottleneckFingerprint(
  session: string,
  fingerprint: Record<string, unknown> | undefined,
): BottleneckFingerprintRecord {
  const value = fingerprint ?? {};
  const category =
    typeof value.category === "string" && (BOTTLENECK_CATEGORIES as readonly string[]).includes(value.category)
      ? value.category
      : "unknown";
  const impactScore =
    typeof value.impact_score === "number" && Number.isFinite(value.impact_score) && value.impact_score >= 0
      ? Math.min(value.impact_score, 1_000_000)
      : 0;
  return base("bottleneck_fingerprint", session, {
    fingerprint_id: typeof value.fingerprint_id === "string" ? truncate(value.fingerprint_id, 128) : "",
    category,
    scope_id: typeof value.scope_id === "string" ? truncate(value.scope_id, 128) : "",
    occurrence_count: boundedCount(value.occurrence_count, 1_000_000_000),
    impact_score: impactScore,
    evidence_count: boundedCount(value.evidence_count, 1_000_000_000),
    evidence_hash: boundedHash(value.evidence_hash),
  }) as unknown as BottleneckFingerprintRecord;
}

export const OPTIMIZATION_EVENT_KINDS = [
  "optimization_proposal",
  "optimization_evaluation",
  "optimization_activation",
  "optimization_rollback",
] as const;
export type OptimizationEventKind = (typeof OPTIMIZATION_EVENT_KINDS)[number];

export interface OptimizationEventMetadata {
  proposal_id: string;
  status: string;
  approval_state?: string;
  rollback_state?: string;
  intervention_hash?: string;
  evidence_hash?: string;
}

export interface OptimizationEventRecord extends BaseRecord {
  kind: OptimizationEventKind;
  proposal_id: string;
  status: string;
  approval_state: string | null;
  rollback_state: string | null;
  intervention_hash: string | null;
  evidence_hash: string | null;
}

/**
 * Bounded telemetry mirror of one optimization lifecycle event (proposal /
 * evaluation / activation / rollback, Task 6's `optimization.py` records).
 * `metadata` never carries proposal bodies or intervention content — only
 * bounded tokens and hashes. Returns null on an unrecognized `kind` or a
 * missing/malformed `proposal_id`/`status` (never emits an unbounded
 * fallback record).
 *
 * NOT WIRED: this sensor is available for future use; the P4 pulse bridge
 * (p4-mirror.ts) does not surface optimization events today.
 */
export function optimizationEvent(
  session: string,
  kind: OptimizationEventKind,
  metadata: OptimizationEventMetadata,
): OptimizationEventRecord | null {
  if (!(OPTIMIZATION_EVENT_KINDS as readonly string[]).includes(kind)) return null;
  const proposalId = boundedToken(metadata.proposal_id);
  const status = boundedToken(metadata.status);
  if (proposalId === null || status === null) return null;
  return base(kind, session, {
    proposal_id: proposalId,
    status,
    approval_state: boundedToken(metadata.approval_state),
    rollback_state: boundedToken(metadata.rollback_state),
    intervention_hash: boundedHash(metadata.intervention_hash),
    evidence_hash: boundedHash(metadata.evidence_hash),
  }) as unknown as OptimizationEventRecord;
}
