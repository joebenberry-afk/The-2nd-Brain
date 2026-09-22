/**
 * Thin OMP -> Second Brain governor budget check bridge.
 * T3.1: hard and soft token budget caps.
 */

import { execFile } from "node:child_process";
import { join } from "node:path";

export type BudgetState = "OK" | "SOFT" | "HARD";

export const BUDGET_DEFAULT_TIMEOUT_MS = 3000;
export const BUDGET_HARD_LINE = "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED";

export interface BudgetCheckOptions {
  home: string;
  sessionId: string;
  role?: string;
  python?: string;
  timeoutMs?: number;
}

export interface BudgetCheckResult {
  state: BudgetState;
  used: number | null;
  cap: number;
  error?: string;
}

export type BudgetRunner = (options: BudgetCheckOptions) => Promise<BudgetCheckResult>;

interface PromiseWithResolvers<T> {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
}

type PromiseWithResolversConstructor = typeof Promise & {
  withResolvers<T>(): PromiseWithResolvers<T>;
};

function createResolvers<T>(): PromiseWithResolvers<T> {
  if ("withResolvers" in Promise && typeof (Promise as unknown as PromiseWithResolversConstructor).withResolvers === "function") {
    return (Promise as unknown as PromiseWithResolversConstructor).withResolvers<T>();
  }
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Run one bounded Brain-owned budget check; every failure fails open to OK. */
export function runBudgetCheck(options: BudgetCheckOptions): Promise<BudgetCheckResult> {
  const python =
    options.python ??
    process.env.SECOND_BRAIN_PYTHON ??
    join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const role = options.role || "default";

  const { promise, resolve } = createResolvers<BudgetCheckResult>();

  execFile(
    python,
    [
      "-m",
      "second_brain",
      "--home",
      options.home,
      "governor",
      "check-budget",
      "--session",
      options.sessionId,
      "--role",
      role,
      "--json",
    ],
    {
      cwd: options.home,
      env,
      timeout: options.timeoutMs ?? BUDGET_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
    },
    (error, stdout) => {
      if (error) {
        resolve({ state: "OK", used: null, cap: 0, error: error.message });
        return;
      }
      try {
        const parsed = JSON.parse(stdout) as Record<string, unknown>;
        const state: BudgetState =
          parsed.state === "HARD" ? "HARD" : parsed.state === "SOFT" ? "SOFT" : "OK";
        const validUsed = typeof parsed.used === "number" && Number.isFinite(parsed.used) && parsed.used >= 0;
        const degraded = typeof parsed.error === "string" ? parsed.error.slice(0, 256) :
          !validUsed ? "ACCOUNTING_UNAVAILABLE" : undefined;
        resolve({
          state: degraded ? "OK" : state,
          used: validUsed ? Number(parsed.used) : null,
          cap: typeof parsed.cap === "number" ? parsed.cap : 0,
          ...(degraded ? { error: degraded } : {}),
        });
      } catch {
        resolve({ state: "OK", used: null, cap: 0, error: "INVALID_JSON" });
      }
    },
  );

  return promise;
}

export interface BudgetReserveOptions extends BudgetCheckOptions {
  /** The worker task this reservation belongs to; idempotent per (session, task). */
  taskId: string;
  /** Tokens to reserve; the Brain defaults to the role cap. */
  tokens?: number;
}

export interface BudgetReserveResult {
  reserved: boolean;
  /** The decided fail-closed outcome: this dispatch must not proceed. */
  blocksDispatch: boolean;
  state: BudgetState;
  used: number | null;
  cap: number;
  outstanding: number;
  reason?: string;
  error?: string;
}

export type BudgetReserver = (options: BudgetReserveOptions) => Promise<BudgetReserveResult>;

/**
 * Atomically check capacity and reserve budget before a worker dispatch.
 *
 * Unlike the budget *check*, this is fail-closed on the cases the owner's policy names:
 * zero remaining allowance and unresolved accounting both refuse the dispatch. A bridge
 * failure is reported as `RESERVATION_UNAVAILABLE` and does not block on its own -- that
 * keeps the transport availability semantics of `runBudgetCheck` and leaves the caller to
 * record the error, with the refusal path reserved for real budget answers.
 */
export function reserveBudget(options: BudgetReserveOptions): Promise<BudgetReserveResult> {
  const python =
    options.python ??
    process.env.SECOND_BRAIN_PYTHON ??
    join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const role = options.role || "worker";
  const args = [
    "-m",
    "second_brain",
    "--home",
    options.home,
    "governor",
    "reserve-budget",
    "--session",
    options.sessionId,
    "--task-id",
    options.taskId,
    "--role",
    role,
    "--json",
  ];
  if (options.tokens !== undefined) args.push("--tokens", String(options.tokens));

  const { promise, resolve } = createResolvers<BudgetReserveResult>();

  execFile(
    python,
    args,
    {
      cwd: options.home,
      env,
      timeout: options.timeoutMs ?? BUDGET_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
    },
    (error, stdout) => {
      // A refusal exits 3 with a well-formed body, so stdout is parsed before the
      // process status is treated as a transport failure.
      let parsed: Record<string, unknown> | null = null;
      try {
        parsed = JSON.parse(stdout) as Record<string, unknown>;
      } catch {
        parsed = null;
      }
      if (parsed === null) {
        resolve({
          reserved: false,
          blocksDispatch: false,
          state: "OK",
          used: null,
          cap: 0,
          outstanding: 0,
          reason: "RESERVATION_UNAVAILABLE",
          ...(error ? { error: error.message } : { error: "INVALID_JSON" }),
        });
        return;
      }
      const reserved = parsed.reserved === true;
      const reason = typeof parsed.reason === "string" ? parsed.reason : undefined;
      const degraded = parsed.reason === "ACCOUNTING_UNAVAILABLE";
      const state: BudgetState =
        parsed.state === "HARD" ? "HARD" : parsed.state === "SOFT" ? "SOFT" : "OK";
      resolve({
        reserved,
        blocksDispatch: !reserved && (reason === "BUDGET_EXHAUSTED" || degraded),
        state,
        used: typeof parsed.used === "number" && Number.isFinite(parsed.used) ? Number(parsed.used) : null,
        cap: typeof parsed.cap === "number" ? parsed.cap : 0,
        outstanding: typeof parsed.outstanding === "number" ? parsed.outstanding : 0,
        ...(reason ? { reason } : {}),
      });
    },
  );

  return promise;
}
