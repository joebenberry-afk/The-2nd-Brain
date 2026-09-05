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
  used: number;
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
        resolve({ state: "OK", used: 0, cap: 0, error: error.message });
        return;
      }
      try {
        const parsed = JSON.parse(stdout) as Record<string, unknown>;
        const state: BudgetState =
          parsed.state === "HARD" ? "HARD" : parsed.state === "SOFT" ? "SOFT" : "OK";
        resolve({
          state,
          used: typeof parsed.used === "number" ? parsed.used : 0,
          cap: typeof parsed.cap === "number" ? parsed.cap : 0,
        });
      } catch {
        resolve({ state: "OK", used: 0, cap: 0, error: "INVALID_JSON" });
      }
    },
  );

  return promise;
}
