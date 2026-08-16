/**
 * The Second Brain OS — Phase 2 observability extension (Prime Agent).
 *
 * MEASUREMENT FIRST, plus the Phase 1 minimal-orchestrator guard: observes
 * the 11 lifecycle events, appends JSONL telemetry to
 * <brain-home>/telemetry/agent-performance/<session>.jsonl, and — for Sol
 * orchestrator-model sessions only — blocks direct execution tools
 * (bash/edit/websearch) and injects the Sol contract as a systemPrompt
 * addendum. All other sessions stay measurement-only.
 *
 * Safety invariants:
 *  - Measurement handlers return undefined. The two guard-capable handlers
 *    (tool_call, before_agent_start) return a patch ONLY for orchestrator
 *    models: tool_call may return {block:true, reason} for Sol + blocked
 *    tool; before_agent_start may return {systemPrompt} for Sol. Everything
 *    else returns undefined.
 *  - tool_call handlers never modify event.input.
 *  - Every handler is wrapped in try/catch; on error an `extension_error`
 *    record is appended best-effort and nothing is thrown into the session.
 *    Guard failures FAIL OPEN (recorded, never blocking) so measurement can
 *    never disturb the agent session.
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
  ToolResultEvent,
  TurnEndEvent,
  TurnStartEvent,
} from "../types/prime";
import { loadConfig, resolveBrainHome } from "./config";
import {
  buildPolicyBlockRecord,
  isOrchestratorModel,
  loadOrchestratorGuardConfig,
  orchestratorPolicyFor,
} from "./orchestrator-guard";
import {
  appendDriverContract,
  loadDriverOrchestratorConfig,
  resolveAgentRole,
} from "./driver-orchestrator";
import {
  buildBrainBrief,
  loadRecallGateConfig,
  runBrainRecall,
  shouldAttemptRecall,
  type RecallGateConfig,
} from "./recall-gate";
import { parseThreshold, rtdEligibility, rtdShadowRecord } from "./rtd";
import {
  loadAutoInjectHostConfig,
  runAdvisoryAutoInject,
  runShadowAutoInject,
  type AdvisoryAutoInjectCall,
} from "./autoinject";
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
 * Sol minimal-orchestrator contract, injected as a systemPrompt addendum for
 * Sol-model sessions only (via the before_agent_start guard below).
 *
 * Condensed from docs/orchestration/SOL_MINIMAL_ORCHESTRATOR.md (canonical
 * source: brainstem/policies/sol-minimal-orchestrator.md). Kept under 1500
 * words; embedded here so the installed extension copy stays self-contained.
 *
 * NOTE: the extension context exposes no rlmDepth, so a subagent spawned
 * WITH a Sol model would also be guarded. That is acceptable: workers run
 * cheaper models by policy; only the orchestrator role uses Sol.
 */
const SOL_ORCHESTRATOR_CONTRACT = `You are Sol, the minimal-cost ORCHESTRATOR. You do NOT execute work; you delegate it and read results.

ROLE: understand the user's request from information already in your context; decide what information or work is required; delegate to the most appropriate worker; read returned evidence; audit for correctness, contradictions, missing proof, and scope drift; request corrections when necessary; make the final decision; return a concise synthesis.

ALLOWED: read the user's request; read information already in your active context; read concise worker reports, focused patches/diffs, and test summaries; compare two worker reports; identify contradictions, missing evidence, and scope drift; judge whether a claim is sufficiently proven; reject a worker result; ask a worker to correct or verify; choose the next worker; decide escalation; make architecture/product decisions on collected evidence; stop when the goal is satisfied.

FORBIDDEN (MUST delegate instead): searching the repository, enumerating files, grep/ripgrep, inspecting source files, browsing the web, executing shell commands or Python, querying databases, inspecting telemetry, running tests/benchmarks/builds, editing files, writing production code, creating patches, trial-and-error debugging, dependency discovery, investigating logs, broad code review, manual call-graph tracing, spawning several subagents merely to gain confidence.

CRITICAL RULE: if you think "I need to inspect/check/search/verify/find...", the next action is normally to DELEGATE that exact information request to one worker. You MUST delegate. If more information is required, delegate.

INFORMATION BOUNDARY: consume only information already handed to you: the user's request, your context, and worker evidence packages. A referenced-but-not-loaded file is delegated.

WORKER SELECTION (cheapest competent first): Qwen 3.5 (local/cheap) for inventory, discovery, references, config mapping, static inspection, telemetry stats, doc-vs-code checks, mechanical refactors, low-risk tests, first-pass validation; DeepSeek V4 Flash (cheap/fast) for moderate implementation, targeted debugging, code comparison, patch review, contained fixes, small designs, performance analysis, stronger tests, second-pass review; GPT-5.6 Luna (premium) for cross-cutting changes, high correctness, failed cheaper workers, architecture-boundary issues, migration/compat, production-critical final validation. Never select by prestige. Escalate only when a worker is insufficient, uncertain, or failed, or the task becomes correctness-critical.

CONCURRENCY: default 1 active worker; at most 2 when work is genuinely independent; NEVER 3+.

WORKER TASK PACKET (every delegation):
## Objective — one precise result required
## Why — one/two sentences: what decision this enables
## Scope — exact subsystem/files if already known
## Constraints — what must not be changed
## Required Evidence — what proof must be returned
## Deliverable — the exact output you need
Never hand workers the whole project history.

WORKER RETURN CONTRACT (require this shape):
## Result — Pass / Fail / Partial / Implemented
## What I Found — concise factual findings
## Evidence — path:line / symbol / command+observed result
## Changes — only if changes were requested
## Tests — exact tests and results
## Risks / Uncertainty — anything not proven
## Recommended Next Step — one concise recommendation

AUDIT (5 checks, then decide): (1) Did the worker answer the exact assigned question? (2) Is the claim supported by evidence? (3) Did the worker change anything outside scope? (4) Are the tests strong enough to prove the change? (5) Does the result contradict existing verified information?

CORRECTION LOOP: all five pass -> accept. One fails -> send a narrow correction task to the SAME worker (do not redo the work yourself). Escalate only after two failures, or when the flaw indicates the task is beyond the worker, the task is correctness-critical, or evidence is contradictory.

FINAL RESPONSE: conclusion, important evidence, material caveats, next action if needed. No giant retelling of worker activity, raw logs, or unverified speculation. Keep your reasoning and output compact.`;

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

  wire<SessionStartEvent>("session_start", (event, ctx, session) => {
    // Phase 0C SHADOW: decide + record only; session_start carries no task
    // text, so the adapter no-ops on empty tasks. Never returns a patch.
    void runShadowAutoInject({
      home: config.home ?? "",
      session,
      task: "",
      agentId: sensors.modelToString(ctx.model) ?? "prime",
      cwd: typeof ctx.cwd === "string" ? ctx.cwd : undefined,
      cfg: loadAutoInjectHostConfig(),
      append: (record) => getStore(session)?.append(record),
    });
    return sensors.sessionStart(session, event.reason, ctx.cwd, ctx.model);
  });

  // before_agent_start: measurement + role resolution + contract injection.
  // Roles (brainstem/policies/driver-orchestration.md): hard_orchestrator
  // (Sol — strict contract, unchanged), driver (deepseek-v4-pro / gpt-5.6-luna
  // by default — driver contract APPENDED to the full current system prompt),
  // worker / normal (measurement-only, never get the driver contract). The
  // record always carries the resolved role; driver-role sessions also carry
  // driver_contract_injected (true when the contract was appended).
  // Phase 14 recall: for non-Sol sessions when enabled (default OFF), ONE
  // bounded Brain recall appends the Brain Brief AFTER the driver contract in
  // a single patch (patched is the composition base). Sol-model sessions get
  // the condensed orchestrator contract (recall must NOT double-inject for
  // Sol). Guard failures fail open: the record is still appended and no patch
  // is returned. Default OFF recall = driver sessions get the contract
  // synchronously, everyone else returns undefined (zero behavior change,
  // zero spawns).
  // Phase 0D: SHADOW (fire-and-forget, never injects) vs ADVISORY/ACTIVE
  // (awaited; may return a LOW-AUTHORITY custom_message patch). The packet
  // text carries "authority: advisory" from the contracts renderer — never
  // upgraded here. Fail-open: any spawn error resolves to no patch.
  const autoinjectCall = (
    session: string,
    event: BeforeAgentStartEvent,
    context: ExtensionContext,
  ): AdvisoryAutoInjectCall => ({
    home: config.home ?? "",
    session,
    task: typeof event.prompt === "string" ? event.prompt : "",
    agentId: sensors.modelToString(context.model) ?? "prime",
    cwd: typeof context.cwd === "string" ? context.cwd : undefined,
    cfg: loadAutoInjectHostConfig(config.home),
    append: (record) => getStore(session)?.append(record),
  });

  /** Merge a custom_message patch into any existing handler result. */
  function withMessage<T extends { systemPrompt?: string } | undefined>(
    result: T,
    message: unknown,
  ): T | { systemPrompt?: string; message: unknown } {
    if (!message) return result;
    return { ...(result ?? {}), message } as T | { systemPrompt?: string; message: unknown };
  }

  pi.on("before_agent_start", async (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      // Phase 0C/0D: SHADOW = fire-and-forget (never returns a patch);
      // ADVISORY/ACTIVE = awaited and may append a low-authority
      // custom_message (packet carries "authority: advisory").
      const aiCfg = loadAutoInjectHostConfig();
      let aiMessage: unknown = undefined;
      if (aiCfg.mode === "advisory" || aiCfg.mode === "active") {
        aiMessage = await runAdvisoryAutoInject(autoinjectCall(session, event, ctx));
      } else {
        void runShadowAutoInject(autoinjectCall(session, event, ctx));
      }
      const modelId = sensors.modelToString(ctx.model) ?? undefined;
      const guardCfg = loadOrchestratorGuardConfig();
      const role = resolveAgentRole(
        modelId,
        loadDriverOrchestratorConfig(),
        guardCfg.orchestratorModels,
      );
      if (isOrchestratorModel(modelId, guardCfg)) {
        getStore(session)?.append(sensors.beforeAgentStart(session, event.prompt, role));
        return withMessage({ systemPrompt: SOL_ORCHESTRATOR_CONTRACT }, aiMessage);
      }
      const base = typeof ctx.getSystemPrompt === "function" ? ctx.getSystemPrompt() : undefined;
      const patched = role === "driver" ? appendDriverContract(base) : base;
      const driverContractInjected = role === "driver" && patched !== undefined && patched !== base;
      getStore(session)?.append(
        sensors.beforeAgentStart(
          session,
          event.prompt,
          role,
          role === "driver" ? driverContractInjected : undefined,
        ),
      );
      const recallCfg = loadRecallGateConfig();
      if (shouldAttemptRecall(event.prompt, recallCfg)) {
        return withMessage(await recallBrief(event.prompt, session, recallCfg, patched), aiMessage);
      }
      if (driverContractInjected && patched !== undefined) {
        return withMessage({ systemPrompt: patched }, aiMessage);
      }
      return withMessage(undefined, aiMessage);
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
    }
    return undefined;
  });

  wire<TurnStartEvent>("turn_start", (event, _ctx, session) =>
    sensors.turnStart(session, event.turnIndex),
  );

  wire<ContextEvent>("context", (event, _ctx, session) =>
    sensors.context(session, event.messages),
  );

  /**
   * Phase 14: run ONE bounded Brain recall for a substantial non-Sol prompt
   * and append the Brain Brief AFTER `base` (the already-composed prompt —
   * for driver sessions this is the driver contract appended to the system
   * prompt, so contract + brief land in ONE patch). Fail silent on every
   * error path (never throws, never returns a brief-only prompt).
   */
  async function recallBrief(
    prompt: string,
    session: string,
    cfg: RecallGateConfig,
    base: string | undefined,
  ): Promise<{ systemPrompt: string } | undefined> {
    try {
      const home = resolveBrainHome();
      if (!home) return undefined;
      const rows = (await runBrainRecall({ home, query: prompt, cfg })) ?? [];
      const brief = buildBrainBrief(rows, cfg.maxRows);
      if (brief === undefined) return undefined;
      if (base === undefined || base.trim() === "") return undefined; // never REPLACE the base prompt
      return { systemPrompt: `${base}\n\n${brief}` };
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — stay silent
      }
      return undefined;
    }
  }

  // tool_call: read-only measurement + minimal-orchestrator guard.
  // event.input is never modified. The normal tool_call record is ALWAYS
  // appended; on top of that, when the active model is the orchestrator
  // (Sol) and the tool is blocked (bash/edit/websearch), an
  // orchestrator_policy_violation record (kind per SCHEMA.md, bounded
  // fields, detected_by=runtime_guard) is appended and {block:true, reason}
  // is returned so the runtime turns the call into an error tool result.
  // Every other model keeps the previous measurement-only behavior
  // (returns undefined). ipython is NOT blocked: RLM delegation runs
  // through the IPython kernel and must stay available to the orchestrator.
  // Guard failures fail open: the violation is never recorded and the call
  // is never blocked (an extension_error record is appended instead).
  pi.on("tool_call", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      getStore(session)?.append(sensors.toolCall(session, event.toolName, event.toolCallId, event.input));
      const modelId = sensors.modelToString(ctx.model) ?? undefined;
      const decision = orchestratorPolicyFor(modelId, event.toolName, loadOrchestratorGuardConfig());
      if (decision.block) {
        // Fill the session stem the same way every other record does
        // (buildPolicyBlockRecord leaves it as a placeholder).
        const violation = buildPolicyBlockRecord(
          modelId,
          event.toolName,
          decision.reason,
          new Date().toISOString(),
        );
        violation.session = session;
        getStore(session)?.append(violation);
        return { block: true, reason: decision.reason };
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
    }
    return undefined;
  });

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

  // agent_end: P0-G9 write-back is intentionally NOT wired here. The SDK
  // AgentEndEvent carries only `messages: AgentMessage[]` — no outcome,
  // summary, or task-success signal — so any extraction would be fabrication.
  // Documented no-op; write-back happens through explicit `brainctl
  // autoinject writeback` (Python authority) and the Codex Stop trigger.
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
