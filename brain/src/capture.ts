/**
 * Capture: tool-event log, proposals (inbox), and known fixes.
 * Ports from V3 Python: capture.py, views.py, and the OMP event logger.
 */
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { scrub } from "./scrub.ts";
import { cutToTokens, estimateTokens, nowIso, writeAtomic } from "./util.ts";

export { scrub };
import {
  GLOBAL,
  type Kind,
  createNote,
  errorPatternProblem,
  headline,
  isActive,
  type Note,
} from "./notes.ts";
import { type Project, resolveProject, visibleTo } from "./project.ts";

export const EVENT_CAP_BYTES = 5 * 1024 * 1024;
export const EVENT_RETENTION_DAYS = 14;
export const FIX_BUDGET = 80;

export interface ToolEvent {
  v: 1;
  at: string;
  session: string;
  cwd: string;
  tool: string;
  command?: string;
  path?: string;
  ok: boolean;
  error?: string;
}

export interface Proposal {
  id: string;
  at: string;
  project: string;
  kind: Kind;
  text: string;
  errors: string[];
  tested: boolean;
  source: "capture" | "commit";
  evidence: string[];
}

export class CaptureError extends Error {}

function inboxDir(home: string): string {
  return join(home, "state", "inbox");
}

/** The same captured pair or trailer always gets the same id, so concurrent scans cannot duplicate it. */
function proposalId(evidence: string[], text: string): string {
  return `p-${createHash("sha256").update(`${evidence.join("|")}\n${text}`).digest("hex").slice(0, 10)}`;
}

function saveProposal(home: string, proposal: Proposal): void {
  writeAtomic(join(inboxDir(home), `${proposal.id}.json`), JSON.stringify(proposal, null, 2) + "\n");
}

/**
 * Directory for event logs: join(home, "state", "events").
 */
export function eventsDir(home: string): string {
  return join(home, "state", "events");
}

/**
 * A file-name-safe session key: [A-Za-z0-9._-] kept, others "_". Long keys (session file paths
 * share long prefixes) keep their distinctive tail plus a hash of the whole key, so two sessions
 * never share a log. Empty → "unknown".
 */
export function safeSession(session: string): string {
  const safe = session.replace(/[^A-Za-z0-9._-]/g, "_");
  if (!/[A-Za-z0-9]/.test(safe)) return "unknown";
  if (safe.length <= 100) return safe;
  return `${safe.slice(-60).replace(/^[._-]+/, "")}-${createHash("sha256").update(session).digest("hex").slice(0, 12)}`;
}

/** A long text as its first and last `keep` characters. */
export function headAndTail(text: string, keep: number): string {
  return text.length <= keep * 2 + 5 ? text : `${text.slice(0, keep)}\n…\n${text.slice(-keep)}`;
}

/**
 * headAndTail with credentials masked (long runs kept). Each end is scrubbed with a margin before
 * it is cut, so a secret the cut goes through is masked, not half-kept.
 */
export function scrubCut(text: string, keep: number): string {
  const clean = (part: string) => scrub(part, { longRuns: false }).text;
  if (text.length <= keep * 2 + 5) return clean(text);
  return `${clean(text.slice(0, keep + 400)).slice(0, keep)}\n…\n${clean(text.slice(-(keep + 400))).slice(-keep)}`;
}

/**
 * Extract tool event fields from host payload defensively (all inputs are unknown).
 */
export function toolEventFrom(
  toolName: unknown,
  input: unknown,
  isError: unknown,
  content: unknown
): {
  tool: string;
  command?: string;
  path?: string;
  ok: boolean;
  error?: string;
} {
  // Tool name
  const tool =
    typeof toolName === "string" && toolName.trim()
      ? toolName.slice(0, 100).trim()
      : "unknown";

  // Command: first of input.command, input.cmd, input.code, input.script
  let command: string | undefined;
  if (typeof input === "object" && input !== null) {
    for (const key of ["command", "cmd", "code", "script"]) {
      const val = (input as Record<string, unknown>)[key];
      if (typeof val === "string" && val.trim()) {
        command = val.trim();
        break;
      }
    }
  }

  // Path: first of input.path, input.file_path, input.filePath, input.file
  let path: string | undefined;
  if (typeof input === "object" && input !== null) {
    for (const key of ["path", "file_path", "filePath", "file"]) {
      const val = (input as Record<string, unknown>)[key];
      if (typeof val === "string" && val.trim()) {
        path = val.trim();
        break;
      }
    }
  }

  // Status
  const ok = isError !== true;

  // Error text: blocks array or string
  let error: string | undefined;
  if (!ok) {
    if (Array.isArray(content)) {
      const blocks: string[] = [];
      for (const block of content) {
        if (
          typeof block === "object" &&
          block !== null &&
          (block as Record<string, unknown>).type === "text"
        ) {
          const text = (block as Record<string, unknown>).text;
          if (typeof text === "string") {
            blocks.push(text);
          }
        }
      }
      if (blocks.length > 0) {
        error = blocks.join("\n");
      }
    }
    if (!error && typeof content === "string") {
      error = content;
    }
  }

  return {
    tool,
    command,
    path,
    ok,
    error,
  };
}

/**
 * The program a shell command ran: its first real word, lower-cased, without folders or a Windows
 * extension (.exe .cmd .bat .ps1 .com). Skipped: `cd X &&`-style segments, VAR=value and PowerShell
 * `$env:X = …` assignments, wrappers (sudo, env and its options, time, `cmd /c`), PowerShell's
 * call operator `&`, and a notebook's `%%bash` line or `!` shell escape. Quoted paths are one word.
 */
export function program(command: string): string {
  const text = command.trim().replace(/^%%\w+[^\n]*\n/, "").replace(/^!/, "");
  // The last segment of "cd X && …", "pushd X; …" is what ran.
  const segments = text.split(/&&|\|\||;|\n/).map((s) => s.trim()).filter(Boolean);
  const skip = (s: string) => /^(cd|pushd|popd|set|export|source|\.)(\s|$)/i.test(s) || /^\$[\w:]+\s*=/.test(s);
  const main = segments.find((s) => !skip(s)) ?? segments.at(-1) ?? "";
  const parts = [...main.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i] as string;
    if (!part || part === "&") continue;
    // VAR=value assignments
    if (part.includes("=") && !part.startsWith("-") && !part.includes("/") && !part.includes("\\")) continue;
    // Wrappers, and their own options (env -u NAME, env -i, cmd /c)
    if (["sudo", "env", "time", "nice", "nohup", "exec", "cmd", "cmd.exe"].includes(part.toLowerCase())) {
      while (/^[-/]/.test(parts[i + 1] ?? "")) i += /^-(u|C|S)$/.test(parts[i + 1] as string) ? 2 : 1;
      continue;
    }
    const prog = (part.replace(/\\/g, "/").split("/").pop() ?? "").toLowerCase();
    return prog.replace(/\.(exe|cmd|bat|ps1|com)$/, "");
  }
  return "";
}

/** Tools that run code cells (python, ipython, a notebook, a JS REPL): their "command" is code, not a shell command. */
const CODE_TOOL = /python|notebook|repl|jupyter|^js$|javascript|eval/i;

/**
 * Extract error signature: first line with error keywords, else first non-empty line.
 * Strip ANSI escapes, collapse whitespace, cut to 120 characters.
 */
export function errorSignature(error: string): string {
  const clean = (line: string) => line.trim().split(/\s+/).join(" ").slice(0, 120);
  const lines = error.replace(/\x1b\[[0-9;]*m/g, "").split(/\r?\n/).filter((l) => l.trim());
  // Banners and headers say nothing about which error it was.
  const banner = /^(traceback \(most recent call last\):|during handling of the above exception|the above exception was the direct cause|[=_*#~-]{3,}.*[=_*#~-]{3,}$|[=_*#~-]{5,}$)/i;
  const useful = lines.filter((l) => !banner.test(l.trim()));
  // A Python-style exception line ("ModuleNotFoundError: …") is the error; the last one wins.
  const exception = [...useful].reverse().find((l) => /^\s*(E\s+)?[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b.*:/.test(l));
  if (exception) return clean(exception.replace(/^\s*E\s+/, ""));
  const keyword = /(error|exception|failed|failure|not found|denied|mismatch|no such|cannot|unable)/i;
  const hit = useful.find((l) => keyword.test(l)) ?? useful[0] ?? lines[0];
  return hit ? clean(hit) : "";
}

/**
 * Append one tool event to the session's event log.
 * Scrubs command and error to 500 chars, path to 300. Never throws.
 * Skips silently when file is already ≥ EVENT_CAP_BYTES.
 */
export function appendEvent(
  home: string,
  session: string,
  cwd: string,
  fields: {
    tool: string;
    command?: string;
    path?: string;
    ok: boolean;
    error?: string;
  },
  now?: Date
): void {
  try {
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const safe = safeSession(session);
    const file = join(dir, `${safe}.jsonl`);

    // Check size cap
    try {
      if (statSync(file).size >= EVENT_CAP_BYTES) return;
    } catch {
      // File doesn't exist yet, that's fine
    }

    // Scrub and truncate fields
    // The log is local (state/): credentials are masked, long runs are kept so the signatures
    // derived from it match future raw errors. Proposals made from it get the full scrub.
    // Cut before scrubbing (scrubbing megabytes of output would block the session). An error keeps
    // its head and its tail: compilers report first, Python tracebacks end with the actual error.
    const command = fields.command ? cutToTokens(scrub(fields.command.slice(0, 2000), { longRuns: false }).text, 125) : undefined;
    const error = fields.error ? scrubCut(fields.error, 300) : undefined;
    const path = fields.path ? fields.path.slice(0, 300) : undefined;

    const line: ToolEvent = {
      v: 1,
      at: nowIso(now),
      session,
      cwd,
      tool: fields.tool,
      command,
      path,
      ok: fields.ok,
      error,
    };

    appendFileSync(file, `${JSON.stringify(line)}\n`, "utf8");
  } catch {
    // Never throw
  }
}

/** Rejected proposals: synced with the notes, so a rejection holds on every machine. */
export function rejectedPath(home: string): string {
  return join(home, "rejected.json");
}

/**
 * A rejection is kept as a hash of the lower-cased headline ("h") or error signature ("e"): the
 * file is synced, and what the owner declined (often because it showed a secret) must not be.
 */
function rejectKey(kind: "h" | "e", text: string): string {
  return createHash("sha256").update(`${kind}:${text.toLowerCase()}`).digest("hex").slice(0, 16);
}

/** The rejection hashes in one rejected.json text; plain `texts`/`signatures` of older files are hashed. */
function rejectedKeys(text: string): string[] {
  let data: Record<string, unknown> = {};
  try {
    data = asRecord(JSON.parse(text));
  } catch {
    return [];
  }
  const strings = (key: string) => (Array.isArray(data[key]) ? (data[key] as unknown[]).filter((v): v is string => typeof v === "string") : []);
  return [...strings("hashes"), ...strings("texts").map((t) => rejectKey("h", t)), ...strings("signatures").map((sig) => rejectKey("e", sig))];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function formatRejected(keys: Iterable<string>): string {
  return JSON.stringify({ hashes: [...new Set(keys)].sort() }, null, 2) + "\n";
}

/** Both sides of a sync conflict on rejected.json, merged: every rejection from either machine. */
export function mergeRejected(a: string, b: string): string {
  return formatRejected([...rejectedKeys(a), ...rejectedKeys(b)]);
}

/** Every rejection, including the pre-sync location (state/rejected.json) when present. */
function readRejected(home: string): Set<string> {
  const keys = new Set<string>();
  for (const path of [rejectedPath(home), join(home, "state", "rejected.json")]) {
    let text: string;
    try {
      text = readFileSync(path, "utf8");
    } catch {
      continue;
    }
    for (const key of rejectedKeys(text)) keys.add(key);
  }
  return keys;
}

/** What must not be proposed again: active notes, pending proposals, rejected ones (lower-cased). */
interface Seen {
  headlines: Set<string>;
  errors: Set<string>;
  rejected: Set<string>;
}

function readJson<T>(path: string, fallback: T): T {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function seenBefore(home: string, notes: Note[]): Seen {
  const seen: Seen = { headlines: new Set(), errors: new Set(), rejected: readRejected(home) };
  const add = (headlineText: string, errors: string[]) => {
    seen.headlines.add(headlineText.toLowerCase());
    for (const e of errors) seen.errors.add(e.toLowerCase());
  };
  // Retired notes count too: an accepted-then-retired learning is not proposed again.
  for (const note of notes) add(headline(note), note.errors);
  for (const p of listProposals(home)) add(headline({ body: p.text }), p.errors);
  return seen;
}

/** Record a new proposal unless it repeats something seen; returns whether it was kept. */
function propose(home: string, seen: Seen, proposal: Proposal, out: Proposal[]): boolean {
  const head = headline({ body: proposal.text }).toLowerCase();
  if (seen.headlines.has(head) || proposal.errors.some((e) => seen.errors.has(e.toLowerCase()))) return false;
  if (seen.rejected.has(rejectKey("h", head)) || proposal.errors.some((e) => seen.rejected.has(rejectKey("e", e)))) return false;
  seen.headlines.add(head);
  for (const e of proposal.errors) seen.errors.add(e.toLowerCase());
  saveProposal(home, proposal);
  out.push(proposal);
  return true;
}

/**
 * Turn new tool events into proposals: a failure followed, within 6 events of the same log, by a
 * successful different command of the same program and tool is a failed→fixed pair. The cursor
 * (`state/capture-cursor.json`) makes each event count once; fully processed logs older than
 * EVENT_RETENTION_DAYS are deleted.
 */
export function scanEvents(home: string, notes: Note[], opts?: { now?: Date }): Proposal[] {
  const now = opts?.now ?? new Date();
  const dir = eventsDir(home);
  if (!existsSync(dir)) return [];
  const cursorFile = join(home, "state", "capture-cursor.json");
  const cursor = readJson<Record<string, number>>(cursorFile, {});
  const seen = seenBefore(home, notes);
  const proposals: Proposal[] = [];

  for (const fileName of readdirSync(dir).filter((n) => n.endsWith(".jsonl")).sort()) {
    const filePath = join(dir, fileName);
    let bytes: Buffer;
    try {
      bytes = readFileSync(filePath);
    } catch {
      continue;
    }
    const offset = cursor[fileName] ?? 0;
    // Only complete lines: a line still being appended is read next time.
    const end = bytes.lastIndexOf(0x0a) + 1;
    if (offset < end) {
      const events: ToolEvent[] = [];
      const starts: number[] = [];
      let at = offset;
      while (at < end) {
        const next = bytes.indexOf(0x0a, at) + 1;
        const line = bytes.subarray(at, next).toString("utf8").trim();
        if (line) {
          try {
            events.push(JSON.parse(line) as ToolEvent);
            starts.push(at);
          } catch {
            // a foreign line is skipped
          }
        }
        at = next;
      }
      // In a live log (written within the hour), a failure whose next 6 events have not all arrived
      // may still be fixed: the cursor waits on it. A quiet log's session is over: nothing waits.
      let live = false;
      try {
        live = now.getTime() - statSync(filePath).mtimeMs < 3_600_000;
      } catch {
        // unknown: treat as over
      }
      let waiting: number | undefined;
      for (let i = 0; i < events.length; i++) {
        const failed = events[i];
        if (!failed || failed.ok !== false || !failed.command || !failed.error) continue;
        // Two code cells are not a failed command and its fix, unless they are shell cells.
        if (CODE_TOOL.test(failed.tool) && !/^(%%(bash|sh|cmd|powershell|pwsh)\b|!)/.test(failed.command.trim())) continue;
        const prog = program(failed.command);
        if (!prog) continue;
        let paired = false;
        for (let j = i + 1; j < Math.min(i + 7, events.length); j++) {
          const fixed = events[j];
          if (!fixed || fixed.tool !== failed.tool || fixed.ok !== true || !fixed.command) continue;
          if (program(fixed.command) !== prog || fixed.command === failed.command) continue;
          const failedCmd = scrub(failed.command).text;
          const fixedCmd = scrub(fixed.command).text;
          const error = scrub(failed.error).text;
          const short = (s: string) => s.replace(/\s+/g, " ").trim().slice(0, 60);
          // The signature is matched against future raw errors: only credentials are masked in it.
          const sig = errorSignature(scrub(failed.error, { longRuns: false }).text).slice(0, 60);
          const head = cutToTokens(`${prog}: ${short(failedCmd)} fails (${sig}); ${short(fixedCmd)} works`, 50);
          const evidence = [`events:${fileName}#${starts[i] ?? i}-${starts[j] ?? j}`];
          const text = `${head}\n\n${failedCmd}\n\n${fixedCmd}\n\nError: ${error}`.slice(0, 800);
          propose(home, seen, {
            id: proposalId(evidence, text),
            at: nowIso(now),
            project: failed.cwd ? resolveProject(home, failed.cwd, {}).id : GLOBAL,
            kind: "gotcha",
            text,
            errors: sig ? [sig] : [],
            tested: true,
            source: "capture",
            evidence,
          }, proposals);
          paired = true;
          i = j;
          break;
        }
        if (live && !paired && waiting === undefined && i + 6 >= events.length) waiting = starts[i];
      }
      cursor[fileName] = waiting ?? end;
    }
    try {
      const old = now.getTime() - statSync(filePath).mtimeMs > EVENT_RETENTION_DAYS * 86_400_000;
      if (old && (cursor[fileName] ?? 0) >= bytes.lastIndexOf(0x0a) + 1) {
        rmSync(filePath);
        delete cursor[fileName];
      }
    } catch {
      // pruning is best effort
    }
  }
  writeAtomic(cursorFile, JSON.stringify(cursor));
  return proposals;
}

/**
 * Proposals from `Brain-Decision:` / `Brain-Gotcha:` commit trailers in `repoRoot`, from the
 * last seen commit (`state/git-cursor.json`) or, the first time, the last 50 commits.
 */
export function scanCommits(home: string, repoRoot: string, project: string, notes: Note[]): Proposal[] {
  const cursorFile = join(home, "state", "git-cursor.json");
  const cursor = readJson<Record<string, string>>(cursorFile, {});
  const last = cursor[repoRoot];
  const range = last ? [`${last}..HEAD`] : ["-50"];
  const log = (r: string[]) => spawnSync("git", ["-C", repoRoot, "log", ...r, "--format=%H%x00%B%x1e"], { encoding: "utf8", timeout: 30_000 });
  let result = log(range);
  // A cursor git no longer knows (history rewritten, fresh clone): start over; dedupe keeps it quiet.
  if (result.status !== 0 && last) result = log(["-50"]);
  if (result.status !== 0 || !result.stdout) return [];

  const commits = result.stdout
    .split("\x1e")
    .map((part) => {
      const nul = part.indexOf("\x00");
      return nul < 0 ? null : { sha: part.slice(0, nul).trim(), body: part.slice(nul + 1) };
    })
    .filter((c): c is { sha: string; body: string } => c !== null && /^[0-9a-f]{40}$/i.test(c.sha))
    .reverse(); // oldest first
  const seen = seenBefore(home, notes);
  const proposals: Proposal[] = [];
  for (const { sha, body } of commits) {
    for (const match of body.matchAll(/^Brain-(Decision|Gotcha):\s*(.+)$/gim)) {
      const text = cutToTokens(scrub((match[2] ?? "").trim().slice(0, 2000)).text, 200);
      if (!text) continue;
      propose(home, seen, {
        id: proposalId([`commit:${sha}`], text),
        at: nowIso(),
        project,
        kind: (match[1] ?? "").toLowerCase() === "decision" ? "decision" : "gotcha",
        text,
        errors: [],
        tested: false,
        source: "commit",
        evidence: [`commit:${sha.slice(0, 12)}`],
      }, proposals);
    }
  }
  const newest = commits.at(-1);
  if (newest) {
    cursor[repoRoot] = newest.sha;
    writeAtomic(cursorFile, JSON.stringify(cursor));
  }
  return proposals;
}

/**
 * List all proposals in the inbox, sorted by at, then id.
 */
export function listProposals(home: string): Proposal[] {
  const dir = join(home, "state", "inbox");
  const proposals: Proposal[] = [];

  if (!existsSync(dir)) return proposals;

  for (const name of readdirSync(dir).sort()) {
    if (!name.endsWith(".json")) continue;
    try {
      const prop = JSON.parse(
        readFileSync(join(dir, name), "utf8")
      ) as Proposal;
      proposals.push(prop);
    } catch {
      // Skip malformed
    }
  }

  proposals.sort((a, b) => {
    const cmp = a.at < b.at ? -1 : a.at > b.at ? 1 : 0;
    return cmp !== 0 ? cmp : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  return proposals;
}

/**
 * Accept a proposal: create a note, delete the inbox file, return the note.
 */
export function acceptProposal(home: string, id: string): Note {
  const inboxDir = join(home, "state", "inbox");
  const inboxFile = join(inboxDir, `${id}.json`);

  if (!existsSync(inboxFile)) {
    throw new CaptureError(`no proposal ${id}`);
  }

  let prop: Proposal;
  try {
    prop = JSON.parse(readFileSync(inboxFile, "utf8")) as Proposal;
  } catch (error) {
    throw new CaptureError(
      `cannot read proposal ${id}: ${error instanceof Error ? error.message : String(error)}`
    );
  }

  // Create note
  const note = createNote(home, {
    text: prop.text,
    project: prop.project,
    kind: prop.kind,
    errors: prop.errors,
    evidence: prop.evidence,
    tested: prop.tested,
    source: prop.source,
  });

  // Delete inbox file
  try {
    rmSync(inboxFile);
  } catch {
    // Ignore
  }

  return note;
}

/**
 * Reject a proposal: remember headline and errors in rejected.json, delete inbox file.
 */
export function rejectProposal(home: string, id: string): void {
  const inboxDir = join(home, "state", "inbox");
  const inboxFile = join(inboxDir, `${id}.json`);

  if (!existsSync(inboxFile)) {
    throw new CaptureError(`no proposal ${id}`);
  }

  let prop: Proposal;
  try {
    prop = JSON.parse(readFileSync(inboxFile, "utf8")) as Proposal;
  } catch (error) {
    throw new CaptureError(
      `cannot read proposal ${id}: ${error instanceof Error ? error.message : String(error)}`
    );
  }

  const rejected = readRejected(home);
  rejected.add(rejectKey("h", headline({ body: prop.text })));
  for (const err of prop.errors) rejected.add(rejectKey("e", err));
  writeAtomic(rejectedPath(home), formatRejected(rejected));

  // Delete inbox file
  try {
    rmSync(inboxFile);
  } catch {
    // Ignore
  }
}

/**
 * Count pending proposals, optionally filtered by project.
 */
export function pendingCount(home: string, project?: string): number {
  const dir = join(home, "state", "inbox");
  if (!existsSync(dir)) return 0;

  let count = 0;
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".json")) continue;
    if (project) {
      try {
        const prop = JSON.parse(
          readFileSync(join(dir, name), "utf8")
        ) as Proposal;
        if (prop.project === project || prop.project === GLOBAL) {
          count += 1;
        }
      } catch {
        // Skip malformed
      }
    } else {
      count += 1;
    }
  }

  return count;
}

const regexCache = new Map<string, RegExp | null>();

function safeRegex(pattern: string): RegExp | null {
  let regex = regexCache.get(pattern);
  if (regex === undefined) {
    regex = errorPatternProblem(pattern) ? null : new RegExp(pattern.slice(3).trim(), "i");
    regexCache.set(pattern, regex);
  }
  return regex;
}

/**
 * Find an eligible fix for an error: active, tested, errors.length > 0, visibleTo project.
 * Match by longest pattern (regex: "re:" prefix, case-insensitive; else substring).
 * Ties: smallest id wins.
 */
export function findFix(
  notes: Note[],
  errorText: string,
  project: Project | null
): Note | null {
  if (!errorText.trim()) return null;

  // Patterns may come from scrubbed text (older logs, hand-written notes with ***) or from an
  // error signature (colour codes stripped, whitespace collapsed): match the raw error, its
  // scrubbed form and its normalized form.
  errorText = headAndTail(errorText, 4000); // patterns run on every failed result: bounded input
  const scrubbed = scrub(errorText).text;
  const flat = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, "").replace(/\s+/g, " ");
  const haystack = `${errorText}\n${scrubbed}\n${flat(errorText)}\n${flat(scrubbed)}`.toLowerCase();
  let split: string[] | undefined;
  const lines = () => (split ??= `${errorText}\n${scrubbed}\n${flat(errorText)}`.split("\n").map((l) => l.slice(0, 500)));
  let best: { len: number; id: string; note: Note } | null = null;

  for (const note of notes) {
    if (!isActive(note) || !note.tested || !note.errors.length) continue;
    if (!visibleTo(note, project)) continue;

    for (const pattern of note.errors) {
      let matchLen = 0;

      if (pattern.startsWith("re:")) {
        // A pattern that could backtrack for seconds, or matches anything, is skipped (it may come
        // from a synced or hand-edited note). The rest run line by line on bounded lines.
        const regex = safeRegex(pattern);
        if (regex && lines().some((line) => regex.test(line))) matchLen = pattern.length - 3;
      } else if (!errorPatternProblem(pattern)) {
        // Substring match (case-folded); a pattern too short to be specific never matches
        const patternLower = pattern.trim().replace(/\s+/g, " ").toLowerCase();
        if (haystack.includes(patternLower)) {
          matchLen = pattern.length;
        }
      }

      if (
        matchLen > 0 &&
        (best === null || matchLen > best.len || (matchLen === best.len && note.id < best.id))
      ) {
        best = { len: matchLen, id: note.id, note };
      }
    }
  }

  return best?.note ?? null;
}

/**
 * Render a fix as an advisory message within FIX_BUDGET tokens.
 * Format: "Brain (advisory): <headline>: <first sentence>" if room, else just headline.
 * Total ≤ FIX_BUDGET tokens with id suffix.
 */
export function renderFix(note: Note): string {
  const hl = headline(note);
  const idSuffix = ` [${note.id}]`;
  const prefix = "Brain (advisory): ";

  // Budget: FIX_BUDGET tokens for entire message
  // Used: prefix + idSuffix, remaining for content
  const totalBudgetChars = FIX_BUDGET * 4;
  const usedChars = estimateTokens(prefix) * 4 + estimateTokens(idSuffix) * 4;
  const contentBudgetChars = Math.max(1, totalBudgetChars - usedChars);

  // Try to add first sentence of body
  let text = hl;
  const rest = note.body.split("\n").slice(1).join(" ").replace(/\s+/g, " ").trim();
  if (rest) {
    const parts = rest.split(/(?<=[.!?])\s+/);
    const firstSentence = (parts[0] ?? "").trim().replace(/\.$/, "");
    if (firstSentence) {
      const candidate = `${hl}: ${firstSentence}`;
      if (candidate.length <= contentBudgetChars) {
        text = candidate;
      }
    }
  }

  // Cut to budget if needed
  const cut =
    text.length <= contentBudgetChars
      ? text
      : text.slice(0, Math.max(1, contentBudgetChars - 1)).trimEnd() + "…";

  return `${prefix}${cut}${idSuffix}`;
}
