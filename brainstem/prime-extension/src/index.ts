/**
 * Second Brain's OMP adapter: memory, context, skills and passive evidence.
 *
 * The native host owns agents, models, tools and task lifecycle. This
 * extension never authorizes, rewrites or settles host execution.
 * Measurement failures do not interrupt the host; protected Brain data
 * writes and compaction checkpoints keep their own authorization boundaries.
 */
import type {
  AgentEndEvent,
  BeforeAgentStartEvent,
  ExtensionAPI,
  ExtensionContext,
  PrimeEvent,
  SessionBeforeCompactEvent,
  SessionCompactEvent,
  SessionShutdownEvent,
  SessionStartEvent,
  TurnEndEvent,
  TurnStartEvent,
} from "../types/prime";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readSync, statSync, writeFileSync } from "node:fs";
import { StringDecoder } from "node:string_decoder";
import { loadConfig, loadRereadAvoidance, resolveBrainHome } from "./config";
import {
  buildBrainBrief,
  buildRecallQuery,
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
  advisoryEmitCached,
  loadAutoInjectHostConfig,
  parseShadowOutput,
  resolveProject,
  resolvedProjectIdForSession,
  runAdvisoryAutoInject,
  runShadowAutoInject,
  type AdvisoryAutoInjectCall,
} from "./autoinject";
import { assemblePrefix, checkPrefixDrift } from "./injection-slots";
import {
  ACTIVE_STATE_DEFAULT_BUDGET,
  ACTIVE_STATE_MAX_TEXT_CHARS,
  activeStateMessage,
  activeStateRenderResult,
  parseActiveStateResult,
  renderActiveState,
  runActiveStateEnsure,
  runActiveStateUpdate,
  runActiveStateUpdateSync,
} from "./active-state-mirror";
import {
  environmentFingerprint,
  runEnvironmentAssessment,
  runEnvironmentAssessmentSync,
  type EnvironmentAssessmentOptions,
} from "./environment-mirror";
import {
  loadQuietPrecheckEnabled,
  precheckQuiet,
  type QuietPrecheckResult,
} from "./quiet-precheck";
import { createCapsuleWrites } from "./capsule-writes";
import { runP4Pulse, runP4PulseSync } from "./p4-mirror";
import {
  mirrorExtensionError,
  mirrorFireAndForget,
  runLedgerCheckpoint,
  runLedgerSegmentRollover,
  taskSha256,
} from "./ledger-mirror";
import { measureContent } from "./sensors";
import * as sensors from "./sensors";
import { e01SpanAsync, e01SpanEnd, e01Trace } from "./e01-trace";
import {
  getTurnHelper,
  loadTurnBridgeConfig,
  prepareTurnWithBridge,
  resolveTurnPython,
  stopTurnHelpers,
  type TurnBridgePayload,
  type TurnBridgeRequest,
  type TurnBridgeSpawner,
} from "./turn-bridge";
import { parseHotContextOutput, runVmemCompactPrep, runVmemEvictSync, runVmemHotContext, runVmemStore } from "./vmem";
import {
  createTelemetryDirEnsurer,
  sanitizeSessionStem,
  TelemetryStore,
  type DirEnsurer,
} from "./storage";
import {
  loadSkillsVisibilityMode,
  OMP_VISIBILITY_MAX_INJECTED_CHARS,
  ompVisibilityRecord,
  runOmpVisibility,
  validateOmpVisibilityResult,
  type OmpVisibilityOptions,
  type OmpVisibilityResult,
} from "./visibility-bridge";



interface NativeSessionIdentity {
  id: string;
  timestamp: string;
}

interface NativeSessionIdentityResult extends NativeSessionIdentity {
  defaultSession: string;
  boundSession?: string;
}

const SESSION_IDENTITY_CUSTOM_TYPE = "brain.session-identity";
const SESSION_IDENTITY_VERSION = 1;
const nativeIdentityCache = new WeakMap<object, Map<string, NativeSessionIdentityResult>>();

function readNativeHeader(file: string): Record<string, unknown> {
  const fd = openSync(file, "r");
  try {
    const buffer = Buffer.allocUnsafe(64 * 1024);
    const bytes = readSync(fd, buffer, 0, buffer.length, 0);
    const lines = buffer.subarray(0, bytes).toString("utf8").replace(/^\uFEFF/u, "").split(/\r?\n/u);
    for (const line of lines) {
      if (!line.trim()) continue;
      const parsed: unknown = JSON.parse(line);
      if (parsed === null || typeof parsed !== "object") {
        throw new Error("native session header is malformed");
      }
      const record = parsed as Record<string, unknown>;
      if (record.type === "title") continue;
      if (record.type !== "session") throw new Error("native session header is missing");
      return record;
    }
    throw new Error("native session header is missing");
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error("native session header is malformed or exceeds the prefix limit");
    throw error;
  } finally {
    closeSync(fd);
  }
}

function nativeIdentityFromHeader(header: Record<string, unknown>): NativeSessionIdentity {
  const id = header.id;
  const timestamp = header.timestamp;
  if (header.type !== "session" || typeof id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u.test(id)) {
    throw new Error("native session identity is malformed");
  }
  if (
    typeof timestamp !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u.test(timestamp) ||
    !Number.isFinite(Date.parse(timestamp)) ||
    new Date(timestamp).toISOString() !== timestamp
  ) {
    throw new Error("native session timestamp is malformed");
  }
  return { id, timestamp };
}

function nativeIdentityForContext(ctx: ExtensionContext): NativeSessionIdentity {
  const manager = ctx?.sessionManager;
  const file = manager?.getSessionFile?.();
  const hasHeader = typeof manager?.getHeader === "function";
  const hasSessionId = typeof manager?.getSessionId === "function";
  if (hasHeader || hasSessionId) {
    if (!hasHeader || !hasSessionId) {
      throw new Error("native session identity surface is incomplete");
    }
    const header = manager.getHeader!();
    if (header === null || typeof header !== "object") {
      throw new Error("native session header is unavailable");
    }
    const identity = nativeIdentityFromHeader(header as Record<string, unknown>);
    const sessionId = manager.getSessionId!();
    if (typeof sessionId !== "string" || sessionId !== identity.id) {
      throw new Error("native session id/header disagreement");
    }
    return identity;
  }
  if (typeof file !== "string" || file.length === 0) {
    throw new Error("native session identity is unavailable");
  }
  return nativeIdentityFromHeader(readNativeHeader(file));
}

function defaultNativeSessionId(identity: NativeSessionIdentity): string {
  const session = `${identity.timestamp.replace(/[:.]/gu, "-")}_${identity.id}`;
  if (legacySessionId(session) === undefined) throw new Error("native session key exceeds the supported identity format");
  return session;
}

function legacySessionId(value: unknown): string | undefined {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u.test(value)
  ) {
    return undefined;
  }
  return value;
}

function entryIdentityDetails(entry: unknown): {
  customType?: string;
  details?: Record<string, unknown>;
  timestamp?: string;
} {
  if (entry === null || typeof entry !== "object") return {};
  const raw = entry as Record<string, unknown>;
  const data = raw.data !== null && typeof raw.data === "object"
    ? raw.data as Record<string, unknown>
    : undefined;
  const customType =
    typeof raw.customType === "string"
      ? raw.customType
      : typeof data?.customType === "string"
        ? data.customType
        : undefined;
  const details =
    raw.details !== null && typeof raw.details === "object"
      ? raw.details as Record<string, unknown>
      : data?.details !== null && typeof data?.details === "object"
        ? data.details as Record<string, unknown>
        : data;
  return {
    customType,
    details,
    timestamp: typeof raw.timestamp === "string" ? raw.timestamp : undefined,
  };
}

function sessionBindingFromEntries(
  entries: Iterable<unknown>,
  identity: NativeSessionIdentity,
): string | undefined {
  let explicit: string | undefined;
  let legacy: string | undefined;
  let legacyUnproven = false;
  for (const entry of entries) {
    const { customType, details, timestamp } = entryIdentityDetails(entry);
    if (!details) continue;
    if (customType === SESSION_IDENTITY_CUSTOM_TYPE) {
      if (typeof details.native_session_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(details.native_session_id)) {
        throw new Error("native session binding is malformed");
      }
      if (details.native_session_id !== identity.id) continue;
      if (details.version !== SESSION_IDENTITY_VERSION) {
        throw new Error("native session binding version is unsupported");
      }
      const candidate = legacySessionId(details.host_session_id);
      if (candidate === undefined) throw new Error("native session binding is malformed");
      if (details.header_timestamp !== identity.timestamp) {
        throw new Error("native session binding contradicts current header");
      }
      if (explicit !== undefined && explicit !== candidate) {
        throw new Error("native session has conflicting identity bindings");
      }
      explicit = candidate;
      continue;
    }
    if (customType !== "brain.active-state" || details.session_id === undefined) continue;
    const candidate = legacySessionId(details.session_id);
    if (candidate === undefined) throw new Error("native legacy session assignment is malformed");
    if (timestamp === undefined) {
      legacyUnproven = true;
      continue;
    }
    const entryTime = Date.parse(timestamp);
    if (!Number.isFinite(entryTime)) {
      legacyUnproven = true;
      continue;
    }
    if (entryTime < Date.parse(identity.timestamp)) continue;
    if (legacy !== undefined && legacy !== candidate) {
      throw new Error("native session has conflicting legacy assignments");
    }
    legacy = candidate;
  }
  if (explicit === undefined && legacy === undefined && legacyUnproven) {
    throw new Error("native legacy session assignment ownership is unproven");
  }
  return explicit ?? legacy;
}


function nativeIdentityForContextWithBinding(
  ctx: ExtensionContext,
  home: string | null,
): NativeSessionIdentityResult {
  const identity = nativeIdentityForContext(ctx);
  const manager = ctx.sessionManager;
  const cacheKey = `${home ?? ""}\u0000${identity.id}\u0000${identity.timestamp}`;
  const cached = nativeIdentityCache.get(manager)?.get(cacheKey);
  if (cached) return cached;
  if (typeof manager.getEntries !== "function") {
    throw new Error("native session entry history is unavailable");
  }
  const entries = manager.getEntries();
  if (!Array.isArray(entries)) throw new Error("native session entries are malformed");
  const resolved: NativeSessionIdentityResult = {
    ...identity,
    defaultSession: defaultNativeSessionId(identity),
    boundSession: sessionBindingFromEntries(entries, identity),
  };
  const file = manager.getSessionFile?.();
  if (resolved.boundSession === undefined && home && typeof file === "string") {
    const stem = file.split(/[\\/]/u).pop()?.replace(/\.jsonl$/u, "") ?? "";
    const legacy = sanitizeSessionStem(stem);
    const headerTime = Date.parse(identity.timestamp);
    const hasOwnWork = entries.some((entry: unknown) => {
      if (entry === null || typeof entry !== "object") return false;
      const record = entry as Record<string, unknown>;
      if (record.type !== "message" || typeof record.timestamp !== "string" || Date.parse(record.timestamp) < headerTime) return false;
      if (!Number.isFinite(Date.parse(record.timestamp)) || record.message === null || typeof record.message !== "object") return false;
      const role = (record.message as Record<string, unknown>).role;
      return role === "user" || role === "assistant" || role === "toolResult" || role === "bashExecution";
    });
    if (legacy !== resolved.defaultSession && hasOwnWork) {
      const root = join(home, "state", "sessions");
      const legacyHash = createHash("sha256").update(legacy).digest("hex");
      if (existsSync(join(root, legacy)) || existsSync(join(root, legacyHash))) {
        throw new Error("existing native session history has no verified canonical binding");
      }
    }
  }
  let managerCache = nativeIdentityCache.get(manager);
  if (!managerCache) {
    managerCache = new Map();
    nativeIdentityCache.set(manager, managerCache);
  }
  managerCache.set(cacheKey, resolved);
  return resolved;
}

function* nativeFileIdentityEntries(file: string, identity: NativeSessionIdentity): Generator<unknown> {
  const fd = openSync(file, "r");
  try {
    const limit = statSync(file).size;
    const buffer = Buffer.allocUnsafe(64 * 1024);
    const decoder = new StringDecoder("utf8");
    let offset = 0;
    let pending = "";
    const metadata = (line: string): unknown => {
      if (!/"customType"\s*:/u.test(line) && !/"type"\s*:\s*"session"/u.test(line)) return undefined;
      const parsed: unknown = JSON.parse(line);
      if (parsed !== null && typeof parsed === "object" && (parsed as Record<string, unknown>).type === "session") {
        const header = nativeIdentityFromHeader(parsed as Record<string, unknown>);
        if (header.id !== identity.id || header.timestamp !== identity.timestamp) {
          throw new Error("native session changed during identity lookup");
        }
        return undefined;
      }
      return parsed;
    };
    while (offset < limit) {
      const count = readSync(fd, buffer, 0, Math.min(buffer.length, limit - offset), offset);
      if (count === 0) throw new Error("native session shortened during identity lookup");
      offset += count;
      pending += decoder.write(buffer.subarray(0, count));
      let newline: number;
      while ((newline = pending.indexOf("\n")) !== -1) {
        const line = pending.slice(0, newline).replace(/\r$/u, "");
        pending = pending.slice(newline + 1);
        if (line.trim()) {
          const entry = metadata(line);
          if (entry !== undefined) yield entry;
        }
      }
    }
    pending += decoder.end();
    if (pending.trim()) {
      JSON.parse(pending); // A snapshot ending inside a record is not complete metadata.
      const entry = metadata(pending);
      if (entry !== undefined) yield entry;
    }
  } finally {
    closeSync(fd);
  }
}

// Native identity assignments are immutable. Appends do not require rescanning
// a resolved ancestor; replacement, truncation, or a new header invalidates it.
const nativeFileBindingCache = new Map<string, {
  id: string; timestamp: string; dev: number; ino: number; size: number; session: string;
}>();

function nativeFileBoundSession(file: string, identity: NativeSessionIdentity): string | undefined {
  const path = resolve(file);
  const stat = statSync(path);
  const cached = nativeFileBindingCache.get(path);
  if (
    cached?.id === identity.id && cached.timestamp === identity.timestamp &&
    cached.dev === stat.dev && cached.ino === stat.ino && stat.size >= cached.size
  ) return cached.session;
  const session = sessionBindingFromEntries(nativeFileIdentityEntries(path, identity), identity);
  if (session !== undefined) {
    if (nativeFileBindingCache.size >= 128) {
      const oldest = nativeFileBindingCache.keys().next().value;
      if (oldest !== undefined) nativeFileBindingCache.delete(oldest);
    }
    nativeFileBindingCache.set(path, { ...identity, dev: stat.dev, ino: stat.ino, size: stat.size, session });
  }
  return session;
}

/** Resolve one native transcript path with the same identity rules as ctx. */
function sessionIdFromFile(file: string): string | undefined {
  if (!file.endsWith(".jsonl")) return undefined;
  const identity = nativeIdentityFromHeader(readNativeHeader(file));
  const defaultSession = defaultNativeSessionId(identity);
  const boundSession = nativeFileBoundSession(file, identity);
  const base = file.split(/[\\/]/u).pop()?.slice(0, -".jsonl".length);
  if (boundSession === undefined && base !== defaultSession) {
    throw new Error("native legacy session assignment ownership is unproven");
  }
  return boundSession ?? defaultSession;
}

/** Resolve the current native session; missing identity refuses safely. */
function resolveSessionId(ctx: ExtensionContext, home: string | null): string {
  const manager = ctx?.sessionManager;
  if (!manager) throw new Error("native session identity is unavailable");
  const file = manager.getSessionFile?.();
  if (
    (typeof file !== "string" || file.length === 0) &&
    typeof manager.getHeader !== "function" &&
    typeof manager.getSessionId !== "function"
  ) {
    throw new Error("native session identity is unavailable");
  }
  const identity = nativeIdentityForContextWithBinding(ctx, home);
  return identity.boundSession ?? identity.defaultSession;
}

/**
 * Follow OMP's native transcript ancestry. Filesystem breadcrumbs remain the
 * authority; header.parentSession is deliberately not used for this lookup.
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
  sessionIdentity: (ctx: ExtensionContext) => string,
  mapper: Mapper<E>,
  final = false,
): (event: E, ctx: ExtensionContext) => void {
  return (event: E, ctx: ExtensionContext): void => {
    let session = "unknown";
    try {
      session = sessionIdentity(ctx);
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
  ompVisibilityRunner?: (options: OmpVisibilityOptions) => Promise<OmpVisibilityResult>;
  /** Read-ledger reread hint seam; production invokes brainctl. */
  rereadHintRunner?: RereadHintRunner;
  /**
   * E01 turn-bridge seam: the reused-interpreter helper spawner. Omitted in
   * production (node:child_process `spawn`); tests inject a scripted child so
   * helper lifecycle behavior is exercised without a Python runtime.
   */
  turnBridgeSpawn?: TurnBridgeSpawner;
}

export default function (pi: ExtensionAPI, options: ExtensionOptions = {}): void {
  const config = loadConfig();
  if (!config.enabled || !config.telemetryDir) {
    // Silently disabled (env gate or missing brain home).
    return;
  }
  const telemetryDir: string = config.telemetryDir;

  // E01 (PERF-02/PERF-04): the per-prompt memory phases run through ONE Python
  // process — batched (`once`) or through a reused interpreter (`helper`, the
  // default) — and fall back to the existing per-phase spawns on ANY failure,
  // so memory delivery never depends on this optimization. The
  // `SECOND_BRAIN_TURN_MODE` env value keeps the three designs directly
  // comparable in measurement (`current` = the pre-E01 path).
  const turnBridgeCfg = loadTurnBridgeConfig();
  const turnPython = resolveTurnPython(config.home ?? "");
  const turnBridgeEnabled = turnBridgeCfg.mode !== "current" && turnPython !== undefined;
  const turnHelper = () =>
    getTurnHelper({
      home: config.home ?? "",
      python: turnPython ?? "",
      cfg: turnBridgeCfg,
      spawnImpl: options.turnBridgeSpawn,
    });

  // Phase 4: one shared directory-readiness seam for the whole factory
  // (plan: "at extension startup, ensure the telemetry directory once").
  // The first store construction performs the single mkdir attempt; every
  // later store in this lifecycle reuses the result (success or failure —
  // never retried). A failure propagates into the constructing store's
  // fail-open handler, so it is reported exactly once and construction,
  // appends, and final writes remain non-fatal. `options.ensureTelemetryDir`
  // is a factory-scoped test seam; defaults to a fresh ensurer per factory.
  const ensureTelemetryDir = options.ensureTelemetryDir ?? createTelemetryDirEnsurer();


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
  const pendingRereads = new Map<string, { path: string }>();
  const activeStateTouchedSessions = new Set<string>();
  const lastToolResultBytes = new Map<string, number>();
  const lastContextProvider = new Map<string, string | null>();
  const lastContextModel = new Map<string, string | null>();
  const lastProvider = new Map<string, string | null>();
  const lastModel = new Map<string, string | null>();
  const lastCacheReadTokens = new Map<string, number | null>();
  const sessionBeforeCompactOccurred = new Set<string>();
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
    pi.on(type, safeHandler<E>(getStore, resolveAndJournalSessionId, mapper, final));
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
    const mirrorStart = performance.now();
    void Promise.resolve(
      mirrorFireAndForget({
        home: config.home ?? "",
        hostSessionId: sessionId,
        cwd: opts.cwd,
        parentSessionId: nativeRootSessions.get(sessionId),
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
      }),
    ).then(() => {
      e01SpanEnd("bg.ledger_mirror", mirrorStart, { kind });
    });
  };
  let currentTurnIndex = 0;
  const visibilityCache = new Map<string, Promise<OmpVisibilityResult>>();
  // Child HOST session -> canonical native transcript root; never prompt/header-derived.
  const nativeRootSessions = new Map<string, string>();
  const nativeAncestrySeen = new Set<string>();
  const recordNativeRootSession = (session: string, ctx: ExtensionContext): void => {
    if (nativeAncestrySeen.has(session)) return;
    nativeAncestrySeen.add(session);
    if (nativeAncestrySeen.size > 1024) {
      const oldest = nativeAncestrySeen.values().next().value;
      if (oldest !== undefined) nativeAncestrySeen.delete(oldest);
    }
    try {
      const rootSession = resolveNativeRootSessionId(ctx);
      if (rootSession === undefined || rootSession === session) return;
      if (!nativeRootSessions.has(session) && nativeRootSessions.size >= 1024) {
        const oldest = nativeRootSessions.keys().next().value;
        if (oldest !== undefined) {
          nativeRootSessions.delete(oldest);
          nativeAncestrySeen.delete(oldest);
        }
      }
      nativeRootSessions.set(session, rootSession);
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    }
  };
  const environmentFingerprints = new Map<string, string>();
  /**
   * Capsule-write ordering barrier (V3 S2 review fix): ONE per-session FIFO for
   * every capsule write — the coalesced background ensure a quiet turn schedules
   * and the foreground write/render/decision sequence of a normal turn. See
   * `src/capsule-writes.ts` for the ordering contract; `quietEnsure` puts the
   * prompt through it, so a run of no-benefit turns keeps the capsule current at
   * no critical-path cost without ever racing a foreground turn.
   */
  const capsuleWrites = createCapsuleWrites();
  const quietPrecheckEnabled = loadQuietPrecheckEnabled();
  const quietEnsure = (session: string, prompt: string): void => {
    capsuleWrites.quiet(session, prompt, async (text) => {
      try {
        const ensured = await runActiveStateEnsure({
          home: config.home ?? "",
          hostSessionId: session,
          objective: text,
          nextAction: text,
        });
        if (ensured.ok) {
          // Same condition the critical-path ensure used to set, so the
          // session's shutdown persistence still runs for this session.
          activeStateTouchedSessions.add(session);
          return;
        }
        getStore(session)?.append(
          sensors.extensionError(session, new Error(ensured.error ?? "active-state ensure failed")),
        );
      } catch (error) {
        try {
          getStore(session)?.append(sensors.extensionError(session, error));
        } catch {
          // storage failed too — never block the host turn
        }
      }
    });
  };
  const rereadRunner = options.rereadHintRunner ?? runRereadHint;
  const visibilityRunner = options.ompVisibilityRunner ?? runOmpVisibility;
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
    const pulseStart = performance.now();
    runP4Pulse({
      home: config.home ?? "",
      hostSessionId: session,
      event,
      repo: ctxCwd(ctx),
    })
      .then((pulse) => {
        e01SpanEnd("bg.p4_pulse", pulseStart, { event });
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

  const identityJournaled = new WeakMap<object, Set<string>>();
  const journalNativeIdentity = (session: string, ctx: ExtensionContext): void => {
    const manager = ctx.sessionManager as object;
    if (typeof pi.appendEntry !== "function") return;
    const identity = nativeIdentityForContextWithBinding(ctx, config.home);
    const key = `${identity.id}\u0000${identity.timestamp}\u0000${session}`;
    let journaled = identityJournaled.get(manager);
    if (!journaled) {
      journaled = new Set<string>();
      identityJournaled.set(manager, journaled);
    }
    if (journaled.has(key)) return;
    try {
      pi.appendEntry(SESSION_IDENTITY_CUSTOM_TYPE, {
        version: SESSION_IDENTITY_VERSION,
        native_session_id: identity.id,
        header_timestamp: identity.timestamp,
        host_session_id: session,
      });
      journaled.add(key);
    } catch (error) {
      getStore(session)?.append(sensors.extensionError(session, error));
    }
  };

  const resolveAndJournalSessionId = (ctx: ExtensionContext): string => {
    const session = resolveSessionId(ctx, config.home);
    journalNativeIdentity(session, ctx);
    return session;
  };

  // Session-start and task-boundary assessments run in the background: the
  // Python side writes the durable evidence file itself, and the ledger gets
  // an environment_assessment record when it finishes. The host turn never
  // waits for it (it measured ~1.4 s on a large repo).
  const assessEnvironmentInBackground = (
    session: string,
    ctx: ExtensionContext,
    options: EnvironmentAssessmentOptions,
  ): void => {
    const backgroundStart = performance.now();
    void runEnvironmentAssessment(options).then((environment) => {
      e01SpanEnd("bg.environment_assessment", backgroundStart, { phase: options.phase });
      if (!environment.ok) {
        getStore(session)?.append(
          mirrorExtensionError(session, environment.error ?? `${options.phase} environment assessment failed`),
        );
        return;
      }
      mirror(
        session,
        "environment_assessment",
        {
          phase: options.phase,
          task_id: options.taskId ?? null,
          environment_steward_id: environment.environmentStewardId ?? null,
          environment_hash: environment.environmentHash ?? null,
          mutation_detected: environment.mutationDetected ?? false,
          mutation_classification: environment.mutationClassification ?? "none",
          completion_eligible: environment.completionEligible ?? true,
        },
        { ignorable: true, cwd: ctxCwd(ctx) },
      );
    });
  };

  /**
   * Assessment cadence (V3 S2): once per session (session_start) and again only
   * when the cheap in-host fingerprint of the repo-root manifests / `.git/HEAD`
   * changes — never once per prompt. The assessment itself stays background and
   * fail-open (PERF-02); the fingerprint costs a handful of stat calls.
   */
  const assessEnvironmentOnChange = (
    session: string,
    ctx: ExtensionContext,
    repo: string,
  ): void => {
    const fingerprint = environmentFingerprint(repo);
    if (environmentFingerprints.get(session) === fingerprint) return;
    environmentFingerprints.set(session, fingerprint);
    assessEnvironmentInBackground(session, ctx, {
      home: config.home ?? "",
      hostSessionId: session,
      repo,
      taskId: fingerprint,
      phase: "task_boundary",
    });
  };

  wire<SessionStartEvent>("session_start", (event, ctx, session) => {
    const hookStart = performance.now();
    e01Trace("hook_enter", { hook: "session_start", session });
    recordNativeRootSession(session, ctx);
    // E01 cold-path option: start the reused interpreter while the HOST is
    // still booting, so the first prompt never pays the interpreter+import
    // cost on its own critical path. The startup span is recorded separately
    // (it is still real CPU); `SECOND_BRAIN_TURN_HELPER_START=lazy` keeps the
    // cost on the first prompt instead.
    if (turnBridgeEnabled && turnBridgeCfg.mode === "helper" && turnBridgeCfg.helperStart === "session_start") {
      void turnHelper().ensureStarted();
    }
    // Phase 0C SHADOW: decide + record only; session_start carries no task
    // text, so the adapter no-ops on empty tasks. Never returns a patch.
    void runShadowAutoInject({
      home: config.home ?? "",
      session,
      task: "",
      agentId: session,
      cwd: typeof ctx.cwd === "string" ? ctx.cwd : undefined,
      cfg: loadAutoInjectHostConfig(config.home),
      append: (record) => getStore(session)?.append(record),
    });
    mirror(
      session,
      "session_started",
      {
        host: "prime",
        reason: event.reason,
        cwd: typeof ctx.cwd === "string" ? ctx.cwd : null,
        model: sensors.modelToString(ctx.model),
        agent_id: session,
        provider: typeof ctx.model?.provider === "string" ? ctx.model.provider : null,
        host_agent_id: session,
      },
      // Project attribution: session_started is the first mirrored event, so
      // the auto-init of the session ledger receives the host cwd (when known)
      // and `ledger init --cwd` resolves project_id via the AutoInject ladder.
      { agentId: session, cwd: ctxCwd(ctx) },
    );
    const sessionRepo = ctxCwd(ctx) ?? config.home ?? "";
    // Seed the fingerprint so the first prompt of this session does not repeat
    // the session-start assessment.
    environmentFingerprints.set(session, environmentFingerprint(sessionRepo));
    assessEnvironmentInBackground(session, ctx, {
      home: config.home ?? "",
      hostSessionId: session,
      repo: sessionRepo,
      phase: "session_start",
    });
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
    e01SpanEnd("session_start.hook", hookStart, {});
    return sensors.sessionStart(session, event.reason, ctx.cwd, ctx.model);
  });

  // before_agent_start composes approved, low-authority knowledge for the
  // current native recipient without appointing a coordinator or changing
  // the host's model, tools or task lifecycle.
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
    agentId: session,
    cwd: typeof context.cwd === "string" ? context.cwd : undefined,
    projectId: resolvedProjectIdForSession(session) ?? resolveProject(),
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
    const hookStart = performance.now();
    let session = "unknown";
    let aiCfg = loadAutoInjectHostConfig(config.home);
    let aiMessage: unknown = undefined;
    let activeMessage: unknown = undefined;
    // Quiet fast path decision, hoisted so the hook's span (in `finally`) can
    // report it on every exit path.
    let quietSkip = false;
    let quietReason: QuietPrecheckResult["reason"] | undefined;
    let quietCheckMs = 0;
    try {
      session = resolveAndJournalSessionId(ctx);
      e01Trace("hook_enter", {
        hook: "before_agent_start",
        session,
        prompt_chars: typeof event.prompt === "string" ? event.prompt.length : 0,
      });
      recordNativeRootSession(session, ctx);
      // Environment Steward cadence: once per session, then only when the cheap
      // in-host fingerprint of the repo-root manifests / `.git/HEAD` changes.
      assessEnvironmentOnChange(session, ctx, ctxCwd(ctx) ?? config.home ?? "");
      // AutoInject contributes low-authority context for any native recipient;
      // the host appends the returned message after this turn's user text.
      // Phase C10 (verifier): the BRANCH decision MUST read the same cfg as
      // the records — config.home is required so config/autoinject.toml
      // [autoinject] mode is honored (env-only cfg made the live flip
      // switch inert and silently ran the shadow branch).
      const taskText = typeof event.prompt === "string" ? event.prompt : "";
      const aiCall = autoinjectCall(session, event, ctx);
      // Quiet fast path (V3 S2): one in-host, read-only, conservative
      // necessary-condition check decides whether this prompt can produce ANY
      // model-visible memory message. `skip` means the capsule/render half is
      // provably the host-dropped echo and no retrieved row could contribute
      // (the AutoInject `match_evidence` rules), so no Python process is spawned
      // on the critical path. Every doubt — an unreadable DB, an unknown schema,
      // a non-ASCII prompt, a memory-id reference, any lexical evidence, or a
      // live AutoInject emit-cache entry — resolves to the unchanged `run` path.
      let quietDetail: QuietPrecheckResult["detail"] | undefined;
      let emitCached: boolean | undefined;
      const emitCachedNow = (): boolean => {
        if (emitCached === undefined) emitCached = advisoryEmitCached(aiCall, taskText);
        return emitCached;
      };
      if (
        quietPrecheckEnabled &&
        config.home &&
        taskText.trim().length > 0 &&
        (aiCfg.mode === "advisory" || aiCfg.mode === "active")
      ) {
        const quietStart = performance.now();
        // A live emit-cache entry means the host is re-emitting an
        // ALREADY-decided task (possibly a packet): keep the decision path.
        const result: QuietPrecheckResult | undefined = emitCachedNow()
          ? undefined
          : precheckQuiet({ home: config.home, session, prompt: taskText });
        quietCheckMs = performance.now() - quietStart;
        quietSkip = result?.decision === "skip";
        quietReason = result?.reason;
        quietDetail = result?.detail;
        if (quietSkip && quietDetail !== undefined && quietReason !== undefined) {
          getStore(session)?.append(
            sensors.quietSkip(session, {
              reason: quietReason,
              candidates: quietDetail.candidates,
              vocab_terms: quietDetail.vocab_terms,
              unique_terms: quietDetail.unique_terms,
              headline_terms: quietDetail.headline_terms,
              ubiquitous_headline_terms: quietDetail.ubiquitous_headline_terms,
              capsule: quietDetail.capsule,
              vmem_objects: quietDetail.vmem_objects,
              total_documents: quietDetail.total_documents,
              precheck_ms: Math.round(quietCheckMs * 1000) / 1000,
            }),
          );
          // Compaction-recovery state stays current without paying for it on
          // this turn: one coalesced background ensure per session.
          quietEnsure(session, taskText);
        }
      }
      // Visibility planning is independent of the active-state and AutoInject
      // spawns, so it runs concurrently with them instead of after them. It is
      // independent of the MEMORY precheck too (V3 S2 review fix): the precheck
      // only proves that no memory/capsule/VMem content can reach the model,
      // while `omp_adapter._prepare_skill_visibility` routes independently
      // through the approved skill files and the handler below injects the
      // hydrated instructions whenever the plan's mode is `enforced`. A task
      // matching an approved skill but no semantic memory would otherwise lose
      // its specialist instructions. A quiet turn therefore still plans
      // visibility unless the mode is provably not `enforced` for this home
      // (then nothing can be injected, so the spawn is the precheck's saving).
      const visibilityEnabled =
        !quietSkip || loadSkillsVisibilityMode(config.home) === "enforced";
      const visibilityPending =
        visibilityEnabled && config.home && taskText.trim().length > 0
          ? e01SpanAsync(
              "bg.visibility_plan",
              ensureVisibilityPlan(session, taskText, ctx).catch(() => undefined),
            )
          : undefined;
      /**
       * The turn's capsule work — write objective/next_action, render hot
       * context, decide AutoInject — as ONE foreground critical section.
       *
       * Ordering (V3 S2 review fix): the whole sequence runs inside the
       * session's capsule-write barrier (`src/capsule-writes.ts`), so the
       * coalesced quiet ensure of an earlier turn can neither interleave with
       * it nor overwrite the objective/next_action this turn's AutoInject
       * decision reads (`autoinject._retrieval_query_text`) — and a quiet
       * prompt this foreground write supersedes is discarded, never replayed
       * afterwards into the capsule. A quiet turn never enters this section:
       * its only capsule write is the background ensure queued in the barrier.
       */
      const prepareTurnCapsuleWork = async (): Promise<void> => {
        // E01: capsule ensure + hot-context render + AutoInject decision in ONE
        // Python process (batched), or through the reused interpreter. The emit
        // probe runs FIRST so a host re-emit of the same prompt never re-runs
        // the Python decision (which would create a duplicate delivery). Any
        // failure — no interpreter, spawn error, timeout, helper death, malformed
        // response — leaves `batched` null and the per-phase path below runs
        // unchanged, so this optimization can only remove latency, never memory.
        let batched: TurnBridgePayload | null = null;
        if (
          turnBridgeEnabled &&
          taskText.trim().length > 0 &&
          (aiCfg.mode === "advisory" || aiCfg.mode === "active")
        ) {
          const boundedTask = taskText.trim().slice(0, ACTIVE_STATE_MAX_TEXT_CHARS);
          const cached = emitCachedNow();
          const turnRequest: TurnBridgeRequest = {
            session,
            task: taskText,
            cwd: ctxCwd(ctx),
            // NO inferred project: `project_id` is an EXPLICIT override in
            // Python (it outranks cwd/registry resolution), so forwarding the
            // adapter's remembered/`default` value would suppress the current
            // repository's memories or admit another project's. The pre-E01
            // per-phase spawn passes cwd only and lets Python resolve.
            agentId: session,
            branch: "main",
            roleProfile: "worker",
            objective: boundedTask,
            nextAction: boundedTask,
            budgetTokens: ACTIVE_STATE_DEFAULT_BUDGET,
            want: cached ? ["capsule", "render"] : ["capsule", "render", "autoinject"],
          };
          const prepared = await e01SpanAsync(
            "before_agent_start.turn_bridge",
            prepareTurnWithBridge({
              cfg: turnBridgeCfg,
              home: config.home ?? "",
              python: turnPython ?? "",
              request: turnRequest,
              spawnImpl: options.turnBridgeSpawn,
            }),
            { mode: turnBridgeCfg.mode, emit_cached: cached },
          );
          // A PARTIAL batch is kept: phases that succeeded committed their own
          // effects (AutoInject records its delivery), so re-running them would
          // see ALREADY_DELIVERED and lose the packet. `batchPhaseDone` decides
          // per phase, and only a failed phase falls back to its own spawn.
          if (prepared !== null) batched = prepared;
        }
        const batchPhaseDone = (phase: "capsule" | "render" | "autoinject"): boolean => {
          if (batched === null) return false;
          // Payloads without the map are all-or-nothing (older helper/one-shot).
          if (batched.phases_ok === undefined) return batched.ok === true;
          return batched.phases_ok[phase] === true;
        };
        if (
          config.home &&
          taskText.trim().length > 0 &&
          (aiCfg.mode === "advisory" || aiCfg.mode === "active")
        ) {
          const ensured =
            batchPhaseDone("capsule") && batched?.capsule_stdout !== undefined && batched.capsule_stdout !== null
              ? parseActiveStateResult(batched.capsule_stdout, session)
              : await e01SpanAsync(
                  "before_agent_start.capsule_ensure",
                  runActiveStateEnsure({
                    home: config.home,
                    hostSessionId: session,
                    objective: taskText,
                    nextAction: taskText,
                  }),
                  { source: "spawn" },
                );
          if (!ensured.ok) {
            getStore(session)?.append(
              sensors.extensionError(session, new Error(ensured.error ?? "active-state ensure failed")),
            );
          } else if (aiCfg.mode === "advisory" || aiCfg.mode === "active") {
            activeStateTouchedSessions.add(session);
            const rendered =
              batchPhaseDone("render") && batched?.render_stdout !== undefined && batched.render_stdout !== null
                ? activeStateRenderResult(parseHotContextOutput(batched.render_stdout), session)
                : await e01SpanAsync(
                    "before_agent_start.hot_context_render",
                    renderActiveState({
                      home: config.home,
                      hostSessionId: session,
                    }),
                    { source: "spawn" },
                  );
            if (!rendered.ok) {
              getStore(session)?.append(
                sensors.extensionError(session, new Error(rendered.error ?? "active-state render failed")),
              );
            } else {
              activeMessage = activeStateMessage(rendered, taskText);
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
          // A batched AutoInject decision is fed to the SAME orchestration
          // (records, emit cache, resolved-project memory) through its runner
          // seam, so the batched path cannot diverge from the spawn path;
          // `undefined` here (emit-cache hit, or no batch) keeps the original
          // spawn/cache behavior unchanged.
          const batchedOutcome =
            batchPhaseDone("autoinject") &&
            batched?.autoinject_stdout !== undefined &&
            batched.autoinject_stdout !== null
              ? parseShadowOutput(batched.autoinject_stdout)
              : undefined;
          aiMessage = await e01SpanAsync(
            "before_agent_start.autoinject",
            runAdvisoryAutoInject(
              batchedOutcome !== undefined
                ? { ...aiCall, runner: async () => batchedOutcome }
                : aiCall,
            ),
            { source: batchedOutcome !== undefined ? "batch" : "spawn" },
          );
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
          void runShadowAutoInject(autoinjectCall(session, event, ctx));
        }
      };
      if (!quietSkip) await capsuleWrites.foreground(session, prepareTurnCapsuleWork);
      if (visibilityPending !== undefined) {
        try {
          const visibilityResult = await visibilityPending;
          if (
            visibilityResult?.visibility_plan?.mode === "enforced" &&
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
        },
        // ledger-cwd-ordering-fix: user_task is the FIRST mirror to reach the
        // ledger in real runs (its init spawn wins the per-process race), so
        // it MUST carry the cwd or project_id resolves to ''.
        { cwd: ctxCwd(ctx) },
      );
      // The approved Lean kernel is optional knowledge, not an agent-role policy.
      // Dedup against the host's original system prompt before adding stable context.
      const promptValue = typeof ctx.getSystemPrompt === "function" ? ctx.getSystemPrompt() : undefined;
      const base = Array.isArray(promptValue)
        ? promptValue.join("\n\n")
        : typeof promptValue === "string"
          ? promptValue
          : undefined;
      const lean = decideLeanRuntime({ home: config.home ?? "", base });
      if (lean.error !== undefined) {
        getStore(session)?.append(sensors.extensionError(session, lean.error));
      }
      getStore(session)?.append(
        sensors.leanKernel(session, {
          decision: lean.decision,
          reason: lean.reason,
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
      // Hash the session-constant prefix so later drift is observable.
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
      let patched = base;
      getStore(session)?.append(sensors.beforeAgentStart(session, event.prompt));
      // Stable approved Lean context precedes dynamic recall and AutoInject.
      // Never invent a prompt when the host did not provide one.
      if (lean.decision === "inject" && lean.kernel !== undefined && lean.placement !== "tail") {
        const merged = appendLeanKernel(patched, lean.kernel);
        if (merged !== patched) {
          patched = merged;
        }
      }
      // Recall is dynamic per-turn context, never a change to the stable prefix.
      // A miss must not discard an approved Lean kernel.
      const recallCfg = loadRecallGateConfig();
      let turnMessage: unknown = mergeActiveStateMessage(aiMessage, activeMessage);
      // The CLI needs keywords, not the prompt: it keeps up to eight query
      // terms by IDF and requires at least half to occur in one memory.
      const recallQuery = shouldAttemptRecall(event.prompt, recallCfg)
        ? buildRecallQuery(event.prompt, recallCfg)
        : undefined;
      if (recallQuery !== undefined) {
        const brief = await e01SpanAsync(
          "before_agent_start.recall_brief",
          recallBrief(recallQuery, session, recallCfg),
        );
        if (brief !== undefined) {
          turnMessage = mergeRecallBriefMessage(turnMessage, brief);
        }
      }
      if (lean.decision === "inject" && lean.kernel !== undefined && lean.placement === "tail") {
        turnMessage = mergeLeanMessage(turnMessage, lean.kernel);
      }
      // Only independently enabled memory/context patches may change this prompt.
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
      // A later failure never discards an already prepared advisory context message.
      const message = mergeActiveStateMessage(aiMessage, activeMessage);
      if (message !== undefined && (aiCfg.mode === "advisory" || aiCfg.mode === "active")) {
        return { message };
      }
    } finally {
      // E01: closes on every exit path (patch, no patch, error) so the span
      // measures the whole hook the host awaits.
      e01SpanEnd("before_agent_start.hook", hookStart, {
        session,
        mode: aiCfg.mode,
        quiet: quietSkip ? "skip" : "run",
        quiet_reason: quietReason ?? null,
        quiet_check_ms: Math.round(quietCheckMs * 1000) / 1000,
      });
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
      session = resolveAndJournalSessionId(ctx);
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

  // Provider hooks observe native model identity and bounded request metadata.
  // Only Brain context paging may replace message content; provider/model
  // selection is always the host's choice.

  let providerRequestSeq = 0;
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
      session = resolveAndJournalSessionId(ctx);
      providerRequestSeq += 1;
      const original = event.payload;
      const identity = payloadIdentity(original, ctx);
      let effective = original;

      // Host-chosen model changes require re-evaluating Brain context capacity.
      const prevProv = lastProvider.get(session);
      const prevMod = lastModel.get(session);
      const isSwitch =
        prevMod !== undefined &&
        (identity.provider !== prevProv || identity.model !== prevMod);

      if (isSwitch) {
        const targetModel = identity.model ?? "default";
        const targetProvider = identity.provider ?? "default";

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

        // Step 5: If load > target capacity * 0.85: run T2.0/T2.1 reclaim
        const reclaimThreshold = Math.floor(targetCapacity * 0.85);
        if (load > reclaimThreshold) {
          const reclaimResult = runVmemEvictSync({
            home: config.home ?? "",
            hostSessionId: session,
            budgetTokens: reclaimThreshold,
          });
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
              effective = { ...payloadObj, messages: paged.messages };
            }
            load = 0;
            for (const msg of (paged.messages ?? messages)) {
              load += estimateTokens(msg, targetModel, config.home ?? undefined);
            }
          }
        }

        // Brain cannot refuse a native model request. If its context cannot
        // fit, leave the host payload intact and report the limitation.
        if (load > targetCapacity) {
          getStore(session)?.append(sensors.extensionError(session, "BRAIN_CONTEXT_OVERFLOW"));
          effective = original;
        }
      }

      lastProvider.set(session, identity.provider);
      lastModel.set(session, identity.model);
      getStore(session)?.append(
        sensors.providerRequestMeta(
          session,
          identity.provider,
          identity.model,
          providerRequestSeq,
          effective,
          leanProviderEvidence.get(session),
        ),
      );
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
      session = resolveAndJournalSessionId(ctx);
      const headers = event.headers ?? {};
      const provider = headers["x-provider"] ?? headers["provider"];
      const model = headers["x-model"] ?? headers["model"];
      const contextIdentity = sensors.splitProviderModel(sensors.modelToString(ctx.model));
      const actualProvider = typeof provider === "string" ? provider : contextIdentity.provider;
      const actualModel = typeof model === "string" ? model : contextIdentity.model;
      getStore(session)?.append(
        sensors.providerResponseMeta(session, actualProvider, actualModel, event.status, event.headers),
      );
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
      session = resolveAndJournalSessionId(ctx);
      const message = event.message;
      if (message != null && message.usage != null) {
        const u = message.usage as unknown as Record<string, unknown>;
        const cr = sensors.usageCounter(u.cacheRead);
        if (cr !== undefined) {
          lastCacheReadTokens.set(session, cr);
        }
        const model = typeof message.model === "string" ? message.model : (ctx.model?.id ?? null);
        const provider = typeof message.provider === "string" ? message.provider : (ctx.model?.provider ?? null);
        const record = sensors.assistantUsage(
          session,
          provider,
          model,
          message.usage,
          message.responseId,
        );
        if (record) getStore(session)?.append(record);
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
   * Return one bounded, low-authority Brain recall brief in the turn's TAIL
   * message without changing the stable system prompt.
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

  // Observe tool use; do not alter native dispatch or permissions.
  pi.on("tool_call", (event, ctx) => {
    let session = "unknown";
    try {
      session = resolveAndJournalSessionId(ctx);
      recordNativeRootSession(session, ctx);
      getStore(session)?.append(sensors.toolCall(session, event.toolName, event.toolCallId, event.input));
      mirror(
        session,
        "tool_requested",
        {
          tool: event.toolName,
          input_bytes: sensors.byteLength(JSON.stringify(event.input ?? {})),
        },
        { cwd: ctxCwd(ctx) },
      );
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
            return undefined;
          }).catch(() => undefined);
        }
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
      session = resolveAndJournalSessionId(ctx);
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

  // session_before_compact: best-effort pre-compaction checkpoint (plan §10.2).
  // The checkpoint is awaited (5s timeout) so it usually lands before the host
  // compacts, but Brain never vetoes compaction (V3 CTX-03): a failed
  // checkpoint is recorded as ledger_degraded and the host proceeds.
  // The event is registered directly (not via wire) so the handler can await.
  pi.on("session_before_compact", async (event, ctx) => {
    const compactEvent = event as SessionBeforeCompactEvent;
    let session = "unknown";
    try {
      session = resolveAndJournalSessionId(ctx);
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
      // then the best-effort checkpoint.
      getStore(session)?.append(
        sensors.sessionBeforeCompact(session, compactEvent.branchEntries),
      );
      const activeStateCfg = loadAutoInjectHostConfig(config.home);
      if (activeStateCfg.mode === "advisory" || activeStateCfg.mode === "active") {
        // Ordering (V3 S2 review fix): the checkpoint runs INSIDE the session's
        // capsule-write barrier, so a coalesced quiet ensure from an earlier turn
        // (a) has settled before the checkpoint reads the capsule and (b) cannot
        // land after it and restore a stale objective/next_action — or drop the
        // checkpoint's own verification fields through its read-modify-write.
        const activeState = await capsuleWrites.foreground(session, () =>
          runActiveStateUpdate({
            home: config.home ?? "",
            hostSessionId: session,
            verification: { pre_compaction: "persisted" },
          }),
        );
        if (!activeState.ok) {
          getStore(session)?.append(
            sensors.extensionError(session, new Error(activeState.error ?? "active-state checkpoint failed")),
          );
        } else {
          activeStateTouchedSessions.add(session);
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
        return undefined;
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
      // only. Disabled by default ([vmem] enabled=false) until a live pilot
      // proves this sound; see outputs/reports/rc4/02-prime-live-callgraph.md.
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
      return undefined; // Brain failure never blocks host compaction (CTX-03)
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

  /**
   * Shutdown persistence + its final record, kept as a named function so the
   * DIRECT `session_shutdown` handler below can settle the session's
   * capsule-write barrier before it runs (V3 S2 review fix), while the record
   * write itself stays synchronous (`appendFinal`) — Prime's daemon tears the
   * worker down right after the event, so an awaited write could lose it.
   */
  const sessionShutdownRecord = (
    event: SessionShutdownEvent,
    ctx: ExtensionContext,
    session: string,
  ): object => {
    // E01 cleanup: the reused interpreter is a memory helper, so it goes
    // away with the session that started it (an orphaned helper also
    // self-exits on stdin EOF if this host dies without shutdown).
    if (turnBridgeEnabled) stopTurnHelpers("session_shutdown");
    const activeStateCfg = loadAutoInjectHostConfig(config.home);
    if (
      activeStateTouchedSessions.has(session) &&
      (activeStateCfg.mode === "advisory" || activeStateCfg.mode === "active")
    ) {
      const activeState = runActiveStateUpdateSync({
        home: config.home ?? "",
        hostSessionId: session,
        verification: { session_shutdown: event.reason ?? "normal" },
      });
      if (!activeState.ok) {
        getStore(session)?.appendFinal(
          sensors.extensionError(session, new Error(activeState.error ?? "active-state shutdown failed")),
        );
      }
    }
    activeStateTouchedSessions.delete(session);
    // Required active-state persistence runs for every native recipient.
    // Skip optional maintenance for a child so its shutdown cannot delay
    // the host's own lifecycle; this is observation, not settlement.
    let childSession = false;
    try {
      const header = ctx.sessionManager?.getHeader?.();
      childSession = header !== null && typeof header === "object" &&
        typeof (header as Record<string, unknown>).parentSession === "string";
    } catch {
      // No verified child marker: run ordinary local maintenance.
    }
    if (childSession) {
      mirror(session, "session_inactive", {
        reason: event.reason,
        optional_maintenance_skipped: "native_child",
      }, { ignorable: true, cwd: ctxCwd(ctx) });
      return sensors.sessionShutdown(session, event.reason);
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
    // No further event-loop turn is guaranteed for shutdown-derived telemetry.
    const p4Result = runP4PulseSync({
      home: config.home ?? "",
      hostSessionId: session,
      event: "session_shutdown",
      repo: ctxCwd(ctx) ?? config.home ?? "",
      projectId,
    });
    if (p4Result.ok) {
      if (p4Result.heartbeat) {
        getStore(session)?.appendFinal(sensors.heartbeatPulse(session, p4Result.heartbeat));
      }
      for (const fingerprint of p4Result.fingerprints ?? []) {
        getStore(session)?.appendFinal(sensors.bottleneckFingerprint(session, fingerprint));
      }
    } else {
      getStore(session)?.appendFinal(
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
  };

  // Registered DIRECTLY (not through `wire`) so the handler can settle the
  // session's capsule-write barrier before its persistence. The drain is the one
  // await a shutdown handler may take: a quiet background ensure left queued must
  // not land after this persistence and restore the objective it replaced (or
  // drop the persisted verification through its own read-modify-write). The
  // record write below stays synchronous, exactly as the `final` mapper write it
  // replaces.
  pi.on("session_shutdown", async (event, ctx) => {
    const shutdownEvent = event as SessionShutdownEvent;
    let session = "unknown";
    try {
      session = resolveAndJournalSessionId(ctx);
      await capsuleWrites.drain(session);
      getStore(session)?.appendFinal(sessionShutdownRecord(shutdownEvent, ctx, session));
    } catch (error) {
      try {
        getStore(session)?.appendFinal(sensors.extensionError(session, error));
      } catch {
        // storage failed too — give up silently (measurement must not crash).
      }
    }
  });
}
