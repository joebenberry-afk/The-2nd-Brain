import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

type JsonRecord = Record<string, unknown>;

export interface RadarObservationOptions {
  home: string;
  hostSessionId: string;
  repo: string;
  projectId: string;
  taskId?: string;
  python?: string;
  timeoutMs?: number;
}

export interface RadarObservationResult {
  ok: boolean;
  sessionId?: string;
  candidateCount?: number;
  candidates?: JsonRecord[];
  error?: string;
}

function parseResult(stdout: string, sessionId: string): RadarObservationResult {
  try {
    const payload = JSON.parse(stdout) as JsonRecord;
    if (payload.session_id !== sessionId) return { ok: false, error: "radar session mismatch" };
    return {
      ok: true,
      sessionId,
      candidateCount: typeof payload.candidate_count === "number" ? payload.candidate_count : 0,
      candidates: Array.isArray(payload.candidates) ? payload.candidates as JsonRecord[] : [],
    };
  } catch {
    return { ok: false, error: "radar returned unparsable output" };
  }
}

export function runRadarObservationSync(
  options: RadarObservationOptions,
): RadarObservationResult {
  const python = options.python ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) return { ok: true, sessionId: options.hostSessionId, candidateCount: 0, candidates: [] };
  const args = [
    "-m", "second_brain", "radar", "observe", options.hostSessionId,
    "--project-id", options.projectId,
    "--repo", options.repo,
    ...(options.taskId ? ["--task-id", options.taskId] : []),
    "--json",
  ];
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  try {
    return parseResult(String(execFileSync(python, args, {
      cwd: options.home,
      env,
      timeout: options.timeoutMs ?? 5000,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
    })), options.hostSessionId);
  } catch (error) {
    return { ok: false, sessionId: options.hostSessionId, error: error instanceof Error ? error.message : String(error) };
  }
}
