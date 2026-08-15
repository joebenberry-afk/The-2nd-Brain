/**
 * Ambient type surface for the Prime Agent extension API (v0.7.2).
 *
 * Hand-written to match the installed runtime (verified against
 * C:/Tools/prime-agent/packages/coding-agent/src/core/extensions/types.ts).
 * Only the members this extension uses are modeled; everything else is
 * `unknown`. Type-only imports from this module are erased at runtime
 * (jiti), so there is no runtime dependency on this file.
 *
 * IMPORTANT: this is a module declaration file (top-level exports). It is
 * sourced via tsconfig "include" and imported with `import type`.
 */

/** Serialized model reference: "provider/id". */
export interface ModelInfo {
  id: string;
  provider: string;
  [key: string]: unknown;
}

/** Context usage as reported by the runtime (verified: tokens/contextWindow/percent). */
export interface ContextUsage {
  tokens: number | null;
  contextWindow: number;
  percent: number | null;
}

/** Read-only session manager surface used by this extension. */
export interface SessionManagerSurface {
  getSessionFile(): string | undefined;
}

/** Context passed to every event handler. */
export interface ExtensionContext {
  cwd: string;
  model: ModelInfo | undefined;
  sessionManager: SessionManagerSurface;
  getContextUsage(): ContextUsage | undefined;
  /** Full current system prompt (base + earlier extensions' patches, chained). */
  getSystemPrompt(): string;
  signal: AbortSignal | undefined;
  hasUI: boolean;
  ui: unknown;
}

// ---------------------------------------------------------------------------
// Event payloads (only the 11 subscribed lifecycle events are modeled).
// Fields we ignore are typed `unknown`; never rely on their shape.
// ---------------------------------------------------------------------------

export interface SessionStartEvent {
  type: "session_start";
  reason: string;
  previousSessionFile?: string;
}

export interface BeforeAgentStartEvent {
  type: "before_agent_start";
  prompt: string;
  images?: unknown;
  systemPrompt: unknown;
  systemPromptOptions?: unknown;
}

export interface TurnStartEvent {
  type: "turn_start";
  turnIndex: number;
  timestamp?: number;
}

export interface ContextEvent {
  type: "context";
  messages: unknown[];
}

export interface ToolCallEvent {
  type: "tool_call";
  toolName: string;
  toolCallId: string;
  /** Tool parameters. MUTABLE in the runtime — this extension only reads it. */
  input: Record<string, unknown>;
}

export interface ToolResultEvent {
  type: "tool_result";
  toolName: string;
  toolCallId: string;
  input: Record<string, unknown>;
  content: unknown[];
  details: unknown;
  isError: boolean;
}

export interface TurnEndEvent {
  type: "turn_end";
  turnIndex: number;
  message: unknown;
  toolResults: unknown[];
}

export interface AgentEndEvent {
  type: "agent_end";
  messages: unknown[];
}

export interface SessionBeforeCompactEvent {
  type: "session_before_compact";
  preparation: unknown;
  branchEntries: unknown[];
}

export interface SessionCompactEvent {
  type: "session_compact";
  compactionEntry: unknown;
  fromExtension: boolean;
}

export interface SessionShutdownEvent {
  type: "session_shutdown";
  reason: string;
  targetSessionFile?: string;
}

/** Union of every event this extension subscribes to. */
export type PrimeEvent =
  | SessionStartEvent
  | BeforeAgentStartEvent
  | TurnStartEvent
  | ContextEvent
  | ToolCallEvent
  | ToolResultEvent
  | TurnEndEvent
  | AgentEndEvent
  | SessionBeforeCompactEvent
  | SessionCompactEvent
  | SessionShutdownEvent;

/**
 * Result from a `tool_call` handler: `{ block: true, reason? }` prevents the
 * tool from executing (the runtime emits an error tool result with `reason`).
 * Verified against packages/coding-agent/src/core/extensions/types.ts
 * (ToolCallEventResult: block?: boolean; reason?: string).
 */
export interface ToolCallEventResult {
  block?: boolean;
  reason?: string;
}

/**
 * Result from a `before_agent_start` handler: `{ systemPrompt }` replaces the
 * system prompt for this turn (chained across extensions).
 * Verified against packages/coding-agent/src/core/extensions/types.ts
 * (BeforeAgentStartEventResult.systemPrompt?: string).
 */
export interface BeforeAgentStartEventResult {
  /** Optional custom message appended before the turn. */
  message?: unknown;
  /** Replace the system prompt for this turn; multiple extensions chain. */
  systemPrompt?: string;
}

/** Extension API surface used by this extension. */
export interface ExtensionAPI {
  /** tool_call handlers may block execution. */
  on(
    event: "tool_call",
    handler: (event: ToolCallEvent, ctx: ExtensionContext) => ToolCallEventResult | undefined,
  ): void;
  /** before_agent_start handlers may patch the system prompt (sync or awaited async — Phase 14 recall). */
  on(
    event: "before_agent_start",
    handler: (
      event: BeforeAgentStartEvent,
      ctx: ExtensionContext,
    ) => BeforeAgentStartEventResult | undefined | Promise<BeforeAgentStartEventResult | undefined>,
  ): void;
  on<E extends PrimeEvent>(
    name: E["type"],
    handler: (event: E, ctx: ExtensionContext) => unknown,
  ): void;
  /** Not used; modeled so callers can type-check `pi` fully. */
  exec?(command: string, args?: string[], options?: unknown): Promise<unknown>;
  appendEntry?(customType: string, data?: unknown): void;
}
