/**
 * Silent recalls mined for what answered them: what the same session read right after a recall that
 * found nothing. Local, derived from telemetry + tool events, never written back; `brain review`
 * turns recurring cases into a doc registration or a note.
 */
import { readFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { parseEvent, safeSession, type ToolEvent } from "./capture.ts";
import { scrub } from "./scrub.ts";
import { projectDocs } from "./docs.ts";
import { normalizePath, projectById, projectDocPath, type Project } from "./project.ts";
import { fold } from "./search.ts";

const WINDOW_EVENTS = 10;
const WINDOW_MS = 10 * 60_000;
const DAY_MS = 86_400_000;
/** Already in the agent's context; reading them says nothing about a missing note or doc. */
const IN_CONTEXT = /^(?:agents|claude)\.md$/i;
const NOISE = /(?:^|\/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$|(?:^|\/)(?:\.[^/]+|node_modules)(?:\/|$)|(?:^|\/)notes\/[^/]+\/private(?:\/|$)/i;

export interface SilentRecall { at: number; project: string; session: string; query: string }

export interface SilentContext {
  root(project: string): string | null;
  /** Registered plan docs of the project, as normalizePath'd absolute paths. */
  registered(project: string): Set<string>;
  /** Brain-owned folders (notes, state): reading them is not reading project material. */
  exclude: string[];
}

export interface SilentCase {
  project: string;
  /** Repo-relative, forward slashes; absent when the sessions never read a qualifying file. */
  path?: string;
  kind: "doc" | "source" | "none";
  queries: string[];
  /** Silent recalls behind this case (a repeated query counts each time). */
  silent: number;
  sessions: number;
  /** Of those, how many were followed by a saved brain_note within the window. */
  noted: number;
}

const SHELL = /^(?:bash|powershell)$/i;

/** First path read in the window that is project material, not yet registered, not noise. */
function readAnswer(project: string, window: ToolEvent[], ctx: SilentContext): { path: string; kind: "doc" | "source" } | undefined {
  const root = ctx.root(project);
  if (!root) return undefined;
  const registered = ctx.registered(project);
  for (const event of window) {
    if (!event.ok || !/^read$/i.test(event.tool) || !event.path || /^[A-Za-z][A-Za-z0-9+.-]+:\/\//.test(event.path)) continue;
    // OMP reads carry selectors (`file.ts:50-100`, `:raw`); the file is what answered.
    const abs = resolve(event.cwd, event.path.replace(/(?::[-+\d,]+|:raw|:img|:conflicts)+$/, "")), rel = relative(root, abs);
    if (!rel || rel.startsWith("..") || isAbsolute(rel)) continue;
    const path = rel.split(sep).join("/");
    if (IN_CONTEXT.test(path.split("/").pop()!) || NOISE.test(path)) continue;
    if (ctx.exclude.some((dir) => { const r = relative(dir, abs); return !!r && !r.startsWith("..") && !isAbsolute(r); })) continue;
    if (/\.md$/i.test(path)) {
      // A doc that is registered already, or no longer exists, is no registration candidate.
      if (registered.has(normalizePath(abs)) || !projectDocPath(root, path)) continue;
      return { path, kind: "doc" };
    }
    return { path, kind: "source" };
  }
  return undefined;
}

/**
 * For each silent recall: the next ≤10 events of its session within 10 minutes (ending at a later
 * recall) name the file that answered it. Recurring cases: one file answering ≥2 distinct silent
 * queries across ≥2 sessions, or one query silent ≥2 times.
 */
export function mineSilentRecalls(recalls: SilentRecall[], events: Map<string, ToolEvent[]>, ctx: SilentContext): { examined: number; cases: SilentCase[] } {
  interface Hit { recall: SilentRecall; key: string; path?: string; kind: "doc" | "source" | "none"; noted: boolean }
  const hits: Hit[] = [];
  for (const recall of recalls) {
    const log = events.get(recall.session) ?? [];
    const window: ToolEvent[] = [];
    for (const event of log) {
      const at = Date.parse(event.at);
      // Telemetry stamps whole seconds, so same-second events belong to this turn.
      if (!(at >= recall.at)) continue;
      if (at > recall.at + WINDOW_MS || window.length >= WINDOW_EVENTS) break;
      if ((event.tool === "brain_recall" || (SHELL.test(event.tool) && /\bbrain\s+recall\b/.test(event.command ?? ""))) && at >= recall.at + 1000) break;
      window.push(event);
    }
    const answer = readAnswer(recall.project, window, ctx);
    const noted = window.some((e) => e.ok && (e.tool === "brain_note" || (SHELL.test(e.tool) && /\bbrain\s+note\b/.test(e.command ?? ""))));
    hits.push({ recall, key: `${recall.project}\0${fold(recall.query).trim().replace(/\s+/g, " ")}`, path: answer?.path, kind: answer?.kind ?? "none", noted });
  }

  const build = (group: Hit[], path: string | undefined): SilentCase => ({
    project: group[0]!.recall.project,
    path,
    kind: path ? group.find((h) => h.path === path)!.kind : "none",
    queries: [...new Set(group.map((h) => h.recall.query))],
    silent: group.length,
    sessions: new Set(group.map((h) => h.recall.session)).size,
    noted: group.filter((h) => h.noted).length,
  });
  const cases: SilentCase[] = [];
  const claimed = new Set<string>();
  const byPath = new Map<string, Hit[]>();
  for (const hit of hits) if (hit.path) byPath.set(`${hit.recall.project}\0${hit.path}`, [...(byPath.get(`${hit.recall.project}\0${hit.path}`) ?? []), hit]);
  for (const group of byPath.values()) {
    if (new Set(group.map((h) => h.key)).size < 2 || new Set(group.map((h) => h.recall.session)).size < 2) continue;
    cases.push(build(group, group[0]!.path));
    for (const hit of group) claimed.add(hit.key);
  }
  const byQuery = new Map<string, Hit[]>();
  for (const hit of hits) if (!claimed.has(hit.key)) byQuery.set(hit.key, [...(byQuery.get(hit.key) ?? []), hit]);
  for (const group of byQuery.values()) {
    if (group.length < 2) continue;
    const paths = new Map<string, number>();
    for (const hit of group) if (hit.path) paths.set(hit.path, (paths.get(hit.path) ?? 0) + 1);
    const best = [...paths].sort((a, b) => b[1] - a[1])[0]?.[0];
    cases.push(build(group, best));
  }
  cases.sort((a, b) => b.silent - a.silent || b.sessions - a.sessions || (a.path ?? "").localeCompare(b.path ?? ""));
  return { examined: recalls.length, cases };
}

/** Silent recalls of the last `days` days (one project, or all) with their sessions' event logs. */
export function loadSilentRecalls(home: string, opts: { days: number; project?: string; now?: Date }): { recalls: SilentRecall[]; events: Map<string, ToolEvent[]> } {
  const now = (opts.now ?? new Date()).getTime(), since = now - opts.days * DAY_MS;
  const recalls: SilentRecall[] = [];
  for (const name of ["telemetry.1.jsonl", "telemetry.jsonl"]) {
    let text: string;
    try { text = readFileSync(join(home, "state", name), "utf8"); } catch { continue; }
    for (const line of text.split("\n")) {
      try {
        const row = JSON.parse(line) as { at?: unknown; kind?: unknown; project?: unknown; session?: unknown; query?: unknown; hits?: unknown };
        if (row.kind !== "recall" || row.hits !== 0 || typeof row.project !== "string" || typeof row.session !== "string" || !row.session || typeof row.query !== "string" || !row.query.trim() || typeof row.at !== "string") continue;
        if (opts.project !== undefined && row.project !== opts.project) continue;
        const at = Date.parse(row.at);
        if (at >= since && at <= now) recalls.push({ at, project: row.project, session: row.session, query: row.query });
      } catch { /* a torn telemetry row is not a recall */ }
    }
  }
  const events = new Map<string, ToolEvent[]>();
  for (const { session } of recalls) {
    if (events.has(session)) continue;
    let text = "";
    try { text = readFileSync(join(home, "state", "events", `${safeSession(session)}.jsonl`), "utf8"); } catch { /* no tool log for this session */ }
    events.set(session, text.split("\n").flatMap((line) => parseEvent(line) ?? []));
  }
  return { recalls, events };
}

/** The bounded `brain review` block (≤5 lines): recurring silent recalls and what to do. `recurring` counts its cases. */
export function silentRecallLines(home: string, cwd: string, opts: { project?: string; days?: number; now?: Date } = {}): { lines: string[]; recurring: number } {
  const days = opts.days ?? 14;
  const { recalls, events } = loadSilentRecalls(home, { days, project: opts.project, now: opts.now });
  if (!recalls.length) return { lines: [], recurring: 0 };
  const projects = new Map<string, Project>();
  const project = (id: string) => projects.get(id) ?? (projects.set(id, projectById(home, id, cwd)), projects.get(id)!);
  const { examined, cases } = mineSilentRecalls(recalls, events, {
    root: (id) => project(id).root,
    registered: (id) => new Set(projectDocs(home, project(id)).map(normalizePath)),
    exclude: [join(home, "notes"), join(home, "state")],
  });
  if (!cases.length) return { lines: [`Silent recalls (last ${days} days): none recur (${examined} examined)`], recurring: 0 };
  const quoted = (c: SilentCase) => c.queries.slice(0, 2).map((q) => `"${scrub(q.replace(/\s+/g, " ")).text.slice(0, 50)}"`).join(", ") + (c.queries.length > 2 ? `, +${c.queries.length - 2}` : "");
  const lines = cases.slice(0, 4).map((c) => {
    const where = opts.project === undefined ? ` [${c.project}]` : "";
    const saved = c.noted ? `; ${c.noted} then saved a note` : "";
    const head = c.queries.length > 1 ? `${c.silent} silent (${quoted(c)}) in ${c.sessions} sessions` : `${quoted(c)} silent ${c.silent}×`;
    if (c.kind === "doc") return `${head}${where} then read ${c.path}${saved} → brain project docs add ${c.path}`;
    return `${head}${where}${c.path ? ` then read ${c.path}` : ""}${saved} → brain note "<what answered it>"`;
  });
  return { lines: [`Silent recalls (last ${days} days, ${examined} examined):`, ...lines.map((l) => "  " + l)], recurring: cases.length };
}
