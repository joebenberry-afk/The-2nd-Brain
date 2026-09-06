/** Trusted OMP native-attempt callbacks to Brain worker ownership. */

import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_WORKER_LIFECYCLE_TIMEOUT_MS = 5000;
export const OMP_WORKER_LIFECYCLE_MAX_STDOUT_CHARS = 64 * 1024;

type WorkerOutcome = "completed" | "failed" | "cancelled" | "interrupted" | null;

interface WorkerAttemptBase {
  home: string;
  sessionId: string;
  taskId: string;
  packetSha256: string;
  attemptId: string;
  projectId: string;
  worktreeId: string;
  callbackToken: string;
  python?: string;
  timeoutMs?: number;
}

export interface OmpWorkerBindOptions extends WorkerAttemptBase {
  hostGeneration: number;
  nativeAttemptId: string;
  nativeJobId: string | null;
  agentId: string;
}

export interface OmpWorkerLifecycleOptions extends OmpWorkerBindOptions {
  sequence: number;
  outcome: WorkerOutcome;
  executorSettled: boolean;
  cleanupComplete: boolean;
}

export interface OmpWorkerDispatchFailedOptions extends WorkerAttemptBase {
  failureCode: string;
}

export interface OmpWorkerCallbackResult {
  ok: boolean;
  status?: "accepted" | "rejected";
  taskId?: string;
  attemptId?: string;
  sequence?: number;
  failureCode?: string;
  error?: string;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

export function parseOmpWorkerCallbackOutput(
  stdout: string,
  expected: { taskId: string; attemptId: string; sequence?: number },
): OmpWorkerCallbackResult {
  if (stdout.length > OMP_WORKER_LIFECYCLE_MAX_STDOUT_CHARS) {
    return { ok: false, error: "BRAIN_WORKER_CALLBACK_OUTPUT_TOO_LARGE" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { ok: false, error: "BRAIN_WORKER_CALLBACK_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") {
    return { ok: false, error: "BRAIN_WORKER_CALLBACK_INVALID_RESPONSE" };
  }
  const value = parsed as Record<string, unknown>;
  const status = value.status === "accepted" || value.status === "rejected" ? value.status : undefined;
  const taskId = bounded(value.task_id, 512);
  const attemptId = bounded(value.attempt_id, 128);
  const sequence = typeof value.lifecycle_sequence === "number" ? value.lifecycle_sequence : undefined;
  const failureCode = bounded(value.failure_code, 128);
  if (
    status === undefined ||
    taskId !== expected.taskId ||
    attemptId !== expected.attemptId ||
    (expected.sequence !== undefined && sequence !== expected.sequence)
  ) {
    return { ok: false, error: "BRAIN_WORKER_CALLBACK_RECEIPT_MISMATCH" };
  }
  if (status === "rejected") {
    return {
      ok: false,
      status,
      taskId,
      attemptId,
      ...(sequence !== undefined ? { sequence } : {}),
      failureCode,
      error: failureCode || "BRAIN_WORKER_CALLBACK_REJECTED",
    };
  }
  return { ok: true, status, taskId, attemptId, ...(sequence !== undefined ? { sequence } : {}) };
}

function runCallback(
  options: WorkerAttemptBase,
  payload: Record<string, unknown>,
  sequence?: number,
): Promise<OmpWorkerCallbackResult> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  return new Promise((resolveResult) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_WORKER_LIFECYCLE_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_WORKER_LIFECYCLE_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolveResult({ ok: false, error: "BRAIN_WORKER_CALLBACK_UNAVAILABLE" });
          return;
        }
        resolveResult(parseOmpWorkerCallbackOutput(stdout, {
          taskId: bounded(options.taskId, 512),
          attemptId: bounded(options.attemptId, 128),
          sequence,
        }));
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}

function basePayload(options: WorkerAttemptBase): Record<string, unknown> {
  return {
    harness: "omp",
    host_session_id: bounded(options.sessionId, 128),
    task_id: bounded(options.taskId, 512),
    packet_sha256: bounded(options.packetSha256, 128),
    attempt_id: bounded(options.attemptId, 128),
    project_id: bounded(options.projectId, 128),
    worktree_id: bounded(options.worktreeId, 512),
    callback_token: bounded(options.callbackToken, 512),
  };
}

export function runOmpWorkerBind(options: OmpWorkerBindOptions): Promise<OmpWorkerCallbackResult> {
  return runCallback(options, {
    ...basePayload(options),
    operation: "worker_bind",
    host_generation: options.hostGeneration,
    native_attempt_id: bounded(options.nativeAttemptId, 128),
    native_job_id: options.nativeJobId === null ? null : bounded(options.nativeJobId, 512),
    agent_id: bounded(options.agentId, 512),
  });
}

export function runOmpWorkerLifecycle(options: OmpWorkerLifecycleOptions): Promise<OmpWorkerCallbackResult> {
  return runCallback(options, {
    ...basePayload(options),
    operation: "worker_lifecycle",
    host_generation: options.hostGeneration,
    native_attempt_id: bounded(options.nativeAttemptId, 128),
    native_job_id: options.nativeJobId === null ? null : bounded(options.nativeJobId, 512),
    agent_id: bounded(options.agentId, 512),
    sequence: options.sequence,
    outcome: options.outcome,
    executor_settled: options.executorSettled,
    cleanup_complete: options.cleanupComplete,
  }, options.sequence);
}

export function runOmpWorkerDispatchFailed(
  options: OmpWorkerDispatchFailedOptions,
): Promise<OmpWorkerCallbackResult> {
  return runCallback(options, {
    ...basePayload(options),
    operation: "worker_dispatch_failed",
    failure_code: bounded(options.failureCode, 128),
  });
}
