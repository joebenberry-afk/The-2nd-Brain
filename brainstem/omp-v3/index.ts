/**
 * Second Brain V3 — standalone OMP extension (installs as `~/.omp/agent/extensions/second-brain-v3/`).
 *
 * Self-contained on purpose: Node built-ins only, no import from the legacy extension, no OMP
 * type package. Every host field is read defensively, so an OMP update that renames or drops
 * one degrades this extension to "adds nothing" instead of breaking the session. The Brain
 * itself never depends on this file: records, search and views work through the `brain` CLI in
 * any shell, with or without a harness.
 *
 * Behaviour (reads the Brain's precompiled views; no retrieval, no process spawn):
 *   - first turn of a session, and the first turn after compaction → the project brief;
 *   - a failed tool call whose error matches a tested correction → that one correction;
 *   - everything else → nothing.
 * Home: SECOND_BRAIN_HOME. Unset or unreadable views → the extension stays silent.
 */
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

export const BRIEF_CUSTOM_TYPE = "brain.v3.brief";

/** The minimal host surface this extension relies on (structural, version-tolerant). */
export interface HostLike {
  on(event: string, handler: (event: unknown, ctx: unknown) => unknown): void;
}

type Json = Record<string, unknown>;

function asObject(value: unknown): Json | undefined {
  return value !== null && typeof value === "object" ? (value as Json) : undefined;
}

/** Mirror of `second_brain.kb.projects.normalize_path`. */
export function normalizePath(value: string): string {
  const text = value.trim();
  if (/^[A-Za-z]:[\\/]/.test(text) || text.includes("\\")) {
    return text.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  }
  return text.replace(/\/+$/, "") || "/";
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return undefined;
  }
}

/** The view key for a working directory: the longest declared project path, else `_none`. */
export function viewKey(home: string, cwd: string | undefined): string {
  if (!cwd) return "_none";
  const projects = readJson(join(home, "views", "projects.json"));
  if (!Array.isArray(projects)) return "_none";
  const here = normalizePath(resolve(cwd));
  let best: { length: number; id: string } | undefined;
  for (const item of projects) {
    const project = asObject(item);
    const id = typeof project?.id === "string" ? project.id : undefined;
    const paths = Array.isArray(project?.paths) ? project.paths : [];
    if (!id) continue;
    for (const raw of paths) {
      if (typeof raw !== "string") continue;
      const root = normalizePath(raw);
      const contains = here === root || here.startsWith(`${root}/`);
      if (contains && (best === undefined || root.length > best.length)) best = { length: root.length, id };
    }
  }
  return best?.id ?? "_none";
}

/** The project brief, or undefined when the project has no current records. */
export function readBrief(home: string, cwd: string | undefined): string | undefined {
  try {
    const text = readFileSync(join(home, "views", viewKey(home, cwd), "brief.md"), "utf8");
    return text.trim() ? text : undefined;
  } catch {
    return undefined;
  }
}

/** At most one tested correction whose pattern matches the error (longest pattern wins). */
export function matchCorrection(home: string, cwd: string | undefined, errorText: string): string | undefined {
  if (!errorText.trim()) return undefined;
  const table = readJson(join(home, "views", viewKey(home, cwd), "corrections.json"));
  if (!Array.isArray(table)) return undefined;
  const haystack = errorText.toLowerCase();
  let best: { length: number; id: string; text: string } | undefined;
  for (const item of table) {
    const entry = asObject(item);
    const id = typeof entry?.id === "string" ? entry.id : undefined;
    const text = typeof entry?.text === "string" ? entry.text : undefined;
    const errors = Array.isArray(entry?.errors) ? entry.errors : [];
    if (!id || !text) continue;
    for (const pattern of errors) {
      if (typeof pattern !== "string" || !pattern) continue;
      let length = 0;
      if (pattern.startsWith("re:")) {
        const source = pattern.slice(3).trim();
        try {
          if (new RegExp(source, "i").test(errorText)) length = source.length;
        } catch {
          continue; // an invalid pattern never matches
        }
      } else if (haystack.includes(pattern.toLowerCase())) {
        length = pattern.length;
      }
      const better = best === undefined || length > best.length || (length === best.length && id < best.id);
      if (length > 0 && better) best = { length, id, text };
    }
  }
  return best ? `Brain correction (advisory): ${best.text} [${best.id}]` : undefined;
}

function telemetry(home: string, event: string, delivered: string | undefined, started: number): void {
  try {
    const dir = join(home, "telemetry");
    mkdirSync(dir, { recursive: true });
    const line = {
      at: new Date().toISOString(),
      event,
      host: "omp",
      ms: Math.round((performance.now() - started) * 100) / 100,
      tokens: delivered ? Math.ceil(delivered.length / 4) : 0,
    };
    appendFileSync(join(dir, "kb-hooks.jsonl"), `${JSON.stringify(line)}\n`);
  } catch {
    // telemetry never affects the session
  }
}

/** A stable per-session key from whatever the host exposes; falls back to one process-wide key. */
function sessionKey(ctx: unknown): string {
  const manager = asObject(asObject(ctx)?.sessionManager);
  for (const name of ["getSessionId", "getSessionFile"]) {
    const fn = manager?.[name];
    if (typeof fn === "function") {
      try {
        const value = (fn as () => unknown).call(manager);
        if (typeof value === "string" && value) return value;
      } catch {
        // try the next accessor
      }
    }
  }
  return "process";
}

function cwdOf(ctx: unknown): string | undefined {
  const cwd = asObject(ctx)?.cwd;
  return typeof cwd === "string" && cwd ? cwd : undefined;
}

function toolErrorText(event: unknown): string | undefined {
  const data = asObject(event);
  if (data?.isError !== true) return undefined;
  const content = Array.isArray(data.content) ? data.content : [];
  return content
    .map((part) => {
      const text = asObject(part)?.text;
      return typeof text === "string" ? text : "";
    })
    .join("\n");
}

export default function secondBrainV3(pi: HostLike, env: NodeJS.ProcessEnv = process.env): void {
  const home = env.SECOND_BRAIN_HOME?.trim();
  if (!home) return; // no Brain configured: register nothing
  const briefed = new Set<string>();

  pi.on("before_agent_start", (_event, ctx) => {
    const started = performance.now();
    try {
      const key = sessionKey(ctx);
      if (briefed.has(key)) return undefined;
      briefed.add(key);
      const brief = readBrief(home, cwdOf(ctx));
      telemetry(home, "brief", brief, started);
      return brief
        ? { message: { customType: BRIEF_CUSTOM_TYPE, content: brief, display: false, details: { v3: true } } }
        : undefined;
    } catch {
      return undefined;
    }
  });

  pi.on("tool_result", (event, ctx) => {
    const started = performance.now();
    try {
      const errorText = toolErrorText(event);
      if (errorText === undefined) return undefined;
      const correction = matchCorrection(home, cwdOf(ctx), errorText);
      telemetry(home, "correction", correction, started);
      if (!correction) return undefined;
      const content = asObject(event)?.content;
      return { content: [...(Array.isArray(content) ? content : []), { type: "text", text: correction }] };
    } catch {
      return undefined;
    }
  });

  pi.on("session_before_compact", (_event, ctx) => {
    try {
      briefed.delete(sessionKey(ctx)); // the next turn gets the brief again
    } catch {
      // never affect compaction
    }
    return undefined;
  });
}
