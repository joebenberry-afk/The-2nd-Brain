/**
 * Capture: tool-event log, proposals (inbox), and known fixes.
 * Ports from V3 Python: capture.py, views.py, and the OMP event logger.
 */
import {
  appendFileSync,
  closeSync,
  fstatSync,
  openSync,
  readSync,
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
import { cutToTokens, nowIso, writeAtomic } from "./util.ts";

export { scrub };
import {
  GLOBAL,
  type Kind,
  createNote,
  errorPatternProblem,
  displayLine,
  firstLine,
  isActive,
  type Note,
} from "./notes.ts";
import { type Project, normalizePath, projectById, resolveProject, visibleTo } from "./project.ts";

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

/** Scrub with bounded context before retaining the small display head and tail. */
export function scrubCut(text: string, keep: number): string {
  return headAndTail(scrub(headAndTail(text, 32_768), { longRuns: false }).text, keep);
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

/** Split shell argv without treating quoted separators as executed commands. */
function commandSegments(command: string): { argv: string[]; next: string }[] {
  const text = command.trim().replace(/^%%\w+[^\n]*\n/, "").replace(/^!/, "");
  const segments: { argv: string[]; next: string }[] = [];
  let argv: string[] = [];
  let skipUntil = 0;
  for (const match of text.matchAll(/"[^"]*"|'[^']*'|&&|\|\||[;|\n]|[^\s;&|]+/g)) {
    if (match.index < skipUntil) continue;
    const token = match[0];
    if (token === "\n") {
      const heredoc = /<<(-?)\s*(['"]?)(\w+)\2/.exec(argv.join(" "));
      if (heredoc) {
        const start = match.index + 1;
        const end = new RegExp("^" + (heredoc[1] ? "\\t*" : "") + heredoc[3] + "\\r?$", "m").exec(text.slice(start));
        const bodyEnd = end ? start + end.index : text.length;
        argv.push(text.slice(start, bodyEnd));
        skipUntil = end ? bodyEnd + end[0].length : text.length;
      }
    }
    if (/^(?:&&|\|\||[;|\n])$/.test(token)) {
      if (argv.length) segments.push({ argv, next: token });
      argv = [];
    } else {
      argv.push(/^["']/.test(token) ? token.slice(1, -1) : token);
    }
  }
  if (argv.length) segments.push({ argv, next: "" });
  return segments;
}

/** Leading directory/environment setup is not the program being repaired. */
function isSetup(argv: string[]): boolean {
  return /^(cd|pushd|popd|set|export|source|\.)$/i.test(argv[0] ?? "") || /^\$[\w:]+\s*=/.test(argv.join(" "));
}

/** The executable basename, with wrappers removed, plus its complete argv. */
function commandIdentity(command: string | string[]): { program: string; argv: string[] } {
  const segments = typeof command === "string" ? commandSegments(command) : [];
  const parts = typeof command !== "string" ? command : (segments.find((s) => !isSetup(s.argv)) ?? segments.at(-1))?.argv ?? [];
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
    return { program: prog.replace(/\.(exe|cmd|bat|ps1|com)$/, ""), argv: parts.slice(i) };
  }
  return { program: "", argv: [] };
}

export function program(command: string): string {
  return commandIdentity(command).program;
}

const EXPLORATION = new Set(["grep", "rg", "ls", "cat", "find", "head", "tail", "wc", "echo", "which", "where", "type", "pwd", "stat", "file", "tree", "dir", "get-childitem", "select-string"]);

/** Non-flag argv define what ran, including inline scripts and heredoc contents. */
function positionals(argv: string[]): string[] {
  return argv.slice(1).filter((arg, index) =>
    !arg.startsWith("-") || /^(?:--(?:eval|print|command)=|-[epc].)/.test(arg) ||
    /^(?:-e|-p|-c|--eval|--print|--command)$/.test(argv[index] ?? "") || /^<</.test(argv[index] ?? ""));
}

/** Throwaway scripts and scratch paths describe an experiment, not a reusable repair. */
function ephemeralCommand(command: string): boolean {
  if (command.includes("<<")) return true;
  return commandSegments(command).some(({ argv }) => {
    const identity = commandIdentity(argv);
    if (identity.argv.some((arg) => /^--eval(?:=|$)/.test(arg) ||
      (/^python[\d.]*$/.test(identity.program) && /^-c/.test(arg)) ||
      (/^(?:node|bun)$/.test(identity.program) && /^-e/.test(arg)))) return true;
    return identity.argv.slice(1).some((arg) => {
      // Include --basetemp=cache/tmp/... as well as positional script paths.
      const path = arg.replace(/^--?[\w-]+=/, "").replace(/\\/g, "/");
      return /(?:^|\/)(?:tmp|temp|cache|\.cache|%TEMP%)(?:\/|$)/i.test(path);
    });
  });
}

/** A changed command is a candidate only while it still targets the failed operation. */
function keepsCommand(failed: string, fixed: string): boolean {
  const original = commandIdentity(failed);
  const args = positionals(original.argv);
  const segments = commandSegments(fixed);
  if (segments.some((s) => s.next === "||" || s.next === "|")) return false;
  return segments.some((segment, index) => {
    if (segments.slice(index, -1).some((s) => s.next !== "&&")) return false;
    const candidate = commandIdentity(segment.argv);
    const target = positionals(candidate.argv);
    return candidate.program === original.program && args.every((arg, i) => target[i] === arg);
  });
}

/** Full argv matters, including a launcher's tool and target, not just its first argument. */
function retriesCommand(failed: string, fixed: string): boolean {
  const original = commandSegments(failed).filter((s) => !isSetup(s.argv));
  if (original.length !== 1) return false;
  const argv = commandIdentity(original[0]!.argv).argv;
  const segments = commandSegments(fixed);
  if (!argv.length || segments.some((s) => s.next === "||" || s.next === "|")) return false;
  return segments.some((segment, index) => {
    // A later unconditional command could hide this retry's exit status.
    if (segments.slice(index, -1).some((s) => s.next !== "&&")) return false;
    const candidate = commandIdentity(segment.argv).argv;
    return argv.every((arg, i) => candidate[i] === arg) &&
      candidate.slice(argv.length).every((arg) => arg.startsWith("-"));
  });
}

/** Tools that run code cells (python, ipython, a notebook, a JS REPL): their "command" is code, not a shell command. */
const CODE_TOOL = /python|notebook|repl|jupyter|^js$|javascript|eval/i;

/** Error-like diagnostic, not an echoed source line; cut only at a word boundary. */
export function errorSignature(error: string, max = 120): string {
  const lines = error.replace(/\x1b\[[0-9;]*m/g, "").split(/\r?\n/).filter((l) => l.trim());
  const banner = /^(traceback \(most recent call last\):|during handling of the above exception|the above exception was the direct cause|[=_*#~-]{3,}.*[=_*#~-]{3,}$|[=_*#~-]{5,}$)/i;
  const code = /^(?:\d+\s*[|:]\s*)?(?:import\b|from\s+\S+\s+import\b|(?:export\s+)?(?:const|let|var|function|class|interface|type)\b|(?:throw|raise|return)\b|(?:expect|assert)\s*\(|at\s+|Node\.js v\d|[{}^|])/;
  const location = /^(?:(?:file:\/\/\/|(?:[A-Za-z]:)?[\/\\]|[\w.-]+[\/\\]).*:\d+(?::\d+)?|\S+:\d+(?::\d+)?\)?)$/;
  const useful = lines.map((l) => l.trim()).filter((l) => /[\p{L}\p{N}]/u.test(l) && !/^Wall time:/i.test(l) && !banner.test(l) && !code.test(l) && !location.test(l));
  const exception = [...useful].reverse().find((l) => /^(E\s+)?[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b.*:/.test(l));
  const keyword = /error|fail|cannot|not found|denied|refused|invalid|exception|timed? ?out|mismatch|no such|unable/i;
  const diagnostic = /error|cannot|not found|denied|refused|invalid|exception|timed? ?out|mismatch|no such|unable/i;
  const hit = exception?.replace(/^E\s+/, "") ?? useful.find((l) => diagnostic.test(l)) ?? useful.find((l) => keyword.test(l)) ?? useful[0] ?? "";
  return signatureCut(hit.replace(/\s+/g, " "), max);
}

function signatureCut(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  return (/\s/.test(text[max] ?? "") ? cut : cut.replace(/\s+\S*$/, "")).trimEnd();
}

/** A private path in any event field must never become a public proposal. */
function touchesPrivate(event: Pick<ToolEvent, "cwd" | "command" | "path" | "error">): boolean {
  return [event.cwd, event.command, event.path, event.error].some((text) =>
    text !== undefined && /(?:^|[\\/\s"'=:(])notes[\\/][^\\/\s]+[\\/]private(?:[\\/]|$)/i.test(text),
  );
}

/** JSON is not a ToolEvent until every consumed field has the expected type. */
export function parseEvent(line: string): ToolEvent | null {
  try {
    const value = asRecord(JSON.parse(line));
    if (value.v !== 1 || typeof value.ok !== "boolean" ||
        !["at", "session", "cwd", "tool"].every((key) => typeof value[key] === "string") ||
        !["command", "path", "error"].every((key) => value[key] === undefined || typeof value[key] === "string")) return null;
    return value as unknown as ToolEvent;
  } catch {
    return null;
  }
}

/** Read only the unprocessed bytes; an externally truncated log starts over. */
function readEventTail(path: string, cursor: number): { bytes: Buffer; offset: number; mtimeMs: number; size: number } {
  const fd = openSync(path, "r");
  try {
    const { size, mtimeMs } = fstatSync(fd);
    const offset = Number.isSafeInteger(cursor) && cursor >= 0 && cursor <= size ? cursor : 0;
    const bytes = Buffer.allocUnsafe(size - offset);
    let read = 0;
    while (read < bytes.length) {
      const count = readSync(fd, bytes, read, bytes.length - read, offset + read);
      if (!count) break;
      read += count;
    }
    return { bytes: bytes.subarray(0, read), offset, mtimeMs, size };
  } finally {
    closeSync(fd);
  }
}

/**
 * Append one tool event to the session's event log.
 * Scrubs command, error, path and cwd; retains bounded command/error/path text. Never throws.
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
  if (touchesPrivate({ cwd, ...fields })) return;
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
    // Bound expensive error scrubbing, preserving context before the small head/tail cut.
    const command = fields.command ? cutToTokens(scrubCut(fields.command, 1000), 125) : undefined;
    const error = fields.error ? scrubCut(fields.error, 300) : undefined;
    const path = fields.path ? scrub(fields.path, { longRuns: false }).text.slice(0, 300) : undefined;

    const line: ToolEvent = {
      v: 1,
      at: nowIso(now),
      session,
      cwd: scrub(cwd, { longRuns: false }).text,
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

/** Retired notes also prevent re-proposing an accepted learning, within its visible scope. */
interface Seen {
  notes: Note[];
  proposals: Proposal[];
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
  return { notes, proposals: listProposals(home), rejected: readRejected(home) };
}

/** Full first-line identity; display truncation must never cause deduplication. */
function identity(body: string): string {
  return firstLine({ body }).replace(/\s+/g, " ").toLowerCase();
}

/** Record a new proposal unless it repeats a learning applicable to its project. */
function propose(home: string, seen: Seen, proposal: Proposal, out: Proposal[], project: Project | null): boolean {
  if (touchesPrivate({ cwd: "", command: proposal.text })) return false;
  const head = identity(proposal.text);
  const errors = new Set(proposal.errors.map((error) => error.toLowerCase()));
  const matches = (body: string, patterns: string[]) => identity(body) === head || patterns.some((error) => errors.has(error.toLowerCase()));
  if (seen.notes.some((note) => visibleTo(note, project) && matches(note.body, note.errors))) return false;
  if (seen.proposals.some((p) => (p.project === GLOBAL || p.project === proposal.project) && matches(p.text, p.errors))) return false;
  if (seen.rejected.has(rejectKey("h", head)) || proposal.errors.some((e) => seen.rejected.has(rejectKey("e", e)))) return false;
  seen.proposals.push(proposal);
  saveProposal(home, proposal);
  out.push(proposal);
  return true;
}

/**
 * Turn new tool events into proposals: a failure followed within 6 events by a successful changed
 * command of the same program (or an explicit retry after preparation), tool and normalized cwd.
 * The cursor makes each event count once; fully processed logs older than
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
  // Evidence survives a waiting cursor, so a later scan cannot reuse an earlier repair.
  const consumed = new Set([...seen.proposals, ...notes].flatMap((item) => item.evidence)
    .filter((ref) => /^events:.*#\d+-\d+$/.test(ref)).map((ref) => ref.replace(/#\d+-/, "#")));

  for (const fileName of readdirSync(dir).filter((n) => n.endsWith(".jsonl")).sort()) {
    const filePath = join(dir, fileName);
    let log: ReturnType<typeof readEventTail>;
    try {
      log = readEventTail(filePath, cursor[fileName] ?? 0);
    } catch {
      continue;
    }
    const { bytes, offset, mtimeMs, size } = log;
    // Only complete lines: a line still being appended is read next time.
    const end = bytes.lastIndexOf(0x0a) + 1;
    if (end > 0) {
      const events: ToolEvent[] = [];
      const starts: number[] = [];
      let at = 0;
      while (at < end) {
        const next = bytes.indexOf(0x0a, at) + 1;
        const line = bytes.subarray(at, next).toString("utf8").trim();
        const event = parseEvent(line);
        if (event) {
          events.push(event);
          starts.push(offset + at);
        }
        at = next;
      }
      // In a live log (written within the hour), a failure whose next 6 events have not all arrived
      // may still be fixed: the cursor waits on it. A quiet log's session is over: nothing waits.
      const live = now.getTime() - mtimeMs < 3_600_000;
      let waiting: number | undefined;

      for (let i = 0; i < events.length; i++) {
        const failed = events[i];
        if (!failed || failed.ok !== false || !failed.command || !failed.error || touchesPrivate(failed) || ephemeralCommand(failed.command)) continue;
        // Two code cells are not a failed command and its fix, unless they are shell cells.
        if (CODE_TOOL.test(failed.tool) && !/^(%%(bash|sh|cmd|powershell|pwsh)\b|!)/.test(failed.command.trim())) continue;
        const identity = commandIdentity(failed.command);
        const prog = identity.program;
        if (!prog || EXPLORATION.has(prog)) continue;
        let paired = false;
        for (let j = i + 1; j < Math.min(i + 7, events.length); j++) {
          const fixed = events[j];
          if (consumed.has(`events:${fileName}#${starts[j] ?? j}`) || !fixed || fixed.tool !== failed.tool || fixed.ok !== true || !fixed.command || touchesPrivate(fixed)) continue;
          if (normalizePath(fixed.cwd) !== normalizePath(failed.cwd) || ephemeralCommand(fixed.command)) continue;
          if (fixed.command === failed.command || !keepsCommand(failed.command, fixed.command)) continue;
          const retriesFailure = retriesCommand(failed.command, fixed.command);
          const failedCmd = scrub(failed.command).text.replace(/\s+/g, " ").trim();
          const fixedCmd = cutToTokens(scrub(fixed.command).text.replace(/\s+/g, " ").trim(), 125);
          const error = scrub(failed.error).text;
          const short = (s: string) => s.replace(/\s+/g, " ").trim().slice(0, 60);
          // The signature is matched against future raw errors: only credentials are masked in it.
          const sig = errorSignature(scrub(failed.error, { longRuns: false }).text, 60);
          const head = cutToTokens(`${prog}: ${short(failedCmd)} fails (${sig}); ${short(fixedCmd)} works`, 50);
          const evidence = [`events:${fileName}#${starts[i] ?? i}-${starts[j] ?? j}`];
          // Reserve the full retained successful command before filling the 800-character body.
          const text = `${head}\n\n${cutToTokens(failedCmd, 20)}\n\n${fixedCmd}\n\nError: ${error}`.slice(0, 800);
          const project = failed.cwd ? resolveProject(home, failed.cwd, {}) : null;
          propose(home, seen, {
            id: proposalId(evidence, text),
            at: nowIso(now),
            project: project?.id ?? GLOBAL,
            kind: "gotcha",
            text,
            errors: sig && !errorPatternProblem(sig) ? [sig] : [],
            tested: retriesFailure,
            source: "capture",
            evidence,
          }, proposals, project);
          consumed.add(`events:${fileName}#${starts[j] ?? j}`);
          paired = true;
          break;
        }
        if (live && !paired && waiting === undefined && i + 6 >= events.length) waiting = starts[i];
      }
      cursor[fileName] = waiting ?? offset + end;
    }
    try {
      const old = now.getTime() - mtimeMs > EVENT_RETENTION_DAYS * 86_400_000;
      if (old && (cursor[fileName] ?? 0) >= size) {
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
      }, proposals, project === GLOBAL ? null : projectById(home, project, repoRoot));
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
  rejected.add(rejectKey("h", identity(prop.text)));
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

/** One advisory fix, successful captured command first, within the complete 80-token budget. */
export function renderFix(note: Note): string {
  const suffix = ` [${note.id}]`;
  const prefix = "Brain: ";
  const budget = Math.max(0, FIX_BUDGET * 4 - prefix.length - suffix.length);
  // Captured bodies retain headline, failed command, successful command, then error.
  const paragraphs = note.source === "capture" ? note.body.split(/\n\s*\n/) : [];
  const fixed = paragraphs[3]?.startsWith("Error:") ? paragraphs[2]?.replace(/\s+/g, " ").trim() : undefined;
  let text = fixed ? `${fixed} works — ${firstLine(note)}` : firstLine(note);
  if (!fixed) {
    const rest = note.body.split("\n").slice(1).join(" ").replace(/\s+/g, " ").trim();
    const sentence = rest.split(/(?<=[.!?])\s+/)[0]?.replace(/\.$/, "");
    if (sentence && text.length + sentence.length + 2 <= budget) text += /[.!?:]$/.test(text) ? ` ${sentence}` : `: ${sentence}`;
  }
  // displayLine is code-point safe; the token estimator counts UTF-16 units.
  let content = displayLine({ body: text }, budget);
  while (content.length > budget) content = displayLine({ body: text }, Array.from(content).length - 1);
  return prefix + content + suffix;
}


/** Recent failed signatures with no visible tested fix, most frequent first. */
export function unmatchedErrors(home: string, notes: Note[], opts: { days?: number; project?: string } = {}): { signature: string; count: number }[] {
  const dir = eventsDir(home);
  if (!existsSync(dir)) return [];
  const since = Date.now() - (opts.days ?? EVENT_RETENTION_DAYS) * 86_400_000;
  const counts = new Map<string, number>();
  const projects = new Map<string, Project>();
  for (const name of readdirSync(dir).filter((name) => name.endsWith(".jsonl"))) {
    let bytes: Buffer;
    try {
      bytes = readEventTail(join(dir, name), 0).bytes;
    } catch {
      continue;
    }
    for (const line of bytes.subarray(0, bytes.lastIndexOf(0x0a) + 1).toString("utf8").split("\n")) {
      const event = parseEvent(line);
      if (!event || event.ok || !event.error || touchesPrivate(event) || !(Date.parse(event.at) >= since)) continue;
      let project: Project | null = null;
      if (event.cwd) {
        project = projects.get(event.cwd) ?? resolveProject(home, event.cwd, {});
        projects.set(event.cwd, project);
      }
      if (opts.project && opts.project !== (project?.id ?? GLOBAL)) continue;
      if (findFix(notes, event.error, project)) continue;
      const signature = signatureCut(errorSignature(scrub(event.error).text, Infinity)
        .replace(/(?:file:\/\/\/)?(?:[A-Za-z]:)?[\/\\]?(?:[\w.@~[\]-]+[\/\\])+[\w.@~[\]-]+(?:\(\d+(?:,\d+)?\)|:\d+(?::\d+)?)?/g, "<path>")
        .replace(/\b[\w.-]+\.[a-z]+(?:\(\d+(?:,\d+)?\)|:\d+(?::\d+)?)/gi, "<path>")
        .replace(/^\d+:\d+\s+/, "").replace(/\bline\s+\d+\b/gi, "line <n>")
        .replace(/\b0x[\da-f]+\b|\b[\da-f]{8,}\b/gi, "<hex>"), 120);
      if (signature) counts.set(signature, (counts.get(signature) ?? 0) + 1);
    }
  }
  return [...counts].map(([signature, count]) => ({ signature, count }))
    .sort((a, b) => b.count - a.count || a.signature.localeCompare(b.signature));
}
