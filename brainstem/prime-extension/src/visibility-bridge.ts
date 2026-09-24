/** Thin OMP -> Second Brain skill-visibility bridge (plan P3.16). */

import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
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

/**
 * `skills.resolve_visibility_mode` — `[visibility] mode` from
 * `<home>/config/skills.toml`. Python injects specialist instructions only when
 * that resolved value is the exact string `enforced`
 * (`omp_adapter._prepare_skill_visibility` -> `skills.build_plan` ->
 * `plan_to_evidence`), so this in-host read lets the quiet fast path keep its
 * saving while leaving the enforced path untouched.
 *
 * Direction of safety: `"shadow"` here SUPPRESSES a Python process that would
 * otherwise deliver skill instructions, so the parser answers `"enforced"`
 * whenever it cannot decode the value itself (an escaped/multiline string, a
 * duplicate `mode` key, anything it does not recognize). A missing file, a
 * file without a `[visibility] mode` key, or a plainly different value resolves
 * to `"shadow"`, which is exactly the fail-safe `resolve_visibility_mode` itself
 * applies to those cases.
 */
export function skillsVisibilityModeFromToml(text: string): "enforced" | "shadow" {
  let section = "";
  let value: string | undefined;
  for (const rawLine of text.split(/\r?\n/u)) {
    // Comment stripping is fine for a bounded string value: a '#' inside it can
    // only make the decode fail, which answers "enforced" (the safe direction).
    const line = (rawLine.split("#")[0] ?? "").trim();
    if (line.length === 0) continue;
    if (line.startsWith("[")) {
      section = line
        .replace(/^\[+/u, "")
        .replace(/\]+$/u, "")
        .trim()
        .replace(/^["']|["']$/gu, "");
      continue;
    }
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line
      .slice(0, eq)
      .trim()
      .replace(/^["']|["']$/gu, "");
    const isVisibilityMode =
      section === "visibility" ? key === "mode" : section === "" && key === "visibility.mode";
    if (!isVisibilityMode) continue;
    const raw = (line.slice(eq + 1) ?? "").trim();
    const quote = raw[0];
    if (raw.length < 2 || (quote !== '"' && quote !== "'") || !raw.endsWith(quote)) {
      return "enforced"; // not a decodable string literal: do not assume shadow
    }
    const decoded = raw.slice(1, -1);
    if (decoded.includes(quote) || decoded.includes("\\") || decoded.includes("\n")) {
      return "enforced"; // multi-line/escaped literal: do not assume shadow
    }
    if (value !== undefined) return "enforced"; // duplicate key: let Python decide
    value = decoded;
  }
  if (value === undefined) return "shadow";
  return value === "enforced" ? "enforced" : "shadow";
}

/** `skills.resolve_visibility_mode` for a home directory; never throws. */
export function loadSkillsVisibilityMode(home: string | null): "enforced" | "shadow" {
  if (!home) return "shadow";
  try {
    return skillsVisibilityModeFromToml(readFileSync(join(home, "config", "skills.toml"), "utf8"));
  } catch {
    return "shadow"; // unreadable file: Python's own OSError fail-safe
  }
}
