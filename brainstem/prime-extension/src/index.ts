/**
 * The Second Brain OS — Phase 2 observability extension (Prime Agent).
 *
 * MEASUREMENT FIRST, plus the Phase 1 minimal-orchestrator guard and the thin
 * OMP -> Second Brain model-routing handoff. Observes lifecycle events and
 * appends JSONL telemetry to <brain-home>/telemetry/agent-performance/<session>.jsonl.
 * For Sol orchestrator-model sessions only, it blocks direct execution tools
 * (bash/edit/websearch) and injects the Sol contract as a systemPrompt addendum.
 * Brain routing may replace only provider/model fields exposed by an OMP request.
 *
 * Safety invariants:
 *  - Measurement handlers return undefined except direct handlers whose runtime
 *    contract consumes a replacement: before_agent_start, context,
 *    before_provider_request, and message_end.
 *  - tool_call handlers do not mutate event.input; the task bridge returns a
 *    validated replacement only through the supported ToolCallEventResult.input.
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
  AsyncJobLifecycleObservation,
  BeforeAgentStartEvent,
  ExtensionAPI,
  ExtensionContext,
  MessageEndMessage,
  PrimeEvent,
  SessionBeforeCompactEvent,
  SessionCompactEvent,
  SessionShutdownEvent,
  SessionStartEvent,
  ToolCallEvent,
  ToolCallEventResult,
  ToolResultEvent,
  TurnEndEvent,
  TurnStartEvent,
} from "../types/prime";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { setTimeout as scheduleObserverExpiry, clearTimeout as cancelObserverExpiry } from "node:timers";
import { loadConfig, loadRereadAvoidance, resolveBrainHome } from "./config";
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
import { appendLeanKernel, decideLeanRuntime, LEAN_KERNEL_MARKER } from "./lean-code";
import {
  loadContextPagingConfig,
  loadContextStructureConfig,
  loadProviderCapabilities,
  loadRtdConfig,
  loadVmemAdmissionConfig,
  loadVmemConfig,
} from "./config";
import { estimateTokens, pageContext } from "./context-paging";
import { dirname, join, resolve } from "node:path";
import {
  cliArtifactPreserver,
  cliRtdPreserver,
  parseThreshold,
  rtdEligibility,
  runRtd,
  type RtdPreserver,
} from "./rtd";
import {
  loadAutoInjectHostConfig,
  resolveProject,
  resolvedProjectIdForSession,
  runAdvisoryAutoInject,
  runShadowAutoInject,
  type AdvisoryAutoInjectCall,
} from "./autoinject";
import { appendPrefixExtras, assemblePrefix, checkPrefixDrift } from "./injection-slots";
import {
  activeStateMessage,
  renderActiveState,
  runActiveStateEnsure,
  runActiveStateUpdate,
  runActiveStateUpdateSync,
} from "./active-state-mirror";
import {
  runEnvironmentAssessmentSync,
  type EnvironmentAssessmentResult,
} from "./environment-mirror";
import { runP4Pulse, runP4PulseSync } from "./p4-mirror";
import {
  mirrorExtensionError,
  mirrorEventSync,
  mirrorFireAndForget,
  runLedgerCheckpoint,
  runLedgerSegmentRollover,
  taskSha256,
} from "./ledger-mirror";
import { measureContent } from "./sensors";
import * as sensors from "./sensors";
import { runVmemCompactPrep, runVmemEvictSync, runVmemHotContext, runVmemStore } from "./vmem";
import {
  createTelemetryDirEnsurer,
  sanitizeSessionStem,
  TelemetryStore,
  type DirEnsurer,
} from "./storage";
import {
  ompRoutingRecord,
  runOmpRouting,
  type OmpModelCandidate,
  type OmpRoutingDecision,
  type OmpRoutingOptions,
  type OmpRoutingResult,
} from "./routing-bridge";
import {
  type BudgetCheckOptions,
  type BudgetCheckResult,
  type BudgetRunner,
  type BudgetState,
  BUDGET_HARD_LINE,
  runBudgetCheck,
} from "./budget-bridge";
export {
  type BudgetCheckOptions,
  type BudgetCheckResult,
  type BudgetRunner,
  type BudgetState,
  BUDGET_HARD_LINE,
  runBudgetCheck,
};
import {
  OMP_VISIBILITY_MAX_INJECTED_CHARS,
  ompVisibilityRecord,
  runOmpVisibility,
  validateOmpVisibilityResult,
  type OmpVisibilityOptions,
  type OmpVisibilityResult,
} from "./visibility-bridge";
import {
  OMP_WORKER_CONTEXT_MAX_TEXT_CHARS,
  renderOmpWorkerContext,
  runOmpWorkerContext,
  type OmpWorkerContextOptions,
  type OmpWorkerContextResult,
} from "./worker-context-bridge";
import {
  runOmpWorkerResult,
  type OmpWorkerResultOptions,
  type OmpWorkerResultOutcome,
} from "./worker-result-bridge";
import {
  runOmpWorkerBind,
  runOmpWorkerDispatchFailed,
  runOmpWorkerLifecycle,
  type OmpWorkerBindOptions,
  type OmpWorkerCallbackResult,
  type OmpWorkerDispatchFailedOptions,
  type OmpWorkerLifecycleOptions,
} from "./worker-lifecycle-bridge";
import {
  STOP_CONTROL_COMMAND,
  StopBoundaryState,
  extractTextContent,
  parseStopDecisionOutput,
  rewriteSessionPlaceholders,
  rewriteStopControlCommand,
  stopControlIdentity,
  stopEvidenceMatches,
  type StopControlIdentity,
} from "./stop-boundary";

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

/** Resolve one native transcript path with the same identity rules as ctx. */
function sessionIdFromFile(file: string): string | undefined {
  const base = file.split(/[\\/]/).pop() ?? file;
  const stem = base.endsWith(".jsonl") ? base.slice(0, -".jsonl".length) : base;
  return stem.length > 0 ? sanitizeSessionStem(stem) : undefined;
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
      const session = sessionIdFromFile(file);
      if (session !== undefined) return session;
    }
  } catch {
    // fall through to anonymous id
  }
  return anonSession();
}

/**
 * Follow OMP's native transcript ancestry: a child at
 * `<parent-without-jsonl>/<agent>.jsonl` has the existing sibling
 * `<parent-without-jsonl>.jsonl`. This matches OMP 18.1.10's bounded
 * breadcrumb resolver without reading transcript content or trusting headers.
 */
function resolveNativeRootSessionId(ctx: ExtensionContext): string | undefined {
  const file = ctx?.sessionManager?.getSessionFile?.();
  if (typeof file !== "string" || !file.endsWith(".jsonl")) return undefined;
  let current = resolve(file);
  let foundAncestor = false;
  for (let depth = 0; depth < 8; depth += 1) {
    const parent = `${dirname(current)}.jsonl`;
    if (!existsSync(parent)) break;
    current = parent;
    foundAncestor = true;
  }
  return foundAncestor ? sessionIdFromFile(current) : undefined;
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
type RereadHint = {
  unchanged: true;
  prior_artifact: string | null;
  prior_turn: number | null;
};

type RereadHintRunner = (
  home: string,
  session: string,
  path: string,
  mode?: "OFF" | "SHADOW" | "ACTIVE",
  toolName?: string,
  toolCallId?: string,
) => Promise<RereadHint | null>;

function rereadPath(toolName: string, input: Record<string, unknown>): string | undefined {
  if (!["read", "cat", "grep"].includes(toolName.toLowerCase())) return undefined;
  const args = input.args;
  const values = [
    input.path,
    input.file,
    input.file_path,
    args && typeof args === "object" && !Array.isArray(args)
      ? (args as Record<string, unknown>).path
      : undefined,
  ];
  return values.find((value): value is string => typeof value === "string" && value.trim().length > 0);
}

function rereadReplacementAllowed(toolName: string, input: Record<string, unknown>): boolean {
  if (!["read", "cat"].includes(toolName.toLowerCase())) return false;
  const args = input.args;
  const selectors = [input.range, input.start, input.end, input.query, input.pattern];
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const values = args as Record<string, unknown>;
    selectors.push(values.range, values.start, values.end, values.query, values.pattern);
  }
  return !selectors.some((value) => value !== undefined && value !== null && value !== "");
}
export function runRereadHint(
  home: string,
  session: string,
  path: string,
  mode: "OFF" | "SHADOW" | "ACTIVE" = "SHADOW",
  toolName = "read",
  toolCallId?: string,
): Promise<RereadHint | null> {
  const python = process.env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env, SECOND_BRAIN_HOME: home };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  return new Promise((resolve) => {
    execFile(
      python,
      [
        "-m", "second_brain", "--home", home, "working-set", "reread-hint", session, path,
        "--mode", mode, "--tool", toolName, ...(toolCallId ? ["--tool-call-id", toolCallId] : []),
      ],
      { cwd: home, env, timeout: 5000, maxBuffer: 64 * 1024 },
      (error, stdout) => {
        if (error) {
          resolve(null);
          return;
        }
        try {
          const parsed = JSON.parse(stdout) as unknown;
          if (
            parsed !== null &&
            typeof parsed === "object" &&
            (parsed as Record<string, unknown>).unchanged === true
          ) {
            const value = parsed as Record<string, unknown>;
            resolve({
              unchanged: true,
              prior_artifact: typeof value.prior_artifact === "string" ? value.prior_artifact : null,
              prior_turn: typeof value.prior_turn === "number" ? value.prior_turn : null,
            });
            return;
          }
        } catch {
          // fail open
        }
        resolve(null);
      },
    );
  });
}

function unchangedMarker(path: string, hint: RereadHint): string | undefined {
  if (!hint.prior_artifact) return undefined;
  try {
    const sha = createHash("sha256").update(readFileSync(path)).digest("hex");
    return `[SECOND_BRAIN_UNCHANGED ${path} ${sha} ${hint.prior_artifact}]\nPrior distilled view reference: ${hint.prior_artifact}`;
  } catch {
    return undefined;
  }
}

export interface ExtensionOptions {
  /**
   * Factory-scoped directory-readiness seam (Phase 4 test hook). When
   * omitted, a fresh `createTelemetryDirEnsurer()` is created per factory
   * invocation. Never module-global.
   */
  ensureTelemetryDir?: DirEnsurer;
  /**
   * P3-F test seam: RTD raw-result preserver (plan §11.4). When omitted, the
   * real CLI preserver (`second_brain artifact store` + `expand`) is created
   * per tool_result event against the brain home. Fail-open: a failing
   * preserver simply disables substitution (original content returned).
   */
  rtdPreserver?: RtdPreserver;
  /**
   * RC4 byte-exact recovery pass Part A test seam: AutoInject packet
   * preserver (kind="autoinject_packet", tool="autoinject"), same
   * `RtdPreserver` shape as `rtdPreserver`. When omitted, the real CLI
   * preserver (`cliArtifactPreserver`) is created per real AutoInject
   * delivery against the brain home. Fail-open: a failing preserver simply
   * omits the richer `packetArtifactRef`/`packetSha256` metadata (admission
   * still happens with the existing delivery-only shape).
   */
  autoinjectPacketPreserver?: RtdPreserver;
  /** OMP worker Context Capsule seam; production uses the bounded Brain CLI bridge. */
  ompWorkerContextRunner?: (options: OmpWorkerContextOptions) => Promise<OmpWorkerContextResult>;
  /** OMP worker-result -> T4.1 lifecycle seam; production uses the bounded Brain CLI bridge. */
  ompWorkerResultRunner?: (options: OmpWorkerResultOptions) => Promise<OmpWorkerResultOutcome>;
  ompWorkerBindRunner?: (options: OmpWorkerBindOptions) => Promise<OmpWorkerCallbackResult>;
  ompWorkerLifecycleRunner?: (options: OmpWorkerLifecycleOptions) => Promise<OmpWorkerCallbackResult>;
  ompWorkerDispatchFailedRunner?: (
    options: OmpWorkerDispatchFailedOptions,
  ) => Promise<OmpWorkerCallbackResult>;
  ompRoutingRunner?: (options: OmpRoutingOptions) => Promise<OmpRoutingResult>;
  ompVisibilityRunner?: (options: OmpVisibilityOptions) => Promise<OmpVisibilityResult>;
  /** Read-ledger reread hint seam; production invokes brainctl. */
  rereadHintRunner?: RereadHintRunner;
  /** Budget check runner seam; production uses governor check-budget CLI bridge. */
  budgetRunner?: BudgetRunner;
  /** Test seam to pre-seed session budget states. */
  sessionBudgetStates?: Map<string, BudgetState>;
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

  // Frozen-per-extension-lifecycle runtime identity (plan §10): resolved
  // exactly once from the SAME config object every handler already shares,
  // and recorded to a dedicated status file (never the per-session
  // telemetry stream, which many wiring tests fixed-count-assert) so an
  // operator can always prove which Brain home/runtime this running
  // instance is frozen to. A later env change never silently retargets a
  // running instance; only /reload or restart re-runs loadConfig() and
  // rewrites this file. Best-effort: a write failure never disables the
  // extension (fail-open, same policy as telemetry persistence).
  try {
    const brainVersion = (() => {
      try {
        return readFileSync(join(config.home ?? "", "VERSION"), "utf8").trim();
      } catch {
        return null;
      }
    })();
    const identityHash = createHash("sha256")
      .update(JSON.stringify({ home: config.home, runtimePython: config.runtimePython }))
      .digest("hex");
    const stateDir = join(config.home ?? "", "state");
    mkdirSync(stateDir, { recursive: true });
    writeFileSync(
      join(stateDir, "extension-runtime-ready.json"),
      JSON.stringify(
        {
          resolved_at: new Date().toISOString(),
          home: config.home,
          runtime_python: config.runtimePython,
          brain_version: brainVersion,
          identity_hash: identityHash,
        },
        null,
        2,
      ),
    );
  } catch {
    // status file is advisory only; never block extension startup
  }

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

  // P2 host event mirror (Phase 2B): fire-and-forget, fail-open, privacy-safe
  // (task text only as sha256; tool names + byte sizes only). Errors append an
  // extension_error record; the host turn is never blocked.
  const mirror = (
    sessionId: string,
    kind: string,
    fields: Record<string, unknown>,
    opts: { agentId?: string; parentEventId?: string; ignorable?: boolean; cwd?: string } = {},
  ): void => {
    mirrorFireAndForget({
      home: config.home ?? "",
      hostSessionId: sessionId,
      cwd: opts.cwd,
      parentSessionId: workerRootSessions.get(sessionId),
      record: {
        kind,
        fields,
        agentId: opts.agentId,
        parentEventId: opts.parentEventId,
        ignorable: opts.ignorable,
      },
      onError: (error) => {
        try {
          getStore(sessionId)?.append(mirrorExtensionError(sessionId, error));
        } catch {
          // storage failed too — stay silent
        }
      },
    });
  };
  let currentTurnIndex = 0;
  let latestRoutingDecision: OmpRoutingDecision | null = null;
  let latestRoutingSession: string | null = null;
  const routingCache = new Map<string, Promise<OmpRoutingResult>>();
  const visibilityCache = new Map<string, Promise<OmpVisibilityResult>>();
  const stopStates = new Map<string, StopBoundaryState>();
  const stopControlCalls = new Map<string, {
    session: string; command: string; originalCommand: string;
    identity: StopControlIdentity | undefined; parentSession: string;
  }>();
  let stopRejections = 0;
  const rejectStopEvidence = (session: string, reason: string): void => {
    if (stopRejections >= 128) return;
    stopRejections += 1;
    getStore(session)?.append({
      v: 2, ts: new Date().toISOString(), kind: "stop_evidence_rejected", session,
      reason_code: reason,
    });
  };
  // Child HOST session -> canonical native transcript root; never prompt/header-derived.
  const workerRootSessions = new Map<string, string>();
  const workerAncestrySessions = new Set<string>();
  // Spawn progress binds native job ids to packets; async-result and hub
  // deliveries later settle those same correlations.
  const pendingWorkerJobs = new Map<
    string,
    { taskId: string; packetSha256: string; parentSessionId: string; agent: string; agentId: string }
  >();
  interface WorkerAdmission {
    taskId: string;
    attemptId: string;
    packetSha256: string;
    projectId: string;
    worktreeId: string | null;
    accessIntent: "read_only" | "mutating";
    callbackToken?: string;
    parentSessionId: string;
    agent: string;
    toolCallId: string;
    sourceIndex: number;
    lifecycleRevision: number;
    callbackChain: Promise<boolean>;
    nativeAttemptId?: string;
    nativeJobId?: string | null;
    agentId?: string;
    hostGeneration?: number;
    cleanupAccepted: boolean;
  }
  const workerAdmissionsByTask = new Map<string, WorkerAdmission>();
  const workerAdmissionsBySource = new Map<string, WorkerAdmission>();
  const workerObservationDisposers = new Map<string, () => void>();
  const workerObserverExpiry = new Map<string, NodeJS.Timeout>();
  const disposeWorkerObserver = (key: string): void => {
    const expiry = workerObserverExpiry.get(key);
    if (expiry) cancelObserverExpiry(expiry);
    workerObserverExpiry.delete(key);
    workerObservationDisposers.get(key)?.();
    workerObservationDisposers.delete(key);
  };
  const pendingWorkerTaskIds = new Set<string>();
  const journalWorkerEvent = (session: string, customType: string, data: unknown): void => {
    try {
      pi.appendEntry?.(customType, data);
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    }
  };
  // Retain correlation until durable acceptance; claims serialize observers.
  const takePendingWorkerJob = (
    jobId: string,
    session: string,
  ) => pendingWorkerJobs.get(JSON.stringify([session, jobId]));
  // A settled hub job can be re-observed by repeated `hub jobs`/`wait` polls;
  // report each worker's completion exactly once.
  const reportedWorkerTaskIds = new Set<string>();
  const workerCompletionsInFlight = new Set<string>();
  const observedWorkerTaskIds = new Set<string>();
  const rememberWorkerIdentity = (set: Set<string>, id: string): void => {
    set.add(id);
    if (set.size > 1024) {
      const oldest = set.values().next().value;
      if (oldest !== undefined) set.delete(oldest);
    }
  };
  const establishWorkerRootSession = (session: string, ctx: ExtensionContext): void => {
    if (workerAncestrySessions.has(session)) return;
    rememberWorkerIdentity(workerAncestrySessions, session);
    try {
      const rootSession = resolveNativeRootSessionId(ctx);
      if (rootSession === undefined || rootSession === session) return;
      if (!workerRootSessions.has(session) && workerRootSessions.size >= 1024) {
        const oldest = workerRootSessions.keys().next().value;
        if (oldest !== undefined) {
          workerRootSessions.delete(oldest);
          workerAncestrySessions.delete(oldest);
        }
      }
      workerRootSessions.set(session, rootSession);
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    }
  };
  const workerRecoverySessions = new Set<string>();
  const environmentTaskHashes = new Map<string, string>();
  const stopStateFor = (session: string): StopBoundaryState => {
    const existing = stopStates.get(session);
    if (existing) return existing;
    const created = new StopBoundaryState();
    stopStates.set(session, created);
    return created;
  };
  const rereadRunner = options.rereadHintRunner ?? runRereadHint;
  const pendingRereads = new Map<string, { path: string }>();
  const readySessions = new Set<string>();
  const lastToolResultBytes = new Map<string, number>();
  const lastContextProvider = new Map<string, string | null>();
  const lastContextModel = new Map<string, string | null>();
  const lastProvider = new Map<string, string | null>();
  const lastModel = new Map<string, string | null>();
  const lastCacheReadTokens = new Map<string, number | null>();
  const sessionBeforeCompactOccurred = new Set<string>();
  const routingRunner = options.ompRoutingRunner ?? runOmpRouting;
  const visibilityRunner = options.ompVisibilityRunner ?? runOmpVisibility;
  const workerContextRunner = options.ompWorkerContextRunner ?? runOmpWorkerContext;
  const workerResultRunner = options.ompWorkerResultRunner ?? runOmpWorkerResult;
  const workerBindRunner = options.ompWorkerBindRunner ?? runOmpWorkerBind;
  const workerLifecycleRunner = options.ompWorkerLifecycleRunner ?? runOmpWorkerLifecycle;
  const workerDispatchFailedRunner = options.ompWorkerDispatchFailedRunner ?? runOmpWorkerDispatchFailed;
  const sessionBudgetStates = options.sessionBudgetStates ?? new Map<string, BudgetState>();
  const budgetRunner = options.budgetRunner ?? runBudgetCheck;
  const safeWorkerContextRunner = async (
    workerOptions: OmpWorkerContextOptions,
  ): Promise<OmpWorkerContextResult> => {
    try {
      return await workerContextRunner(workerOptions);
    } catch {
      return { ok: false, error: "BRAIN_WORKER_CONTEXT_UNAVAILABLE" };
    }
  };

  const workerRoleForAgent = (agent: unknown): string =>
    typeof agent === "string" && agent.toLowerCase().includes("validator") ? "validator" : "worker";

  const releaseUndispatchedAdmission = async (
    admission: WorkerAdmission,
    failureCode: string,
  ): Promise<boolean> => {
    if (
      admission.accessIntent !== "mutating" ||
      admission.worktreeId === null ||
      admission.callbackToken === undefined ||
      admission.nativeAttemptId !== undefined
    ) {
      return admission.accessIntent === "read_only";
    }
    try {
      const receipt = await workerDispatchFailedRunner({
        home: config.home ?? "",
        sessionId: admission.parentSessionId,
        taskId: admission.taskId,
        packetSha256: admission.packetSha256,
        attemptId: admission.attemptId,
        projectId: admission.projectId,
        worktreeId: admission.worktreeId,
        callbackToken: admission.callbackToken,
        failureCode,
      });
      if (!receipt.ok) return false;
      admission.cleanupAccepted = true;
      pendingWorkerTaskIds.delete(admission.taskId);
      workerAdmissionsByTask.delete(admission.taskId);
      workerAdmissionsBySource.delete(
        JSON.stringify([admission.parentSessionId, admission.toolCallId, admission.sourceIndex]),
      );
      journalWorkerEvent(admission.parentSessionId, "second-brain.worker-dispatch-failed-accepted", {
        session: admission.parentSessionId,
        taskId: admission.taskId,
        attemptId: admission.attemptId,
        failureCode,
      });
      return true;
    } catch {
      return false;
    }
  };

  const observeWorkerAttempt = async (
    admission: WorkerAdmission,
    observation: Readonly<AsyncJobLifecycleObservation>,
    ctx: ExtensionContext,
  ): Promise<boolean> => {
    if (
      observation.type !== "task" ||
      observation.sourceToolCallId !== admission.toolCallId ||
      observation.sourceIndex !== admission.sourceIndex ||
      !observation.agentId
    ) {
      return false;
    }
    if (
      admission.nativeAttemptId !== undefined &&
      (admission.nativeAttemptId !== observation.nativeAttemptId ||
        admission.nativeJobId !== observation.jobId ||
        admission.agentId !== observation.agentId ||
        admission.hostGeneration !== observation.generation)
    ) {
      return false;
    }
    const binding: OmpWorkerBindOptions = {
      home: config.home ?? "",
      sessionId: admission.parentSessionId,
      taskId: admission.taskId,
      packetSha256: admission.packetSha256,
      attemptId: admission.attemptId,
      projectId: admission.projectId,
      worktreeId: admission.worktreeId ?? "",
      callbackToken: admission.callbackToken ?? "",
      hostGeneration: observation.generation,
      nativeAttemptId: observation.nativeAttemptId,
      nativeJobId: observation.jobId,
      agentId: observation.agentId,
    };
    if (admission.nativeAttemptId === undefined) {
      let bound: OmpWorkerCallbackResult;
      try {
        bound = await workerBindRunner(binding);
      } catch {
        return false;
      }
      if (!bound.ok) return false;
      admission.nativeAttemptId = observation.nativeAttemptId;
      admission.nativeJobId = observation.jobId;
      admission.agentId = observation.agentId;
      admission.hostGeneration = observation.generation;
      if (observation.jobId !== null) {
        pendingWorkerJobs.set(JSON.stringify([admission.parentSessionId, observation.jobId]), {
          taskId: admission.taskId,
          packetSha256: admission.packetSha256,
          parentSessionId: admission.parentSessionId,
          agent: admission.agent,
          agentId: observation.agentId,
        });
        journalWorkerEvent(admission.parentSessionId, "second-brain.worker-job-pending", {
          session: admission.parentSessionId,
          jobId: observation.jobId,
          accessIntent: admission.accessIntent,
          toolCallId: admission.toolCallId,
          sourceIndex: admission.sourceIndex,
          taskId: admission.taskId,
          attemptId: admission.attemptId,
          packetSha256: admission.packetSha256,
          parentSessionId: admission.parentSessionId,
          agent: admission.agent,
          agentId: observation.agentId,
          hostGeneration: observation.generation,
          nativeAttemptId: observation.nativeAttemptId,
          projectId: admission.projectId,
          worktreeId: admission.worktreeId,
        });
      }
    }
    if (observation.revision <= admission.lifecycleRevision) return true;
    // Native revisions identify immutable snapshots. A lost response must not
    // cause a newer cleanup snapshot to reuse an already-persisted sequence.
    const sequence = observation.revision;
    let lifecycle: OmpWorkerCallbackResult;
    try {
      lifecycle = await workerLifecycleRunner({
        ...binding,
        sequence,
        outcome:
          observation.status === "completed"
            ? "completed"
            : observation.status === "failed"
              ? "failed"
              : observation.status === "cancelled"
                ? "cancelled"
                : null,
        executorSettled: observation.executorSettled,
        cleanupComplete: observation.cleanupComplete,
      });
    } catch {
      return false;
    }
    if (!lifecycle.ok) return false;
    admission.lifecycleRevision = observation.revision;
    journalWorkerEvent(admission.parentSessionId, "second-brain.worker-lifecycle-accepted", {
      session: admission.parentSessionId,
      taskId: admission.taskId,
      attemptId: admission.attemptId,
      lifecycleSequence: sequence,
      nativeAttemptId: observation.nativeAttemptId,
      nativeJobId: observation.jobId,
      agentId: observation.agentId,
      hostGeneration: observation.generation,
      status: observation.status,
      executorSettled: observation.executorSettled,
      cleanupComplete: observation.cleanupComplete,
    });
    if (observation.status !== "running") {
      await emitWorkerCompletion(admission.parentSessionId, ctx, {
        task_id: admission.taskId,
        packet_sha256: admission.packetSha256,
        child_omp_agent_id: observation.agentId,
        child_omp_session_file: null,
        worker_agent: admission.agent,
        worker_model: null,
        status: observation.status,
      }, "");
    }
    if (observation.executorSettled && observation.cleanupComplete) {
      admission.cleanupAccepted = true;
      pendingWorkerTaskIds.delete(admission.taskId);
      for (const [key, job] of pendingWorkerJobs) if (job.taskId === admission.taskId) pendingWorkerJobs.delete(key);
      const sourceKey = JSON.stringify([
        admission.parentSessionId,
        admission.toolCallId,
        admission.sourceIndex,
      ]);
      workerAdmissionsBySource.delete(sourceKey);
      if (reportedWorkerTaskIds.has(admission.taskId)) {
        workerAdmissionsByTask.delete(admission.taskId);
      }
      const stillPending = Array.from(workerAdmissionsBySource.values()).some(
        (candidate) =>
          candidate.parentSessionId === admission.parentSessionId &&
          candidate.toolCallId === admission.toolCallId &&
          candidate.accessIntent === "mutating" &&
          !candidate.cleanupAccepted,
      );
      if (!stillPending) {
        const observerKey = JSON.stringify([admission.parentSessionId, admission.toolCallId]);
        disposeWorkerObserver(observerKey);
      }
    }
    return true;
  };

  const prepareWorkerTaskInput = async (
    event: ToolCallEvent,
    ctx: ExtensionContext,
    session: string,
  ): Promise<ToolCallEventResult | undefined> => {
    if (event.toolName !== "task") return undefined;
    const rootSession = workerRootSessions.get(session) ?? session;
    if (sessionBudgetStates.get(session) === "HARD" || sessionBudgetStates.get(rootSession) === "HARD") {
      getStore(session)?.append(
        ompRoutingRecord("omp_worker_context_failure", session, {
          task_id: "omp-budget-blocked",
          failure_code: "BUDGET_EXCEEDED",
        }),
      );
      return { block: true, reason: BUDGET_HARD_LINE };
    }
    const input = event.input;
    const batchItems = Array.isArray(input.tasks) ? input.tasks : [];
    const items: Array<Record<string, unknown>> =
      batchItems.filter((item): item is Record<string, unknown> => item != null && typeof item === "object");
    if (batchItems.length !== items.length) {
      return { block: true, reason: "P3.2 worker context requires object task items" };
    }
    if (items.length === 0 && typeof input.task === "string") {
      items.push(input);
    }
    if (items.length === 0) return undefined;
    if (typeof event.toolCallId !== "string" || event.toolCallId.length === 0) {
      return { block: true, reason: "BRAIN_WORKER_DISPATCH_ID_REQUIRED" };
    }
    if (items.some((item) => typeof item.task !== "string" || item.task.trim() === "")) {
      return { block: true, reason: "P3.2 worker context requires a non-empty task" };
    }
    if (
      items.some(
        (item) => item.access_intent !== "read_only" && item.access_intent !== "mutating",
      )
    ) {
      return { block: true, reason: "BRAIN_WORKER_ACCESS_INTENT_REQUIRED" };
    }
    const hasMutating = items.some((item) => item.access_intent === "mutating");
    if (hasMutating && typeof ctx.observeAsyncJobLifecycle !== "function") {
      return { block: true, reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE" };
    }
    const projectId = resolvedProjectIdForSession(session) ?? resolveProject();
    if (typeof projectId !== "string" || projectId.trim() === "") {
      return { block: true, reason: "BRAIN_WORKER_PROJECT_ID_REQUIRED" };
    }
    const taskIds = items.map((_, index) => `omp-${taskSha256(JSON.stringify([session, event.toolCallId, index]))}`);
    const reservations = taskIds.filter((id) => !pendingWorkerTaskIds.has(id));
    if (pendingWorkerTaskIds.size + reservations.length > 1024) {
      return { block: true, reason: "BRAIN_WORKER_PENDING_LIMIT" };
    }
    for (const id of reservations) pendingWorkerTaskIds.add(id);
    const batch = batchItems.length > 0;
    const modelId = sensors.modelToString(ctx.model) ?? "unknown";
    const provider = typeof ctx.model?.provider === "string" ? ctx.model.provider : "unknown";
    const guardCfg = loadOrchestratorGuardConfig();
    const role = resolveAgentRole(modelId, loadDriverOrchestratorConfig(), guardCfg.orchestratorModels);
    const augmented: Array<Record<string, unknown>> = [];
    const preparedAdmissions: WorkerAdmission[] = [];
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      const rawTask = item.task as string;
      const task = rawTask.slice(0, OMP_WORKER_CONTEXT_MAX_TEXT_CHARS);
      const taskId = taskIds[index];
      const accessIntent = item.access_intent as "read_only" | "mutating";
      const result = await safeWorkerContextRunner({
        home: config.home ?? "",
        sessionId: session,
        taskId,
        task,
        scope: ctx.cwd,
        completionCondition:
          typeof input.completion_condition === "string"
            ? input.completion_condition
            : "Return bounded evidence for the delegated task",
        projectId,
        accessIntent,
        cwd: ctx.cwd,
        role,
        provider,
        model: modelId,
        workerRole: workerRoleForAgent(item.agent),
        depth: typeof input.depth === "number" ? input.depth : 0,
        contextRefs: Array.isArray(input.context_refs) ? input.context_refs.filter((ref): ref is string => typeof ref === "string") : undefined,
      });
      if (
        !result.ok ||
        result.contextHandoff === undefined ||
        result.contextMetadata === undefined ||
        result.taskId !== taskId ||
        result.attemptId === undefined ||
        result.packetSha256 === undefined ||
        result.projectId !== projectId ||
        result.accessIntent !== accessIntent ||
        (accessIntent === "mutating" &&
          (typeof result.worktreeId !== "string" || result.callbackToken === undefined))
      ) {
        await Promise.all(
          preparedAdmissions.map((admission) =>
            releaseUndispatchedAdmission(admission, "OMP_BATCH_PREPARATION_FAILED"),
          ),
        );
        for (const id of reservations) pendingWorkerTaskIds.delete(id);
        const reason = result.error ?? "P3.2 worker context preparation failed";
        getStore(session)?.append(
          ompRoutingRecord("omp_worker_context_failure", session, {
            task_id: taskId,
            worker_agent: typeof item.agent === "string" ? item.agent : "default",
            failure_code: reason,
          }),
        );
        return { block: true, reason };
      }
      const admission: WorkerAdmission = {
        taskId,
        attemptId: result.attemptId,
        packetSha256: result.packetSha256,
        projectId,
        worktreeId: result.worktreeId ?? null,
        accessIntent,
        ...(result.callbackToken ? { callbackToken: result.callbackToken } : {}),
        parentSessionId: session,
        agent: typeof item.agent === "string" ? item.agent : "default",
        toolCallId: event.toolCallId,
        sourceIndex: index,
        lifecycleRevision: 0,
        callbackChain: Promise.resolve(true),
        cleanupAccepted: accessIntent === "read_only",
      };
      preparedAdmissions.push(admission);
      journalWorkerEvent(session, "second-brain.worker-admission-pending", {
        session,
        taskId,
        attemptId: admission.attemptId,
        packetSha256: admission.packetSha256,
        projectId: admission.projectId,
        worktreeId: admission.worktreeId,
        accessIntent: admission.accessIntent,
        parentSessionId: session,
        agent: admission.agent,
        toolCallId: event.toolCallId,
        sourceIndex: index,
      });
      workerAdmissionsByTask.set(taskId, admission);
      workerAdmissionsBySource.set(JSON.stringify([session, event.toolCallId, index]), admission);
      const metadata = result.contextMetadata;
      const metadataRecord = {
        task_id: taskId,
        packet_sha256: result.packetSha256 ?? null,
        worker_agent: typeof item.agent === "string" ? item.agent : "default",
        worker_role: workerRoleForAgent(item.agent),
        parent_role: role,
        attempt_id: result.attemptId,
        access_intent: accessIntent,
        project_id: result.projectId,
        worktree_id: result.worktreeId,
        parent_session_id: session,
        context_ref_count: metadata.resolved_count,
        context_source_bytes: metadata.visible_bytes ?? 0,
        context_source_tokens: metadata.visible_tokens_estimate ?? 0,
        context_handoff_bytes: metadata.context_handoff_bytes,
        context_handoff_tokens: metadata.context_handoff_tokens_estimate,
        context_delta_bytes: metadata.context_delta_bytes,
        context_delta_tokens: metadata.context_delta_tokens_estimate,
        context_mode: metadata.mode,
        context_fingerprint: metadata.context_fingerprint,
        context_reused: metadata.reused,
        context_cache_hit: metadata.cache_hit,
      };
      getStore(session)?.append(ompRoutingRecord("omp_worker_context_handoff", session, metadataRecord));
      mirror(session, "task_context_resolved", metadataRecord, { cwd: ctxCwd(ctx) });
      // Own marker must be first: raw task text may quote marker-shaped data.
      augmented.push({
        ...item,
        task: `[SECOND_BRAIN_WORKER_TASK task_id=${taskId} packet_sha256=${result.packetSha256 ?? ""} parent_session_id=${session}]\n${rawTask}\n\n${renderOmpWorkerContext(result.contextHandoff)}`,
      });
    }
    if (hasMutating) {
      const disposer = ctx.observeAsyncJobLifecycle?.(
        (observation) => {
          const admission = workerAdmissionsBySource.get(
            JSON.stringify([session, event.toolCallId, observation.sourceIndex]),
          );
          if (!admission || admission.accessIntent !== "mutating") return false;
          admission.callbackChain = admission.callbackChain
            .catch(() => false)
            .then(() => observeWorkerAttempt(admission, observation, ctx));
          return admission.callbackChain;
        },
        { sourceToolCallId: event.toolCallId },
      );
      if (!disposer) {
        await Promise.all(
          preparedAdmissions.map((admission) =>
            releaseUndispatchedAdmission(admission, "OMP_SETTLEMENT_CAPABILITY_UNAVAILABLE"),
          ),
        );
        return { block: true, reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE" };
      }
      workerObservationDisposers.set(JSON.stringify([session, event.toolCallId]), disposer);
    }
    if (batch) return { input: { ...input, tasks: augmented } };
    return { input: { ...input, task: String(augmented[0].task ?? "") } };
  };
  const emitWorkerCompletion = async (
    session: string,
    ctx: ExtensionContext,
    fields: {
      task_id: string;
      packet_sha256: string;
      child_omp_agent_id: string | null;
      child_omp_session_file: string | null;
      worker_agent: string;
      worker_model: string | null;
      status: "completed" | "failed" | "cancelled";
    },
    summaryText: string,
  ): Promise<void> => {
    const admission = workerAdmissionsByTask.get(fields.task_id);
    if (!admission || admission.packetSha256 !== fields.packet_sha256) {
      getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_ATTEMPT_BINDING_UNAVAILABLE"));
      return;
    }
    if (reportedWorkerTaskIds.has(fields.task_id) || workerCompletionsInFlight.has(fields.task_id)) return;
    workerCompletionsInFlight.add(fields.task_id);
    if (!observedWorkerTaskIds.has(fields.task_id)) {
      rememberWorkerIdentity(observedWorkerTaskIds, fields.task_id);
      getStore(session)?.append(ompRoutingRecord("omp_worker_child_result", session, fields));
    }
    try {
      // The host journal is recovery input, not a Brain acceptance receipt.
      journalWorkerEvent(session, "second-brain.worker-result-pending", {
        session,
        attemptId: admission.attemptId,
        fields,
        summary: summaryText.slice(0, 2048),
      });
      const outcome = await workerResultRunner({
        home: config.home ?? "",
        sessionId: session,
        taskId: fields.task_id,
        attemptId: admission.attemptId,
        packetSha256: fields.packet_sha256,
        status: fields.status,
        workerAgent: fields.worker_agent,
        workerModel: fields.worker_model ?? "",
        summary: summaryText.slice(0, 2048),
        childOmpAgentId: fields.child_omp_agent_id ?? "",
      });
      if (!outcome.ok) throw new Error(outcome.error ?? "BRAIN_WORKER_RESULT_NOT_ACCEPTED");
      rememberWorkerIdentity(reportedWorkerTaskIds, fields.task_id);
      if (admission.accessIntent === "read_only" || admission.cleanupAccepted) {
        pendingWorkerTaskIds.delete(fields.task_id);
        workerAdmissionsByTask.delete(fields.task_id);
        workerAdmissionsBySource.delete(
          JSON.stringify([admission.parentSessionId, admission.toolCallId, admission.sourceIndex]),
        );
      }
      journalWorkerEvent(session, "second-brain.worker-result-accepted", {
        session,
        taskId: fields.task_id,
        attemptId: admission.attemptId,
      });
      mirror(session, "worker_completed", fields, { cwd: ctxCwd(ctx) });
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    } finally {
      workerCompletionsInFlight.delete(fields.task_id);
    }
  };
  const recoverWorkerResults = async (session: string, ctx: ExtensionContext): Promise<void> => {
    if (workerRecoverySessions.has(session)) return;
    rememberWorkerIdentity(workerRecoverySessions, session);
    const pending = new Map<string, { fields: Parameters<typeof emitWorkerCompletion>[2]; summary: string }>();
    let recoveryLimited = false;
    for (const entry of ctx.sessionManager?.getEntries?.() ?? []) {
      if (entry === null || typeof entry !== "object" || !("type" in entry) || entry.type !== "custom" ||
          !("customType" in entry) || !("data" in entry)) continue;
      const data = entry.data;
      if (data === null || typeof data !== "object" || !("session" in data) || data.session !== session) continue;
      if (
        entry.customType === "second-brain.worker-admission-pending" &&
        "taskId" in data && typeof data.taskId === "string" &&
        "attemptId" in data && typeof data.attemptId === "string" &&
        "packetSha256" in data && typeof data.packetSha256 === "string" && /^[0-9a-f]{64}$/.test(data.packetSha256) &&
        "projectId" in data && typeof data.projectId === "string" &&
        "accessIntent" in data && (data.accessIntent === "read_only" || data.accessIntent === "mutating") &&
        "parentSessionId" in data && typeof data.parentSessionId === "string" &&
        "agent" in data && typeof data.agent === "string" &&
        "toolCallId" in data && typeof data.toolCallId === "string" &&
        "sourceIndex" in data && typeof data.sourceIndex === "number" &&
        ("worktreeId" in data && (data.worktreeId === null || typeof data.worktreeId === "string"))
      ) {
        const admission: WorkerAdmission = {
          taskId: data.taskId,
          attemptId: data.attemptId,
          packetSha256: data.packetSha256,
          projectId: data.projectId,
          worktreeId: data.worktreeId,
          accessIntent: data.accessIntent,
          parentSessionId: data.parentSessionId,
          agent: data.agent,
          toolCallId: data.toolCallId,
          sourceIndex: data.sourceIndex,
          lifecycleRevision: 0,
          callbackChain: Promise.resolve(true),
          cleanupAccepted: data.accessIntent === "read_only",
        };
        workerAdmissionsByTask.set(admission.taskId, admission);
        workerAdmissionsBySource.set(
          JSON.stringify([admission.parentSessionId, admission.toolCallId, admission.sourceIndex]),
          admission,
        );
        pendingWorkerTaskIds.add(admission.taskId);
        continue;
      }
      if (
        entry.customType === "second-brain.worker-lifecycle-accepted" &&
        "taskId" in data && typeof data.taskId === "string" &&
        "attemptId" in data && typeof data.attemptId === "string" &&
        "executorSettled" in data && data.executorSettled === true &&
        "cleanupComplete" in data && data.cleanupComplete === true
      ) {
        const admission = workerAdmissionsByTask.get(data.taskId);
        if (!admission || admission.attemptId !== data.attemptId) continue;
        admission.cleanupAccepted = true;
        pendingWorkerTaskIds.delete(admission.taskId);
        if (reportedWorkerTaskIds.has(admission.taskId)) {
          workerAdmissionsByTask.delete(admission.taskId);
        }
        workerAdmissionsBySource.delete(
          JSON.stringify([admission.parentSessionId, admission.toolCallId, admission.sourceIndex]),
        );
        continue;
      }
      if (entry.customType === "second-brain.worker-job-pending" &&
          "jobId" in data && typeof data.jobId === "string" && data.jobId.length > 0 && data.jobId.length <= 512 &&
          "agentId" in data && typeof data.agentId === "string" && data.agentId.length > 0 && data.agentId.length <= 512 &&
          "taskId" in data && typeof data.taskId === "string" && data.taskId.length <= 512 &&
          "packetSha256" in data && typeof data.packetSha256 === "string" && /^[0-9a-f]{64}$/.test(data.packetSha256) &&
          "agent" in data && typeof data.agent === "string" && data.agent.length <= 512) {
        const key = JSON.stringify([session, data.jobId]);
        if (pendingWorkerJobs.has(key)) continue;
        if (pendingWorkerJobs.size >= 1024 ||
            (!pendingWorkerTaskIds.has(data.taskId) && pendingWorkerTaskIds.size >= 1024)) {
          recoveryLimited = true;
          continue;
        }
        pendingWorkerTaskIds.add(data.taskId);
        pendingWorkerJobs.set(key, {
          taskId: data.taskId, packetSha256: data.packetSha256, parentSessionId: session, agent: data.agent,
          agentId: data.agentId,
        });
        const admission = workerAdmissionsByTask.get(data.taskId);
        if (
          admission &&
          "attemptId" in data && data.attemptId === admission.attemptId &&
          "nativeAttemptId" in data && typeof data.nativeAttemptId === "string" &&
          "hostGeneration" in data && typeof data.hostGeneration === "number"
        ) {
          admission.nativeJobId = data.jobId;
          admission.nativeAttemptId = data.nativeAttemptId;
          admission.agentId = data.agentId;
          admission.hostGeneration = data.hostGeneration;
        }
        continue;
      }
      if (
        entry.customType === "second-brain.worker-result-accepted" &&
        "taskId" in data && typeof data.taskId === "string" &&
        "attemptId" in data && typeof data.attemptId === "string"
      ) {
        pending.delete(data.taskId);
        const admission = workerAdmissionsByTask.get(data.taskId);
        if (!admission || admission.attemptId !== data.attemptId) continue;
        rememberWorkerIdentity(reportedWorkerTaskIds, data.taskId);
        if (admission.accessIntent === "read_only" || admission.cleanupAccepted) {
          pendingWorkerTaskIds.delete(data.taskId);
          workerAdmissionsByTask.delete(data.taskId);
          workerAdmissionsBySource.delete(
            JSON.stringify([admission.parentSessionId, admission.toolCallId, admission.sourceIndex]),
          );
          for (const [key, job] of pendingWorkerJobs) if (job.taskId === data.taskId) pendingWorkerJobs.delete(key);
        }
        continue;
      }
      if (entry.customType !== "second-brain.worker-result-pending" || !("fields" in data)) continue;
      const f = data.fields;
      if (f === null || typeof f !== "object" ||
          !("task_id" in f) || typeof f.task_id !== "string" || f.task_id.length > 512 ||
          !("packet_sha256" in f) || typeof f.packet_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(f.packet_sha256) ||
          !("status" in f) || (f.status !== "completed" && f.status !== "failed" && f.status !== "cancelled") ||
          !("worker_agent" in f) || typeof f.worker_agent !== "string") continue;
      if (!("attemptId" in data) || data.attemptId !== workerAdmissionsByTask.get(f.task_id)?.attemptId) continue;
      if (reportedWorkerTaskIds.has(f.task_id)) continue;
      if (!pending.has(f.task_id) && pending.size >= 1024) {
        recoveryLimited = true;
        continue;
      }
      pending.set(f.task_id, {
        fields: {
          task_id: f.task_id, packet_sha256: f.packet_sha256, status: f.status, worker_agent: f.worker_agent,
          child_omp_agent_id: "child_omp_agent_id" in f && typeof f.child_omp_agent_id === "string" ? f.child_omp_agent_id : null,
          child_omp_session_file: "child_omp_session_file" in f && typeof f.child_omp_session_file === "string" ? f.child_omp_session_file : null,
          worker_model: "worker_model" in f && typeof f.worker_model === "string" ? f.worker_model : null,
        },
        summary: "summary" in data && typeof data.summary === "string" ? data.summary.slice(0, 2048) : "",
      });
    }
    // Bound work at each native resume; overflow stays in the journal, not lost.
    if (pending.size > 128 || recoveryLimited) {
      getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_RECOVERY_LIMIT"));
      workerRecoverySessions.delete(session);
    }
    for (const { fields, summary } of [...pending.values()].slice(0, 128)) {
      rememberWorkerIdentity(observedWorkerTaskIds, fields.task_id);
      await emitWorkerCompletion(session, ctx, fields, summary);
    }
  };
  const WORKER_TASK_MARKER_RE = /\[SECOND_BRAIN_WORKER_TASK task_id=([^\s\]]+) packet_sha256=([0-9a-f]{64})(?: parent_session_id=([^\s\]]+))?\]/;
  const recordWorkerChildResults = async (
    event: ToolResultEvent,
    ctx: ExtensionContext,
    session: string,
  ): Promise<void> => {
    if (event.toolName !== "task") return;
    if (event.isError) {
      const count = Array.isArray(event.input.tasks) ? event.input.tasks.length : 1;
      for (let index = 0; index < count; index += 1) {
        const sourceKey = JSON.stringify([session, event.toolCallId, index]);
        const admission = workerAdmissionsBySource.get(sourceKey);
        if (!admission) continue;
        if (admission.accessIntent === "mutating") {
          await releaseUndispatchedAdmission(admission, "OMP_TASK_DISPATCH_FAILED");
        } else {
          pendingWorkerTaskIds.delete(admission.taskId);
          workerAdmissionsByTask.delete(admission.taskId);
          workerAdmissionsBySource.delete(sourceKey);
        }
      }
      const observerKey = JSON.stringify([session, event.toolCallId]);
      const hasBoundAttempt = Array.from(workerAdmissionsBySource.values()).some(
        (admission) =>
          admission.parentSessionId === session &&
          admission.toolCallId === event.toolCallId &&
          admission.accessIntent === "mutating",
      );
      if (!hasBoundAttempt) {
        disposeWorkerObserver(observerKey);
      }
    }
    if (event.details == null || typeof event.details !== "object") return;
    await recoverWorkerResults(session, ctx);
    const details = event.details as Record<string, unknown>;
    // Background spawns (this OMP version's default for the generic `task`
    // agent, confirmed live) return `results: []` on the spawning tool_result
    // and instead expose the marker-embedded task text via `progress[]`.
    // Bind the actual manager job id to packet identity and expected child id;
    // rendered output and agent-name equality are not correlation sources.
    const rawProgress = details.progress;
    if (Array.isArray(rawProgress)) {
      for (const rawEntry of rawProgress) {
        if (rawEntry == null || typeof rawEntry !== "object") continue;
        const entry = rawEntry as Record<string, unknown>;
        const agentId = typeof entry.id === "string" ? entry.id : undefined;
        const jobId = typeof entry.jobId === "string" ? entry.jobId : undefined;
        const entryTask = typeof entry.task === "string" ? entry.task : "";
        const marker = entryTask.match(WORKER_TASK_MARKER_RE);
        if (agentId === undefined || agentId.length === 0 || agentId.length > 512 ||
            jobId === undefined || jobId.length === 0 || jobId.length > 512 ||
            marker === null || (marker[3] !== undefined && marker[3] !== session)) continue;
        if (workerAdmissionsByTask.get(marker[1])?.accessIntent === "mutating") continue;
        if (reportedWorkerTaskIds.has(marker[1])) continue;
        const key = JSON.stringify([session, jobId]);
        if (pendingWorkerJobs.has(key)) continue;
        if (pendingWorkerJobs.size >= 1024 ||
            (!pendingWorkerTaskIds.has(marker[1]) && pendingWorkerTaskIds.size >= 1024)) {
          getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_PENDING_LIMIT"));
          continue;
        }
        pendingWorkerTaskIds.add(marker[1]);
        pendingWorkerJobs.set(key, {
          taskId: marker[1],
          packetSha256: marker[2],
          parentSessionId: marker[3] ?? session,
          agent: typeof entry.agent === "string" ? entry.agent : "unknown",
          agentId,
        });
        journalWorkerEvent(session, "second-brain.worker-job-pending", { session, jobId, ...pendingWorkerJobs.get(key) });
      }
    }
    const rawResults = details.results;
    if (!Array.isArray(rawResults)) return;
    for (const rawResult of rawResults) {
      if (rawResult == null || typeof rawResult !== "object") continue;
      const result = rawResult as Record<string, unknown>;
      const taskText = typeof result.task === "string" ? result.task : "";
      const marker = taskText.match(WORKER_TASK_MARKER_RE);
      if (marker === null || (marker[3] !== undefined && marker[3] !== session)) continue;
      if (result.aborted !== true && typeof result.abortReason !== "string" && event.isError !== true &&
          (typeof result.exitCode !== "number" || !Number.isFinite(result.exitCode))) continue;
      const status =
        result.aborted === true || typeof result.abortReason === "string"
          ? "cancelled"
          : event.isError === true || (typeof result.exitCode === "number" && result.exitCode !== 0)
            ? "failed"
            : "completed";
      const agentId = typeof result.id === "string" ? result.id : null;
      const firstBlock = Array.isArray(event.content) ? event.content[0] : undefined;
      const summaryText =
        firstBlock != null && typeof firstBlock === "object" && "text" in firstBlock && typeof firstBlock.text === "string"
          ? firstBlock.text
          : "";
      await emitWorkerCompletion(
        session,
        ctx,
        {
          task_id: marker[1],
          packet_sha256: marker[2],
          child_omp_agent_id: agentId,
          child_omp_session_file: typeof result.sessionFile === "string" ? result.sessionFile : null,
          worker_agent: typeof result.agent === "string" ? result.agent : "unknown",
          worker_model: typeof result.resolvedModel === "string" ? result.resolvedModel : null,
          status,
        },
        summaryText,
      );
    }
  };
  /** Observe explicit hub delivery using the same durable settlement as auto-delivery. */
  const recordAsyncWorkerCompletions = async (
    event: ToolResultEvent,
    ctx: ExtensionContext,
    session: string,
  ): Promise<void> => {
    if (event.toolName !== "hub" || event.details == null || typeof event.details !== "object") return;
    const rawJobs = (event.details as Record<string, unknown>).jobs;
    if (!Array.isArray(rawJobs)) return;
    await recoverWorkerResults(session, ctx);
    for (const rawJob of rawJobs) {
      if (rawJob == null || typeof rawJob !== "object") continue;
      const job = rawJob as Record<string, unknown>;
      if (job.type !== "task" || !["completed", "failed", "cancelled"].includes(String(job.status))) continue;
      const jobId = typeof job.id === "string" ? job.id : undefined;
      if (jobId === undefined) continue;
      const pending = takePendingWorkerJob(jobId, session);
      if (pending === undefined) continue;
      if (job.agentId !== undefined && job.agentId !== pending.agentId) {
        getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_AGENT_ID_MISMATCH"));
        continue;
      }
      const status = job.status === "completed" ? "completed" : job.status === "cancelled" ? "cancelled" : "failed";
      const summaryText =
        typeof job.resultText === "string"
          ? job.resultText
          : typeof job.errorText === "string"
            ? job.errorText
            : "";
      await emitWorkerCompletion(
        pending.parentSessionId,
        ctx,
        {
          task_id: pending.taskId,
          packet_sha256: pending.packetSha256,
          child_omp_agent_id: pending.agentId,
          child_omp_session_file: null,
          worker_agent: pending.agent,
          worker_model: typeof job.resolvedModel === "string" ? job.resolvedModel : null,
          status,
        },
        summaryText,
      );
    }
  };
  let structuredAsyncUnavailableReported = false;
  /** Native delivery metadata is authoritative; rendered text is summary only. */
  const recordAsyncResultDeliveries = async (
    message: MessageEndMessage,
    ctx: ExtensionContext,
  ): Promise<void> => {
    if (message.role !== "custom" || message.customType !== "async-result") return;
    const details = message.details;
    if (details === null || typeof details !== "object" || !("jobs" in details) || !Array.isArray(details.jobs)) {
      throw new Error("BRAIN_WORKER_RESULT_MALFORMED_ENVELOPE");
    }
    if (details.jobs.length > 128) throw new Error("BRAIN_WORKER_RESULT_ENVELOPE_TOO_LARGE");
    const session = resolveSessionId(ctx, anonSession);
    await recoverWorkerResults(session, ctx);
    let summary = typeof message.content === "string" ? message.content.slice(0, 2048) : "";
    if (Array.isArray(message.content)) {
      for (const part of message.content) {
        if (summary.length >= 2048) break;
        if (part !== null && typeof part === "object" && part.type === "text" && typeof part.text === "string") {
          summary += part.text.slice(0, 2048 - summary.length);
        }
      }
    }
    for (const job of details.jobs) {
      if (job === null || typeof job !== "object" || job.type !== "task" ||
          typeof job.jobId !== "string" || job.jobId.length > 512) continue;
      const pending = takePendingWorkerJob(job.jobId, session);
      if (pending === undefined || pending.parentSessionId !== session) continue;
      if (typeof job.status !== "string" || typeof job.agentId !== "string" ||
          job.agentId.length === 0 || job.agentId.length > 512) {
        if (!structuredAsyncUnavailableReported) {
          structuredAsyncUnavailableReported = true;
          getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_STRUCTURED_ASYNC_UNAVAILABLE"));
        }
        continue;
      }
      if (job.agentId !== pending.agentId) {
        getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_AGENT_ID_MISMATCH"));
        continue;
      }
      const status = job.status === "completed" || job.status === "failed" || job.status === "cancelled" ? job.status : undefined;
      if (status === undefined) {
        getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_RESULT_INVALID_STATUS"));
        continue;
      }
      await emitWorkerCompletion(pending.parentSessionId, ctx, {
        task_id: pending.taskId,
        packet_sha256: pending.packetSha256,
        child_omp_agent_id: job.agentId,
        child_omp_session_file: null,
        worker_agent: pending.agent,
        worker_model: null,
        status,
      }, summary);
    }
  };
  const mirrorWorkerContextReceipt = (
    prompt: string,
    session: string,
    ctx: ExtensionContext,
  ): void => {
    const marker = prompt.match(WORKER_TASK_MARKER_RE);
    if (marker === null) return;
    const rootSession = workerRootSessions.get(session) ?? null;
    if (rootSession === null) {
      getStore(session)?.append(sensors.extensionError(session, "BRAIN_WORKER_ANCESTRY_UNVERIFIED"));
    }
    mirror(
      session,
      "task_context_resolved",
      {
        task_id: marker[1],
        packet_sha256: marker[2],
        parent_session_id: rootSession,
        worker_session_id: session,
        status: "child_received",
      },
      { cwd: ctxCwd(ctx) },
    );
  };

  const modelCandidates = (ctx: ExtensionContext): OmpModelCandidate[] => {
    const model = ctx.model as (Record<string, unknown> & { provider?: unknown; id?: unknown }) | undefined;
    const raw = model?.candidates ?? model?.availableModels ?? model?.models;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (candidate): candidate is OmpModelCandidate =>
        candidate != null &&
        typeof candidate === "object" &&
        typeof (candidate as Record<string, unknown>).provider === "string" &&
        typeof (candidate as Record<string, unknown>).model === "string",
    );
  };

  const routingOptions = (
    session: string,
    task: string,
    ctx: ExtensionContext,
    role: string,
  ): OmpRoutingOptions => {
    const model = ctx.model;
    const budgetState = sessionBudgetStates.get(session);
    return {
      home: config.home ?? "",
      task,
      sessionId: session,
      projectId: process.env.SECOND_BRAIN_PROJECT ?? ctxCwd(ctx) ?? "",
      role,
      provider: typeof model?.provider === "string" ? model.provider : "",
      model: typeof model?.id === "string" ? model.id : "",
      cwd: ctxCwd(ctx),
      candidates: modelCandidates(ctx),
      ...(budgetState === "SOFT" ? { minimumTier: "efficient" } : {}),
    };
  };

  const ensureRoutingDecision = async (
    session: string,
    task: string,
    ctx: ExtensionContext,
    role: string,
  ): Promise<OmpRoutingResult> => {
    const taskHash = taskSha256(task);
    const key = `${session}:${currentTurnIndex}:${taskHash}`;
    const existing = routingCache.get(key);
    if (existing) return existing;
    latestRoutingDecision = null;
    const promise = routingRunner(routingOptions(session, task, ctx, role))
      .then((result) => {
        if (result.decision) {
          latestRoutingDecision = result.decision;
          latestRoutingSession = session;
          getStore(session)?.append(
            ompRoutingRecord("omp_routing_decision", session, {
              decision_id: result.decision.decision_id,
              task_hash: result.decision.task_hash,
              selected_provider: result.decision.selected_provider,
              selected_model: result.decision.selected_model,
              selected_tier: result.decision.selected_tier,
              fallback_used: result.decision.fallback_used,
              reason_code: result.decision.reason_code,
              status: result.decision.status,
            }),
          );
          mirror(session, "decision", {
            routing_event: "model_decision",
            decision_id: result.decision.decision_id,
            task_hash: result.decision.task_hash,
            selected_provider: result.decision.selected_provider,
            selected_model: result.decision.selected_model,
            fallback_used: result.decision.fallback_used,
          }, { cwd: ctxCwd(ctx), agentId: sensors.modelToString(ctx.model) ?? "omp" });
          if (
            result.decision.status === "selected" &&
            result.decision.selected_provider &&
            result.decision.selected_model &&
            !readySessions.has(session)
          ) {
            readySessions.add(session);
            getStore(session)?.append(ompRoutingRecord("OMP_SECOND_BRAIN_READY", session, {
              decision_id: result.decision.decision_id,
              task_hash: result.decision.task_hash,
            }));
            const emit = (pi as unknown as { emit?: (event: string, payload: unknown) => void }).emit;
            if (typeof emit === "function") emit.call(pi, "OMP_SECOND_BRAIN_READY", {
              decision_id: result.decision.decision_id,
              session,
            });
          }
        }
        return result;
      })
      .catch(() => ({ decision: null, error: "BRAIN_ROUTING_UNAVAILABLE" }));
    routingCache.set(key, promise);
    return promise;
  };

  const ensureVisibilityPlan = (
    session: string,
    task: string,
    ctx: ExtensionContext,
  ): Promise<OmpVisibilityResult> => {
    const taskHash = taskSha256(task);
    const key = `${session}:${currentTurnIndex}:${taskHash}`;
    const existing = visibilityCache.get(key);
    if (existing) return existing;
    const promise = Promise.resolve()
      .then(() =>
        visibilityRunner({
          home: config.home ?? "",
          task,
          sessionId: session,
          projectId: process.env.SECOND_BRAIN_PROJECT ?? ctxCwd(ctx) ?? "",
        }),
      )
      .then((result) => validateOmpVisibilityResult(result))
      .catch(() => ({
        visibility_plan: null,
        hydrated_instructions: {},
        error: "BRAIN_VISIBILITY_UNAVAILABLE",
      }))
      .then((result) => {
        try {
          getStore(session)?.append(
            ompVisibilityRecord("omp_visibility_plan", session, {
              mode: result.visibility_plan?.mode ?? null,
              selected_skill_ids: result.visibility_plan?.selected_skill_ids ?? [],
              hydrated_skill_ids: result.visibility_plan?.hydrated_skill_ids ?? [],
              visibility_plan_id: result.visibility_plan?.visibility_plan_id ?? null,
              error: result.error,
            }),
          );
        } catch {
          // Visibility telemetry is advisory and must never block injection.
        }
        return result;
      });
    visibilityCache.set(key, promise);
    return promise;
  };

  /**
   * Project attribution for mirror call sites (ledger-cwd-ordering-fix):
   * every mirror that has a ctx hands its cwd to `ledger init` so the FIRST
   * auto-init of a session — whichever event wins the per-process race —
   * resolves project_id through the AutoInject ladder instead of ''.
   */
  const ctxCwd = (ctx: ExtensionContext): string | undefined =>
    typeof ctx.cwd === "string" && ctx.cwd.length > 0 ? ctx.cwd : undefined;

  /**
   * Task 7: queue one bounded, non-blocking P4 pulse (heartbeat only —
   * Radar/fingerprints run on shutdown, never here) for `session_start`/
   * `turn_start`. Fire-and-forget: every bridge failure is silently
   * fail-open and never affects the host turn or return value.
   */
  const queueP4Pulse = (event: string, session: string, ctx: ExtensionContext): void => {
    runP4Pulse({
      home: config.home ?? "",
      hostSessionId: session,
      event,
      repo: ctxCwd(ctx),
    })
      .then((pulse) => {
        if (pulse.ok && pulse.heartbeat) {
          getStore(session)?.append(sensors.heartbeatPulse(session, pulse.heartbeat));
        }
      })
      .catch(() => {
        // bridge failure: bounded fail-open, never affects the host turn.
      });
  };

  /**
   * Phase B: VMem admission — the SMALLEST automatic path that stores an
   * ALREADY-COMPUTED, structured reference object (never raw prompt/tool
   * content) into VMem's session-object store (`second_brain vmem store`).
   * Gated behind [vmem_admission].enabled (default false, independent of
   * [vmem].enabled's compact-prep/hot-context bookkeeping). Fire-and-forget
   * and fail-open: a failing admission call only records an
   * extension_error, never blocks or throws from the calling hook.
   * `content` MUST already be a small structured object (ids/hashes/sizes
   * only) — callers never pass transcript/tool text here. `metadata`
   * (RC4 byte-exact recovery pass, Part A) is the SAME already-wired
   * `--metadata <json>` CLI flag (`vmem.ts`'s `VmemStoreOptions.metadata`,
   * previously unused by this call site) — small correlation/recovery keys
   * only (e.g. `packetArtifactRef`/`packetSha256`), never raw text.
   */
  const vmemAdmit = (
    session: string,
    kind: string,
    title: string,
    content: Record<string, unknown>,
    metadata?: Record<string, unknown>,
  ): Promise<{ ok: boolean; objId?: string; error?: string }> => {
    if (!loadVmemAdmissionConfig(config.home).enabled) {
      return Promise.resolve({ ok: false, error: "vmem admission disabled" });
    }
    return runVmemStore({
      home: config.home ?? "",
      hostSessionId: session,
      kind,
      title,
      content: sensors.safeJson(content),
      metadata,
    })
      .then((result) => {
        if (!result.ok) {
          getStore(session)?.append(
            mirrorExtensionError(session, `vmem store failed: ${result.error ?? "unknown"}`),
          );
        }
        return result;
      })
      .catch((error) => {
        getStore(session)?.append(
          sensors.extensionError(session, error),
        );
        return { ok: false, error: "vmem store failed" };
      });
  };

  wire<SessionStartEvent>("session_start", (event, ctx, session) => {
    establishWorkerRootSession(session, ctx);
    // Phase 0C SHADOW: decide + record only; session_start carries no task
    // text, so the adapter no-ops on empty tasks. Never returns a patch.
    void runShadowAutoInject({
      home: config.home ?? "",
      session,
      task: "",
      agentId: sensors.modelToString(ctx.model) ?? "prime",
      cwd: typeof ctx.cwd === "string" ? ctx.cwd : undefined,
      cfg: loadAutoInjectHostConfig(config.home),
      append: (record) => getStore(session)?.append(record),
    });
    const modelId = sensors.modelToString(ctx.model) ?? "unknown";
    const role = resolveAgentRole(
      modelId,
      loadDriverOrchestratorConfig(),
      loadOrchestratorGuardConfig().orchestratorModels,
    );
    const environment = runEnvironmentAssessmentSync({
      home: config.home ?? "",
      hostSessionId: session,
      repo: ctxCwd(ctx) ?? config.home ?? "",
      phase: "session_start",
    });
    if (environment.ok) {
      mirror(
        session,
        "environment_assessment",
        {
          phase: "session_start",
          environment_steward_id: environment.environmentStewardId ?? null,
          environment_hash: environment.environmentHash ?? null,
          mutation_detected: environment.mutationDetected ?? false,
          mutation_classification: environment.mutationClassification ?? "none",
          completion_eligible: environment.completionEligible ?? true,
        },
        { ignorable: true, cwd: ctxCwd(ctx) },
      );
    } else {
      getStore(session)?.append(
        mirrorExtensionError(session, environment.error ?? "environment assessment failed"),
      );
    }
    mirror(
      session,
      "session_started",
      {
        host: "prime",
        reason: event.reason,
        cwd: typeof ctx.cwd === "string" ? ctx.cwd : null,
        model: modelId,
        agent_id: modelId,
        role_profile: role,
        provider: modelId.split("/")[0] ?? "unknown",
        host_agent_id: modelId,
        environment_steward_id: environment.ok ? environment.environmentStewardId ?? null : null,
        environment_hash: environment.ok ? environment.environmentHash ?? null : null,
        environment_mutation_detected: environment.ok ? environment.mutationDetected ?? false : null,
        environment_mutation_classification: environment.ok ? environment.mutationClassification ?? "none" : "assessment_failed",
        environment_completion_eligible: environment.ok ? environment.completionEligible ?? true : false,
      },
      // Project attribution: session_started is the first mirrored event, so
      // the auto-init of the session ledger receives the host cwd (when known)
      // and `ledger init --cwd` resolves project_id via the AutoInject ladder.
      { agentId: modelId, cwd: ctxCwd(ctx) },
    );
    // Prime-owned artifact REFERENCES (never copied): transcript + telemetry.
    try {
      const transcript = ctx.sessionManager?.getSessionFile?.();
      if (typeof transcript === "string" && transcript.length > 0) {
        mirror(
          session,
          "host_artifact_ref",
          { kind: "transcript", path: transcript },
          { ignorable: true, cwd: ctxCwd(ctx) },
        );
      }
    } catch {
      // artifact reference is best-effort
    }
    if (config.telemetryDir) {
      mirror(
        session,
        "host_artifact_ref",
        { kind: "telemetry", path: join(config.telemetryDir, `${session}.jsonl`) },
        { ignorable: true, cwd: ctxCwd(ctx) },
      );
    }
    // Phase R6: capture Prime's real tool surface. getAllTools/getActiveTools
    // are declared on ExtensionAPI (prime.d.ts:306-309, "modelled for Phase J
    // measurement, not consumed today") — this is the first place in the
    // codebase that ever calls them. Read-only measurement; this pass never
    // calls setActiveTools (see outputs/reports/rc4/06-tool-working-set-live.md
    // for why: the Python Tool Working Set catalog's tool names — view_file,
    // run_command, git_commit_and_sync, ... — don't match Prime's real tool
    // names, and setActiveTools takes a REPLACEMENT list, so calling it with
    // fictional names would strip Prime's actual tool exposure).
    // Phase D (intentionally NOT implemented, per this pass's scope): stays
    // dormant until a real main-agent session (not this RLM/IPython-tool-
    // only shape) exposes a larger catalog — setActiveTools() takes a
    // REPLACEMENT list, so calling it against the single-tool ["ipython"]
    // catalog observed in pilot 1 would strip Prime's actual tool exposure.
    try {
      const allTools = typeof pi.getAllTools === "function" ? pi.getAllTools() : undefined;
      const activeTools =
        typeof pi.getActiveTools === "function" ? pi.getActiveTools() : undefined;
      if (allTools !== undefined || activeTools !== undefined) {
        getStore(session)?.append(
          sensors.primeToolSurface(
            session,
            Array.isArray(allTools) ? allTools.map((t) => t.name) : undefined,
            activeTools,
          ),
        );
      }
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    }
    queueP4Pulse("session_start", session, ctx);
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
    roleProfile: string,
  ): AdvisoryAutoInjectCall => ({
    home: config.home ?? "",
    session,
    task: typeof event.prompt === "string" ? event.prompt : "",
    agentId: sensors.modelToString(context.model) ?? "prime",
    cwd: typeof context.cwd === "string" ? context.cwd : undefined,
    projectId: resolvedProjectIdForSession(session) ?? resolveProject(),
    cfg: loadAutoInjectHostConfig(config.home),
    roleProfile,
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
  /** Keep the existing AutoInject custom message and append bounded active state. */
  function mergeActiveStateMessage(primary: unknown, active: unknown): unknown {
    if (active === undefined || active === null) return primary;
    if (primary === undefined || primary === null) return active;
    if (
      typeof primary === "object" &&
      typeof active === "object" &&
      primary !== null &&
      active !== null &&
      "content" in primary &&
      "content" in active &&
      typeof primary.content === "string" &&
      typeof active.content === "string"
    ) {
      const primaryDetails =
        "details" in primary && typeof primary.details === "object" && primary.details !== null
          ? primary.details
          : {};
      const activeDetails = "details" in active ? active.details : undefined;
      return {
        ...primary,
        content: `${primary.content}\n\n${active.content}`,
        details: {
          ...primaryDetails,
          active_state: activeDetails,
        },
      };
    }
    return primary;
  }
  /** Merge an enforced-mode skill-visibility injection into any existing
   * custom_message under its own "visibility" details key (P3.16) --
   * deliberately NOT routed through mergeActiveStateMessage's "active_state"
   * key, which mergeActiveStateMessage unconditionally overwrites on every
   * call: doing so would silently drop visibility_plan_id whenever AutoInject
   * mode, active-state mode, and an enforced visibility plan all coincide. */
  function mergeVisibilityMessage(primary: unknown, specialistText: string, visibilityPlanId: string): unknown {
    const visibility = { visibility_plan_id: visibilityPlanId };
    if (primary === undefined || primary === null) {
      return { content: specialistText, details: { visibility } };
    }
    if (typeof primary === "object" && "content" in primary && typeof primary.content === "string") {
      const primaryDetails =
        "details" in primary && typeof primary.details === "object" && primary.details !== null
          ? primary.details
          : {};
      return {
        ...primary,
        content: `${primary.content}\n\n${specialistText}`,
        details: { ...primaryDetails, visibility },
      };
    }
    return primary; // incompatible existing custom message shape -> fail open, keep it unchanged
  }

  /** T2.4: merge the dynamic Brain recall brief (TAIL slot -- hot-context
   * refs appended after the latest user message) into any existing custom
   * message, under its own "recall_brief" details flag. Never routed into
   * systemPrompt: PREFIX must stay session-constant/byte-stable across
   * turns (injection-slots.ts / the prefix-drift check in
   * before_agent_start). */
  function mergeRecallBriefMessage(primary: unknown, brief: string): unknown {
    if (primary === undefined || primary === null) {
      return { content: brief, details: { recall_brief: true } };
    }
    if (typeof primary === "object" && "content" in primary && typeof primary.content === "string") {
      const primaryDetails =
        "details" in primary && typeof primary.details === "object" && primary.details !== null
          ? primary.details
          : {};
      return {
        ...primary,
        content: `${primary.content}\n\n${brief}`,
        details: { ...primaryDetails, recall_brief: true },
      };
    }
    return primary; // incompatible existing custom message shape -> fail open, keep it unchanged
  }

  /** T3.1: merge the hard budget warning into the TAIL custom message slot. */
  function mergeBudgetWarningMessage(primary: unknown, warning: string): unknown {
    if (primary === undefined || primary === null) {
      return { content: warning, details: { budget_warning: true } };
    }
    if (typeof primary === "object" && "content" in primary && typeof primary.content === "string") {
      const primaryDetails =
        "details" in primary && typeof primary.details === "object" && primary.details !== null
          ? primary.details
          : {};
      return {
        ...primary,
        content: `${primary.content}\n\n${warning}`,
        details: { ...primaryDetails, budget_warning: true },
      };
    }
    return primary;
  }

  /** T3.4: merge the lean opportunity injection (NUDGE / FULL) into the TAIL custom message slot. */
  function mergeLeanMessage(primary: unknown, leanText: string): unknown {
    if (primary === undefined || primary === null) {
      return { content: leanText, details: { lean: true } };
    }
    if (typeof primary === "object" && "content" in primary && typeof primary.content === "string") {
      const primaryDetails =
        "details" in primary && typeof primary.details === "object" && primary.details !== null
          ? primary.details
          : {};
      return {
        ...primary,
        content: `${primary.content}\n\n${leanText}`,
        details: { ...primaryDetails, lean: true },
      };
    }
    return primary;
  }

  pi.on("before_agent_start", async (event, ctx) => {
    let session = "unknown";
    let aiCfg = loadAutoInjectHostConfig(config.home);
    let aiMessage: unknown = undefined;
    let activeMessage: unknown = undefined;
    let environmentTask: EnvironmentAssessmentResult | undefined;
    try {
      session = resolveSessionId(ctx, anonSession);
      establishWorkerRootSession(session, ctx);
      const modelId = sensors.modelToString(ctx.model) ?? undefined;
      const guardCfg = loadOrchestratorGuardConfig();
      const role = resolveAgentRole(
        modelId,
        loadDriverOrchestratorConfig(),
        guardCfg.orchestratorModels,
      );
      await recoverWorkerResults(session, ctx);
      mirrorWorkerContextReceipt(typeof event.prompt === "string" ? event.prompt : "", session, ctx);
      const environmentPrompt = typeof event.prompt === "string" ? event.prompt : "";
      const taskHash = taskSha256(environmentPrompt);
      if (taskHash && environmentTaskHashes.get(session) !== taskHash) {
        environmentTaskHashes.set(session, taskHash);
        environmentTask = runEnvironmentAssessmentSync({
          home: config.home ?? "",
          hostSessionId: session,
          repo: ctxCwd(ctx) ?? config.home ?? "",
          taskId: taskHash,
          phase: "task_boundary",
        });
        if (!environmentTask.ok) {
          getStore(session)?.append(
            mirrorExtensionError(session, environmentTask.error ?? "task environment assessment failed"),
          );
        }
      }
      // Phase 0C/0D: SHADOW = fire-and-forget (never returns a patch);
      // ADVISORY/ACTIVE = awaited and may append a low-authority
      // custom_message (packet carries "authority: advisory"). The message
      // is returned on EVERY role path (Phase C3 FIX 1): orchestrator and
      // driver merge it with their systemPrompt patch, worker/normal return
      // a bare { message } result — the host appends it as a model-visible
      // role:"custom" entry (SDK runner.ts emitBeforeAgentStart: messages
      // are collected from every handler result and inserted as custom
      // messages; _appendBeforeAgentStartMessages builds role:"custom").
      // Phase C10 (verifier): the BRANCH decision MUST read the same cfg as
      // the records — config.home is required so config/autoinject.toml
      // [autoinject] mode is honored (env-only cfg made the live flip
      // switch inert and silently ran the shadow branch).
      const taskText = typeof event.prompt === "string" ? event.prompt : "";
      if (
        config.home &&
        taskText.trim().length > 0 &&
        (aiCfg.mode === "advisory" || aiCfg.mode === "active")
      ) {
        const ensured = await runActiveStateEnsure({
          home: config.home,
          hostSessionId: session,
          objective: taskText,
          nextAction: taskText,
        });
        if (!ensured.ok) {
          getStore(session)?.append(
            sensors.extensionError(session, new Error(ensured.error ?? "active-state ensure failed")),
          );
        } else if (aiCfg.mode === "advisory" || aiCfg.mode === "active") {
          const rendered = await renderActiveState({
            home: config.home,
            hostSessionId: session,
          });
          if (!rendered.ok) {
            getStore(session)?.append(
              sensors.extensionError(session, new Error(rendered.error ?? "active-state render failed")),
            );
          } else {
            activeMessage = activeStateMessage(rendered);
            if (activeMessage !== undefined) {
              getStore(session)?.append(
                sensors.activeStateDelivery(
                  session,
                  ensured.capsuleSha256,
                  ensured.capsuleBytes,
                  rendered.renderedText?.length ?? 0,
                  ensured.changed === true,
                ),
              );
            }
          }
        }
      }
      aiCfg = loadAutoInjectHostConfig(config.home);
      if (aiCfg.mode === "advisory" || aiCfg.mode === "active") {
        aiMessage = await runAdvisoryAutoInject(autoinjectCall(session, event, ctx, role));
        // Phase B admission ref #1: AutoInject delivery. `aiMessage.details`
        // (delivery_id + packet_tokens) is the structured, non-transcript
        // reference already computed by messageFromOutcome (autoinject.ts)
        // â€” the packet TEXT itself (aiMessage.content) is never sent to
        // telemetry. RC4 byte-exact recovery pass Part A: BEFORE admitting,
        // preserve the EXACT packet text through the same preserve->verify
        // machinery RTD uses for raw tool output (`cliArtifactPreserver`,
        // kind="autoinject_packet", tool="autoinject"), so a LATER context-
        // paging fault-in can recover byte-exactly what the model actually
        // saw even if the underlying memory is superseded afterward. Fully
        // fail-open: any preserve/verify failure (or exception) falls back
        // to the EXISTING delivery-only admission shape unchanged; admission
        // itself, and the packet message returned to the host, are never
        // affected.
        if (aiMessage !== undefined && aiMessage !== null && typeof aiMessage === "object" && "details" in aiMessage) {
          const details = (aiMessage as { details?: unknown }).details;
          if (details !== null && typeof details === "object") {
            const detailsObj = details as Record<string, unknown>;
            const packetText = (aiMessage as { content?: unknown }).content;
            let packetMetadata: Record<string, unknown> | undefined;
            if (typeof packetText === "string" && packetText.length > 0) {
              try {
                const preserver =
                  options.autoinjectPacketPreserver ??
                  cliArtifactPreserver({
                    home: config.home ?? "",
                    session,
                    kind: "autoinject_packet",
                    tool: "autoinject",
                  });
                const preserved = await preserver.preserve(packetText);
                if (preserved !== null) {
                  const verified = await preserver.verify(preserved.sha256, packetText);
                  if (verified) {
                    packetMetadata = {
                      ...detailsObj,
                      packetArtifactRef: preserved.handle,
                      packetSha256: preserved.sha256,
                    };
                  }
                }
              } catch {
                // preserve/verify failed unexpectedly -> fail open, admit
                // with the existing delivery-only shape below (no metadata).
                packetMetadata = undefined;
              }
            }
            vmemAdmit(session, "RESEARCH_RESULT", "autoinject_delivery", detailsObj, packetMetadata);
          }
        }
      } else {
        void runShadowAutoInject(autoinjectCall(session, event, ctx, role));
      }
      if (config.home && taskText.trim().length > 0) {
        try {
          const visibilityResult = await ensureVisibilityPlan(session, taskText, ctx);
          if (
            visibilityResult.visibility_plan?.mode === "enforced" &&
            Object.keys(visibilityResult.hydrated_instructions).length > 0
          ) {
            // validateOmpVisibilityResult already rejects the whole plan if
            // the concatenated total exceeds OMP_VISIBILITY_MAX_INJECTED_CHARS
            // (P3.16 defect fix) -- hydrated_instructions is always within
            // budget here, so this slice is a redundant safety net, never
            // the active truncation path.
            const specialistText = Object.entries(visibilityResult.hydrated_instructions)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([, text]) => text)
              .join("\n\n")
              .slice(0, OMP_VISIBILITY_MAX_INJECTED_CHARS);
            aiMessage = mergeVisibilityMessage(
              aiMessage,
              specialistText,
              visibilityResult.visibility_plan.visibility_plan_id,
            );
          }
        } catch {
          // Visibility is advisory: any failure must not block AutoInject/session start.
        }
      }
      mirror(
        session,
        "user_task",
        {
          task_sha256: taskSha256(typeof event.prompt === "string" ? event.prompt : ""),
          prompt_chars: typeof event.prompt === "string" ? event.prompt.length : 0,
          environment_steward_id: environmentTask?.environmentStewardId ?? null,
          environment_hash: environmentTask?.environmentHash ?? null,
          environment_mutation_detected: environmentTask?.mutationDetected ?? false,
          environment_mutation_classification: environmentTask?.mutationClassification ?? "none",
          environment_completion_eligible: environmentTask?.completionEligible ?? true,
        },
        // ledger-cwd-ordering-fix: user_task is the FIRST mirror to reach the
        // ledger in real runs (its init spawn wins the per-process race), so
        // it MUST carry the cwd or project_id resolves to ''.
        { cwd: ctxCwd(ctx) },
      );
      const budgetCheck = await budgetRunner({
        home: config.home ?? "",
        sessionId: session,
        role,
      }).catch(() => ({ state: "OK" as const, used: null, cap: 0, error: "ACCOUNTING_UNAVAILABLE" }));
      sessionBudgetStates.set(session, budgetCheck.state);
      if (budgetCheck.error) getStore(session)?.append(sensors.extensionError(session, budgetCheck.error));
      const task = typeof event.prompt === "string" ? event.prompt.slice(0, 2048) : "";
      if (task.length > 0) {
        await ensureRoutingDecision(session, task, ctx, role);
      }
      // P3-D lean runtime adapter (plan §8): decide + record BEFORE the
      // branch points so every path emits exactly ONE lean_kernel record.
      // Sol resolves omit/role here and is never injected (the guard branch
      // returns before any kernel could be applied). The dedup check runs
      // against the pre-patch base; appendLeanKernel re-checks the assembled
      // prompt (contract + kernel) when applying.
      const promptValue = typeof ctx.getSystemPrompt === "function" ? ctx.getSystemPrompt() : undefined;
      const base = Array.isArray(promptValue)
        ? promptValue.join("\n\n")
        : typeof promptValue === "string"
          ? promptValue
          : undefined;
      const lean = decideLeanRuntime({ home: config.home ?? "", role, base });
      if (lean.error !== undefined) {
        getStore(session)?.append(sensors.extensionError(session, lean.error));
      }
      getStore(session)?.append(
        sensors.leanKernel(session, {
          decision: lean.decision,
          reason: lean.reason,
          role,
          skill_status: lean.skillStatus,
          mode: lean.mode,
          eval_source: lean.evalSource,
          kernel_chars: lean.kernelChars,
          dedup_hit: lean.dedupHit,
        }),
      );
      leanProviderEvidence.set(session, {
        marker: `[${LEAN_KERNEL_MARKER}]`,
        kernel: lean.kernel,
      });
      // T2.4 (injection-slots): the session-constant PREFIX slot is the
      // lean kernel + the two T1.6 memory commands + the project identity
      // line (skill descriptors are added when a global descriptor source
      // is wired). checkPrefixDrift seeds the baseline sha256 on the FIRST
      // before_agent_start call for a session (effectively "session start"
      // in this host's event model, since session_start carries no task/
      // role yet) and flags prefix_drift=1 on every later call whose
      // recomputed PREFIX differs byte-for-byte — mirrored (not the
      // telemetry store, so existing fixed-record-count assertions are
      // untouched) only when drift actually occurs.
      const prefix = assemblePrefix({
        projectId: resolvedProjectIdForSession(session) ?? resolveProject(),
        leanKernel: lean.decision === "inject" && lean.placement !== "tail" ? lean.kernel : undefined,
      });
      const prefixDrift = checkPrefixDrift(session, prefix);
      if (prefixDrift.drift) {
        mirror(
          session,
          "prefix_drift",
          { prefix_drift: 1, prefix_sha256: prefixDrift.hash },
          { cwd: ctxCwd(ctx) },
        );
      }
      if (isOrchestratorModel(modelId, guardCfg)) {
        getStore(session)?.append(sensors.beforeAgentStart(session, event.prompt, role));
        return withMessage({ systemPrompt: SOL_ORCHESTRATOR_CONTRACT }, mergeActiveStateMessage(aiMessage, activeMessage));
      }
      let patched = role === "driver" ? appendDriverContract(base) : base;
      const driverContractInjected = role === "driver" && patched !== undefined && patched !== base;
      getStore(session)?.append(
        sensors.beforeAgentStart(
          session,
          event.prompt,
          role,
          role === "driver" ? driverContractInjected : undefined,
        ),
      );
      // P3-D: apply the kernel AFTER the stable role/base context (driver
      // contract) and BEFORE the dynamic recall brief / AutoInject packet
      // (plan §7.4 ordering — the kernel lives in the systemPrompt patch;
      // the AutoInject packet is a separate custom message appended by the
      // host after the task; real assembly order is documented in
      // src/lean-code.ts). appendLeanKernel dedups on the stable marker and
      // never invents a prompt (undefined base stays undefined).
      if (lean.decision === "inject" && lean.kernel !== undefined && lean.placement !== "tail") {
        const merged = appendLeanKernel(patched, lean.kernel);
        if (merged !== patched) {
          patched = merged;
        }
      }
      // T2.4: deliver the remaining PREFIX components (the two T1.6 memory
      // commands + the project identity line) into the same systemPrompt
      // patch, right after the lean kernel -- PREFIX order is kernel,
      // skill descriptors (not yet wired on the TS side, see report),
      // T1.6 commands, project line. PREFIX must be session-constant on
      // EVERY session (Core Rule), so this is unconditional whenever a
      // real base prompt exists -- never gated on whether the driver
      // contract or lean kernel already modified `patched` (a worker/
      // normal-role turn that gets no other patch still needs PREFIX
      // delivered). appendPrefixExtras itself never invents a prompt
      // (returns undefined when base is undefined/empty) and dedups on
      // its own stable marker, so this is only ever delivered once per
      // accumulated base, exactly like the lean kernel and driver
      // contract above it.
      const withExtras = appendPrefixExtras(
        patched,
        resolvedProjectIdForSession(session) ?? resolveProject(),
      );
      if (withExtras !== undefined) {
        patched = withExtras;
      }
      // T2.4: the recall brief is dynamic per-turn content (hot-context
      // refs), so it belongs in the TAIL message slot appended after the
      // latest user message -- never in systemPrompt (PREFIX must stay
      // session-constant/byte-stable; see injection-slots.ts / the
      // prefix-drift check above). Evaluated independently of the
      // driver-contract/lean-kernel systemPrompt patch below, so a recall
      // miss (no rows, spawn failure) never drops that patch.
      const recallCfg = loadRecallGateConfig();
      let turnMessage: unknown = mergeActiveStateMessage(aiMessage, activeMessage);
      if (shouldAttemptRecall(event.prompt, recallCfg)) {
        const brief = await recallBrief(event.prompt, session, recallCfg);
        if (brief !== undefined) {
          turnMessage = mergeRecallBriefMessage(turnMessage, brief);
        }
      }
      if (sessionBudgetStates.get(session) === "HARD") {
        turnMessage = mergeBudgetWarningMessage(turnMessage, BUDGET_HARD_LINE);
      }
      if (lean.decision === "inject" && lean.kernel !== undefined && lean.placement === "tail") {
        turnMessage = mergeLeanMessage(turnMessage, lean.kernel);
      }
      if (role === "driver" && patched !== undefined) {
        return withMessage({ systemPrompt: patched }, turnMessage);
      }
      if (patched !== undefined && patched !== base) {
        return withMessage({ systemPrompt: patched }, turnMessage);
      }
      return withMessage(undefined, turnMessage);
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
      // Phase C3 FIX 1 hardening: a packet already computed by the pipeline
      // is NEVER dropped by a later handler failure (role resolution, config
      // load, prompt getter). Return it bare in advisory/active; shadow/off
      // keep returning undefined (aiMessage is undefined there).
      let message = mergeActiveStateMessage(aiMessage, activeMessage);
      if (sessionBudgetStates.get(session) === "HARD") {
        message = mergeBudgetWarningMessage(message, BUDGET_HARD_LINE);
      }
      if (
        message !== undefined &&
        (aiCfg.mode === "advisory" || aiCfg.mode === "active" || sessionBudgetStates.get(session) === "HARD")
      ) {
        return { message };
      }
    }
    return undefined;
  });

  wire<TurnStartEvent>("turn_start", (event, ctx, session) => {
    currentTurnIndex = event.turnIndex;
    queueP4Pulse("turn_start", session, ctx);
    return sensors.turnStart(session, event.turnIndex);
  });

  // context: registered DIRECTLY (Phase R3 fix), NOT through wire(). The host
  // applies this handler's return value as a real context replacement
  // (ContextEventResult{messages}, prime.d.ts:249-251/294-298) — but
  // wire()/safeHandler() (above) intentionally always returns `void` to the
  // host regardless of what the mapper computes (see
  // outputs/reports/rc4/02-prime-live-callgraph.md, "context" section: this
  // was the confirmed structural reason VMem paging could never reach the
  // host even once implemented). Telemetry stays unconditional and separate
  // from any future mutation decision, exactly like before_agent_start /
  // tool_result / session_before_compact below.
  //
  // Part B (RC4 pass): pilot 2 (outputs/reports/rc4/12-real-prime-pilot-2.md
  // "Observed context message schema") captured the REAL `event.messages`
  // element shape for the first time — no more guessing. A bounded
  // `{messages}` replacement patch is now implemented in context-paging.ts
  // (`pageContext`), gated behind `[context_paging] enabled=false` by
  // default (config/context.toml) and INDEPENDENT of [vmem]/
  // [vmem_admission]/[context_structure]. Only two element classes are ever
  // eligible for paging (see context-paging.ts's module docstring for the
  // exact rules); everything else — including the entire current-turn pin
  // window — passes through completely untouched, and the whole path is
  // fail-open (Part E): any error returns the original messages unchanged
  // and records an extension_error, never throws. NOTE: per
  // types/prime.d.ts, this handler's real host contract is SYNCHRONOUS
  // (`ContextEventResult | undefined`, no `Promise` variant, unlike
  // before_agent_start) — `pageContext` and its one VMem correlation query
  // are synchronous for that reason (see vmem.ts `runVmemListSync`).
  pi.on("context", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      getStore(session)?.append(sensors.context(session, event.messages));
      // Phase A: privacy-safe structural telemetry (config-gated, default
      // OFF; see sensors.contextStructure). Additive to the unconditional
      // .length-only record above — never replaces it.
      if (loadContextStructureConfig(config.home).enabled) {
        getStore(session)?.append(sensors.contextStructure(session, event.messages));
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
    }
    // Part B/E (RC4 pass): [context_paging] enabled=false by default — see
    // config/context.toml. `pageContext` is synchronous and NEVER throws
    // (Part E fail-open); it only ever returns a patch for the two eligible
    // classes documented in context-paging.ts, bounded by the current-turn
    // pin window, the resident token budget, and the per-event page cap.
    try {
      const pagingCfg = loadContextPagingConfig(config.home);
      if (pagingCfg.enabled && Array.isArray(event.messages)) {
        // T2.3 Cache break-point gate (a)-(e)
        // (a) previous tool_result bytes > [rtd].threshold_chars (default 8000)
        const rtdCfg = loadRtdConfig(config.home);
        const thresholdChars = parseThreshold(
          process.env.SECOND_BRAIN_RTD_THRESHOLD,
          rtdCfg.thresholdChars,
        );
        const toolBytes = lastToolResultBytes.get(session) ?? 0;
        const condA = toolBytes > thresholdChars;

        // (b) session_before_compact event occurred
        const condB = sessionBeforeCompactOccurred.has(session);

        // (c) model/provider changed since last request
        const currentIdentity = sensors.splitProviderModel(sensors.modelToString(ctx.model));
        const prevProv = lastContextProvider.get(session);
        const prevMod = lastContextModel.get(session);
        const condC =
          prevProv !== undefined &&
          prevMod !== undefined &&
          (currentIdentity.provider !== prevProv || currentIdentity.model !== prevMod);

        // (d) last assistant_usage.cache_read_tokens == 0
        const lastCache = lastCacheReadTokens.get(session);
        const condD = lastCache !== undefined && lastCache === 0;

        // (e) resident tokens > capacity_hard (default 6000 or 1.5 * budget)
        const capacityHard = Math.max(6000, Math.floor(pagingCfg.residentTokenBudget * 1.5));
        let residentTokens = 0;
        for (const msg of event.messages) {
          residentTokens += estimateTokens(msg, currentIdentity.model ?? undefined, config.home ?? undefined);
        }
        const condE = residentTokens > capacityHard;

        const breakPoint = condA || condB || condC || condD || condE;

        if (!breakPoint) {
          // No transformation is needed; preserve the host's current sequence.
          return undefined;
        }

        const paged = pageContext({
          home: config.home ?? "",
          hostSessionId: session,
          messages: event.messages,
          cfg: pagingCfg,
        });

        // Reset one-shot break flags
        sessionBeforeCompactOccurred.delete(session);
        lastToolResultBytes.delete(session);
        lastContextProvider.set(session, currentIdentity.provider);
        lastContextModel.set(session, currentIdentity.model);

        // the RESIDENT/FAULTED_IN group no longer forces the WHOLE event to
        // discard its patch — `paged.messages` can be defined (Path B
        // reprojection succeeded independently) AT THE SAME TIME as
        // `paged.error` (the Path A claim call failed). Apply the patch
        // whenever one exists, and separately/additionally record the
        // extension_error for observability. A pure fail-open call (no
        // patch at all) still records ONLY the extension_error, unchanged.
        if (paged.messages !== undefined) {
          getStore(session)?.append(
            sensors.contextPaging(session, paged.pagedCount, {
              candidateCount: paged.candidateCount,
              eligibleCount: paged.eligibleCount,
              pressureEstimatedTokens: paged.pressureEstimatedTokens,
              residentBudget: paged.residentBudget,
              requestedPageCount: paged.requestedPageCount,
              claimedPageCount: paged.claimedPageCount,
              newlyClaimedCount: paged.newlyClaimedCount,
              reprojectedPageCount: paged.reprojectedPageCount,
              estimatedTokensBefore: paged.estimatedTokensBefore,
              estimatedTokensAfter: paged.estimatedTokensAfter,
              objectKinds: paged.objectKinds,
              stateBefore: paged.stateBefore,
              stateAfter: paged.stateAfter,
            }),
          );
          if (paged.error !== undefined) {
            getStore(session)?.append(
              mirrorExtensionError(session, `context paging partial failure: ${paged.error}`),
            );
          }
          return { messages: paged.messages };
        } else if (paged.error !== undefined) {
          getStore(session)?.append(
            mirrorExtensionError(session, `context paging failed: ${paged.error}`),
          );
        }
      }
    } catch (error) {
      // Part E fail-open: this try/catch must never let a paging failure
      // reach the host — same discipline as every other handler here.
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
    }
    return undefined;
  });

  // ---------------------------------------------------------------------------
  // P3-B economics instrumentation (plan §5.1/§5.4/§5.5; schema v3 records).
  // Privacy (plan §25): provider_request_meta / provider_response_meta persist
  // keys, counts, sizes, and sha256 hashes ONLY — never payload text, tool
  // output, or raw header values. All three handlers are fail-open and
  // fire-and-forget like every other measurement handler. The two read-only
  // These hooks are direct registrations: the provider-request return value
  // is the supported OMP payload replacement contract.
  // ---------------------------------------------------------------------------

  let providerRequestSeq = 0;
  let lastEffectiveProvider: string | null = null;
  let lastEffectiveModel: string | null = null;
  const leanProviderEvidence = new Map<string, sensors.LeanProviderEvidence>();
  const payloadIdentity = (
    payload: unknown,
    ctx: ExtensionContext,
  ): { provider: string | null; model: string | null } => {
    const obj = payload != null && typeof payload === "object"
      ? payload as Record<string, unknown>
      : {};
    const contextIdentity = sensors.splitProviderModel(sensors.modelToString(ctx.model));
    if (typeof obj.model === "string") {
      const parsed = sensors.splitProviderModel(
        typeof obj.provider === "string" ? `${obj.provider}/${obj.model}` : obj.model,
      );
      return {
        provider: parsed.provider ?? contextIdentity.provider,
        model: parsed.model,
      };
    }
    return contextIdentity;
  };

  pi.on("before_provider_request", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      providerRequestSeq += 1;
      const original = event.payload;
      const identity = payloadIdentity(original, ctx);
      let effective = original;
      const selected = latestRoutingSession === session ? latestRoutingDecision : null;
      let handoffFailure: string | undefined;
      if (selected?.status === "selected" && selected.selected_provider && selected.selected_model) {
        const originalObject =
          original != null && typeof original === "object"
            ? original as Record<string, unknown>
            : null;
        const hasProvider = typeof originalObject?.provider === "string";
        const hasModel = typeof originalObject?.model === "string";
        if (originalObject && hasProvider && hasModel) {
          effective = {
            ...originalObject,
            provider: selected.selected_provider,
            model: selected.selected_model,
          };
        } else if (
          originalObject &&
          hasModel &&
          !hasProvider &&
          identity.provider === selected.selected_provider
        ) {
          effective = { ...originalObject, model: selected.selected_model };
        } else {
          handoffFailure = "OMP_PROVIDER_NOT_REPRESENTABLE";
          getStore(session)?.append(ompRoutingRecord("omp_routing_handoff_failure", session, {
            decision_id: selected.decision_id,
            task_hash: selected.task_hash,
            reason: handoffFailure,
            original_provider: identity.provider,
            original_model: identity.model,
          }));
        }
      }
      const effectiveIdentity = payloadIdentity(effective, ctx);

      // T2.3 Model-switch preflight (Deep Upgrade Plan U6 §7.4, literal order 1-8)
      const prevProv = lastProvider.get(session);
      const prevMod = lastModel.get(session);
      const isSwitch =
        prevMod !== undefined &&
        (effectiveIdentity.provider !== prevProv || effectiveIdentity.model !== prevMod);

      if (isSwitch) {
        const targetModel = effectiveIdentity.model ?? "default";
        const targetProvider = effectiveIdentity.provider ?? "default";

        // Step 1 & 2 (T2.6): resolve target context_tokens (config/v2.toml
        // [models].<id>, default 128_000) and cache scope (config/v2.toml
        // [providers].<id>.cache_scope, default "model") through the one
        // canonical provider-capability lookup.
        const preflightCaps = loadProviderCapabilities(config.home, targetModel, targetProvider);
        const targetCapacity = preflightCaps.contextTokens;
        const cacheScope = preflightCaps.cacheScope;

        // Step 3: If model-scoped, mark prefix cache cold (cache_read_tokens = 0)
        const cacheCold = cacheScope === "model";
        if (cacheCold) {
          lastCacheReadTokens.set(session, 0);
        }

        // Step 4: Recompute resident load with T0.6 estimator
        const payloadObj =
          effective != null && typeof effective === "object"
            ? (effective as Record<string, unknown>)
            : {};
        const messages = Array.isArray(payloadObj.messages) ? payloadObj.messages : [];
        let load = 0;
        for (const msg of messages) {
          load += estimateTokens(msg, targetModel, config.home ?? undefined);
        }
        const loadBefore = load;

        // Step 5: If load > target capacity * 0.85: run T2.0/T2.1 reclaim
        const reclaimThreshold = Math.floor(targetCapacity * 0.85);
        let reclaimedCount = 0;
        if (load > reclaimThreshold) {
          const reclaimResult = runVmemEvictSync({
            home: config.home ?? "",
            hostSessionId: session,
            budgetTokens: reclaimThreshold,
          });
          reclaimedCount = reclaimResult.evictedCount ?? 0;
          if (reclaimResult.evictedTokens !== undefined && reclaimResult.evictedTokens > 0) {
            load = Math.max(0, load - reclaimResult.evictedTokens);
          } else {
            const paged = pageContext({
              home: config.home ?? "",
              hostSessionId: session,
              messages,
              cfg: loadContextPagingConfig(config.home),
            });
            if (paged.messages !== undefined) {
              payloadObj.messages = paged.messages;
              effective = { ...payloadObj };
            }
            load = 0;
            for (const msg of (paged.messages ?? messages)) {
              load += estimateTokens(msg, targetModel, config.home ?? undefined);
            }
          }
        }

        // Step 6: Assert fit: if still load > target capacity: return INPUT_REQUIRED(CONTEXT_OVERFLOW)
        if (load > targetCapacity) {
          return {
            status: "INPUT_REQUIRED",
            error: "CONTEXT_OVERFLOW",
            reason: "INPUT_REQUIRED(CONTEXT_OVERFLOW)",
            target_capacity: targetCapacity,
            load,
          };
        }

        // Step 7: Emit MODEL_ROUTE_TRANSITION telemetry + decisions(kind="routing", propensity=1.0)
        getStore(session)?.append(
          sensors.modelRouteTransition(session, {
            current_provider: prevProv ?? null,
            current_model: prevMod ?? null,
            target_provider: targetProvider,
            target_model: targetModel,
            target_capacity: targetCapacity,
            cache_scope: cacheScope,
            cache_cold: cacheCold,
            load_before: loadBefore,
            load_after: load,
            reclaimed_count: reclaimedCount,
          }),
        );
        mirror(
          session,
          "decision",
          {
            routing_event: "MODEL_ROUTE_TRANSITION",
            kind: "routing",
            propensity: 1.0,
            current_provider: prevProv ?? null,
            current_model: prevMod ?? null,
            target_provider: targetProvider,
            target_model: targetModel,
          },
          { cwd: ctxCwd(ctx), agentId: sensors.modelToString(ctx.model) ?? "omp" },
        );

        // Step 8: Send / proceed
      }

      lastProvider.set(session, effectiveIdentity.provider);
      lastModel.set(session, effectiveIdentity.model);
      lastEffectiveProvider = effectiveIdentity.provider;
      lastEffectiveModel = effectiveIdentity.model;
      getStore(session)?.append(
        sensors.providerRequestMeta(
          session,
          effectiveIdentity.provider,
          effectiveIdentity.model,
          providerRequestSeq,
          effective,
          leanProviderEvidence.get(session),
        ),
      );
      if (selected) {
        getStore(session)?.append(ompRoutingRecord("omp_routing_invocation", session, {
          decision_id: selected.decision_id,
          task_hash: selected.task_hash,
          selected_provider: selected.selected_provider,
          selected_model: selected.selected_model,
          effective_provider: effectiveIdentity.provider,
          effective_model: effectiveIdentity.model,
          handoff_failure: handoffFailure ?? null,
        }));
      }
      return effective === original ? undefined : effective;
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // fail open
      }
      return undefined;
    }
  });

  pi.on("after_provider_response", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      const headers = event.headers ?? {};
      const provider = headers["x-provider"] ?? headers["provider"];
      const model = headers["x-model"] ?? headers["model"];
      const contextIdentity = sensors.splitProviderModel(sensors.modelToString(ctx.model));
      const actualProvider =
        typeof provider === "string"
          ? provider
          : latestRoutingSession === session
            ? lastEffectiveProvider
            : contextIdentity.provider;
      const actualModel =
        typeof model === "string"
          ? model
          : latestRoutingSession === session
            ? lastEffectiveModel
            : contextIdentity.model;
      getStore(session)?.append(
        sensors.providerResponseMeta(session, actualProvider, actualModel, event.status, event.headers),
      );
      const responseDecision = latestRoutingSession === session ? latestRoutingDecision : null;
      if (responseDecision) {
        getStore(session)?.append(ompRoutingRecord("omp_routing_response", session, {
          decision_id: responseDecision.decision_id,
          task_hash: responseDecision.task_hash,
          selected_provider: responseDecision.selected_provider,
          selected_model: responseDecision.selected_model,
          actual_provider: actualProvider,
          actual_model: actualModel,
          status: event.status,
        }));
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // fail open
      }
    }
  });

  // message_end: capture per-assistant-message usage (plan §5.1). Registered
  // directly (not via wire) because the runtime consumes the return value: the
  // handler MUST return the finalized message unchanged ({ message }) — the
  // host replaces the message in place and rejects role changes
  // (agent-session.ts:3315); returning the same object is a provably safe
  // no-op that keeps the original role.
  pi.on("message_end", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      const message = event.message;
      if (message != null && message.usage != null) {
        const u = message.usage as unknown as Record<string, unknown>;
        const cr = sensors.usageCounter(u.cacheRead);
        if (cr !== undefined) {
          lastCacheReadTokens.set(session, cr);
        }
        const routed =
          latestRoutingSession === session && lastEffectiveProvider && lastEffectiveModel
            ? { provider: lastEffectiveProvider, model: lastEffectiveModel }
            : null;
        const model =
          routed?.model ??
          (typeof message.model === "string" ? message.model : (ctx.model?.id ?? null));
        const provider =
          routed?.provider ??
          (typeof message.provider === "string" ? message.provider : (ctx.model?.provider ?? null));
        const record = sensors.assistantUsage(
          session,
          provider,
          model,
          message.usage,
        );
        if (record) getStore(session)?.append(record);
      }
      // Native OMP 18.1.10 awaits extension handlers. Await settlement instead
      // of abandoning its child process when the host finishes this turn.
      if (message?.role === "custom" && message.customType === "async-result") {
        return recordAsyncResultDeliveries(message, ctx).then(() => ({ message: event.message })).catch((error: unknown) => {
          try {
            getStore(session)?.append(sensors.extensionError(session, error));
          } catch {
            // storage failed too — measurement must not crash the session.
          }
          return { message: event.message };
        });
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
    }
    return { message: event.message };
  });

  /**
   * Phase 14 / T2.4: run ONE bounded Brain recall for a substantial non-Sol
   * prompt and return the rendered Brain Brief text for the TAIL message
   * slot (appended after the latest user message, never merged into
   * systemPrompt -- PREFIX must stay session-constant/byte-stable). Fail
   * silent on every error path (never throws, never returns partial text).
   */
  async function recallBrief(
    prompt: string,
    session: string,
    cfg: RecallGateConfig,
  ): Promise<string | undefined> {
    try {
      const home = resolveBrainHome();
      if (!home) return undefined;
      const rows = (await runBrainRecall({ home, query: prompt, cfg })) ?? [];
      return buildBrainBrief(rows, cfg.maxRows);
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — stay silent
      }
      return undefined;
    }
  }

  // tool_call: read-only measurement + minimal-orchestrator guard, plus the
  // narrow OMP task-dispatch Context Capsule bridge. Task input is replaced
  // only for `task` calls after Brain prepares a bounded handoff; parent
  // transcript content is never read or copied.
  pi.on("tool_call", (event, ctx): ToolCallEventResult | Promise<ToolCallEventResult | undefined> | undefined => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      establishWorkerRootSession(session, ctx);
      const rootSession = workerRootSessions.get(session) ?? session;
      if (sessionBudgetStates.get(session) === "HARD" || sessionBudgetStates.get(rootSession) === "HARD") {
        return { block: true, reason: BUDGET_HARD_LINE };
      }
      const command =
        typeof event.input?.command === "string" ? event.input.command : "";
      const isStopControl =
        event.toolName === "bash" && STOP_CONTROL_COMMAND.test(command);
      const rewrittenCommand =
        isStopControl || rewriteSessionPlaceholders(command, session, rootSession) !== command
          ? (isStopControl
            ? rewriteStopControlCommand(command, session, rootSession)
            : rewriteSessionPlaceholders(command, session, rootSession))
          : command;
      const stopState = stopStateFor(session);
      if (stopState.shouldBlock(event.toolName) && !(isStopControl && stopControlIdentity(rewrittenCommand))) {
        getStore(session)?.append({
          v: 2,
          ts: new Date().toISOString(),
          kind: "stop_blocked",
          session,
          tool: event.toolName,
          tool_call_id: event.toolCallId,
          reason_code: stopState.current?.reason_code ?? "stop_boundary",
        });
        return { block: true, reason: "Second Brain STOP boundary is active" };
      }
      getStore(session)?.append(sensors.toolCall(session, event.toolName, event.toolCallId, event.input));
      mirror(
        session,
        "tool_requested",
        {
          tool: event.toolName,
          input_bytes: sensors.byteLength(JSON.stringify(event.input ?? {})),
          control_plane: isStopControl,
        },
        { cwd: ctxCwd(ctx) },
      );
      const modelId = sensors.modelToString(ctx.model) ?? undefined;
      const decision = orchestratorPolicyFor(modelId, event.toolName, loadOrchestratorGuardConfig());
      if (decision.block) {
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
      if (isStopControl) {
        const key = `${session}\u0000${event.toolCallId}`;
        const identity = stopControlIdentity(rewrittenCommand);
        const targetRoot = identity ? workerRootSessions.get(identity.session) ?? identity.session : session;
        const sessionFile = ctx?.sessionManager?.getSessionFile?.();
        const applicable = identity !== undefined && typeof sessionFile === "string" &&
          sessionIdFromFile(sessionFile) === session &&
          (identity.session === session || workerRootSessions.get(identity.session) === session) &&
          (identity.parent === undefined || identity.parent === targetRoot) &&
          (identity.worker === undefined || identity.worker === identity.session);
        if (!stopControlCalls.has(key) && stopControlCalls.size >= 1024) {
          const oldest = stopControlCalls.keys().next().value;
          if (oldest !== undefined) stopControlCalls.delete(oldest);
        }
        stopControlCalls.set(key, {
          session, command: rewrittenCommand, originalCommand: command,
          identity: applicable && !stopControlCalls.has(key) ? identity : undefined, parentSession: targetRoot,
        });
      }
      if (event.toolName === "task") {
        return prepareWorkerTaskInput(event, ctx, session).catch((error) => {
          try {
            getStore(session)?.append(sensors.extensionError(session, error));
          } catch {
            // measurement must not disturb the session.
          }
          return { block: true, reason: "BRAIN_WORKER_CONTEXT_UNAVAILABLE" };
        });
      }
      const readPath = rereadPath(event.toolName, event.input ?? {});
      if (readPath && config.home) {
        const configuredMode = process.env.SECOND_BRAIN_REREAD_AVOIDANCE?.trim().toUpperCase();
        const mode =
          configuredMode === "ACTIVE" || configuredMode === "SHADOW" || configuredMode === "OFF"
            ? configuredMode
            : loadRereadAvoidance(config.home);
        if (mode !== "OFF") {
          return rereadRunner(config.home, session, readPath, mode, event.toolName, event.toolCallId).then((hint) => {
            if (hint?.unchanged === true && mode === "ACTIVE" &&
                rereadReplacementAllowed(event.toolName, event.input ?? {})) {
              pendingRereads.set(`${session}\u0000${event.toolCallId}`, { path: readPath });
            }
            return rewrittenCommand !== command ? { input: { ...event.input, command: rewrittenCommand } } : undefined;
          }).catch(() => undefined);
        }
      }
      if (rewrittenCommand !== command) {
        return { input: { ...event.input, command: rewrittenCommand } };
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not disturb the session.
      }
    }
    return undefined;
  });

  // Phase 5 RTD (P3-F: substitution when config/context.toml [rtd]
  // enabled=true; shadow-only otherwise). After the normal tool_result
  // record, eligible large bash results (pytest/git/rg/grep) are FIRST
  // preserved byte-exactly via the artifact store and verified recoverable
  // (plan §11.4); only then is the model-visible content replaced by the
  // deterministic [SECOND_BRAIN_RTD] block. Preservation failure returns the
  // ORIGINAL content unchanged (never trade recoverability for savings).
  // Registered directly (not via wire) because the handler may return a
  // {content} patch that the host applies to the tool result (SDK
  // ToolResultEventResult; Phase A probe proven live).
  //
  // Phase 3 (corrected): RTD eligibility (tool/command) is decided FIRST —
  // before ANY content measurement. Eligible results get one JSON.stringify
  // attempt plus one UTF-8 byte count in `measureContent`, shared by
  // ordinary telemetry (`output_bytes`) and RTD evaluation/recording
  // (`serializedChars`). Ineligible results perform ZERO RTD-specific
  // serialization. The precomputed eligibility is passed through so RTD
  // never re-measures.
  pi.on("tool_result", async (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      let rereadPatch: { content: Array<{ type: "text"; text: string }> } | undefined;
      const rereadKey = `${session}\u0000${event.toolCallId}`;
      const pending = pendingRereads.get(rereadKey);
      if (pending) {
        pendingRereads.delete(rereadKey);
        const configuredMode = process.env.SECOND_BRAIN_REREAD_AVOIDANCE?.trim().toUpperCase();
        const mode =
          configuredMode === "ACTIVE" || configuredMode === "SHADOW" || configuredMode === "OFF"
            ? configuredMode
            : loadRereadAvoidance(config.home);
        if (mode === "ACTIVE" && !event.isError && config.home) {
          const hint = await rereadRunner(config.home, session, pending.path);
          const marker = hint ? unchangedMarker(pending.path, hint) : undefined;
          if (marker) rereadPatch = { content: [{ type: "text", text: marker }] };
        }
      }
      const stopKey = `${session}\u0000${event.toolCallId}`;
      const stopCall = stopControlCalls.get(stopKey);
      const resultCommand = typeof event.input?.command === "string" ? event.input.command : "";
      const isStopControl = stopCall !== undefined && event.toolName === "bash" &&
        (resultCommand === stopCall.command || resultCommand === stopCall.originalCommand);
      if (!isStopControl && (stopCall || (event.toolName === "bash" && STOP_CONTROL_COMMAND.test(resultCommand)))) {
        rejectStopEvidence(session, "invocation_mismatch");
        return undefined;
      }
      const stopState = stopStateFor(session);
      if (stopState.shouldBlock(event.toolName) && !isStopControl) {
        getStore(session)?.append({
          v: 2,
          ts: new Date().toISOString(),
          kind: "stop_blocked_result",
          session,
          tool: event.toolName,
          tool_call_id: event.toolCallId,
        });
        return undefined;
      }
      if (isStopControl) {
        stopControlCalls.delete(stopKey);
        const content = Array.isArray(event.content) ? event.content : [];
        const stopText = extractTextContent(content);
        getStore(session)?.append({
          v: 2,
          ts: new Date().toISOString(),
          kind: "stop_control_result",
          session,
          tool_call_id: event.toolCallId,
          content_item_count: content.length,
          content_item_types: content.slice(0, 4).map((item) =>
            item === null ? "null" : Array.isArray(item) ? "array" : typeof item,
          ),
          output_chars: stopText?.length ?? 0,
        });
        const evidence = parseStopDecisionOutput(stopText ?? "");
        if (event.isError || !evidence || !stopCall.identity ||
            stopCall.session !== session || !stopEvidenceMatches(evidence, stopCall.identity, stopCall.parentSession)) {
          rejectStopEvidence(session, event.isError ? "tool_error" : !evidence ? "malformed_evidence" : "identity_mismatch");
        } else if (evidence.decision !== "stop" || !stopStateFor(stopCall.identity.session).stopped) {
          const targetState = stopStateFor(stopCall.identity.session);
          targetState.accept(evidence);
          const fields = {
            stop_id: evidence.stop_id,
            task_id: evidence.task_id,
            session_id: evidence.session_id,
            parent_session_id: evidence.parent_session_id,
            worker_session_id: evidence.worker_session_id,
            decision: evidence.decision,
            reason_code: evidence.reason_code,
            triggering_condition: evidence.triggering_condition,
            verification_state: evidence.verification_state,
            completion_condition_state: evidence.completion_condition_state,
            final_substantive_event: evidence.final_substantive_event,
            stop_boundary_seq:
              typeof evidence.sequence === "number" ? evidence.sequence : null,
            substantive_events_after_boundary: targetState.substantiveEventsAfterBoundary,
            finalization_state:
              evidence.decision === "stop" ? "execution_blocked" : "not_triggered",
          };
          getStore(stopCall.identity.session)?.append({
            v: 2,
            ts: new Date().toISOString(),
            kind: evidence.decision === "stop" ? "stop_boundary" : "stop_not_triggered",
            session: stopCall.identity.session,
            ...fields,
          });
          if (evidence.decision === "stop") {
            const finalization = mirrorEventSync({
              home: config.home ?? "",
              hostSessionId: stopCall.identity.session,
              parentSessionId: stopCall.parentSession !== stopCall.identity.session ? stopCall.parentSession : undefined,
              record: {
                kind: "stop_finalized",
                fields,
                agentId: stopCall.identity.session,
              },
              cwd: ctxCwd(ctx),
            });
            if (!finalization.ok) {
              getStore(session)?.append({
                v: 2,
                ts: new Date().toISOString(),
                kind: "stop_finalization_error",
                session,
                error: finalization.error ?? "ledger append failed",
              });
            }
          }
        }
      }
      await recordWorkerChildResults(event, ctx, session);
      await recordAsyncWorkerCompletions(event, ctx, session);
      const rtdCfg = loadRtdConfig(config.home);
      const eligibility = rtdEligibility(event.toolName, event.input, rtdCfg);
      // ONE shared measurement (Phase 3 correction); mirror reuses output_bytes.
      const measurement = measureContent(event.content, eligibility === "ok");
      const rtd = await runRtd({
        session,
        tool: event.toolName,
        id: event.toolCallId,
        input: event.input,
        content: Array.isArray(event.content) ? event.content : [],
        isError: event.isError === true,
        measurement,
        threshold: parseThreshold(process.env.SECOND_BRAIN_RTD_THRESHOLD),
        cfg: rtdCfg,
        preserver:
          options.rtdPreserver ??
          cliRtdPreserver({ home: config.home ?? "", session }),
      });
      if (rtd.record) getStore(session)?.append(rtd.record);
      // Phase B admission ref #2: RTD-preserved artifact. Only when RTD
      // actually substituted (real preservation + verify already ran) —
      // content is the artifact pointer/sha256/size metadata RTD already
      // computed, never the raw or distilled tool text.
      // RC4 CVM closure repair (Repair A): the 5th `metadata` argument was
      // previously omitted here (unlike the AutoInject admission call site
      // below), so this object's `metadata_json` was always `{}` and could
      // never correlate in context-paging.ts's `byToolCallId` map — an
      // RTD-backed object could structurally never become a paging
      // candidate (Pilot 4, outputs/reports/rc4/14-real-prime-pilot-4.md).
      // `toolCallId`/`artifactRef` are the SAME real, already-verified
      // values already used above (`event.toolCallId`, in scope from this
      // handler's signature; `rtd.record.artifact_ref`, identical to the
      // artifact_ref already placed in `content`) — no new identity, no
      // raw/distilled tool text, same existing gate, unweakened.
      let vmemResult: { ok: boolean; objId?: string; error?: string } | undefined;
      if (rtd.record?.distilled === true) {
        vmemResult = await vmemAdmit(
          session,
          "TOOL_OBSERVATION",
          "rtd_artifact",
          {
            artifact_ref: rtd.record.artifact_ref,
            original_chars: rtd.record.original_chars,
            visible_chars: rtd.record.visible_chars,
            saved_chars: rtd.record.saved_chars,
            command_class: rtd.record.command_class,
          },
          {
            toolCallId: event.toolCallId,
            artifactRef: rtd.record.artifact_ref,
          },
        );
      }
      const artifactRef = rtd.record?.artifact_ref ?? null;
      const artifactSha256 =
        typeof artifactRef === "string"
          ? artifactRef.match(/sha256:([0-9a-f]{64})/)?.[1] ?? null
          : null;
      mirror(
        session,
        "tool_completed",
        {
          tool: event.toolName,
          tool_call_id: event.toolCallId,
          result_bytes: measurement.outputBytes,
          is_error: event.isError === true,
          rtd_distilled: rtd.record?.distilled === true,
          rtd_original_chars: rtd.record?.original_chars ?? null,
          rtd_visible_chars: rtd.record?.visible_chars ?? null,
          rtd_saved_chars: rtd.record?.saved_chars ?? null,
          rtd_artifact_sha256: artifactSha256,
          rtd_artifact_ref: artifactRef,
          rtd_command_class: rtd.record?.command_class ?? null,
          vmem_obj_id: vmemResult?.objId ?? null,
          recovery_status:
            rtd.record?.distilled !== true
              ? "not_applicable"
              : vmemResult?.ok === true
                ? "admitted"
                : "admission_failed",
        },
        { cwd: ctxCwd(ctx) },
      );
      getStore(session)?.append(
        sensors.toolResult(
          session,
          event.toolName,
          event.toolCallId,
          event.isError,
          measurement.outputBytes,
        ),
      );
      lastToolResultBytes.set(session, measurement.outputBytes);
      return rereadPatch ?? rtd.patch;
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — measurement must not crash the session.
      }
      return undefined;
    }
  });

  wire<TurnEndEvent>("turn_end", (event, ctx, session) => {
    let usage: Parameters<typeof sensors.turnEnd>[2] = undefined;
    try {
      usage = ctx.getContextUsage ? ctx.getContextUsage() : undefined;
    } catch {
      usage = undefined;
    }
    mirror(
      session,
      "turn_end",
      {
        turn_index: event.turnIndex,
        tool_result_count: Array.isArray(event.toolResults) ? event.toolResults.length : 0,
      },
      { cwd: ctxCwd(ctx) },
    );
    return sensors.turnEnd(session, event.turnIndex, usage, event.toolResults);
  });

  // agent_end: P0-G9 write-back is intentionally NOT wired here. The SDK
  // AgentEndEvent carries only `messages: AgentMessage[]` — no outcome,
  // summary, or task-success signal — so any extraction would be fabrication.
  // Documented no-op; write-back happens through explicit `brainctl
  // autoinject writeback` (Python authority) and the Codex Stop trigger.
  wire<AgentEndEvent>("agent_end", (event, ctx, session) => {
    mirror(
      session,
      "agent_ended",
      {
        message_count: Array.isArray(event.messages) ? event.messages.length : 0,
      },
      { cwd: ctxCwd(ctx) },
    );
    return sensors.agentEnd(session, event.messages);
  });

  // session_before_compact: pre-compaction DURABILITY BARRIER (plan §10.2).
  // The checkpoint is AWAITED (5s timeout). On flush/integrity failure the
  // handler returns { cancel: true } — the host throws "Compaction cancelled"
  // (SDK agent-session.ts:7199 reads result.cancel) and no context is lost.
  // The event is registered directly (not via wire) so the handler can await.
  pi.on("session_before_compact", async (event, ctx) => {
    const compactEvent = event as SessionBeforeCompactEvent;
    let session = "unknown";
    try {
      session = resolveSessionId(ctx, anonSession);
      sessionBeforeCompactOccurred.add(session);
      mirror(
        session,
        "compaction_started",
        {
          branch_entries: Array.isArray(compactEvent.branchEntries)
            ? compactEvent.branchEntries.length
            : 0,
        },
        { cwd: ctxCwd(ctx) },
      );
      // measurement record first (every lifecycle event writes one record),
      // then the durability barrier decides whether compaction may proceed.
      getStore(session)?.append(
        sensors.sessionBeforeCompact(session, compactEvent.branchEntries),
      );
      const activeStateCfg = loadAutoInjectHostConfig(config.home);
      if (activeStateCfg.mode === "advisory" || activeStateCfg.mode === "active") {
        const activeState = await runActiveStateUpdate({
          home: config.home ?? "",
          hostSessionId: session,
          verification: { pre_compaction: "persisted" },
        });
        if (!activeState.ok) {
          getStore(session)?.append(
            sensors.extensionError(session, new Error(activeState.error ?? "active-state checkpoint failed")),
          );
          return { cancel: true };
        }
      }
      const checkpoint = await runLedgerCheckpoint({
        home: config.home ?? "",
        hostSessionId: session,
      });
      if (!checkpoint.ok) {
        mirror(
          session,
          "ledger_degraded",
          {
            reason: "pre-compaction checkpoint failed",
            detail: checkpoint.error ?? "integrity bad",
          },
          { ignorable: true, cwd: ctxCwd(ctx) },
        );
        getStore(session)?.append(
          mirrorExtensionError(session, `pre-compaction checkpoint failed: ${checkpoint.error ?? "integrity bad"}`),
        );
        return { cancel: true };
      }
      // Phase B admission ref #3: compaction-boundary checkpoint. Content is
      // exactly the checkpoint outcome + branch_entries count already
      // computed above (not new data collection) + a fixed reason string.
      vmemAdmit(session, "DECISION", "pre_compaction_checkpoint", {
        branch_entries: Array.isArray(compactEvent.branchEntries)
          ? compactEvent.branchEntries.length
          : 0,
        checkpoint_ok: checkpoint.ok,
        reason: "pre-compaction checkpoint",
      });
      // Phase R3: VMem compaction-boundary bookkeeping (vmem.py §6.7 "Compaction
      // barrier interaction" — its own documented integration point). Advisory
      // only: never cancels compaction (the ledger checkpoint above is the sole
      // durability barrier). Disabled by default ([vmem] enabled=false) until a
      // live pilot proves this sound; see outputs/reports/rc4/02-prime-live-callgraph.md.
      const vmemCfg = loadVmemConfig(config.home);
      if (vmemCfg.enabled) {
        const prep = await runVmemCompactPrep({ home: config.home ?? "", hostSessionId: session });
        if (prep.ok) {
          getStore(session)?.append(
            sensors.vmemCompactPrep(session, prep.evictedAtCompaction, prep.pinnedPreserved),
          );
        } else {
          getStore(session)?.append(
            mirrorExtensionError(session, `vmem compact-prep failed: ${prep.error ?? "unknown"}`),
          );
        }
      }
    } catch (error) {
      try {
        getStore(session)?.append(sensors.extensionError(session, error));
      } catch {
        // storage failed too — stay silent
      }
      return { cancel: true }; // never compact on an unproven barrier
    }
    return undefined;
  });

  wire<SessionCompactEvent>("session_compact", (event, ctx, session) => {
    mirror(
      session,
      "compaction_completed",
      { from_extension: event.fromExtension === true },
      { cwd: ctxCwd(ctx) },
    );
    // Compaction boundary: close the prior segment and open a new one
    // (plan §10.3) — fire-and-forget; failure only records an extension_error.
    runLedgerSegmentRollover({
      home: config.home ?? "",
      hostSessionId: session,
      onError: (error) => {
        try {
          getStore(session)?.append(mirrorExtensionError(session, `segment rollover: ${error}`));
        } catch {
          // storage failed too — stay silent
        }
      },
    });
    // Phase R3: VMem hot-context render after the real compaction event —
    // fire-and-forget (mirror is fire-and-forget style already used above),
    // records what the resident/evicted working set looks like post-compact.
    // Renders only; does not touch model-visible context (see context handler).
    const vmemCfg = loadVmemConfig(config.home);
    if (vmemCfg.enabled) {
      runVmemHotContext({
        home: config.home ?? "",
        hostSessionId: session,
        budgetTokens: vmemCfg.budgetTokens,
      })
        .then((hc) => {
          if (hc.ok) {
            getStore(session)?.append(
              sensors.vmemHotContext(session, hc.residentCount, hc.evictedCount, hc.residentTokens),
            );
          } else {
            getStore(session)?.append(
              mirrorExtensionError(session, `vmem hot-context failed: ${hc.error ?? "unknown"}`),
            );
          }
        })
        .catch(() => {
          // storage/subprocess failed too — measurement must not crash the session.
        });
    }
    return sensors.sessionCompact(session, event.fromExtension);
  });

  wire<SessionShutdownEvent>(
    "session_shutdown",
    (event, ctx, session) => {
      for (const key of workerObservationDisposers.keys()) {
        const [ownerSession, toolCallId] = JSON.parse(key) as unknown[];
        if (ownerSession !== session) continue;
        const awaitingCleanup = Array.from(workerAdmissionsBySource.values()).some(
          (admission) => admission.parentSessionId === session &&
            admission.toolCallId === toolCallId && admission.accessIntent === "mutating" &&
            !admission.cleanupAccepted,
        );
        if (!awaitingCleanup) {
          disposeWorkerObserver(key);
        } else if (!workerObserverExpiry.has(key)) {
          // Shutdown precedes host cancellation/reaping. Keep receipt consumers
          // alive without awaiting them here (that would deadlock host disposal).
          // Expiry only detaches observers: it never releases an unproven lease.
          const expiry = scheduleObserverExpiry(() => disposeWorkerObserver(key), 30_000);
          expiry.unref();
          workerObserverExpiry.set(key, expiry);
        }
      }
      const activeStateCfg = loadAutoInjectHostConfig(config.home);
      if (activeStateCfg.mode === "advisory" || activeStateCfg.mode === "active") {
        const activeState = runActiveStateUpdateSync({
          home: config.home ?? "",
          hostSessionId: session,
          verification: { session_shutdown: event.reason ?? "normal" },
        });
        if (!activeState.ok) {
          getStore(session)?.append(
            sensors.extensionError(session, new Error(activeState.error ?? "active-state shutdown failed")),
          );
        }
      }
      const environment = runEnvironmentAssessmentSync({
        home: config.home ?? "",
        hostSessionId: session,
        repo: ctxCwd(ctx) ?? config.home ?? "",
        phase: "shutdown",
      });
      const projectId =
        environment.ok &&
        environment.evidence &&
        typeof environment.evidence.project_id === "string"
          ? environment.evidence.project_id
          : undefined;
      // Task 7: one bounded P4 pulse — heartbeat always runs; Radar/
      // fingerprints run only when `projectId` is known (gated inside
      // p4.pulse() itself, mirrors the prior project_id-gated Radar call).
      const p4Result = runP4PulseSync({
        home: config.home ?? "",
        hostSessionId: session,
        event: "session_shutdown",
        repo: ctxCwd(ctx) ?? config.home ?? "",
        projectId,
      });
      if (p4Result.ok) {
        if (p4Result.heartbeat) {
          getStore(session)?.append(sensors.heartbeatPulse(session, p4Result.heartbeat));
        }
        for (const fingerprint of p4Result.fingerprints ?? []) {
          getStore(session)?.append(sensors.bottleneckFingerprint(session, fingerprint));
        }
      } else {
        getStore(session)?.append(
          sensors.extensionError(session, new Error(p4Result.error ?? "P4 pulse failed")),
        );
      }
      mirror(
        session,
        "session_inactive",
        {
          reason: event.reason,
          environment_steward_id: environment.ok ? environment.environmentStewardId ?? null : null,
          environment_hash: environment.ok ? environment.environmentHash ?? null : null,
          environment_mutation_detected: environment.ok ? environment.mutationDetected ?? false : null,
          environment_mutation_classification: environment.ok ? environment.mutationClassification ?? "none" : "assessment_failed",
          environment_completion_eligible: environment.ok ? environment.completionEligible ?? true : false,
        },
        { cwd: ctxCwd(ctx) },
      );
      return sensors.sessionShutdown(session, event.reason);
    },
    true, // final: sync write so the record survives worker teardown
  );
}
