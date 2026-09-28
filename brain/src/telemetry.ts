/**
 * One local line per Brain moment, so "is this used?" is answered by data (plan rule 1).
 * `<home>/state/telemetry.jsonl`: local usage, including subagent and recall-hit data. Past 1 MiB
 * it is renamed to `telemetry.1.jsonl` (replacing the previous one): a rename, never a rewrite, so a
 * concurrent session's append lands in one file or the other and is never lost. Never throws.
 */
import { appendFileSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { nowIso } from "./util.ts";

export type UseKind = "card" | "resume" | "fix" | "recall" | "note" | "state" | "nudge";

export interface Use {
  kind: UseKind;
  project: string;
  tokens: number;
  ms: number;
  session?: string;
  via?: "tool" | "cli" | "hook" | "mcp";
  sub?: boolean;
  hits?: number;
  /** The note behind a fix, so stats can say which fixes keep firing. */
  id?: string;
}

let build: string | undefined;

/**
 * The code that wrote a row: newest mtime among the Brain's source files. A running session keeps
 * the code it loaded, so a week's rows can mix builds; stats reads the newest by default.
 */
export function buildStamp(): string {
  if (build === undefined) {
    try {
      const dir = dirname(fileURLToPath(import.meta.url));
      const newest = Math.max(...readdirSync(dir).filter((name) => name.endsWith(".ts")).map((name) => statSync(join(dir, name)).mtimeMs));
      build = Number.isFinite(newest) ? Math.floor(newest / 1000).toString(36) : "";
    } catch {
      build = "";
    }
  }
  return build;
}

export function telemetryPath(home: string): string {
  return join(home, "state", "telemetry.jsonl");
}

const MAX_BYTES = 1_048_576;

export function logUse(home: string, use: Use, now: Date = new Date()): void {
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    const path = telemetryPath(home);
    const row = JSON.stringify({ at: nowIso(now), ...use, ms: Math.round(use.ms * 10) / 10, ...(buildStamp() ? { v: buildStamp() } : {}) }) + "\n";
    try {
      if (statSync(path).size + Buffer.byteLength(row) > MAX_BYTES) renameSync(path, join(home, "state", "telemetry.1.jsonl"));
    } catch {
      // no file yet, or another session rotated it first
    }
    appendFileSync(path, row);
  } catch {
    // telemetry must never affect the caller
  }
}

export interface Stats {
  days: number;
  sessions: number;
  byKind: Record<string, { count: number; tokens: number }>;
  cards: { main: number; sub: number };
  recalls: { calls: number; measured: number; matched: number };
  /** Sessions that called brain_recall, brain_note or brain_state, of all sessions in that role. */
  toolUse: { main: { sessions: number; using: number }; sub: { sessions: number; using: number } };
  toolCalls: Record<"tool" | "cli" | "hook" | "mcp", number>;
  /** Rows from older builds left out (0 with allBuilds, or when no row carries a build). */
  olderBuildRows: number;
  /** Fixes by the number of distinct sessions they fired in, most first. */
  fixes: { id: string; sessions: number }[];
}

const TOOL_KINDS = new Set(["recall", "note", "state"]);

/** Usage over the last days; old recall rows without hit counts are unmeasured, not misses. */
export function stats(home: string, days = 7, now: Date = new Date(), opts: { allBuilds?: boolean } = {}): Stats {
  const since = now.getTime() - days * 86_400_000;
  const byKind: Stats["byKind"] = Object.create(null);
  const cards = { main: 0, sub: 0 };
  const recalls = { calls: 0, measured: 0, matched: 0 };
  const toolCalls = { tool: 0, cli: 0, hook: 0, mcp: 0 };
  const sessions = new Set<string>();
  const roles = new Map<string, { sub: boolean; known: boolean; using: boolean }>();
  let text = "";
  for (const file of [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)]) {
    try {
      text += readFileSync(file, "utf8") + "\n";
    } catch {
      // either file may be missing
    }
  }
  type Row = { at?: unknown; kind?: unknown; tokens?: unknown; session?: unknown; sub?: unknown; hits?: unknown; via?: unknown; id?: unknown; v?: unknown };
  const rows: Row[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: Row | null;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (!row || typeof row.at !== "string" || !Number.isFinite(Date.parse(row.at)) || Date.parse(row.at) < since || typeof row.kind !== "string") continue;
    rows.push(row);
  }
  // Rows are appended in time order: the last stamped row names the newest build in the window.
  const newest = opts.allBuilds ? undefined : rows.findLast((row) => typeof row.v === "string")?.v;
  const fired = new Map<string, Set<string>>();
  let olderBuildRows = 0;
  for (const row of rows) {
    if (typeof row.kind !== "string") continue;
    if (newest !== undefined && row.v !== newest) {
      olderBuildRows += 1;
      continue;
    }
    if (row.kind === "fix" && typeof row.id === "string") {
      const seen = fired.get(row.id) ?? new Set<string>();
      seen.add(typeof row.session === "string" ? row.session : "");
      fired.set(row.id, seen);
    }
    const slot = (byKind[row.kind] ??= { count: 0, tokens: 0 });
    slot.count += 1;
    slot.tokens += typeof row.tokens === "number" ? row.tokens : 0;
    if (row.kind === "card") cards[row.sub === true ? "sub" : "main"] += 1;
    if (TOOL_KINDS.has(row.kind) && (row.via === "tool" || row.via === "cli" || row.via === "hook" || row.via === "mcp")) toolCalls[row.via] += 1;
    if (row.kind === "recall") {
      recalls.calls += 1;
      if (typeof row.hits === "number" && Number.isInteger(row.hits) && row.hits >= 0) {
        recalls.measured += 1;
        if (row.hits > 0) recalls.matched += 1;
      }
    }
    if (typeof row.session === "string" && row.session) {
      sessions.add(row.session);
      const role = roles.get(row.session) ?? { sub: false, known: false, using: false };
      if (row.sub === true) role.sub = true;
      // A CLI or hook row names a session but not whether it is a child: role stays unknown
      // until an OMP/MCP row (or a legacy OMP row, which never had `via`) says so.
      if (typeof row.sub === "boolean" || row.kind === "card" || row.via === undefined) role.known = true;
      if (TOOL_KINDS.has(row.kind)) role.using = true;
      roles.set(row.session, role);
    }
  }
  const toolUse = { main: { sessions: 0, using: 0 }, sub: { sessions: 0, using: 0 } };
  for (const role of roles.values()) {
    if (!role.known) continue;
    const slot = toolUse[role.sub ? "sub" : "main"];
    slot.sessions += 1;
    if (role.using) slot.using += 1;
  }
  const fixes = [...fired].map(([id, seen]) => ({ id, sessions: seen.size })).sort((a, b) => b.sessions - a.sessions || a.id.localeCompare(b.id));
  return { days, sessions: sessions.size, byKind, cards, recalls, toolUse, toolCalls, olderBuildRows, fixes };
}
