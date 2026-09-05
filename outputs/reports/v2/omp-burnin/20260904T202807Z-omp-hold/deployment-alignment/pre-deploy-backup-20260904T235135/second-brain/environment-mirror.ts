import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

export const ENVIRONMENT_DEFAULT_TIMEOUT_MS = 5000;

type JsonRecord = Record<string, unknown>;

export interface EnvironmentAssessmentOptions {
  home: string;
  hostSessionId: string;
  repo: string;
  taskId?: string;
  phase: "session_start" | "task_boundary" | "doctor" | "shutdown";
  expectedFields?: string[];
  python?: string;
  timeoutMs?: number;
}

export interface EnvironmentAssessmentResult {
  ok: boolean;
  sessionId?: string;
  environmentStewardId?: string;
  environmentHash?: string;
  mutationDetected?: boolean;
  mutationClassification?: string;
  completionEligible?: boolean;
  evidence?: JsonRecord;
  error?: string;
}

function pythonExe(home: string, python?: string): string {
  return python ?? join(home, ".venv", "Scripts", "python.exe");
}

function runEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

function parseResult(stdout: string, sessionId: string): EnvironmentAssessmentResult {
  try {
    const evidence = JSON.parse(stdout) as JsonRecord;
    if (evidence.session_id !== sessionId) {
      return { ok: false, error: "environment session mismatch" };
    }
    return {
      ok: true,
      sessionId,
      environmentStewardId:
        typeof evidence.environment_steward_id === "string"
          ? evidence.environment_steward_id
          : undefined,
      environmentHash:
        typeof evidence.environment_hash === "string" ? evidence.environment_hash : undefined,
      mutationDetected: evidence.mutation_detected === true,
      mutationClassification:
        typeof evidence.mutation_classification === "string"
          ? evidence.mutation_classification
          : undefined,
      completionEligible: evidence.completion_eligible === true,
      evidence,
    };
  } catch {
    return { ok: false, error: "environment assessment returned unparsable output" };
  }
}

export function runEnvironmentAssessmentSync(
  options: EnvironmentAssessmentOptions,
): EnvironmentAssessmentResult {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) return { ok: true, sessionId: options.hostSessionId };
  const args = [
    "-m", "second_brain", "env", "assess", options.repo,
    "--session", options.hostSessionId,
    ...(options.taskId ? ["--task-id", options.taskId] : []),
    "--phase", options.phase,
  ];
  for (const field of options.expectedFields ?? []) args.push("--expected-field", field);
  args.push("--json");
  try {
    const stdout = execFileSync(python, args, {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? ENVIRONMENT_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
    });
    return parseResult(String(stdout), options.hostSessionId);
  } catch (error) {
    return { ok: false, sessionId: options.hostSessionId, error: error instanceof Error ? error.message : String(error) };
  }
}
