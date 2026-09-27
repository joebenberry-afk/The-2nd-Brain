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
import { cutToTokens, estimateTokens, nowIso, randomId, writeAtomic } from "./util.ts";
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
 * Safe session key: keep [A-Za-z0-9._-], replace others with "_", cut to 100 chars.
 * Empty or only-non-alphanumeric → "unknown".
 */
export function safeSession(session: string): string {
  const safe = session.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 100);
  return safe && /[A-Za-z0-9]/.test(safe) ? safe : "unknown";
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
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: GitHub tokens, sk-*, xox*, AWS/Google tokens, Bearer, password=value, long hex/base64.
 */
export function scrub(text: string): { text: string; scrubbed: boolean } {
  const original = text;
  let result = text;

  // GitHub tokens
  result = result.replace(/ghp_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/gho_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/github_pat_[A-Za-z0-9_]+/g, "***");

  // OpenAI/Slack tokens
  result = result.replace(/sk-[A-Za-z0-9_\-.]{20,}/g, "***");
  result = result.replace(/xox[baprs]-[A-Za-z0-9_]+/g, "***");

  // AWS and Google tokens
  result = result.replace(/AKIA[0-9A-Z]{16}/g, "***");
  result = result.replace(/AIza[0-9A-Za-z_-]{35}/g, "***");

  // Bearer tokens
  result = result.replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer ***");

  // Password/secret/token patterns (key kept, value masked)
  result = result.replace(
    /(password|passwd|secret|token|api[_-]?key)\s*([=:])\s*([^\s]+)/gi,
    "$1$2 ***"
  );

  // Long base64/hex runs (≥40 chars)
  result = result.replace(/[A-Fa-f0-9]{40,}/g, "***");
  result = result.replace(
    /[A-Za-z0-9+/]{40,}={0,2}/g,
    (match) => (match.includes("=") || match.length >= 40 ? "***" : match)
  );

  return { text: result, scrubbed: result !== original };
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

/**
 * Scan event logs from cursor, pair failures with fixes, create proposals.
 * Rule: pair a failure with first later event within 6 events where:
 * - tool matches, ok is true, command is set
 * - program() is equal and command differs
 * Dedupe case-insensitive against active notes, inbox, and rejected.
 * Prune files older than EVENT_RETENTION_DAYS only when fully processed.
 */
export function scanEvents(
  home: string,
  notes: Note[],
  opts?: { now?: Date }
): Proposal[] {
  const now = opts?.now ?? new Date();
  const nowTime = now.getTime();

  const dir = eventsDir(home);
  if (!existsSync(dir)) return [];

  const cursorFile = join(dir, ".cursor.json");
  let cursor: Record<string, number> = {};
  try {
    cursor = JSON.parse(readFileSync(cursorFile, "utf8"));
  } catch {
    // No cursor yet
  }

  // Collect existing headlines and error sigs for dedup
  const activeHeadlines = new Set<string>();
  const activeErrors = new Set<string>();
  for (const note of notes) {
    if (isActive(note)) {
      activeHeadlines.add(headline(note).toLowerCase());
      for (const err of note.errors) {
        activeErrors.add(err.toLowerCase());
      }
    }
  }

  // Load rejected
  const rejectedFile = join(home, "state", "rejected.json");
  let rejected: { signatures: string[]; texts: string[] } = {
    signatures: [],
    texts: [],
  };
  try {
    rejected = JSON.parse(readFileSync(rejectedFile, "utf8"));
  } catch {
    // No rejected file yet
  }
  const rejectedTexts = new Set(
    rejected.texts.map((t) => t.toLowerCase())
  );
  const rejectedSigs = new Set(
    rejected.signatures.map((s) => s.toLowerCase())
  );

  // Load inbox proposals
  const inboxDir = join(home, "state", "inbox");
  const inboxHeadlines = new Set<string>();
  const inboxErrors = new Set<string>();
  if (existsSync(inboxDir)) {
    for (const name of readdirSync(inboxDir)) {
      if (!name.endsWith(".json")) continue;
      try {
        const prop = JSON.parse(
          readFileSync(join(inboxDir, name), "utf8")
        ) as Proposal;
        inboxHeadlines.add(headline({ body: prop.text }).toLowerCase());
        for (const err of prop.errors) {
          inboxErrors.add(err.toLowerCase());
        }
      } catch {
        // Skip malformed
      }
    }
  }

  const proposals: Proposal[] = [];

  // Process each event file
  const eventFiles = readdirSync(dir)
    .filter((n) => n.endsWith(".jsonl"))
    .sort();

  const filesToPrune: string[] = [];

  for (const fileName of eventFiles) {
    const filePath = join(dir, fileName);
    let fileContent: Buffer;
    try {
      fileContent = readFileSync(filePath);
    } catch {
      continue;
    }

    const offset = cursor[fileName] ?? 0;
    if (offset >= fileContent.length) continue;

    const newContent = fileContent.slice(offset).toString("utf8");
    const lines = newContent.split("\n");
    const events: ToolEvent[] = [];

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const evt = JSON.parse(line) as ToolEvent;
        events.push(evt);
      } catch {
        // Skip malformed
      }
    }

    // Find failure→fix pairs
    let i = 0;
    while (i < events.length) {
      const eventI = events[i];
      if (!eventI) {
        i += 1;
        continue;
      }

      if (eventI.ok === false && eventI.command && eventI.error) {
        const progI = program(eventI.command);
        const toolI = eventI.tool;
        const cmdI = eventI.command;
        const errorI = eventI.error;

        // Look for fix within next 6 events
        let found = false;
        for (let j = i + 1; j < Math.min(i + 7, events.length); j++) {
          const eventJ = events[j];
          if (!eventJ) continue;
          const progJ = program(eventJ.command ?? "");

          if (
            eventJ.tool === toolI &&
            eventJ.ok === true &&
            eventJ.command &&
            progJ === progI &&
            eventJ.command !== cmdI
          ) {
            // Found a pair
            const cmdJ = eventJ.command;

            // Scrub
            const { text: cmdIClean } = scrub(cmdI);
            const { text: cmdJClean } = scrub(cmdJ);
            const { text: errorClean } = scrub(errorI);

            // Build headline
            const cmdIShort = cmdIClean.split(/\s+/).join(" ").slice(0, 60);
            const cmdJShort = cmdJClean.split(/\s+/).join(" ").slice(0, 60);
            const sig = errorSignature(errorClean).slice(0, 60);
            const hl = `${progI}: ${cmdIShort} fails (${sig}); ${cmdJShort} works`;
            const hlCut = cutToTokens(hl, 50);

            // Check for duplicates (case-insensitive)
            const hlLower = hlCut.toLowerCase();
            if (
              activeHeadlines.has(hlLower) ||
              inboxHeadlines.has(hlLower) ||
              rejectedTexts.has(hlLower)
            ) {
              i = j;
              found = true;
              break;
            }

            if (sig && (activeErrors.has(sig.toLowerCase()) ||
              inboxErrors.has(sig.toLowerCase()) ||
              rejectedSigs.has(sig.toLowerCase()))) {
              i = j;
              found = true;
              break;
            }

            // Resolve project
            const projectId = eventI.cwd ? resolveProject(home, eventI.cwd).id : GLOBAL;

            // Build full text
            const text =
              `${hlCut}\n\n${cmdIClean}\n\n${cmdJClean}\n\nError: ${errorClean}`.slice(
                0,
                800
              );

            const proposal: Proposal = {
              id: randomId("p"),
              at: nowIso(),
              project: projectId,
              kind: "gotcha",
              text,
              errors: sig ? [sig] : [],
              tested: true,
              source: "capture",
              evidence: [`events:${fileName}#${i}-${j}`],
            };

            saveProposal(home, proposal);
            proposals.push(proposal);

            // Update dedup sets
            activeHeadlines.add(hlLower);
            if (sig) activeErrors.add(sig.toLowerCase());

            i = j;
            found = true;
            break;
          }
        }

        if (!found) {
          i += 1;
        }
      } else {
        i += 1;
      }
    }

    // Update cursor
    cursor[fileName] = fileContent.length;

    // Mark for pruning if fully processed and old
    if (cursor[fileName] >= fileContent.length) {
      try {
        const stat = statSync(filePath);
        const fileAge = nowTime - stat.mtimeMs;
        const retentionMs = EVENT_RETENTION_DAYS * 24 * 60 * 60 * 1000;
        if (fileAge > retentionMs) {
          filesToPrune.push(fileName);
        }
      } catch {
        // Ignore stat errors
      }
    }
  }

  // Prune old files
  for (const fileName of filesToPrune) {
    try {
      rmSync(join(dir, fileName));
      delete cursor[fileName];
    } catch {
      // Ignore
    }
  }

  // Write cursor
  try {
    mkdirSync(dir, { recursive: true });
    writeFileSync(cursorFile, JSON.stringify(cursor), "utf8");
  } catch {
    // Ignore
  }

  return proposals;
}

/**
 * Scan git commits for Brain-Decision and Brain-Gotcha trailers.
 * Use cursor to read only new commits (exclusive).
 */
export function scanCommits(
  home: string,
  repoRoot: string,
  project: string,
  notes: Note[]
): Proposal[] {
  const dir = eventsDir(home);
  const cursorFile = join(dir, ".git-cursor.json");

  // Load cursor
  let cursor: Record<string, string> = {};
  try {
    cursor = JSON.parse(readFileSync(cursorFile, "utf8"));
  } catch {
    // No cursor yet
  }

  // Run git log
  const args = ["log"];
  const lastSha = cursor[repoRoot];
  if (lastSha) {
    args.push(`${lastSha}..HEAD`);
  } else {
    args.push("-50");
  }
  args.push("--format=%H%x00%B%x1e");

  const result = spawnSync("git", ["-C", repoRoot, ...args], {
    encoding: "utf8",
    timeout: 30000,
  });

  if (result.status !== 0 || !result.stdout) return [];

  // Collect headlines and errors for dedup
  const activeHeadlines = new Set<string>();
  const activeErrors = new Set<string>();
  for (const note of notes) {
    if (isActive(note)) {
      activeHeadlines.add(headline(note).toLowerCase());
      for (const err of note.errors) {
        activeErrors.add(err.toLowerCase());
      }
    }
  }

  // Load rejected
  const rejectedFile = join(home, "state", "rejected.json");
  let rejected: { signatures: string[]; texts: string[] } = {
    signatures: [],
    texts: [],
  };
  try {
    rejected = JSON.parse(readFileSync(rejectedFile, "utf8"));
  } catch {
    // No rejected file yet
  }
  const rejectedTexts = new Set(
    rejected.texts.map((t) => t.toLowerCase())
  );

  // Load inbox proposals
  const inboxDir = join(home, "state", "inbox");
  const inboxHeadlines = new Set<string>();
  if (existsSync(inboxDir)) {
    for (const name of readdirSync(inboxDir)) {
      if (!name.endsWith(".json")) continue;
      try {
        const prop = JSON.parse(
          readFileSync(join(inboxDir, name), "utf8")
        ) as Proposal;
        inboxHeadlines.add(headline({ body: prop.text }).toLowerCase());
      } catch {
        // Skip malformed
      }
    }
  }

  const proposals: Proposal[] = [];

  // Parse commits: split by \x1e (last commit ends with it)
  // Format is %H%x00%B%x1e: sha, null byte, body, record separator
  const commits: Array<{ sha: string; body: string }> = [];
  for (const part of result.stdout.split("\x1e")) {
    if (!part.trim()) continue;
    const nullIndex = part.indexOf("\x00");
    if (nullIndex < 0) continue;
    const sha = part.slice(0, nullIndex).trim();
    const body = part.slice(nullIndex + 1);
    if (sha && sha.match(/^[0-9a-f]{40}$/i)) {
      commits.push({ sha, body });
    }
  }

  // Process in reverse (oldest to newest)
  for (const { sha, body } of commits.reverse()) {
    // Look for trailers (case-insensitive)
    for (const trailerType of ["Brain-Decision", "Brain-Gotcha"]) {
      const pattern = new RegExp(`^${trailerType}:\\s*(.+)$`, "gmiu");
      for (const match of body.matchAll(pattern)) {
        const text = (match[1] ?? "").trim();
        if (!text) continue;

        // Scrub
        const { text: textClean } = scrub(text);
        const textCut = cutToTokens(textClean, 200);

        // Check for duplicates
        const textLower = textCut.toLowerCase();
        if (
          activeHeadlines.has(textLower) ||
          inboxHeadlines.has(textLower) ||
          rejectedTexts.has(textLower)
        ) {
          continue;
        }

        // Determine kind
        const kind: Kind =
          trailerType.toLowerCase() === "brain-decision"
            ? "decision"
            : "gotcha";

        const proposal: Proposal = {
          id: randomId("p"),
          at: nowIso(),
          project,
          kind,
          text: textCut,
          errors: [],
          tested: false,
          source: "commit",
          evidence: [`commit:${sha.slice(0, 12)}`],
        };

        saveProposal(home, proposal);
        proposals.push(proposal);
        activeHeadlines.add(textLower);
      }
    }
  }

  // Update cursor to HEAD
  if (commits.length > 0) {
    const lastCommit = commits[commits.length - 1];
    if (lastCommit) {
      cursor[repoRoot] = lastCommit.sha;
    }
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(cursorFile, JSON.stringify(cursor), "utf8");
    } catch {
      // Ignore
    }
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

  const haystack = errorText.toLowerCase();
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
          if (regex.test(errorText)) {
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
