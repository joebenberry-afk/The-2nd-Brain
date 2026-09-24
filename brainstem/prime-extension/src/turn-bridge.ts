/**
 * E01 turn bridge client: one Python spawn per prompt (batched), or one reused
 * interpreter per host session (JSON-lines helper).
 *
 * The adapter's per-prompt memory phases — capsule ensure, hot-context render
 * and the AutoInject decision — used to be three separate CLI processes, each
 * paying the full package-import cost. This module reaches the SAME three
 * Python implementations (see `src/second_brain/turn_bridge.py`) through:
 *
 *   - `once`   — `second_brain turn prepare ...` (bounded process per prompt);
 *   - `helper` — `second_brain turn serve`: a per-host-session interpreter
 *                kept alive across turns, one JSON request/response per turn.
 *
 * The helper is a MEMORY OPERATION ONLY (no host-agent authority, no
 * lifecycle decision): the adapter still decides what to patch. Every failure
 * — missing interpreter, spawn error, timeout, malformed response, helper
 * identity change, queue overflow, helper death — resolves `null` so the
 * caller can fall back to the existing per-phase path, i.e. the host turn
 * never loses memory context because of this optimization.
 *
 * Isolation/bounds (contract E01): one helper per (home, interpreter); each
 * request carries its own session/project and the helper rejects a different
 * home; requests are serialized with a bounded queue; the helper exits after
 * a bounded request count / lifetime / resident-set size and is restarted on
 * demand; identity drift (code, config or DB change) is answered
 * `identity_changed` and the helper is restarted before the retry; the child
 * is killed after a shutdown grace period and on host exit, and self-exits on
 * stdin EOF if the host dies without cleanup.
 *
 * Config (env, read at call time like src/config.ts):
 *   SECOND_BRAIN_TURN_MODE              "current" | "once" | "helper" (default once)
 *   SECOND_BRAIN_TURN_TIMEOUT_MS        per call, default 5000
 *   SECOND_BRAIN_TURN_HELPER_START      "lazy" (default) | "session_start"
 *   SECOND_BRAIN_TURN_HELPER_MAX_REQUESTS default 256
 *   SECOND_BRAIN_TURN_HELPER_LIFETIME_MS  default 1800000
 *   SECOND_BRAIN_TURN_QUEUE_LIMIT       concurrent+queued requests, default 2
 */
import { spawn, type ChildProcess } from "node:child_process";

/** The helper spawner seam: node:child_process `spawn` (tests inject a fake). */
export type TurnBridgeSpawner = typeof spawn;
import { existsSync } from "node:fs";
import { join } from "node:path";

import { e01SpanEnd } from "./e01-trace";

export const TURN_MODE_ENV = "SECOND_BRAIN_TURN_MODE";
export const TURN_TIMEOUT_ENV = "SECOND_BRAIN_TURN_TIMEOUT_MS";
export const TURN_HELPER_START_ENV = "SECOND_BRAIN_TURN_HELPER_START";
export const TURN_HELPER_MAX_REQUESTS_ENV = "SECOND_BRAIN_TURN_HELPER_MAX_REQUESTS";
export const TURN_HELPER_LIFETIME_ENV = "SECOND_BRAIN_TURN_HELPER_LIFETIME_MS";
export const TURN_QUEUE_LIMIT_ENV = "SECOND_BRAIN_TURN_QUEUE_LIMIT";

export const TURN_DEFAULT_TIMEOUT_MS = 5000;
export const TURN_DEFAULT_MAX_REQUESTS = 256;
export const TURN_DEFAULT_LIFETIME_MS = 1_800_000;
export const TURN_DEFAULT_QUEUE_LIMIT = 2;
/** Shutdown grace before the helper is killed outright. */
export const TURN_HELPER_STOP_GRACE_MS = 250;

export type TurnBridgeMode = "current" | "once" | "helper";

export interface TurnBridgeConfig {
  mode: TurnBridgeMode;
  timeoutMs: number;
  helperStart: "lazy" | "session_start";
  helperMaxRequests: number;
  helperLifetimeMs: number;
  queueLimit: number;
}

export function loadTurnBridgeConfig(
  env: Record<string, string | undefined> = process.env,
): TurnBridgeConfig {
  const rawMode = (env[TURN_MODE_ENV] ?? "").trim().toLowerCase();
  // Default `once`: the S2 E01 pilot measured one bounded spawn per prompt as
  // the cheapest design whose cold cost is fully attributed (see
  // outputs/reports/v3-s2/e01/E01_REPORT.md). `helper` (reused interpreter) and
  // `current` (pre-E01 per-phase spawns) stay selectable for measurement and
  // rollback; an unset or unrecognized value is `once`, never `current`.
  const mode: TurnBridgeMode =
    rawMode === "current" || rawMode === "helper" ? rawMode : "once";
  const positive = (value: string | undefined, fallback: number): number => {
    const parsed = Number((value ?? "").trim());
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
  };
  return {
    mode,
    timeoutMs: positive(env[TURN_TIMEOUT_ENV], TURN_DEFAULT_TIMEOUT_MS),
    helperStart:
      (env[TURN_HELPER_START_ENV] ?? "").trim().toLowerCase() === "session_start"
        ? "session_start"
        : "lazy",
    helperMaxRequests: positive(env[TURN_HELPER_MAX_REQUESTS_ENV], TURN_DEFAULT_MAX_REQUESTS),
    helperLifetimeMs: positive(env[TURN_HELPER_LIFETIME_ENV], TURN_DEFAULT_LIFETIME_MS),
    queueLimit: positive(env[TURN_QUEUE_LIMIT_ENV], TURN_DEFAULT_QUEUE_LIMIT),
  };
}

/** Interpreter the memory operations run on, or undefined when none exists. */
export function resolveTurnPython(
  home: string,
  env: Record<string, string | undefined> = process.env,
): string | undefined {
  const python = env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe");
  return existsSync(python) ? python : undefined;
}

interface TurnChildEnv {
  home: string;
  python: string;
}

function turnChildEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

export interface TurnBridgeCapsule {
  session_id?: string;
  capsule_path?: string;
  capsule_sha256?: string;
  capsule_bytes?: number;
  changed?: boolean;
  capsule?: Record<string, unknown>;
}

export interface TurnBridgeActiveState {
  ok?: boolean;
  session_id?: string;
  rendered_text?: string;
  resident_count?: number;
  evicted_count?: number;
  resident_tokens?: number;
  error?: string;
}

export interface TurnBridgePayload {
  ok: boolean;
  session_id?: string;
  capsule: TurnBridgeCapsule | null;
  active_state: TurnBridgeActiveState | null;
  autoinject: Record<string, unknown> | null;
  /** Byte-identical `autoinject shadow --json` output (parse with parseShadowOutput). */
  autoinject_stdout?: string | null;
  /** Byte-identical `capsule ensure --json` output (parseActiveStateResult). */
  capsule_stdout?: string | null;
  /** Byte-identical `vmem hot-context --json` output (parseHotContextOutput). */
  render_stdout?: string | null;
  capsule_error?: string | null;
  render_error?: string | null;
  autoinject_error?: string | null;
  errors?: string[];
  /** Per-phase success (`null` = phase not requested); absent in older payloads. */
  phases_ok?: Record<string, boolean | null>;
  timings_ms?: Record<string, number>;
}

export interface TurnBridgeRequest {
  session: string;
  task: string;
  cwd?: string;
  projectId?: string;
  agentId?: string;
  branch?: string;
  roleProfile?: string;
  objective?: string;
  nextAction?: string;
  budgetTokens?: number;
  /** Phases to run; a cached AutoInject emit drops "autoinject". */
  want?: string[];
}

function requestToWire(home: string, request: TurnBridgeRequest): Record<string, unknown> {
  // The request id is assigned by `send` (one per round trip); a caller-supplied
  // id here would make every later request look like the first one and strand
  // its reply on a mismatched id until the timeout.
  return {
    op: "prepare_turn",
    home,
    session_id: request.session,
    task: request.task,
    cwd: request.cwd,
    project_id: request.projectId,
    agent_id: request.agentId,
    branch: request.branch,
    role_profile: request.roleProfile,
    objective: request.objective,
    next_action: request.nextAction,
    budget_tokens: request.budgetTokens ?? 256,
    want: request.want ?? ["capsule", "render", "autoinject"],
  };
}

function isPayload(value: unknown): value is TurnBridgePayload {
  if (value === null || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.ok === "boolean" && "capsule" in record && "active_state" in record;
}

/**
 * One bounded spawn: `second_brain turn prepare ...` (design "once"). Resolves
 * null on ANY failure (never rejects), like every other bridge in this
 * extension. `spawnImpl` is the same seam the helper uses, so tests drive both
 * designs with one scripted child.
 */
export async function runTurnPrepareOnce(options: {
  home: string;
  python: string;
  request: TurnBridgeRequest;
  timeoutMs: number;
  spawnImpl?: TurnBridgeSpawner;
}): Promise<TurnBridgePayload | null> {
  const args = [
    "-m",
    "second_brain",
    "turn",
    "prepare",
    "--session",
    options.request.session,
    "--task",
    options.request.task,
    "--branch",
    options.request.branch ?? "main",
    "--role",
    options.request.roleProfile ?? "worker",
    "--budget-tokens",
    String(options.request.budgetTokens ?? 256),
  ];
  if (options.request.want !== undefined && options.request.want.length > 0) {
    // Reduced phase sets (an emit-cache hit wants capsule+render only) MUST
    // reach the child: a rerun of the AutoInject decision would commit a
    // second delivery while the host serves the cached packet.
    args.push("--phases", options.request.want.join(","));
  }
  args.push("--json");
  if (options.request.cwd !== undefined && options.request.cwd.length > 0) {
    args.push("--cwd", options.request.cwd);
  }
  if (options.request.projectId !== undefined && options.request.projectId.length > 0) {
    args.push("--project", options.request.projectId);
  }
  if (options.request.agentId !== undefined && options.request.agentId.length > 0) {
    args.push("--agent", options.request.agentId);
  }
  if (options.request.objective !== undefined) {
    args.push("--objective", options.request.objective);
  }
  if (options.request.nextAction !== undefined) {
    args.push("--next-action", options.request.nextAction);
  }
  const spawnImpl = options.spawnImpl ?? spawn;
  return new Promise((resolve) => {
    let settled = false;
    let buffer = "";
    const finish = (value: TurnBridgePayload | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    let child: ChildProcess;
    try {
      child = spawnImpl(options.python, args, {
        cwd: options.home,
        env: turnChildEnv(options.home) as NodeJS.ProcessEnv,
        windowsHide: true,
        stdio: ["ignore", "pipe", "ignore"],
      });
    } catch {
      resolve(null);
      return;
    }
    const timer = setTimeout(() => {
      try {
        child.kill();
      } catch {
        // already gone
      }
      finish(null);
    }, options.timeoutMs);
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk: string) => {
      buffer += chunk;
    });
    child.once("error", () => finish(null));
    child.once("exit", (code) => {
      // Exit 0 = every requested phase succeeded; exit 1 = the JSON is still
      // complete but some phase failed. Both are parsed: the caller consumes
      // the phases that succeeded and retries only the failed ones.
      if (code !== 0 && code !== 1) {
        finish(null);
        return;
      }
      try {
        const parsed: unknown = JSON.parse(buffer);
        finish(isPayload(parsed) ? parsed : null);
      } catch {
        finish(null);
      }
    });
  });
}

interface PendingRequest {
  id: number;
  resolve: (value: Record<string, unknown> | null) => void;
  timer: NodeJS.Timeout;
}

/**
 * A reused interpreter for one (home, python) pair: JSON-lines over stdio,
 * memory operations only. Requests are serialized; the queue is bounded and
 * an over-limit request resolves null (the caller falls back) instead of
 * growing an unbounded backlog.
 */
export class TurnHelper {
  readonly home: string;
  readonly python: string;
  readonly timeoutMs: number;
  readonly maxRequests: number;
  readonly lifetimeMs: number;
  readonly queueLimit: number;
  readonly spawnImpl: TurnBridgeSpawner;

  private child?: ChildProcess;
  private state: "idle" | "starting" | "ready" | "dead" = "idle";
  private startPromise?: Promise<boolean>;
  private disposed = false;
  private chain: Promise<void> = Promise.resolve();
  private depth = 0;
  private nextId = 1;
  private stdoutBuffer = "";
  private readyBuffer: string[] = [];
  private pending?: PendingRequest;
  private exitHandler?: () => void;
  private starts = 0;
  private requests = 0;
  private failures = 0;
  private startFailures = 0;
  private lastFailure?: string;
  readyIdentity?: Record<string, unknown>;

  constructor(options: {
    home: string;
    python: string;
    timeoutMs: number;
    maxRequests: number;
    lifetimeMs: number;
    queueLimit: number;
    spawnImpl?: TurnBridgeSpawner;
  }) {
    this.home = options.home;
    this.python = options.python;
    this.timeoutMs = options.timeoutMs;
    this.maxRequests = options.maxRequests;
    this.lifetimeMs = options.lifetimeMs;
    this.queueLimit = options.queueLimit;
    this.spawnImpl = options.spawnImpl ?? spawn;
  }

  stats(): Record<string, unknown> {
    return {
      state: this.state,
      starts: this.starts,
      requests: this.requests,
      failures: this.failures,
      last_failure: this.lastFailure ?? null,
      queue_depth: this.depth,
      identity: this.readyIdentity ?? null,
    };
  }

  /** Start the helper if needed; resolves true only when the handshake completed. */
  async ensureStarted(): Promise<boolean> {
    if (this.disposed) return false;
    if (this.state === "ready") return true;
    if (this.state === "dead") return false;
    if (this.startPromise === undefined) {
      const start = performance.now();
      this.startPromise = this.spawnHelper().then((ok) => {
        e01SpanEnd("turn_helper.start", start, { ok, starts: this.starts });
        if (ok) {
          this.startFailures = 0;
        } else {
          // Bounded: three consecutive start failures retire the helper for
          // this process, so a broken interpreter is never respawned on every
          // request (the caller falls back to the per-phase path either way).
          this.failures += 1;
          this.startFailures += 1;
          if (this.startFailures >= 3) this.state = "dead";
        }
        this.startPromise = undefined;
        return ok;
      });
    }
    return this.startPromise;
  }

  /**
   * One request/response round trip. Resolves null when the helper cannot
   * answer (dead, timeout, malformed, identity change after one restart).
   */
  async request(payload: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    // `dead` is terminal (disposed); a dead transport (state idle) may restart.
    if (this.state === "dead" || this.disposed) return null;

    if (this.depth >= this.queueLimit) {
      this.failures += 1;
      this.lastFailure = "queue_full";
      return null;
    }
    this.depth += 1;
    const previous = this.chain;
    let release!: () => void;
    this.chain = new Promise<void>((resolve) => {
      release = resolve;
    });
    try {
      await previous;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        if (this.disposed) return null; // disposed while queued
        if (!(await this.ensureStarted())) return null;
        if (this.disposed) return null; // disposed during the handshake
        const start = performance.now();
        const response = await this.send(payload);
        if (this.disposed) return null; // disposed in flight: never retry
        e01SpanEnd("turn_helper.request", start, {
          attempt,
          ok: response !== null && response.ok !== false,
          starts: this.starts,
        });
        if (response === null) {
          this.kill("request_failed");
          continue;
        }
        if (response.ok === false && response.error === "identity_changed") {
          this.kill("identity_changed");
          continue;
        }
        this.requests += 1;
        return response;
      }
      return null;
    } finally {
      release();
      this.depth -= 1;
    }
  }

  /** Graceful shutdown: `shutdown` request, kill after the grace period. */
  stop(reason: string): void {
    const child = this.child;
    this.child = undefined;
    // Terminal: a disposed helper is never revived by the in-flight request
    // loop (kill() must not clear this), and no new child may be spawned.
    this.disposed = true;
    this.state = "dead";
    if (child === undefined) return;
    this.resolvePending(null);
    try {
      child.stdin?.write(`${JSON.stringify({ op: "shutdown", reason })}\n`);
    } catch {
      // stdin already gone: the kill below is the cleanup.
    }
    const timer = setTimeout(() => {
      try {
        child.kill();
      } catch {
        // already gone
      }
    }, TURN_HELPER_STOP_GRACE_MS);
    child.once("exit", () => clearTimeout(timer));
    child.unref();
    (child.stdin as unknown as { unref?: () => void } | undefined)?.unref?.();
    (child.stdout as unknown as { unref?: () => void } | undefined)?.unref?.();
  }

  private async spawnHelper(): Promise<boolean> {
    if (this.disposed) return false;
    if (this.child !== undefined) return this.state === "ready";
    const args = [
      "-m",
      "second_brain",
      "turn",
      "serve",
      "--max-requests",
      String(this.maxRequests),
      "--max-lifetime-s",
      String(Math.max(1, Math.round(this.lifetimeMs / 1000))),
    ];
    let child: ChildProcess;
    try {
      child = this.spawnImpl(this.python, args, {
        cwd: this.home,
        env: turnChildEnv(this.home),
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      this.failures += 1;
      this.lastFailure = error instanceof Error ? error.message : String(error);
      return false;
    }
    this.child = child;
    this.state = "starting";
    this.starts += 1;
    this.stdoutBuffer = "";
    if (this.exitHandler === undefined) {
      // Safety net: a host that exits without session_shutdown still never
      // leaves a live helper behind.
      this.exitHandler = () => {
        try {
          child.kill();
        } catch {
          // already gone
        }
      };
      process.once("exit", this.exitHandler);
    }
    const started = this.handshake(child);
    return started;
  }

  private handshake(child: ChildProcess): Promise<boolean> {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (ok: boolean, reason?: string): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (ok) {
          this.state = "ready";
        } else if (this.child === child) {
          // The transport never became usable: drop it and stay restartable
          // (the caller's retry/fallback decides whether to try again).
          this.lastFailure = reason ?? "handshake_failed";
          this.child = undefined;
          this.state = "idle";
          try {
            child.kill();
          } catch {
            // already gone
          }
        }
        resolve(ok);
      };
      const timer = setTimeout(() => finish(false, "helper start timeout"), this.timeoutMs);
      child.stdout?.setEncoding("utf8");
      child.stdout?.on("data", (chunk: string) => {
        this.stdoutBuffer += chunk;
        let index = this.stdoutBuffer.indexOf("\n");
        while (index >= 0) {
          const line = this.stdoutBuffer.slice(0, index).trim();
          this.stdoutBuffer = this.stdoutBuffer.slice(index + 1);
          if (line.length > 0) this.handleLine(line, finish);
          index = this.stdoutBuffer.indexOf("\n");
        }
      });
      child.stderr?.setEncoding("utf8");
      child.stderr?.on("data", (chunk: string) => {
        this.lastFailure = chunk.slice(-400);
      });
      child.once("error", (error) => finish(false, error.message));
      child.once("exit", () => {
        // A child we already retired (kill/dispose) must never mutate the
        // state of its successor.
        if (this.child !== child) {
          finish(false, "helper exited");
          return;
        }
        this.child = undefined;
        if (this.state !== "dead") this.state = "idle";
        this.resolvePending(null);
        finish(false, "helper exited");
      });
    });
  }

  /** Route one output line: the ready handshake, or the pending request's reply. */
  private handleLine(line: string, finishHandshake: (ok: boolean, reason?: string) => void): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      return;
    }
    if (parsed === null || typeof parsed !== "object") return;
    const record = parsed as Record<string, unknown>;
    if (record.op === "ready") {
      this.readyIdentity =
        record.identity !== null && typeof record.identity === "object"
          ? (record.identity as Record<string, unknown>)
          : undefined;
      finishHandshake(true);
      return;
    }
    const pending = this.pending;
    if (pending === undefined) return;
    if (record.id !== pending.id) return;
    this.pending = undefined;
    clearTimeout(pending.timer);
    pending.resolve(record);
  }

  private send(payload: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    const child = this.child;
    if (child === undefined || child.stdin === null) return Promise.resolve(null);
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending = undefined;
        this.failures += 1;
        this.lastFailure = "request timeout";
        resolve(null);
      }, this.timeoutMs);
      this.pending = { id, resolve, timer };
      try {
        child.stdin?.write(`${JSON.stringify({ ...payload, id })}\n`);
      } catch (error) {
        clearTimeout(timer);
        this.pending = undefined;
        this.lastFailure = error instanceof Error ? error.message : String(error);
        resolve(null);
      }
    });
  }

  private resolvePending(value: Record<string, unknown> | null): void {
    const pending = this.pending;
    if (pending === undefined) return;
    this.pending = undefined;
    clearTimeout(pending.timer);
    pending.resolve(value);
  }

  private kill(reason: string): void {
    const child = this.child;
    this.child = undefined;
    // A dead TRANSPORT is restarted by the next request (the caller still
    // decides whether to wait or fall back), but disposal stays terminal: a
    // request that was in flight when the helper was disposed must not spawn a
    // replacement after the registry was cleared.
    this.state = this.disposed ? "dead" : "idle";
    this.lastFailure = reason;
    this.failures += 1;
    this.resolvePending(null);
    if (child === undefined) return;
    try {
      child.stdin?.end();
    } catch {
      // stdin already closed
    }
    try {
      child.kill();
    } catch {
      // already gone
    }
  }

  /** Called on host session shutdown / process exit (cleanup contract). */
  dispose(reason: string): void {
    if (this.exitHandler !== undefined) {
      process.removeListener("exit", this.exitHandler);
      this.exitHandler = undefined;
    }
    this.stop(reason);
  }
}

const helpers = new Map<string, TurnHelper>();

/** One helper per (home, interpreter) for this host process. */
export function getTurnHelper(options: {
  home: string;
  python: string;
  cfg: TurnBridgeConfig;
  spawnImpl?: TurnBridgeSpawner;
}): TurnHelper {
  const key = `${options.home}\u0000${options.python}`;
  const existing = helpers.get(key);
  if (existing !== undefined) return existing;
  const helper = new TurnHelper({
    home: options.home,
    python: options.python,
    timeoutMs: options.cfg.timeoutMs,
    maxRequests: options.cfg.helperMaxRequests,
    lifetimeMs: options.cfg.helperLifetimeMs,
    queueLimit: options.cfg.queueLimit,
    spawnImpl: options.spawnImpl,
  });
  helpers.set(key, helper);
  return helper;
}

/** Current helper (test/diagnostics seam); no helper is created here. */
export function peekTurnHelper(home: string, python: string): TurnHelper | undefined {
  return helpers.get(`${home}\u0000${python}`);
}

/** Stop every helper this process started (session shutdown / host exit). */
export function stopTurnHelpers(reason: string): void {
  for (const helper of helpers.values()) helper.dispose(reason);
  helpers.clear();
}

/**
 * Batched per-prompt preparation with the configured design. `once` always
 * spawns; `helper` reuses the interpreter and falls back to one spawn when the
 * helper cannot answer. Returns null when nothing could be prepared.
 */
export async function prepareTurnWithBridge(options: {
  cfg: TurnBridgeConfig;
  home: string;
  python: string;
  request: TurnBridgeRequest;
  spawnImpl?: TurnBridgeSpawner;
}): Promise<TurnBridgePayload | null> {
  if (options.cfg.mode === "once") {
    const start = performance.now();
    const result = await runTurnPrepareOnce({
      home: options.home,
      python: options.python,
      request: options.request,
      timeoutMs: options.cfg.timeoutMs,
      spawnImpl: options.spawnImpl,
    });
    e01SpanEnd("turn_bridge.once", start, { ok: result !== null });
    return result;
  }
  if (options.cfg.mode === "helper") {
    const helper = getTurnHelper({
      home: options.home,
      python: options.python,
      cfg: options.cfg,
      spawnImpl: options.spawnImpl,
    });
    const response = await helper.request(requestToWire(options.home, options.request));
    if (response === null) {
      // Bounded fallback: the helper could not answer, so pay one bounded
      // spawn rather than losing this turn's memory context.
      const fallback = await runTurnPrepareOnce({
        home: options.home,
        python: options.python,
        request: options.request,
        timeoutMs: options.cfg.timeoutMs,
        spawnImpl: options.spawnImpl,
      });
      e01SpanEnd("turn_bridge.helper_fallback", performance.now(), {
        ok: fallback !== null,
      });
      return fallback;
    }
    const payload = response.result;
    return isPayload(payload) ? payload : null;
  }
  return null;
}

/** Test seam: drop the process-scoped helper registry. */
export function resetTurnHelpers(): void {
  for (const helper of helpers.values()) helper.stop("reset");
  helpers.clear();
}

export type { TurnChildEnv };
