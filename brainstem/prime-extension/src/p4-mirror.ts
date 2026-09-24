/** Thin Prime -> Second Brain P4 bridge: one bounded call per lifecycle
 * event, composing the local heartbeat with shutdown-only Radar/fingerprint
 * observation (Task 7; replaces the narrower radar-mirror.ts). Follows the
 * exact fail-open/venv/timeout/session-id-verification contract established
 * by radar-mirror.ts and environment-mirror.ts. */
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

type JsonRecord = Record<string, unknown>;

export const P4_DEFAULT_TIMEOUT_MS = 5000;
export const P4_MAX_OUTPUT_BYTES = 1024 * 1024;

export interface P4PulseOptions {
  home: string;
  hostSessionId: string;
  event: string;
  repo?: string;
  projectId?: string;
  force?: boolean;
  python?: string;
  timeoutMs?: number;
}

export interface P4PulseResult {
  ok: boolean;
  sessionId?: string;
  heartbeat?: Record<string, unknown>;
  candidates?: Record<string, unknown>[];
  fingerprints?: Record<string, unknown>[];
  error?: string;
}

function p4Env(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

function parseResult(stdout: string, sessionId: string): P4PulseResult {
  try {
    const payload = JSON.parse(stdout) as JsonRecord;
    if (payload.session_id !== sessionId) return { ok: false, error: "p4 session mismatch" };
    return {
      ok: true,
      sessionId,
      heartbeat:
        payload.heartbeat != null && typeof payload.heartbeat === "object"
          ? (payload.heartbeat as JsonRecord)
          : undefined,
      candidates: Array.isArray(payload.candidates) ? (payload.candidates as JsonRecord[]) : [],
      fingerprints: Array.isArray(payload.fingerprints) ? (payload.fingerprints as JsonRecord[]) : [],
    };
  } catch {
    return { ok: false, error: "p4 pulse returned unparsable output" };
  }
}

/**
 * Asynchronous P4 pulse for `session_start`/`turn_start`: queued
 * fire-and-forget, never blocks the host turn. `--no-telemetry` always
 * accompanies the call: Python composes and returns the pulse but writes
 * nothing itself, so the bounded TS sensor (`heartbeatPulse`) owns the one
 * telemetry write this bridge produces. Shutdown does not use this bridge at
 * all — its pulse is detached and self-telemetring
 * (`src/detached-maintenance.ts`).
 */
export function runP4Pulse(options: P4PulseOptions): Promise<P4PulseResult> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) return Promise.resolve({ ok: true, sessionId: options.hostSessionId });
  const args = [
    "-m", "second_brain", "p4", "pulse",
    "--event", options.event,
    "--session", options.hostSessionId,
    ...(options.repo ? ["--repo", options.repo] : []),
    ...(options.projectId ? ["--project-id", options.projectId] : []),
    ...(options.force ? ["--force"] : []),
    "--no-telemetry",
    "--json",
  ];
  return new Promise((resolve) => {
    execFile(
      python,
      args,
      {
        cwd: options.home,
        env: p4Env(options.home),
        timeout: options.timeoutMs ?? P4_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: P4_MAX_OUTPUT_BYTES,
      },
      (error, stdout) => {
        if (error) {
          resolve({
            ok: false,
            sessionId: options.hostSessionId,
            error: error instanceof Error ? error.message : String(error),
          });
          return;
        }
        resolve(parseResult(String(stdout), options.hostSessionId));
      },
    );
  });
}
