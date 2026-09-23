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
  /** Native UUID-like identity, independent of transcript filename. */
  getSessionId?(): string;
  /** Native session header, including its authoritative timestamp/id. */
  getHeader?(): unknown;
  getSessionFile(): string | undefined;
  getEntries?(): unknown[];
}


export interface ExtensionContext {
  cwd: string;
  model: ModelInfo | undefined;
  sessionManager: SessionManagerSurface;
  getContextUsage(): ContextUsage | undefined;
  /** Effective system prompt sections returned by the current OMP runtime. */
  getSystemPrompt(): string | string[];
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

// ---------------------------------------------------------------------------
// P3-B economics events (plan §5.1/§5.4/§5.5; verified against the installed
// v0.7.2 runtime — packages/coding-agent/src/core/extensions/types.ts:612,
// :618, :690 — and the Phase A live probe).
// ---------------------------------------------------------------------------

/**
 * Fired before a provider request is sent. `payload` is the raw provider
 * request object. A returned value replaces the payload; OMP uses this direct
 * handler contract for Brain-selected provider/model identity.
 */
export interface BeforeProviderRequestEvent {
  type: "before_provider_request";
  payload: unknown;
}

/** Fired after a provider response is received, before the stream is consumed. Read-only hook. */
export interface AfterProviderResponseEvent {
  type: "after_provider_response";
  status: number;
  headers: Record<string, string>;
}

/** Minimal assistant-message surface consumed for passive usage capture. */
export interface MessageEndMessage {
  role?: string;
  provider?: unknown;
  model?: unknown;
  usage?: Usage;
  customType?: string;
  content?: unknown;
  [key: string]: unknown;
}

/**
 * Fired when an assistant message finishes streaming. Returning
 * `{ message }` replaces the finalized message; the runtime REQUIRES the
 * replacement to keep the original message role (agent-session.ts:3315).
 */
export interface MessageEndEvent {
  type: "message_end";
  message: MessageEndMessage;
}

export interface ToolCallEvent {
  type: "tool_call";
  toolName: string;
  toolCallId: string;
  /** Tool parameters as received before execution. */
  input: Record<string, unknown>;
}

export interface ToolCallEventResult {
  block?: boolean;
  reason?: string;
  /** Replacement input executed by OMP after handler validation. */
  input?: Record<string, unknown>;
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
  | BeforeProviderRequestEvent
  | AfterProviderResponseEvent
  | MessageEndEvent
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

/**
 * Provider usage counters as reported by the host on every assistant message
 * (verified against @earendil-works/pi-ai src/types.ts:201). All fields are
 * numbers when present; the P3 sensors preserve the host's zero-vs-missing
 * distinction and never invent values.
 */
export interface Usage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
  cost: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    total: number;
  };
}

/**
 * Result from a `message_end` handler: `{ message }` replaces the finalized
 * message. The replacement MUST keep the original message role — the runtime
 * rejects role changes (types.ts:951, runner.ts:729).
 */
export interface MessageEndEventResult {
  message?: MessageEndMessage;
}

/**
 * Result from a `tool_result` handler: only defined `content`/`details`/
 * `isError` fields are applied (runner.ts:770-781). Verified against
 * types.ts:945.
 */
export interface ToolResultEventResult {
  content?: unknown[];
  details?: unknown;
  isError?: boolean;
}

/** Result from a `context` handler: `{ messages }` replaces the LLM context (types.ts:925). */
export interface ContextEventResult {
  messages?: unknown[];
}

/** Minimal tool descriptor returned by `getAllTools` (only `name` is consumed). */
export interface ToolInfo {
  name: string;
  [key: string]: unknown;
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
  /** before_provider_request may return a replacement payload; undefined preserves it. */
  on(
    event: "before_provider_request",
    handler: (event: BeforeProviderRequestEvent, ctx: ExtensionContext) => unknown,
  ): void;
  /** P3-B: after_provider_response is a read-only hook (status + header metadata). */
  on(
    event: "after_provider_response",
    handler: (event: AfterProviderResponseEvent, ctx: ExtensionContext) => void,
  ): void;
  /** P3-B: message_end handlers may replace the finalized message (role must be preserved). */
  on(
    event: "message_end",
    handler: (event: MessageEndEvent, ctx: ExtensionContext) => MessageEndEventResult | undefined | Promise<MessageEndEventResult | undefined>,
  ): void;
  /** tool_result handlers may patch content/details/isError (only defined fields apply). */
  on(
    event: "tool_result",
    handler: (event: ToolResultEvent, ctx: ExtensionContext) => ToolResultEventResult | undefined,
  ): void;
  /** context handlers may replace the LLM context via { messages }. */
  on(
    event: "context",
    handler: (event: ContextEvent, ctx: ExtensionContext) => ContextEventResult | undefined,
  ): void;
  on<E extends PrimeEvent>(
    name: E["type"],
    handler: (event: E, ctx: ExtensionContext) => unknown,
  ): void;
  /** Not used; modeled so callers can type-check `pi` fully. */
  exec?(command: string, args?: string[], options?: unknown): Promise<unknown>;
  appendEntry?(customType: string, data?: unknown): void;
  /** Shared session event bus; `on` returns a detach handle (host EventBus contract). */
  events?: {
    on?(channel: string, handler: (payload: unknown) => void): (() => void) | void;
  };
  /** P3-B tool-control API (types.ts:1435-1439) — modeled for Phase J measurement, not consumed today. */
  getActiveTools?(): string[];
  getAllTools?(): ToolInfo[];
  setActiveTools?(toolNames: string[]): void;
}
