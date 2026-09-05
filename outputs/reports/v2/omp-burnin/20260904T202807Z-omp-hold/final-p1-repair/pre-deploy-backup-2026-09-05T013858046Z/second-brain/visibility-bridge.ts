/** Thin OMP -> Second Brain skill-visibility bridge (plan P3.16). */

import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_VISIBILITY_MAX_TASK_CHARS = 2048;
export const OMP_VISIBILITY_MAX_IDENTITY_CHARS = 128;
export const OMP_VISIBILITY_MAX_SKILLS = 3;
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

function validBoundedString(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function parseSkillIds(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > OMP_VISIBILITY_MAX_SKILLS) return null;
  const ids = value.map((id) => (validBoundedString(id, OMP_VISIBILITY_MAX_IDENTITY_CHARS) ? id : null));
  return ids.every((id): id is string => id !== null) ? ids : null;
}

function parseSkillReasons(value: unknown): Record<string, string> | null {
  if (!isPlainObject(value)) return null;
  const entries = Object.entries(value);
  if (
    entries.some(
      ([key, reason]) =>
        !validBoundedString(key, OMP_VISIBILITY_MAX_IDENTITY_CHARS) ||
        typeof reason !== "string" ||
        reason.length > OMP_VISIBILITY_MAX_IDENTITY_CHARS,
    )
  ) {
    return null;
  }
  return Object.fromEntries(entries) as Record<string, string>;
}

function invalidResult(error: string): OmpVisibilityResult {
  return { visibility_plan: null, hydrated_instructions: {}, error };
}

/** Validate an untrusted visibility result and discard malformed injections. */
export function validateOmpVisibilityResult(raw: unknown): OmpVisibilityResult {
  if (!isPlainObject(raw)) return invalidResult("BRAIN_VISIBILITY_INVALID_RESPONSE");
  const value = raw as Record<string, unknown>;
  const rawPlan = value.visibility_plan;
  if (!isPlainObject(rawPlan)) {
    return invalidResult(bounded(value.error, 128) || "BRAIN_VISIBILITY_UNAVAILABLE");
  }
  const selectedSkillIds = parseSkillIds(rawPlan.selected_skill_ids);
  const hydratedSkillIds = parseSkillIds(rawPlan.hydrated_skill_ids);
  const rejectedSkillIds = parseSkillReasons(rawPlan.rejected_skill_ids);
  const unavailableSkillIds = parseSkillReasons(rawPlan.unavailable_skill_ids);
  if (
    !validBoundedString(rawPlan.visibility_plan_id, OMP_VISIBILITY_MAX_IDENTITY_CHARS) ||
    (rawPlan.mode !== "shadow" && rawPlan.mode !== "enforced") ||
    selectedSkillIds === null ||
    hydratedSkillIds === null ||
    rejectedSkillIds === null ||
    unavailableSkillIds === null
  ) {
    return invalidResult("BRAIN_VISIBILITY_INVALID_PLAN");
  }
  if (!isPlainObject(value.hydrated_instructions)) {
    return invalidResult("BRAIN_VISIBILITY_INVALID_PLAN");
  }
  const hydratedEntries = Object.entries(value.hydrated_instructions);
  if (
    hydratedEntries.some(
      ([skillId, text]) =>
        !validBoundedString(skillId, OMP_VISIBILITY_MAX_IDENTITY_CHARS) ||
        !selectedSkillIds.includes(skillId) ||
        !hydratedSkillIds.includes(skillId) ||
        typeof text !== "string" ||
        text.length > OMP_VISIBILITY_MAX_INJECTED_CHARS,
    )
  ) {
    return invalidResult("BRAIN_VISIBILITY_INVALID_PLAN");
  }
  // hydrated_skill_ids must equal the complete bodies actually present --
  // never a subset/superset (P3.16 defect fix companion check).
  if (hydratedSkillIds.length !== hydratedEntries.length) {
    return invalidResult("BRAIN_VISIBILITY_INVALID_PLAN");
  }
  // Aggregate injection budget (P3.16 defect fix): the same bound OMP applies
  // when concatenating hydrated bodies with a 2-char "\n\n" separator before
  // injection. Reject the WHOLE plan here -- fail open to no injection --
  // rather than let a later concatenate+slice silently truncate one body.
  const totalInjectedChars =
    hydratedEntries.reduce((sum, [, text]) => sum + (text as string).length, 0) +
    Math.max(0, hydratedEntries.length - 1) * 2;
  if (totalInjectedChars > OMP_VISIBILITY_MAX_INJECTED_CHARS) {
    return invalidResult("BRAIN_VISIBILITY_AGGREGATE_TOO_LARGE");
  }
  const plan: OmpVisibilityPlan = {
    visibility_plan_id: rawPlan.visibility_plan_id,
    mode: rawPlan.mode,
    selected_skill_ids: selectedSkillIds,
    hydrated_skill_ids: hydratedSkillIds,
    rejected_skill_ids: rejectedSkillIds,
    unavailable_skill_ids: unavailableSkillIds,
  };
  return {
    visibility_plan: plan,
    hydrated_instructions: Object.fromEntries(hydratedEntries) as Record<string, string>,
    error: null,
  };
}

/** Parse the omp-routing CLI bridge's skill_visibility JSON response. Every
 * malformed/oversized/non-object shape fails open to a null plan. */
export function parseOmpVisibilityOutput(stdout: string): OmpVisibilityResult {
  if (stdout.length > OMP_VISIBILITY_MAX_STDOUT_CHARS) {
    return invalidResult("BRAIN_VISIBILITY_OUTPUT_TOO_LARGE");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return invalidResult("BRAIN_VISIBILITY_INVALID_JSON");
  }
  return validateOmpVisibilityResult(parsed);
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
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
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
