/**
 * The Second Brain OS — Phase 2 observability extension (Prime Agent).
 *
 * MEASUREMENT ONLY. Observes the 11 lifecycle events and appends JSONL
 * telemetry to <brain-home>/telemetry/agent-performance/<session>.jsonl.
 *
 * Safety invariants:
 *  - No handler ever returns {block}, {messages}, {systemPrompt}, or any
 *    patch — handlers always return undefined.
 *  - tool_call handlers never modify event.input.
 *  - Every handler is wrapped in try/catch; on error an `extension_error`
 *    record is appended best-effort and nothing is thrown into the session.
 *  - Writes are fire-and-forget: append() is never awaited on the critical
 *    path and storage never throws.
 *
 * Schema: brainstem/telemetry/SCHEMA.md (v=2). Privacy rules are enforced in
 * src/sensors.ts (counts/sizes only; bash command text truncated to 500).
 */
import type {
  AgentEndEvent,
  BeforeAgentStartEvent,
  ContextEvent,
  ExtensionAPI,
  ExtensionContext,
  PrimeEvent,
  SessionBeforeCompactEvent,
  SessionCompactEvent,
  SessionShutdownEvent,
  SessionStartEvent,
  ToolCallEvent,
  ToolResultEvent,
  TurnEndEvent,
  TurnStartEvent,
} from "../types/prime";
import { loadConfig } from "./config";
import * as sensors from "./sensors";
import { sanitizeSessionStem, TelemetryStore } from "./storage";

/** Random fallback session id (used only when no session file exists). */
function anonSessionId(): string {
  const rand = Math.floor(Math.random() * 0xffff)
    .toString(16)
    .padStart(4, "0");
  return `anon-${Date.now()}-${rand}`;
}

/**
 * Resolve the session id for the current ctx. Prefers the persisted session
 * file stem; falls back to an anonymous id so ephemeral sessions still get
 * telemetry without exposing a path.
 */
function resolveSessionId(ctx: ExtensionContext): string {
  try {
    const file = ctx?.sessionManager?.getSessionFile?.();
    if (typeof file === "string" && file.length > 0) {
      const base = file.split(/[\\/]/).pop() ?? file;
      const stem = base.endsWith(".jsonl") ? base.slice(0, -".jsonl".length) : base;
      if (stem.length > 0) return sanitizeSessionStem(stem);
    }
  } catch {
    // fall through to anonymous id
  }
  return anonSessionId();
}

type Mapper<E extends PrimeEvent> = (
  event: E,
  ctx: ExtensionContext,
  session: string,
) => object | null;

/**
 * Wrap a mapper in a safe handler: never throws, never returns a value,
 * never awaits on the critical path. Errors become `extension_error` records
 * (best-effort). The store is (re)created whenever the session id changes.
 *
 * `final` handlers (session_shutdown) write synchronously: Prime's daemon
 * tears the worker down right after the event, so async writes can lose the
 * race with process exit.
 */
function safeHandler<E extends PrimeEvent>(
  getStore: (session: string) => TelemetryStore | null,
  mapper: Mapper<E>,
  final = false,
): (event: E, ctx: ExtensionContext) => void {
  return (event: E, ctx: ExtensionContext): void => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx);
      const record = mapper(event, ctx, session);
      if (!record) return;
      const store = getStore(session);
      if (!store) return;
      if (final) {
        store.appendFinal(record);
      } else {
        store.append(record);
      }
    } catch (error) {
      try {
        const store = getStore(session);
        if (!store) return;
        if (final) {
          store.appendFinal(sensors.extensionError(session, error));
        } else {
          store.append(sensors.extensionError(session, error));
        }
      } catch {
        // storage failed too — give up silently (measurement must not crash).
      }
    }
  };
}

export default function (pi: ExtensionAPI): void {
  const config = loadConfig();
  if (!config.enabled || !config.telemetryDir) {
    // Silently disabled (env gate or missing brain home).
    return;
  }
  const telemetryDir: string = config.telemetryDir;

  let store: TelemetryStore | null = null;
  const getStore = (session: string): TelemetryStore | null => {
    if (!store || store.sessionId !== session) {
      store = new TelemetryStore(telemetryDir, session);
    }
    return store;
  };

  const wire = <E extends PrimeEvent>(
    type: E["type"],
    mapper: Mapper<E>,
    final = false,
  ): void => {
    pi.on(type, safeHandler<E>(getStore, mapper, final));
  };

  wire<SessionStartEvent>("session_start", (event, ctx, session) =>
    sensors.sessionStart(session, event.reason, ctx.cwd, ctx.model),
  );

  wire<BeforeAgentStartEvent>("before_agent_start", (event, _ctx, session) =>
    sensors.beforeAgentStart(session, event.prompt),
  );

  wire<TurnStartEvent>("turn_start", (event, _ctx, session) =>
    sensors.turnStart(session, event.turnIndex),
  );

  wire<ContextEvent>("context", (event, _ctx, session) =>
    sensors.context(session, event.messages),
  );

  // tool_call: read-only. event.input is never modified.
  wire<ToolCallEvent>("tool_call", (event, _ctx, session) =>
    sensors.toolCall(session, event.toolName, event.toolCallId, event.input),
  );

  wire<ToolResultEvent>("tool_result", (event, _ctx, session) =>
    sensors.toolResult(session, event.toolName, event.toolCallId, event.isError, event.content),
  );

  wire<TurnEndEvent>("turn_end", (event, ctx, session) => {
    let usage: Parameters<typeof sensors.turnEnd>[2] = undefined;
    try {
      usage = ctx.getContextUsage ? ctx.getContextUsage() : undefined;
    } catch {
      usage = undefined;
    }
    return sensors.turnEnd(session, event.turnIndex, usage, event.toolResults);
  });

  wire<AgentEndEvent>("agent_end", (event, _ctx, session) =>
    sensors.agentEnd(session, event.messages),
  );

  wire<SessionBeforeCompactEvent>("session_before_compact", (event, _ctx, session) =>
    sensors.sessionBeforeCompact(session, event.branchEntries),
  );

  wire<SessionCompactEvent>("session_compact", (event, _ctx, session) =>
    sensors.sessionCompact(session, event.fromExtension),
  );

  wire<SessionShutdownEvent>(
    "session_shutdown",
    (event, _ctx, session) => sensors.sessionShutdown(session, event.reason),
    true, // final: sync write so the record survives worker teardown
  );
}
