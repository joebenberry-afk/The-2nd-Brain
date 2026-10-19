/**
 * Real-session outcome metric for `brain stats`: per owner request (one human prompt in a main
 * session until the next prompt), the model turns spent and the wall time. Read from the session
 * files the hosts already keep (OMP `~/.omp/agent/sessions/<dir>/*.jsonl`, Claude Code
 * `~/.claude/projects/<dir>/*.jsonl`), so history before any change exists as a baseline and
 * nothing new is logged. Subagent transcripts live in subfolders (and are `isSidechain` in Claude
 * Code); they are never scanned. `brain stats` keeps what it parsed per transcript in a derived cache
 * (see collectAsks), so an unchanged history is not read again.
 */
import { closeSync, openSync, readdirSync, readFileSync, readSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { writeAtomic } from "./util.ts";

/** Host-reported usage for one ask. `requests` is how many model requests carried counters, so a partial ask is visible. */
export type AskUsage = { requests: number; input: number; output: number; cacheRead: number; cacheWrite: number; cost?: number };
export type Ask = { at: number; turns: number; wallMs: number; usage?: AskUsage };

/**
 * Where the hosts keep main-session transcripts: OMP's agent folder and Claude Code's config folder.
 * An injected environment without the variable falls back to the process's, as the host would.
 */
export function hostSessionRoots(env: NodeJS.ProcessEnv): { omp: string; claude: string } {
  return {
    omp: join(env.PI_CODING_AGENT_DIR || process.env.PI_CODING_AGENT_DIR || join(homedir(), ".omp", "agent"), "sessions"),
    claude: join(env.CLAUDE_CONFIG_DIR || process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude"), "projects"),
  };
}

export type Format = "omp" | "claude";
export type WeekUsage = { asks: number; input: number; output: number; cacheRead: number; cacheWrite: number; cost?: number; costAsks: number };
export type WeekRow = { week: string; asks: number; turnsMedian: number; turnsP75: number; wallMedianMin: number; usage?: WeekUsage };

export type Entry = {
  type?: string; timestamp?: string; isMeta?: boolean; isSidechain?: boolean; isCompactSummary?: boolean; entrypoint?: string;
  origin?: { kind?: string }; promptSource?: string;
  message?: { role?: string; id?: string; model?: string; attribution?: string; content?: unknown; usage?: Record<string, unknown> };
};

/** Claude Code writes these as user entries, but the owner did not type them. */
const SYNTHETIC = /^\s*<(?:command-name|command-message|local-command|task-notification|system-reminder)/;

export function promptText(content: unknown): string | null {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return null;
  if (content.some((part) => (part as { type?: string } | null)?.type === "tool_result")) return null;
  return content.map((part) => (part as { text?: unknown } | null)?.text).filter((t): t is string => typeof t === "string").join("\n");
}

/** Whether the entry is a prompt the owner submitted; OMP hidden injections are `custom_message`, never `message`. */
export function humanPrompt(e: Entry, format: Format): boolean {
  if (format === "omp") return e.type === "message" && e.message?.role === "user" && (e.message.attribution === undefined || e.message.attribution === "user");
  if (e.type !== "user" || e.message?.role !== "user" || e.isMeta || e.isSidechain || e.isCompactSummary) return false;
  if (e.promptSource === "system" || (e.origin?.kind !== undefined && e.origin.kind !== "human")) return false;
  // Scripted `claude -p` runs (SDK entrypoints) are harness work, not the owner asking.
  if (typeof e.entrypoint === "string" && e.entrypoint.startsWith("sdk")) return false;
  const text = promptText(e.message.content);
  return text !== null && !SYNTHETIC.test(text);
}

/** One model request: OMP stores one entry per request; Claude Code one entry per content block, sharing `message.id`. */
function requestId(e: Entry, format: Format, seq: number): string | null {
  if (format === "omp") return e.type === "message" && e.message?.role === "assistant" ? String(seq) : null;
  if (e.type !== "assistant" || e.isSidechain || e.message?.model === "<synthetic>") return null;
  return e.message?.id ?? String(seq);
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** One request's counters, or null when the host wrote no usage (an aborted request, an old build). */
function requestUsage(e: Entry, format: Format): Omit<AskUsage, "requests"> | null {
  const raw = e.message?.usage;
  if (!raw || typeof raw !== "object") return null;
  const u = raw as Record<string, unknown>;
  if (format === "omp") {
    const cost = u.cost && typeof u.cost === "object" ? (u.cost as Record<string, unknown>).total : undefined;
    return {
      input: finite(u.input) ? u.input : 0,
      output: finite(u.output) ? u.output : 0,
      cacheRead: finite(u.cacheRead) ? u.cacheRead : 0,
      cacheWrite: finite(u.cacheWrite) ? u.cacheWrite : 0,
      ...(finite(cost) ? { cost } : {}),
    };
  }
  return {
    input: finite(u.input_tokens) ? u.input_tokens : 0,
    output: finite(u.output_tokens) ? u.output_tokens : 0,
    cacheRead: finite(u.cache_read_input_tokens) ? u.cache_read_input_tokens : 0,
    cacheWrite: finite(u.cache_creation_input_tokens) ? u.cache_creation_input_tokens : 0,
  };
}

/** An ask stays active while consecutive assistant/tool-result entries are at most this far apart. */
const IDLE_MS = 5 * 60_000;

/** Timestamp of a raw line without parsing it (tool results are large and only their time matters). */
function rawTime(line: string): number {
  const i = line.indexOf("\"timestamp\":\"");
  return i < 0 ? NaN : Date.parse(line.slice(i + 13, i + 13 + 24));
}

/**
 * Asks of one main session file: turns = model requests after a prompt up to the next prompt (or
 * the file's end); wall = last request's timestamp minus the prompt's. The span ends at the first
 * gap > 5 min between consecutive assistant/tool-result entries: later turns are a background
 * wake-up after the owner went idle and count for nothing. Prompts with no request are dropped.
 * Pure: lines in, asks out.
 */
export function parseAsks(lines: Iterable<string>, format: Format): Ask[] {
  const asks: Ask[] = [];
  let open: { at: number; last: number; prev: number; ended: boolean; ids: Set<string>; usage: AskUsage; usageIds: Set<string>; costKnown: boolean } | null = null;
  const close = (): void => {
    if (open && open.ids.size > 0) {
      const { cost, ...counters } = open.usage;
      // A request that wrote no counters makes the total partial, so a partial ask never claims a price.
      const usage = open.usage.requests
        ? { ...counters, ...(open.usage.requests === open.ids.size && open.costKnown && cost !== undefined ? { cost } : {}) }
        : undefined;
      asks.push({ at: open.at, turns: open.ids.size, wallMs: Math.max(0, open.last - open.at), ...(usage ? { usage } : {}) });
    }
    open = null;
  };
  /** Registers an activity entry at `at`; false once the ask has gone idle. */
  const active = (o: NonNullable<typeof open>, at: number): boolean => {
    if (o.ended) return false;
    if (at - o.prev > IDLE_MS) { o.ended = true; return false; }
    o.prev = Math.max(o.prev, at);
    return true;
  };
  let seq = 0;
  for (const line of lines) {
    if (!line) continue;
    // Tool results dominate session files and never decide a span: skip them before parsing.
    const toolResult = format === "omp" ? line.startsWith("{\"type\":\"message\"") && line.slice(0, 400).includes("\"role\":\"toolResult\"") : line.includes("\"type\":\"tool_result\"");
    if (toolResult) {
      if (open) { const t = rawTime(line); if (!Number.isNaN(t)) active(open, t); }
      continue;
    }
    let e: Entry;
    try { e = JSON.parse(line) as Entry; } catch { continue; }
    const at = Date.parse(e.timestamp ?? "");
    if (Number.isNaN(at)) continue;
    if (humanPrompt(e, format)) {
      close();
      open = {
        at, last: at, prev: at, ended: false, ids: new Set(),
        usage: { requests: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, usageIds: new Set(), costKnown: true,
      };
      continue;
    }
    const id = open ? requestId(e, format, seq++) : null;
    if (open && id !== null && active(open, at)) {
      open.ids.add(id);
      open.last = Math.max(open.last, at);
      const used = requestUsage(e, format);
      if (used && !open.usageIds.has(id)) {
        open.usageIds.add(id);
        open.usage.requests += 1;
        open.usage.input += used.input;
        open.usage.output += used.output;
        open.usage.cacheRead += used.cacheRead;
        open.usage.cacheWrite += used.cacheWrite;
        if (used.cost === undefined) open.costKnown = false;
        else open.usage.cost = (open.usage.cost ?? 0) + used.cost;
      }
    }
  }
  close();
  return asks;
}

/** Monday 00:00 UTC of the week holding `ms`, as YYYY-MM-DD. */
function weekStart(ms: number): number {
  const d = new Date(ms);
  const day = (d.getUTCDay() + 6) % 7;
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day);
}

const median = (sorted: number[]): number => sorted.length % 2 ? sorted[(sorted.length - 1) / 2]! : (sorted[sorted.length / 2 - 1]! + sorted[sorted.length / 2]!) / 2;

/** First ms of the oldest of the last `weeks` UTC weeks (the current one included). */
export function windowStart(now: Date, weeks: number): number {
  return weekStart(now.getTime()) - (weeks - 1) * 7 * 86_400_000;
}

/** Oldest week first; weeks with no asks are kept so a gap is visible. */
export function weeklyAsks(asks: Ask[], weeks: number, now: Date): WeekRow[] {
  const first = windowStart(now, weeks);
  const rows: WeekRow[] = [];
  for (let i = 0; i < weeks; i++) {
    const from = first + i * 7 * 86_400_000;
    const inWeek = asks.filter((ask) => ask.at >= from && ask.at < from + 7 * 86_400_000);
    const turns = inWeek.map((ask) => ask.turns).sort((a, b) => a - b);
    const wall = inWeek.map((ask) => ask.wallMs).sort((a, b) => a - b);
    const measured = inWeek.flatMap((ask) => ask.usage ? [ask.usage] : []);
    const priced = measured.filter((usage) => usage.cost !== undefined);
    const usage = measured.length ? {
      asks: measured.length,
      input: measured.reduce((sum, u) => sum + u.input, 0),
      output: measured.reduce((sum, u) => sum + u.output, 0),
      cacheRead: measured.reduce((sum, u) => sum + u.cacheRead, 0),
      cacheWrite: measured.reduce((sum, u) => sum + u.cacheWrite, 0),
      ...(priced.length ? { cost: priced.reduce((sum, u) => sum + u.cost!, 0) } : {}),
      costAsks: priced.length,
    } : undefined;
    rows.push({
      week: new Date(from).toISOString().slice(0, 10), asks: inWeek.length,
      turnsMedian: inWeek.length ? median(turns) : 0, turnsP75: inWeek.length ? turns[Math.ceil(0.75 * turns.length) - 1]! : 0,
      wallMedianMin: inWeek.length ? median(wall) / 60_000 : 0,
      ...(usage ? { usage } : {}),
    });
  }
  return rows;
}

const compact = (tokens: number): string => tokens >= 1_000_000
  ? `${(tokens / 1_000_000).toFixed(1)}M`
  : tokens >= 1_000 ? `${Math.round(tokens / 1_000)}k` : String(tokens);

export function formatWeek(row: WeekRow): string {
  if (!row.asks) return `${row.week} · 0 asks`;
  const base = `${row.week} · ${row.asks} asks · turns median ${+row.turnsMedian.toFixed(1)} (p75 ${row.turnsP75}) · wall median ${row.wallMedianMin.toFixed(1)} min`;
  const u = row.usage;
  if (!u) return base;
  const input = u.input + u.cacheRead + u.cacheWrite;
  const cached = input ? Math.round(100 * u.cacheRead / input) : 0;
  const priced = u.cost === undefined ? "" : ` · $${u.cost >= 0.01 ? u.cost.toFixed(2) : u.cost > 0 ? u.cost.toFixed(4) : "0.00"}` +
    (u.costAsks < u.asks ? ` (${u.costAsks}/${u.asks} priced)` : "");
  return `${base} · ${u.asks < row.asks ? `${u.asks}/${row.asks} measured: ` : ""}${compact(input)} in (${cached}% cached) · ${compact(u.output)} out${priced}`;
}

/** The longest window `brain stats` shows; the cache keeps no summary of an older transcript. */
export const MAX_WEEKS = 12;

/** Bump when parseAsks or sessionCwd change what a transcript yields: older cache files are then ignored. */
const CACHE_VERSION = 2;

/**
 * What one transcript yields, valid while the file's size, mtime and ctime are unchanged. `asks` is
 * null until a scan whose project accepted `cwd` has parsed the file, so other projects' files cost
 * only their header. No transcript text is kept.
 */
type Summary = { format: Format; size: number; mtimeMs: number; ctimeMs: number; cwd: string | null; asks: Ask[] | null };

function isSummary(value: unknown): value is Summary {
  const s = value as Partial<Record<keyof Summary, unknown>> | null;
  if (typeof s !== "object" || s === null) return false;
  if ((s.format !== "omp" && s.format !== "claude") || !finite(s.size) || !finite(s.mtimeMs) || !finite(s.ctimeMs)) return false;
  if (s.cwd !== null && typeof s.cwd !== "string") return false;
  if (s.asks !== null) {
    if (!Array.isArray(s.asks)) return false;
    for (const a of s.asks as (Partial<Ask> | null)[]) {
      if (!a || !finite(a.at) || !finite(a.turns) || !finite(a.wallMs)) return false;
      if (a.usage !== undefined) {
        const u = a.usage as Partial<AskUsage> | null;
        if (!u || !finite(u.requests) || !finite(u.input) || !finite(u.output) || !finite(u.cacheRead) || !finite(u.cacheWrite)
          || (u.cost !== undefined && !finite(u.cost))) return false;
      }
    }
  }
  return true;
}

/** The cached summaries by transcript path; a missing, foreign-version or corrupt file yields none (a rescan). */
function loadCache(file: string): Map<string, Summary> {
  const files = new Map<string, Summary>();
  try {
    const raw = JSON.parse(readFileSync(file, "utf8")) as { v?: unknown; files?: unknown } | null;
    if (!raw || raw.v !== CACHE_VERSION || typeof raw.files !== "object" || raw.files === null) return files;
    for (const [path, summary] of Object.entries(raw.files)) if (isSummary(summary)) files.set(path, summary);
  } catch { /* no usable cache */ }
  return files;
}

/** The session's cwd from the first 64 KB: OMP's session header, or the first Claude Code entry carrying one. */
function sessionCwd(path: string): string | null {
  const fd = openSync(path, "r");
  try {
    const buffer = Buffer.alloc(65_536);
    const match = /"cwd":("(?:[^"\\]|\\.)*")/.exec(buffer.toString("utf8", 0, readSync(fd, buffer, 0, buffer.length, 0)));
    return match ? (JSON.parse(match[1]!) as string) : null;
  } finally {
    closeSync(fd);
  }
}

/**
 * Asks since `since` (ms) from main-session files modified since then, whose cwd `accept`s. Only
 * files directly inside a host's session folders are read: subagent transcripts sit deeper.
 * An unreadable file or folder is skipped; stats must not fail on someone else's files.
 *
 * With `cacheFile`, each transcript is read once per change: its cwd, and its asks once a scan
 * accepts its project, are kept by path with the size/mtime/ctime they were read at (stamped before
 * the read, so an append during it only costs a reparse). `accept` is asked afresh on every call
 * and its answer never stored, so a project registered or renamed since changes the result at once.
 * Summaries of deleted files and of files older than MAX_WEEKS are dropped; the file is rewritten
 * only when something changed, and a failed write costs only the next scan's speed.
 */
export function collectAsks(roots: { omp?: string; claude?: string }, since: number, accept: (cwd: string) => boolean, cacheFile?: string): Ask[] {
  const asks: Ask[] = [];
  const verdicts = new Map<string, boolean>();
  const files = cacheFile ? loadCache(cacheFile) : new Map<string, Summary>();
  const cutoff = windowStart(new Date(), MAX_WEEKS);
  const listed = new Set<string>();
  const seen = new Set<string>();
  let changed = false;
  const keep = (path: string, summary: Summary): void => {
    if (summary.mtimeMs >= cutoff) { files.set(path, summary); changed = true; } else if (files.delete(path)) changed = true;
  };
  for (const [format, root] of [["omp", roots.omp], ["claude", roots.claude]] as const) {
    if (!root) continue;
    let folders: string[];
    try { folders = readdirSync(root); } catch { continue; }
    for (const folder of folders) {
      let names: string[];
      try { names = readdirSync(join(root, folder)); } catch { continue; }
      listed.add(join(root, folder));
      for (const name of names) {
        if (!name.endsWith(".jsonl")) continue;
        const path = join(root, folder, name);
        try {
          const stat = statSync(path);
          seen.add(path);
          if (stat.mtimeMs < since) continue;
          let summary = files.get(path);
          if (!summary || summary.format !== format || summary.size !== stat.size || summary.mtimeMs !== stat.mtimeMs || summary.ctimeMs !== stat.ctimeMs) {
            const cwd = sessionCwd(path);
            summary = { format, size: stat.size, mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs, cwd, asks: cwd === null ? [] : null };
            keep(path, summary);
          }
          if (summary.cwd === null) continue;
          let ok = verdicts.get(summary.cwd);
          if (ok === undefined) verdicts.set(summary.cwd, ok = accept(summary.cwd));
          if (!ok) continue;
          if (summary.asks === null) {
            summary.asks = parseAsks(readFileSync(path, "utf8").split("\n"), format);
            keep(path, summary);
          }
          for (const ask of summary.asks) if (ask.at >= since) asks.push(ask);
        } catch { /* skip */ }
      }
    }
  }
  if (cacheFile) {
    for (const [path, summary] of files) {
      if (summary.mtimeMs < cutoff || (listed.has(dirname(path)) && !seen.has(path))) { files.delete(path); changed = true; }
    }
    if (changed) {
      try { writeAtomic(cacheFile, JSON.stringify({ v: CACHE_VERSION, files: Object.fromEntries(files) })); } catch { /* the cache is derived */ }
    }
  }
  return asks;
}
