/** Thin OMP -> Second Brain skill-visibility bridge (plan P3.16). */

import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_VISIBILITY_MAX_TASK_CHARS = 2048;
export const OMP_VISIBILITY_MAX_IDENTITY_CHARS = 128;
export const OMP_VISIBILITY_TIMEOUT_MS = 3000;
export const OMP_VISIBILITY_MAX_STDOUT_CHARS = 256 * 1024;
export const OMP_VISIBILITY_MAX_INJECTED_CHARS = 8192;

export interface OmpVisibilityOptions {
  home: string;
  task: string;
  sessionId: string;
  projectId: string;
  python?: string;
  timeoutMs?: number;
}

export interface OmpVisibilityPlan {
  visibility_plan_id: string;
  mode: "shadow" | "enforced";
  selected_skill_ids: string[];
  hydrated_skill_ids: string[];
  rejected_skill_ids: Record<string, string>;
  unavailable_skill_ids: Record<string, string>;
  [key: string]: unknown;
}

export interface OmpVisibilityResult {
  visibility_plan: OmpVisibilityPlan | null;
  hydrated_instructions: Record<string, string>;
  error: string | null;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

/** Parse the omp-routing CLI bridge's skill_visibility JSON response. Every
 * malformed/oversized/non-object shape fails open to a null plan. */
export function parseOmpVisibilityOutput(stdout: string): OmpVisibilityResult {
  if (stdout.length > OMP_VISIBILITY_MAX_STDOUT_CHARS) {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_OUTPUT_TOO_LARGE" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_INVALID_RESPONSE" };
  }
  const value = parsed as Record<string, unknown>;
  const plan = value.visibility_plan;
  const hydrated = value.hydrated_instructions;
  const hydratedInstructions: Record<string, string> =
    hydrated != null && typeof hydrated === "object" && !Array.isArray(hydrated)
      ? Object.fromEntries(
          Object.entries(hydrated as Record<string, unknown>).filter(
            ([, text]) => typeof text === "string",
          ) as [string, string][],
        )
      : {};
  if (plan == null || typeof plan !== "object" || Array.isArray(plan)) {
    return {
      visibility_plan: null,
      hydrated_instructions: {},
      error: bounded(value.error, 128) || "BRAIN_VISIBILITY_UNAVAILABLE",
    };
  }
  return { visibility_plan: plan as OmpVisibilityPlan, hydrated_instructions: hydratedInstructions, error: null };
}

export function ompVisibilityRecord(
  kind: string,
  session: string,
  fields: Record<string, unknown>,
): Record<string, unknown> {
  return {
    v: 3,
    ts: new Date().toISOString(),
    kind,
    session,
    ...fields,
  };
}

/** Run one bounded Brain-owned skill-visibility plan; every failure fails open. */
export function runOmpVisibility(options: OmpVisibilityOptions): Promise<OmpVisibilityResult> {
  const python = options.python ?? join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const payload = {
    operation: "skill_visibility",
    task: bounded(options.task, OMP_VISIBILITY_MAX_TASK_CHARS),
    host_session_id: bounded(options.sessionId, OMP_VISIBILITY_MAX_IDENTITY_CHARS),
    project_id: bounded(options.projectId, OMP_VISIBILITY_MAX_IDENTITY_CHARS),
  };
  return new Promise((resolve) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_VISIBILITY_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_VISIBILITY_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolve({ visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_UNAVAILABLE" });
          return;
        }
        resolve(parseOmpVisibilityOutput(stdout));
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}
