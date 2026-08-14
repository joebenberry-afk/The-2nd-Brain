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

/** Common record fields (v, ts, kind, session). */
export interface BaseRecord {
  v: 2;
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
 * Bash command text from a tool_call input, truncated to 500 chars.
 * Returns undefined for non-bash tools or missing/empty command.
 */
export function bashCommand(input: Record<string, unknown>): string | undefined {
  if (input == null || typeof input !== "object") return undefined;
  const command = input.command;
  if (typeof command !== "string" || command.length === 0) return undefined;
  return truncate(command, BASH_COMMAND_MAX_CHARS);
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
}

export function beforeAgentStart(session: string, prompt: unknown): BeforeAgentStartRecord {
  return base("before_agent_start", session, {
    prompt_chars: typeof prompt === "string" ? prompt.length : 0,
  }) as unknown as BeforeAgentStartRecord;
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

export function toolResult(
  session: string,
  toolName: unknown,
  toolCallId: unknown,
  isError: unknown,
  content: unknown,
): ToolResultRecord {
  return base("tool_result", session, {
    tool: typeof toolName === "string" ? toolName : "unknown",
    id: typeof toolCallId === "string" ? toolCallId : "unknown",
    is_error: isError === true,
    output_bytes: byteLength(content),
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

export interface SessionShutdownRecord extends BaseRecord {
  kind: "session_shutdown";
  reason: string;
}

export function sessionShutdown(session: string, reason: unknown): SessionShutdownRecord {
  return base("session_shutdown", session, {
    reason: typeof reason === "string" ? reason : String(reason),
  }) as unknown as SessionShutdownRecord;
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
