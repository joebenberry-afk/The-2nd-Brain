/**
 * Second Brain V3 for OMP: read the Brain's precompiled views, nothing else.
 *
 * The Python core compiles, whenever records change, `views/<project>/brief.md`,
 * `views/<project>/corrections.json` and `views/projects.json`. This module only reads them,
 * in-process: no retrieval, no Python spawn, no per-prompt work. The extension pushes at two
 * moments — the brief on a session's first turn (and again after compaction) and one tested
 * correction when a tool call fails — and adds nothing otherwise. Every failure returns
 * `undefined` (nothing added).
 *
 * Enabled by `SECOND_BRAIN_V3=on`; when enabled the legacy per-prompt pipeline is bypassed.
 */
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

export const V3_ENV = "SECOND_BRAIN_V3";
export const V3_BRIEF_CUSTOM_TYPE = "brain.v3.brief";
const ON_VALUES = new Set(["on", "1", "true", "yes"]);

export function v3Enabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return ON_VALUES.has((env[V3_ENV] ?? "").trim().toLowerCase());
}

interface ViewProject {
  id: string;
  paths?: string[];
}

interface CorrectionEntry {
  id: string;
  errors?: string[];
  text?: string;
}

/** Mirror of `second_brain.kb.projects.normalize_path`. */
export function normalizePath(value: string): string {
  const text = value.trim();
  if (/^[A-Za-z]:[\\/]/.test(text) || text.includes("\\")) {
    return text.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  }
  return text.replace(/\/+$/, "") || "/";
}

function readJson<T>(path: string): T | undefined {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return undefined;
  }
}

/** The view key for a working directory: the longest declared project path, else `_none`. */
export function viewKey(home: string, cwd: string | undefined): string {
  if (!cwd) return "_none";
  const projects = readJson<ViewProject[]>(join(home, "views", "projects.json"));
  if (!Array.isArray(projects)) return "_none";
  const here = normalizePath(resolve(cwd));
  let best: { length: number; id: string } | undefined;
  for (const project of projects) {
    for (const raw of project.paths ?? []) {
      const root = normalizePath(raw);
      const contains = here === root || here.startsWith(`${root}/`);
      if (contains && (best === undefined || root.length > best.length)) {
        best = { length: root.length, id: project.id };
      }
    }
  }
  return best?.id ?? "_none";
}

/** The project brief, or undefined when the project has no current records. */
export function v3Brief(home: string, cwd: string | undefined): string | undefined {
  try {
    const text = readFileSync(join(home, "views", viewKey(home, cwd), "brief.md"), "utf8");
    return text.trim() ? text : undefined;
  } catch {
    return undefined;
  }
}

/** At most one tested correction whose pattern matches the error (longest pattern wins). */
export function v3Correction(
  home: string,
  cwd: string | undefined,
  errorText: string,
): string | undefined {
  if (!errorText.trim()) return undefined;
  const table = readJson<CorrectionEntry[]>(
    join(home, "views", viewKey(home, cwd), "corrections.json"),
  );
  if (!Array.isArray(table)) return undefined;
  const haystack = errorText.toLowerCase();
  let best: { length: number; entry: CorrectionEntry } | undefined;
  for (const entry of table) {
    for (const pattern of entry.errors ?? []) {
      let length = 0;
      if (pattern.startsWith("re:")) {
        try {
          if (new RegExp(pattern.slice(3).trim(), "i").test(errorText)) {
            length = pattern.slice(3).trim().length;
          }
        } catch {
          continue; // invalid pattern: never matches
        }
      } else if (pattern && haystack.includes(pattern.toLowerCase())) {
        length = pattern.length;
      }
      const better =
        best === undefined ||
        length > best.length ||
        (length === best.length && entry.id < best.entry.id);
      if (length > 0 && better) best = { length, entry };
    }
  }
  if (best === undefined || !best.entry.text) return undefined;
  return `Brain correction (advisory): ${best.entry.text} [${best.entry.id}]`;
}

/** The custom message OMP appends for the brief. */
export function v3BriefMessage(brief: string): {
  customType: string;
  content: string;
  display: boolean;
  details: { v3: true; kind: "brief" };
} {
  return { customType: V3_BRIEF_CUSTOM_TYPE, content: brief, display: false, details: { v3: true, kind: "brief" } };
}

/** One telemetry line per push decision; never throws. */
export function v3Telemetry(home: string, event: string, delivered: string | undefined, ms: number): void {
  try {
    const dir = join(home, "telemetry");
    mkdirSync(dir, { recursive: true });
    appendFileSync(
      join(dir, "kb-hooks.jsonl"),
      `${JSON.stringify({
        at: new Date().toISOString(),
        event,
        host: "omp",
        ms: Math.round(ms * 100) / 100,
        tokens: delivered ? Math.ceil(delivered.length / 4) : 0,
      })}\n`,
    );
  } catch {
    // telemetry must never affect the session
  }
}
