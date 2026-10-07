/**
 * One local line per Brain moment, so "is this used?" is answered by data (plan rule 1).
 * `<home>/state/telemetry.jsonl`: local usage, including subagent and recall-hit data. Past 1 MiB
 * it is renamed to `telemetry.1.jsonl` (replacing the previous one): a rename, never a rewrite, so a
 * concurrent session's append lands in one file or the other and is never lost. Only a full file
 * can replace the rotated one; a held rotated file hands the rows back to telemetry.jsonl (the next
 * row retries); only a crash between the two renames, or a failed hand-back, can leave a `*.rot`
 * file, which no reader sees. Never throws.
 */
import { appendFileSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { nowIso, writeAtomic } from "./util.ts";
import { scrub } from "./scrub.ts";
import { idQuery, type Note } from "./notes.ts";

/** Per-note uses across builds; each retained telemetry file is read once. */
export function noteUsage(home: string, days = 30, now = new Date()): Map<string, { recalled: number; opened: number; carded: number; fired: number; last: string }> {
  const since = now.getTime() - days * 86_400_000;
  const usage = new Map<string, { recalled: number; opened: number; carded: number; fired: number; last: string }>();
  for (const file of [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)]) {
    let text: string;
    try { text = readFileSync(file, "utf8"); } catch { continue; }
    for (const line of text.split("\n")) {
      try {
        const row = JSON.parse(line) as { at?: unknown; kind?: unknown; query?: unknown; ids?: unknown; id?: unknown } | null;
        if (!row || typeof row.at !== "string") continue;
        const at = Date.parse(row.at);
        if (!(at >= since && at <= now.getTime())) continue;
        const ids = row.kind === "fix" && typeof row.id === "string" ? [row.id]
          : (row.kind === "recall" || row.kind === "card") && Array.isArray(row.ids) ? row.ids.filter((id): id is string => typeof id === "string") : [];
        const opened = row.kind === "recall" && ids.length === 1 && typeof row.query === "string" && idQuery(row.query).toLowerCase() === ids[0]!.toLowerCase();
        for (const id of new Set(ids)) {
          if (!id || id.startsWith("doc:")) continue;
          const counts = usage.get(id) ?? { recalled: 0, opened: 0, carded: 0, fired: 0, last: "" };
          if (row.kind === "fix") counts.fired++;
          else if (row.kind === "card") counts.carded++;
          else if (opened) counts.opened++;
          else counts.recalled++;
          if (!counts.last || at > Date.parse(counts.last)) counts.last = row.at;
          usage.set(id, counts);
        }
      } catch { /* torn or malformed local telemetry is skipped */ }
    }
  }
  return usage;
}

export type UseKind = "card" | "fix" | "fixout" | "recall" | "note" | "state" | "error";

export interface Use {
  kind: UseKind;
  project: string;
  tokens: number;
  ms: number;
  session?: string;
  via?: "tool" | "cli" | "hook" | "mcp";
  sub?: boolean;
  hits?: number;
  /** Scrubbed at the write boundary; recall answers themselves are never logged. */
  query?: string;
  ids?: string[];
  judged?: boolean;
  dropped?: number;
  outcome?: "helped" | "missed";
  /** The note behind a fix, so stats can say which fixes keep firing. */
  id?: string;
  /** Where a fail-open handler swallowed an error, and the (scrubbed, cut) message. */
  error?: string;
}

/**
 * The code that wrote a row: newest mtime among the Brain's source files, taken when this module
 * loads. OMP and MCP processes keep the build they started with; hooks and CLI calls stamp the
 * build current at each call. A week's rows can mix builds; stats counts the newest by default,
 * and takes a session's role from all its rows in the window.
 */
const BUILD = ((): string => {
  try {
    const dir = dirname(fileURLToPath(import.meta.url));
    const newest = Math.max(...readdirSync(dir).filter((name) => name.endsWith(".ts")).map((name) => statSync(join(dir, name)).mtimeMs));
    return Number.isFinite(newest) ? Math.floor(newest / 1000).toString(36) : "";
  } catch {
    return "";
  }
})();

export function telemetryPath(home: string): string {
  return join(home, "state", "telemetry.jsonl");
}

const MAX_BYTES = 1_048_576;

export function logUse(home: string, use: Use, now: Date = new Date()): void {
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    const path = telemetryPath(home);
    const row = JSON.stringify({ at: nowIso(now), ...use, ...(use.query === undefined ? {} : { query: scrub(use.query).text.slice(0, 200) }), ms: Math.round(use.ms * 10) / 10, ...(BUILD ? { v: BUILD } : {}) }) + "\n";
    rotateTelemetry(home, Buffer.byteLength(row));
    appendFileSync(path, row);
  } catch {
    // telemetry must never affect the caller
  }
}

/**
 * Rotate a full telemetry file. The file is claimed by a rename first, so a session that lost the
 * race to rotate hands back the fresh file it took instead of putting it over the rotated one.
 */
export function rotateTelemetry(home: string, rowBytes: number): void {
  const path = telemetryPath(home);
  try {
    if (statSync(path).size + rowBytes <= MAX_BYTES) return;
    const claim = `${path}.${process.pid}.rot`;
    renameSync(path, claim);
    // Another session rotated between our stat and rename: we took its fresh file, so hand it back.
    // A held rotated file (Windows: antivirus, an open reader) hands the rows back too; the next row
    // retries, so one try each: a file held for good must not stall every row.
    if (statSync(claim).size > MAX_BYTES / 2) {
      try {
        renameSync(claim, join(home, "state", "telemetry.1.jsonl"));
        return;
      } catch {
        // fall through: put the rows back where readers look
      }
    }
    appendFileSync(path, readFileSync(claim));
    unlinkSync(claim);
  } catch {
    // no file yet, or another session rotated it first
  }
}

export interface Stats {
  days: number;
  sessions: number;
  byKind: Record<string, { count: number; tokens: number }>;
  cards: { main: number; sub: number };
  recalls: { calls: number; measured: number; matched: number };
  recallQueries: { logged: number; silent: number };
  fixOutcomes: { id: string; firings: number; helped: number; missed: number }[];
  /** Sessions that called brain_recall, brain_note or brain_state, of all sessions in that role. */
  toolUse: { main: { sessions: number; using: number }; sub: { sessions: number; using: number } };
  toolCalls: Record<"tool" | "cli" | "mcp", number>;
  /** Rows from older builds left out (0 with allBuilds, or when no row carries a build). */
  olderBuildRows: number;
  /** Fixes by the number of distinct sessions they fired in, most first. */
  fixes: { id: string; sessions: number }[];
  /** Errors fail-open handlers swallowed, newest last. */
  errors: { at: string; error: string }[];
}

const TOOL_KINDS = new Set(["recall", "note", "state"]);

/**
 * Distinct sessions of one role (child or not) in which each fix fired lately. Cheap enough for
 * a card: only fix rows are parsed, from at most two 1 MiB files. `host` limits fires to that
 * host's sessions: Claude Code hook rows carry via "hook", OMP rows no via; `brain fix` (via
 * "cli") counts for neither.
 */
export function fixFires(home: string, sub: boolean, days = 7, now: Date = new Date(), host?: "omp" | "claude-code"): Map<string, number> {
  const since = now.getTime() - days * 86_400_000;
  const sessions = new Map<string, Set<string>>();
  for (const file of [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)]) {
    let text = "";
    try {
      text = readFileSync(file, "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) {
      if (!line.includes('"kind":"fix"') || !line.includes('"id":')) continue;
      try {
        const row = JSON.parse(line) as { at?: unknown; id?: unknown; session?: unknown; sub?: unknown; via?: unknown };
        if (typeof row.id !== "string" || typeof row.session !== "string" || (row.sub === true) !== sub) continue;
        if (host && (host === "claude-code" ? row.via !== "hook" : row.via !== undefined)) continue;
        if (typeof row.at !== "string" || !(Date.parse(row.at) >= since)) continue;
        const seen = sessions.get(row.id) ?? new Set<string>();
        seen.add(row.session);
        sessions.set(row.id, seen);
      } catch {
        // a torn line is skipped
      }
    }
  }
  return new Map([...sessions].map(([id, seen]) => [id, seen.size]));
}

/** Usage over the last days; old recall rows without hit counts are unmeasured, not misses. */
export function stats(home: string, days = 7, now: Date = new Date(), opts: { allBuilds?: boolean } = {}): Stats {
  const since = now.getTime() - days * 86_400_000;
  const byKind: Stats["byKind"] = Object.create(null);
  const cards = { main: 0, sub: 0 };
  const recalls = { calls: 0, measured: 0, matched: 0 };
  const recallQueries = { logged: 0, silent: 0 };
  const outcomes = new Map<string, Stats["fixOutcomes"][number]>();
  const toolCalls = { tool: 0, cli: 0, mcp: 0 };
  const sessions = new Set<string>();
  // present: a row in the counted builds; hookOnly: only Claude Code hook rows, which cannot see a
  // child's own Brain use (its CLI and MCP calls carry the parent's session); card: the role a
  // delivered card gave the session.
  const roles = new Map<string, { sub: boolean; known: boolean; using: boolean; present: boolean; hookOnly: boolean; card?: boolean }>();
  let text = "";
  for (const file of [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)]) {
    try {
      text += readFileSync(file, "utf8") + "\n";
    } catch {
      // either file may be missing
    }
  }
  type Row = { at?: unknown; kind?: unknown; tokens?: unknown; session?: unknown; sub?: unknown; hits?: unknown; via?: unknown; id?: unknown; v?: unknown; error?: unknown; query?: unknown; ids?: unknown; outcome?: unknown };
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
  // Stamps are base-36 seconds: the largest is the newest build, whatever order old and new
  // sessions appended their rows in.
  const stamps = rows.map((row) => row.v).filter((v): v is string => typeof v === "string" && /^[0-9a-z]+$/.test(v));
  const newest = opts.allBuilds || !stamps.length ? undefined : stamps.reduce((a, b) => (parseInt(b, 36) > parseInt(a, 36) ? b : a));
  // A session's role comes from all its rows, whatever build wrote them: a Claude Code session's
  // hook card can predate a source change that its later CLI calls already carry.
  for (const row of rows) {
    if (typeof row.session !== "string" || !row.session) continue;
    const role = roles.get(row.session) ?? { sub: false, known: false, using: false, present: false, hookOnly: true };
    if (row.sub === true) role.sub = true;
    // A CLI or hook row names a session but not whether it is a child: role stays unknown until an
    // OMP/MCP row (or a legacy OMP row, which never had `via`) or a delivered card says so. A
    // `brain card` preview (via cli) is not a delivery.
    if (typeof row.sub === "boolean" || (row.kind === "card" && row.via !== "cli") || row.via === undefined) role.known = true;
    if (row.via !== "hook") role.hookOnly = false;
    if (row.kind === "card" && row.via !== "cli") role.card = role.card === true || row.sub === true;
    roles.set(row.session, role);
  }
  // A delivered card names the role: older hook builds logged a child's fixes under the parent's
  // plain session id with sub:true.
  for (const role of roles.values()) if (role.card !== undefined) role.sub = role.card;
  const fired = new Map<string, Set<string>>();
  const errors: Stats["errors"] = [];
  let olderBuildRows = 0;
  for (const row of rows) {
    if (typeof row.kind !== "string") continue;
    if (newest !== undefined && row.v !== newest) {
      olderBuildRows += 1;
      continue;
    }
    if (row.kind === "error" && typeof row.error === "string") errors.push({ at: String(row.at), error: row.error });
    if (typeof row.id === "string" && (row.kind === "fix" || row.kind === "fixout")) {
      const counts = outcomes.get(row.id) ?? { id: row.id, firings: 0, helped: 0, missed: 0 };
      if (row.kind === "fix") counts.firings += 1;
      else if (row.outcome === "helped" || row.outcome === "missed") counts[row.outcome] += 1;
      outcomes.set(row.id, counts);
    }
    if (row.kind === "fix" && typeof row.id === "string") {
      const seen = fired.get(row.id) ?? new Set<string>();
      seen.add(typeof row.session === "string" ? row.session : "");
      fired.set(row.id, seen);
    }
    const slot = (byKind[row.kind] ??= { count: 0, tokens: 0 });
    slot.count += 1;
    slot.tokens += typeof row.tokens === "number" ? row.tokens : 0;
    if (row.kind === "card" && row.via !== "cli") cards[row.sub === true ? "sub" : "main"] += 1;
    if (TOOL_KINDS.has(row.kind) && (row.via === "tool" || row.via === "cli" || row.via === "mcp")) toolCalls[row.via] += 1;
    if (row.kind === "recall") {
      recalls.calls += 1;
      if (typeof row.query === "string" && Array.isArray(row.ids) && row.ids.every(id => typeof id === "string")) {
        recallQueries.logged += 1;
        if (!row.ids.length) recallQueries.silent += 1;
      }
      if (typeof row.hits === "number" && Number.isInteger(row.hits) && row.hits >= 0) {
        recalls.measured += 1;
        if (row.hits > 0) recalls.matched += 1;
      }
    }
    if (typeof row.session === "string" && row.session) {
      sessions.add(row.session);
      const role = roles.get(row.session)!;
      role.present = true;
      if (TOOL_KINDS.has(row.kind)) role.using = true;
    }
  }
  const toolUse = { main: { sessions: 0, using: 0 }, sub: { sessions: 0, using: 0 } };
  for (const role of roles.values()) {
    // A Claude Code child is seen only through hook rows, so its own tool use can never count.
    if (!role.known || !role.present || (role.sub && role.hookOnly)) continue;
    const slot = toolUse[role.sub ? "sub" : "main"];
    slot.sessions += 1;
    if (role.using) slot.using += 1;
  }
  const fixes = [...fired].map(([id, seen]) => ({ id, sessions: seen.size })).sort((a, b) => b.sessions - a.sessions || a.id.localeCompare(b.id));
  const fixOutcomes = [...outcomes.values()].filter(f => f.helped + f.missed > 0).sort((a, b) => b.firings - a.firings || a.id.localeCompare(b.id));
  return { days, sessions: sessions.size, byKind, cards, recalls, recallQueries, fixOutcomes, toolUse, toolCalls, olderBuildRows, fixes, errors };
}

/** One tool the host sends the model on every request, with its schema size. */
export interface ToolSchema {
  name: string;
  /** Host origin class: builtin, extension, mcp, sdk. */
  source: string;
  tokens: number;
}

const TOOL_SCHEMAS = "tool-schemas-omp.json";

/**
 * The newest OMP main session's active tool schemas and system prompt block sizes (agent cost is
 * turns × context: every request re-sends both). Names and sizes only, never descriptions or
 * prompt text. A rename, so readers never see half a file. Never throws.
 */
export function saveToolSchemas(home: string, tools: ToolSchema[], now: Date = new Date(), system: number[] = []): void {
  try {
    writeAtomic(join(home, "state", TOOL_SCHEMAS), JSON.stringify({ at: nowIso(now), tools, system }) + "\n");
  } catch {
    // the snapshot is advisory
  }
}

/** Active tool schemas next to their calls in the event logs: what each request pays for unused tools. */
export function toolSchemaUse(home: string, days = 7, now: Date = new Date()): { at: string; tools: number; tokens: number; unused: ToolSchema[]; system: number[] } | null {
  let snapshot: { at: string; tools: ToolSchema[]; system?: unknown };
  try {
    snapshot = JSON.parse(readFileSync(join(home, "state", TOOL_SCHEMAS), "utf8"));
    if (typeof snapshot.at !== "string" || !Array.isArray(snapshot.tools)) return null;
  } catch {
    return null;
  }
  // Snapshots written before 2026-10-07 carry no system prompt sizes.
  const system = Array.isArray(snapshot.system) ? snapshot.system.filter((n): n is number => typeof n === "number") : [];
  const since = now.getTime() - days * 86_400_000;
  const called = new Set<string>();
  const dir = join(home, "state", "events");
  let names: string[] = [];
  try { names = readdirSync(dir).filter(name => name.endsWith(".jsonl")); } catch { /* no events yet */ }
  for (const name of names) {
    let text: string;
    try {
      if (statSync(join(dir, name)).mtimeMs < since) continue;
      text = readFileSync(join(dir, name), "utf8");
    } catch { continue; }
    for (const line of text.split("\n")) {
      // A cheap pre-filter: event rows are written by appendEvent with these exact keys.
      const tool = /"tool":"([^"]+)"/.exec(line)?.[1], at = /"at":"([^"]+)"/.exec(line)?.[1];
      if (tool && at && Date.parse(at) >= since) called.add(tool);
    }
  }
  const unused = snapshot.tools.filter(tool => !called.has(tool.name)).sort((a, b) => b.tokens - a.tokens);
  return { at: snapshot.at, tools: snapshot.tools.length, tokens: snapshot.tools.reduce((sum, tool) => sum + tool.tokens, 0), unused, system };
}

/** Apply outcome demotion since each note was last edited. */
export function pausedFixes(home: string, notes: Note[]): Set<string> {
  return demotedFixes(home, (id) => {
    const path = notes.find((note) => note.id === id)?.path;
    try { return path ? statSync(path).mtimeMs : undefined; }
    catch { return undefined; }
  });
}

/** Outcome rows (fix id, time, helped?) parsed once per telemetry file version. */
let outcomeCache: { key: string; rows: { id: string; at: number; helped: boolean }[] } | undefined;

/**
 * Fixes that stopped earning their place: helped less than half the time over 4+ judged runs since
 * the note last changed (`changed` gives a note's file mtime; editing the fix starts a new trial).
 * They are no longer fired and are listed for review; the note files are never touched.
 */
export function demotedFixes(home: string, changed: (id: string) => number | undefined): Set<string> {
  const demoted = new Set<string>();
  try {
    const files = [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)];
    const key = files.map((file) => {
      try {
        const s = statSync(file);
        return `${s.size}:${s.mtimeMs}`;
      } catch {
        return "-";
      }
    }).join("|");
    if (outcomeCache?.key !== key) {
      const rows: { id: string; at: number; helped: boolean }[] = [];
      for (const file of files) {
        let text = "";
        try {
          text = readFileSync(file, "utf8");
        } catch {
          continue;
        }
        for (const line of text.split("\n")) {
          if (!line.includes('"fixout"')) continue;
          try {
            const row = JSON.parse(line) as { kind?: unknown; id?: unknown; at?: unknown; outcome?: unknown };
            const at = typeof row.at === "string" ? Date.parse(row.at) : NaN;
            if (row.kind === "fixout" && typeof row.id === "string" && Number.isFinite(at) && (row.outcome === "helped" || row.outcome === "missed")) rows.push({ id: row.id, at, helped: row.outcome === "helped" });
          } catch {
            // a torn line from a concurrent append
          }
        }
      }
      outcomeCache = { key, rows };
    }
    const counts = new Map<string, { helped: number; total: number }>();
    const since = new Map<string, number>();
    for (const row of outcomeCache.rows) {
      if (!since.has(row.id)) since.set(row.id, changed(row.id) ?? 0);
      // Rows are whole seconds: a note written in the same second as an outcome started before it.
      if (row.at + 1000 <= (since.get(row.id) ?? 0)) continue;
      const c = counts.get(row.id) ?? { helped: 0, total: 0 };
      c.total += 1;
      if (row.helped) c.helped += 1;
      counts.set(row.id, c);
    }
    for (const [id, c] of counts) if (c.total >= 4 && c.helped * 2 < c.total) demoted.add(id);
  } catch {
    // demotion is advisory: on any error every fix stays eligible
  }
  return demoted;
}
