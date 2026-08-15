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
import { parseThreshold, rtdEligibility, rtdShadowRecord } from "./rtd";
import { measureContent } from "./sensors";
import * as sensors from "./sensors";
import {
  createTelemetryDirEnsurer,
  sanitizeSessionStem,
  TelemetryStore,
  type DirEnsurer,
} from "./storage";

/** Random fallback session id (used only when no session file exists). */
function anonSessionId(): string {
  const rand = Math.floor(Math.random() * 0xffff)
    .toString(16)
    .padStart(4, "0");
  return `anon-${Date.now()}-${rand}`;
}

/**
 * Resolve the session id for the current ctx. Prefers the persisted session
 * file stem (unchanged, always wins); falls back to `anonSession()` — the
 * anonymous identity cached for THIS extension lifecycle — so ephemeral
 * sessions get one stable in-process id instead of a new id per event.
 */
function resolveSessionId(ctx: ExtensionContext, anonSession: () => string): string {
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
  return anonSession();
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
  anonSession: () => string,
  mapper: Mapper<E>,
  final = false,
): (event: E, ctx: ExtensionContext) => void {
  return (event: E, ctx: ExtensionContext): void => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
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

export interface ExtensionOptions {
  /**
   * Factory-scoped directory-readiness seam (Phase 4 test hook). When
   * omitted, a fresh `createTelemetryDirEnsurer()` is created per factory
   * invocation. Never module-global.
   */
  ensureTelemetryDir?: DirEnsurer;
}

export default function (pi: ExtensionAPI, options: ExtensionOptions = {}): void {
  const config = loadConfig();
  if (!config.enabled || !config.telemetryDir) {
    // Silently disabled (env gate or missing brain home).
    return;
  }
  const telemetryDir: string = config.telemetryDir;

  // Phase 4: one shared directory-readiness seam for the whole factory
  // (plan: "at extension startup, ensure the telemetry directory once").
  // The first store construction performs the single mkdir attempt; every
  // later store in this lifecycle reuses the result (success or failure —
  // never retried). A failure propagates into the constructing store's
  // fail-open handler, so it is reported exactly once and construction,
  // appends, and final writes remain non-fatal. `options.ensureTelemetryDir`
  // is a factory-scoped test seam; defaults to a fresh ensurer per factory.
  const ensureTelemetryDir = options.ensureTelemetryDir ?? createTelemetryDirEnsurer();

  // Phase 2 fix: the anonymous fallback identity is created once per
  // extension lifecycle (this factory invocation) and reused for every event
  // that lacks an explicit Prime session file. Closure state — not a
  // module/process global — so separate lifecycles get separate identities
  // and all anonymous events share one telemetry file.
  let anonSessionIdValue: string | null = null;
  const anonSession = (): string => {
    if (anonSessionIdValue === null) {
      anonSessionIdValue = anonSessionId();
    }
    return anonSessionIdValue;
  };

  let store: TelemetryStore | null = null;
  const getStore = (session: string): TelemetryStore | null => {
    if (!store || store.sessionId !== session) {
      store = new TelemetryStore(telemetryDir, session, ensureTelemetryDir);
    }
    return store;
  };

  const wire = <E extends PrimeEvent>(
    type: E["type"],
    mapper: Mapper<E>,
    final = false,
  ): void => {
    pi.on(type, safeHandler<E>(getStore, anonSession, mapper, final));
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

  // Phase 5 RTD (shadow only): after the normal tool_result record, decide
  // whether the result would be distilled and log rtd_shadow. Never
  // substitutes content in this phase. RTD failures must not disturb the
  // normal telemetry record, hence the inner try/catch.
  //
  // Phase 3 (corrected): RTD eligibility (tool/command) is decided FIRST —
  // before ANY content measurement. Eligible results get one JSON.stringify
  // attempt plus one UTF-8 byte count in `measureContent`, shared by
  // ordinary telemetry (`output_bytes`) and RTD shadow evaluation/recording
  // (`serializedChars`). Ineligible results perform ZERO RTD-specific
  // serialization: primitive strings are measured with only the raw
  // TextEncoder byte count base telemetry already required (no
  // JSON.stringify), and non-strings keep exactly the single
  // serialization/fallback base telemetry already required. The precomputed
  // eligibility is passed to rtdShadowRecord so RTD never re-measures.
  wire<ToolResultEvent>("tool_result", (event, _ctx, session) => {
    const eligibility = rtdEligibility(event.toolName, event.input);
    const measurement = measureContent(event.content, eligibility === "ok");
    try {
      const shadow = rtdShadowRecord({
        session,
        tool: event.toolName,
        id: event.toolCallId,
        input: event.input,
        eligibility,
        measurement,
        threshold: parseThreshold(process.env.SECOND_BRAIN_RTD_THRESHOLD),
        active: process.env.SECOND_BRAIN_RTD === "active",
      });
      if (shadow) getStore(session)?.append(shadow);
    } catch {
      // measurement must not disturb measurement
    }
    return sensors.toolResult(
      session,
      event.toolName,
      event.toolCallId,
      event.isError,
      measurement.outputBytes,
    );
  });

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
