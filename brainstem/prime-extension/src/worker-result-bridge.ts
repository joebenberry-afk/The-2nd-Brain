/** Thin OMP worker-result bridge to the existing Brain T4.1 lifecycle. */

import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_WORKER_RESULT_TIMEOUT_MS = 5000;
export const OMP_WORKER_RESULT_MAX_STDOUT_CHARS = 256 * 1024;
export const OMP_WORKER_RESULT_MAX_SUMMARY_CHARS = 2048;

export type OmpWorkerResultStatus = "completed" | "failed" | "cancelled";

export interface OmpWorkerResultOutcome {
  ok: boolean;
  status?: string;
  failureCode?: string;
  taskId?: string;
  packetSha256?: string;
  resultSha256?: string;
  error?: string;
}

export interface OmpWorkerResultOptions {
  home: string;
  sessionId: string;
  taskId: string;
  packetSha256: string;
  status: OmpWorkerResultStatus;
  workerAgent: string;
  workerModel?: string;
  workerRole?: string;
  summary?: string;
  childOmpAgentId?: string;
  python?: string;
  timeoutMs?: number;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

export function parseOmpWorkerResultOutput(stdout: string): OmpWorkerResultOutcome {
  if (stdout.length > OMP_WORKER_RESULT_MAX_STDOUT_CHARS) {
    return { ok: false, error: "BRAIN_WORKER_RESULT_OUTPUT_TOO_LARGE" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { ok: false, error: "BRAIN_WORKER_RESULT_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") {
    return { ok: false, error: "BRAIN_WORKER_RESULT_INVALID_RESPONSE" };
  }
  const value = parsed as Record<string, unknown>;
  const taskId = bounded(value.task_id, 512);
  const status = bounded(value.status, 32);
  if (!taskId || !status) {
    return { ok: false, error: "BRAIN_WORKER_RESULT_INVALID_RESPONSE" };
  }
  const outcome: OmpWorkerResultOutcome = { ok: status !== "failed", status, taskId };
  const failureCode = bounded(value.failure_code, 128);
  if (failureCode) outcome.failureCode = failureCode;
  if (sha256(value.packet_sha256)) outcome.packetSha256 = value.packet_sha256;
  if (sha256(value.result_sha256)) outcome.resultSha256 = value.result_sha256;
  if (!outcome.ok && !outcome.error) outcome.error = failureCode || "BRAIN_WORKER_RESULT_FAILED";
  return outcome;
}

/**
 * Convert one completed/failed/cancelled worker child result into a validated
 * T4.1 lifecycle event. `worker_identity` assembly (agent_id, internal
 * session id, role_profile normalization) happens Python-side inside
 * `omp_adapter._prepare_worker_result` — this bridge sends only the flat
 * wire fields the Python `worker_result` operation expects.
 */
export function runOmpWorkerResult(
  options: OmpWorkerResultOptions,
): Promise<OmpWorkerResultOutcome> {
  const python =
    options.python ??
    process.env.SECOND_BRAIN_PYTHON ??
    join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const payload = {
    operation: "worker_result",
    harness: "omp",
    host_session_id: bounded(options.sessionId, 128),
    session_id: bounded(options.sessionId, 128),
    task_id: bounded(options.taskId, 512),
    packet_sha256: bounded(options.packetSha256, 128),
    status: options.status,
    worker_agent: bounded(options.workerAgent, 128),
    worker_model: bounded(options.workerModel ?? "", 128),
    worker_role: bounded(options.workerRole ?? "", 128),
    summary: bounded(options.summary ?? "", OMP_WORKER_RESULT_MAX_SUMMARY_CHARS),
    child_omp_agent_id: bounded(options.childOmpAgentId ?? "", 128),
  };
  return new Promise((resolve) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_WORKER_RESULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_WORKER_RESULT_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: "BRAIN_WORKER_RESULT_UNAVAILABLE" });
          return;
        }
        resolve(parseOmpWorkerResultOutput(stdout));
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}
