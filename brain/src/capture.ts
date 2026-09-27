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
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { scrub } from "./scrub.ts";
import { cutToTokens, estimateTokens, nowIso, randomId, writeAtomic } from "./util.ts";

export { scrub };
import {
  GLOBAL,
  type Kind,
  createNote,
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
 * Extract the first real word of a shell command.
 * Skip VAR=value assignments, sudo, env, time; take basename; strip .exe on Windows.
 */
export function program(command: string): string {
  if (!command.trim()) return "";

  const parts = command.split(/\s+/);
  for (const part of parts) {
    // Skip VAR=value
    if (part.includes("=") && !part.startsWith("-")) continue;
    // Skip sudo, env, time
    if (["sudo", "env", "time"].includes(part)) continue;
    // Found the program
    const prog = part.replace(/\\/g, "/").split("/").pop() ?? "";
    return prog.toLowerCase().endsWith(".exe") ? prog.slice(0, -4) : prog;
  }

  return "";
}

/**
 * Extract error signature: first line with error keywords, else first non-empty line.
 * Strip ANSI escapes, collapse whitespace, cut to 120 characters.
 */
export function errorSignature(error: string): string {
  if (!error.trim()) return "";

  // Strip ANSI escapes
  const clean = error.replace(/\x1b\[[0-9;]*m/g, "");

  // Split into lines
  const lines = clean.split("\n");

  // Find first line with error keywords (case-insensitive)
  const keywordPattern =
    /(error|exception|failed|failure|not found|denied|mismatch|no such|cannot|unable)/i;
  for (const line of lines) {
    if (line.trim() && keywordPattern.test(line)) {
      const sig = line.split(/\s+/).join(" ");
      return sig.slice(0, 120);
    }
  }

  // Fall back to first non-empty line
  for (const line of lines) {
    if (line.trim()) {
      const sig = line.split(/\s+/).join(" ");
      return sig.slice(0, 120);
    }
  }

  return "";
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
    const command = fields.command
      ? cutToTokens(scrub(fields.command).text, 125)
      : undefined;
    const error = fields.error
      ? cutToTokens(scrub(fields.error).text, 125)
      : undefined;
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

/** What must not be proposed again: active notes, pending proposals, rejected ones (lower-cased). */
interface Seen {
  headlines: Set<string>;
  errors: Set<string>;
}

function readJson<T>(path: string, fallback: T): T {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function seenBefore(home: string, notes: Note[]): Seen {
  const seen: Seen = { headlines: new Set(), errors: new Set() };
  const add = (headlineText: string, errors: string[]) => {
    seen.headlines.add(headlineText.toLowerCase());
    for (const e of errors) seen.errors.add(e.toLowerCase());
  };
  for (const note of notes) if (isActive(note)) add(headline(note), note.errors);
  for (const p of listProposals(home)) add(headline({ body: p.text }), p.errors);
  const rejected = readJson<{ signatures?: string[]; texts?: string[] }>(join(home, "state", "rejected.json"), {});
  for (const text of rejected.texts ?? []) seen.headlines.add(text.toLowerCase());
  for (const sig of rejected.signatures ?? []) seen.errors.add(sig.toLowerCase());
  return seen;
}

/** Record a new proposal unless it repeats something seen; returns whether it was kept. */
function propose(home: string, seen: Seen, proposal: Proposal, out: Proposal[]): boolean {
  const head = headline({ body: proposal.text }).toLowerCase();
  if (seen.headlines.has(head) || proposal.errors.some((e) => seen.errors.has(e.toLowerCase()))) return false;
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
        const prog = program(failed.command);
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
          propose(home, seen, {
            id: randomId("p"),
            at: nowIso(now),
            project: failed.cwd ? resolveProject(home, failed.cwd).id : GLOBAL,
            kind: "gotcha",
            text: `${head}\n\n${failedCmd}\n\n${fixedCmd}\n\nError: ${error}`.slice(0, 800),
            errors: sig ? [sig] : [],
            tested: true,
            source: "capture",
            evidence: [`events:${fileName}#${i}-${j}`],
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
      const text = cutToTokens(scrub((match[2] ?? "").trim()).text, 200);
      if (!text) continue;
      propose(home, seen, {
        id: randomId("p"),
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

  // Load or create rejected.json
  const rejectedFile = join(home, "state", "rejected.json");
  let rejected: { signatures: string[]; texts: string[] } = {
    signatures: [],
    texts: [],
  };
  try {
    rejected = JSON.parse(readFileSync(rejectedFile, "utf8"));
  } catch {
    // Create new
  }

  // Add headline and errors (lower-cased)
  const hl = headline({ body: prop.text }).toLowerCase();
  if (!rejected.texts.includes(hl)) {
    rejected.texts.push(hl);
  }
  for (const err of prop.errors) {
    const errLower = err.toLowerCase();
    if (!rejected.signatures.includes(errLower)) {
      rejected.signatures.push(errLower);
    }
  }

  // Write rejected.json
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    writeFileSync(rejectedFile, JSON.stringify(rejected), "utf8");
  } catch {
    // Ignore
  }

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

  const scrubbed = scrub(errorText).text;
  const haystack = `${errorText}\n${scrubbed}`.toLowerCase();
  let best: { len: number; id: string; note: Note } | null = null;

  for (const note of notes) {
    if (!isActive(note) || !note.tested || !note.errors.length) continue;
    if (!visibleTo(note, project)) continue;

    for (const pattern of note.errors) {
      let matchLen = 0;

      if (pattern.startsWith("re:")) {
        // Regex pattern
        const regexText = pattern.slice(3).trim();
        try {
          const regex = new RegExp(regexText, "i");
          if (regex.test(errorText) || regex.test(scrubbed)) {
            matchLen = regexText.length;
          }
        } catch {
          // Invalid regex, skip
        }
      } else {
        // Substring match (case-folded)
        const patternLower = pattern.toLowerCase();
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
