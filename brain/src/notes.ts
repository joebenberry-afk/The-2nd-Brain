/**
 * Notes: one Markdown file per durable fact, with a small frontmatter.
 *
 *   notes/<project>/<id>.md            visible to that project
 *   notes/<project>/private/<id>.md    same, never synced
 *   notes/global/<id>.md               visible everywhere, or only to projects sharing a tag
 *
 * The body's first line is the headline. Scope comes from the path, never from a field.
 * A note is active until it is retired; retired notes stay on disk as history.
 */
import { existsSync, readdirSync, readFileSync, realpathSync, rmSync, statSync } from "node:fs";
import { isAbsolute, join, resolve, win32 } from "node:path";
import { scrub } from "./scrub.ts";
import { nowIso, randomId, retrying, slug, tagList, writeAtomic } from "./util.ts";

export const GLOBAL = "global";
export const KINDS = ["note", "fact", "decision", "gotcha", "procedure"] as const;
export type Kind = (typeof KINDS)[number];

export interface Note {
  id: string;
  kind: Kind;
  /** Project id from the path, or "global". */
  project: string;
  /** True when stored under a `private/` directory (never synced). */
  private: boolean;
  at: string;
  /** Who wrote it: agent | user | capture | commit | convert. */
  source: string;
  tags: string[];
  /** Error patterns this note fixes; a "re:" prefix means a case-insensitive regex. */
  errors: string[];
  evidence: string[];
  /** Verified to work; only tested notes are pushed when a tool fails. */
  tested: boolean;
  /** The one host whose tools produce this note's errors ("omp" | "claude-code"); unset, every host. */
  host?: string;
  replaces?: string;
  replacedBy?: string;
  /** ISO time the note stopped being current. */
  retired?: string;
  /** Markdown; the first non-empty line is the headline. */
  body: string;
  /** Absolute path of the file ("" before the first save). */
  path: string;
}

export class NoteError extends Error {}

const LIST_KEYS = new Set(["tags", "errors", "evidence"]);
const ORDER = ["id", "kind", "at", "source", "tags", "errors", "evidence", "tested", "host", "replaces", "replaced_by", "retired"];

/** The full first non-empty body line, without leading "#". */
export function firstLine(note: Pick<Note, "body">): string {
  const line = note.body.split("\n").find((l) => l.trim()) ?? "";
  return line.replace(/^#+\s*/, "").trim();
}

/** Everything after the first non-empty line, whitespace collapsed. */
export function restOfBody(note: Pick<Note, "body">): string {
  const lines = note.body.split("\n");
  const first = lines.findIndex((l) => l.trim());
  return first < 0 ? "" : lines.slice(first + 1).join(" ").replace(/\s+/g, " ").trim();
}

/** The first line for display on the card and in lists, at most 160 chars. */
export function headline(note: Pick<Note, "body">): string {
  const text = firstLine(note);
  return text.length > 160 ? text.slice(0, 159) + "…" : text;
}

/** Full first line, bounded by code points; prefer a complete word before the ellipsis. */
export function displayLine(note: Pick<Note, "body">, maxChars: number): string {
  const chars = Array.from(firstLine(note));
  const limit = Math.max(0, Math.floor(maxChars));
  if (chars.length <= limit) return chars.join("");
  if (!limit) return "";
  let text = chars.slice(0, limit - 1).join("");
  if (chars[limit - 1] && !/\s/.test(chars[limit - 1]!)) {
    const boundary = text.search(/\s+\S*$/u);
    if (boundary >= 0) text = text.slice(0, boundary);
  }
  return text.trimEnd() + "…";
}

export function isActive(note: Note): boolean {
  return !note.retired;
}

function parseScalar(raw: string): string {
  const value = raw.trim();
  if (value.startsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(value);
      if (typeof parsed === "string") return parsed;
    } catch {
      // fall through: keep the raw text
    }
  }
  if (value.length >= 2 && value.startsWith("'") && value.endsWith("'")) return value.slice(1, -1).replace(/''/g, "'");
  return value;
}

/** Index just past the quoted span opening at `start`, or -1 when it never closes. */
function quoteEnd(text: string, start: number): number {
  const q = text[start];
  for (let j = start + 1; j < text.length; j++) {
    if (q === '"' && text[j] === "\\") j++;
    else if (text[j] === q) {
      if (q === "'" && text[j + 1] === "'") j++;
      else return j + 1;
    }
  }
  return -1;
}

/**
 * Walk a YAML flow value: a quote opens a quoted span only where an item starts (value start,
 * after `[` or `,`), so apostrophes inside plain items (`can't open`) stay literal. Calls `at`
 * for every unquoted character; `at` returning true stops the walk.
 */
function walkFlow(text: string, at: (c: string, i: number) => boolean): void {
  let itemStart = true;
  for (let i = 0; i < text.length; i++) {
    const c = text[i] as string;
    if (itemStart && (c === '"' || c === "'")) {
      const end = quoteEnd(text, i);
      if (end > 0) {
        i = end - 1;
        itemStart = false;
        continue;
      }
    }
    if (at(c, i)) return;
    if (c === "[" || c === ",") itemStart = true;
    else if (!/\s/.test(c)) itemStart = false;
  }
}

function parseInlineList(raw: string): string[] {
  const inner = raw.trim().slice(1, -1).trim();
  const parts: string[] = [];
  let start = 0;
  walkFlow(inner, (c, i) => {
    if (c === ",") {
      parts.push(parseScalar(inner.slice(start, i)));
      start = i + 1;
    }
    return false;
  });
  parts.push(parseScalar(inner.slice(start)));
  return parts.filter((part) => part !== "");
}

/** Only unquoted whitespace-prefixed hashes start YAML comments, including within lists. */
function stripComment(value: string): string {
  let cut = -1;
  walkFlow(value, (c, i) => {
    if (c === "#" && (i === 0 || /\s/.test(value[i - 1] as string))) cut = i;
    return cut >= 0;
  });
  return cut < 0 ? value : value.slice(0, cut).trimEnd();
}

/**
 * Parse frontmatter into scalars and lists. Unknown keys are kept; malformed lines throw.
 * Also read, as Agent Skills files use them: `# comments`, a `key:` followed by an indented map
 * (kept as an empty value) and `>` / `|` block scalars (folded to one line / kept as lines).
 */
export function parseFrontmatter(text: string): { fields: Map<string, string | string[]>; body: string } {
  const normalized = text.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) throw new NoteError("missing frontmatter");
  const end = normalized.indexOf("\n---", 4);
  if (end < 0) throw new NoteError("unterminated frontmatter");
  const head = normalized.slice(4, end);
  const afterFence = normalized.indexOf("\n", end + 1);
  const body = afterFence < 0 ? "" : normalized.slice(afterFence + 1);
  const fields = new Map<string, string | string[]>();
  let listKey: string | null = null;
  let block: { key: string; folded: boolean; lines: string[] } | null = null;
  const endBlock = () => {
    if (!block) return;
    const lines = block.lines.join("\n").replace(/\n+$/, "").split("\n");
    fields.set(block.key, block.folded ? lines.map((l) => l.trim()).filter(Boolean).join(" ") : lines.join("\n"));
    block = null;
  };
  for (const line of head.split("\n")) {
    if (block && (!line.trim() || /^\s/.test(line))) {
      block.lines.push(line.replace(/^\s+/, ""));
      continue;
    }
    endBlock();
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const item = /^\s+-\s?(.*)$/.exec(line);
    if (item && listKey !== null) {
      (fields.get(listKey) as string[]).push(parseScalar(stripComment(item[1] ?? "")));
      continue;
    }
    // An indented `key: value` under a bare `key:` is a nested map (metadata:, compatibility:).
    if (listKey !== null && /^\s+[A-Za-z_][\w-]*:(\s|$)/.test(line)) continue;
    const pair = /^([A-Za-z_][\w-]*):(?:\s+(.*))?$/.exec(line);
    if (!pair) throw new NoteError(`bad frontmatter line: ${line.slice(0, 80)}`);
    const key = pair[1] as string;
    const value = stripComment((pair[2] ?? "").trim());
    listKey = null;
    if (value === "") {
      fields.set(key, []);
      listKey = key;
    } else if (/^[>|][+-]?$/.test(value)) {
      block = { key, folded: value.startsWith(">"), lines: [] };
    } else if (value.startsWith("[") && value.endsWith("]")) {
      fields.set(key, parseInlineList(value));
    } else {
      fields.set(key, parseScalar(value));
    }
  }
  endBlock();
  return { fields, body: body.replace(/^\n+/, "") };
}

/** A frontmatter value is one line: line breaks of every kind (\r, \u2028 …) and control characters become spaces. */
function oneLine(value: string): string {
  return value.replace(/\s*[\r\n\u2028\u2029\u0085]+\s*/g, " ").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, " ");
}

function scalarOut(value: string): string {
  const plain = /^[A-Za-z0-9_./@+-][^\n]*$/.test(value) && !/(:\s|\s#|:$|^[-?]\s|\s$)/.test(value);
  const reserved = /^(true|false|null|yes|no|~|-?\d+(\.\d+)?)$/i.test(value);
  return plain && !reserved ? value : JSON.stringify(value);
}

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value.filter((v) => v !== "") : value ? [value] : [];
}

function asScalar(value: string | string[] | undefined): string | undefined {
  if (value === undefined) return undefined;
  if (Array.isArray(value)) return value.length ? value.join(", ") : undefined;
  return value || undefined;
}

/** Build a Note from file text. `project` and `isPrivate` come from the file's location. */
export function parseNote(text: string, path: string, project: string, isPrivate: boolean): Note {
  const { fields, body } = parseFrontmatter(text);
  const id = asScalar(fields.get("id"));
  if (!id) throw new NoteError("missing id");
  const kindRaw = asScalar(fields.get("kind")) ?? "note";
  const kind = (KINDS as readonly string[]).includes(kindRaw) ? (kindRaw as Kind) : "note";
  return {
    id,
    kind,
    project,
    private: isPrivate,
    at: asScalar(fields.get("at")) ?? "1970-01-01T00:00:00Z",
    source: asScalar(fields.get("source")) ?? "user",
    tags: tagList(asList(fields.get("tags"))),
    errors: asList(fields.get("errors")),
    evidence: asList(fields.get("evidence")),
    tested: asScalar(fields.get("tested")) === "true",
    // Hand-written: "OMP" still means omp. `brain check` reports a value that is no host.
    host: asScalar(fields.get("host"))?.trim().toLowerCase() || undefined,
    replaces: asScalar(fields.get("replaces")),
    replacedBy: asScalar(fields.get("replaced_by")),
    retired: asScalar(fields.get("retired")),
    body: body.trimEnd(),
    path,
  };
}

/** Serialize a note; the output parses back to the same note. */
export function formatNote(note: Note): string {
  const values: Record<string, string | string[] | undefined> = {
    id: note.id,
    kind: note.kind,
    at: note.at,
    source: note.source,
    tags: note.tags,
    errors: note.errors,
    evidence: note.evidence,
    tested: note.tested ? "true" : undefined,
    host: note.host,
    replaces: note.replaces,
    replaced_by: note.replacedBy,
    retired: note.retired,
  };
  const lines = ["---"];
  for (const key of ORDER) {
    const value = values[key];
    if (LIST_KEYS.has(key)) {
      const items = (value as string[]).map(oneLine).filter((v) => v.trim() !== "");
      if (!items.length) continue;
      lines.push(`${key}:`);
      for (const item of items) lines.push(`  - ${scalarOut(item)}`);
    } else if (typeof value === "string" && value !== "") {
      lines.push(`${key}: ${scalarOut(oneLine(value))}`);
    }
  }
  lines.push("---", "", note.body.trim(), "");
  return lines.join("\n");
}

export function notesRoot(home: string): string {
  return join(home, "notes");
}

export function noteDir(home: string, project: string, isPrivate: boolean): string {
  const dir = join(notesRoot(home), project);
  return isPrivate ? join(dir, "private") : dir;
}

interface CachedNote {
  signature: string;
  note: Note;
  /** When this entry was read, to spot a read in the same timestamp tick as the last change. */
  readAtNs: bigint;
}

/** Longer than the coarsest timestamp tick in use (NTFS updates at ~16 ms). */
const RACY_NS = 100_000_000n;

const NOTE_CACHE = new Map<string, Map<string, CachedNote>>();
/** Evidence files change without any note changing: a result is reused only briefly. */
const EVIDENCE_CACHE = new Map<string, { stale: boolean; at: number }>();
const EVIDENCE_TTL_MS = 10_000;

function readDirNotes(dir: string, project: string, isPrivate: boolean, out: Note[], errors: string[], previous: Map<string, CachedNote> | undefined, current: Map<string, CachedNote>): void {
  let names: string[];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith(".md")).sort();
  } catch {
    return;
  }
  for (const name of names) {
    const path = join(dir, name);
    try {
      // Directory mtimes miss in-place edits. Stat every file, including ctime for editors that
      // preserve mtime; only changed files need reading and parsing.
      const stat = statSync(path, { bigint: true });
      const signature = `${stat.mtimeNs}:${stat.ctimeNs}:${stat.size}:${stat.ino}`;
      let cached = previous?.get(path);
      // Racily clean (git's term): an entry read within one timestamp tick of the file's last
      // change could miss a same-size edit that keeps the stamp. Only such entries are re-read, so
      // a fresh `git pull` costs one extra read per file, not a re-read on every load.
      const changedNs = stat.ctimeNs > stat.mtimeNs ? stat.ctimeNs : stat.mtimeNs;
      if (!cached || cached.signature !== signature || cached.readAtNs - changedNs < RACY_NS) {
        const readAtNs = BigInt(Date.now()) * 1_000_000n;
        const note = parseNote(readFileSync(path, "utf8"), path, project, isPrivate);
        if (`${note.id}.md` !== name) throw new NoteError(`id ${note.id} does not match file name`);
        cached = { signature, note, readAtNs };
      }
      current.set(path, cached);
      // Callers may edit returned notes before saving; those edits must not alter cached truth.
      const note = cached.note;
      out.push({ ...note, tags: [...note.tags], errors: [...note.errors], evidence: [...note.evidence] });
    } catch (error) {
      errors.push(`${path}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

/** Every note under the home, sorted by id; unreadable files are reported, never fatal. */
export function loadNotes(home: string): { notes: Note[]; errors: string[] } {
  home = resolve(home);
  const previous = NOTE_CACHE.get(home);
  const current = new Map<string, CachedNote>();
  const notes: Note[] = [];
  const errors: string[] = [];
  let projects: string[];
  try {
    projects = readdirSync(notesRoot(home), { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith("."))
      .map((d) => d.name)
      .sort();
  } catch {
    NOTE_CACHE.delete(home);
    EVIDENCE_CACHE.clear();
    return { notes, errors };
  }
  for (const project of projects) {
    readDirNotes(noteDir(home, project, false), project, false, notes, errors, previous, current);
    readDirNotes(noteDir(home, project, true), project, true, notes, errors, previous, current);
  }
  if (!previous || previous.size !== current.size || [...current].some(([path, cached]) => previous.get(path) !== cached)) EVIDENCE_CACHE.clear();
  NOTE_CACHE.set(home, current);
  const seen = new Map<string, string>();
  const unique: Note[] = [];
  for (const note of notes) {
    const first = seen.get(note.id);
    if (first !== undefined) {
      errors.push(`${note.path}: duplicate id ${note.id} (also ${first})`);
      continue;
    }
    seen.set(note.id, note.path);
    unique.push(note);
  }
  unique.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { notes: unique, errors };
}

/** A note id as pasted: brackets, quotes and trailing punctuation removed. */
export const idQuery = (query: string) => query.trim().replace(/^[[(<"'`]+|[\])>"'`.,;:?!]+$/g, "");

/** A note by id as pasted: exact first, then ignoring case ("[N-D610AE4031]."). */
export function findNote(notes: Note[], id: string): Note | undefined {
  const q = idQuery(id);
  return notes.find((n) => n.id === q) ?? notes.find((n) => n.id.toLowerCase() === q.toLowerCase());
}

function sameFile(a: string, b: string): boolean {
  try {
    return realpathSync.native(a) === realpathSync.native(b);
  } catch {
    return false;
  }
}

/** Ids and project names become path segments: only plain, single segments are accepted. */
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** Write a note to the file its project/private flags say; removes the old file when it moved. */
export function saveNote(home: string, note: Note): Note {
  if (!SAFE_ID.test(note.id) || note.id.includes("..")) throw new NoteError(`unsafe note id ${JSON.stringify(note.id)}`);
  if (note.project !== slug(note.project)) throw new NoteError(`not a project id: ${JSON.stringify(note.project)} (use ${slug(note.project)})`);
  const path = join(noteDir(home, note.project, note.private), `${note.id}.md`);
  NOTE_CACHE.delete(resolve(home));
  EVIDENCE_CACHE.clear();
  writeAtomic(path, formatNote(note));
  // On a case-insensitive filesystem (Windows, macOS) notes/MyProj and notes/myproj are one
  // folder: the "old" file is the one just written, so it must not be removed.
  // A held old file would leave the note in two folders (a duplicate id): the new copy is rolled back.
  if (note.path && note.path !== path && existsSync(note.path) && !sameFile(note.path, path)) {
    try {
      retrying(() => rmSync(note.path, { force: true })); // force: an old file already gone is fine
    } catch {
      rmSync(path, { force: true });
      throw new NoteError(`${note.path} is held open by another program; ${note.id} was not moved — close it and try again`);
    }
  }
  return { ...note, path };
}

export interface NewNote {
  text: string;
  project: string;
  kind?: Kind;
  tags?: string[];
  errors?: string[];
  evidence?: string[];
  tested?: boolean;
  source?: string;
  private?: boolean;
  replaces?: string;
}

/** A host's exit-status wrapper says that a command failed, never why. */
export const EXIT_WRAPPER = /^(?:command|process)? ?exited with (?:code|status) -?\d+\.?$|^exit (?:code|status):? -?\d+$/i;

/**
 * Why an error pattern cannot be used, or null. A known fix is appended to every failure it
 * matches, in every project that sees it, so a pattern must be specific: a literal of at least 5
 * characters that names more than an exit status, an exception class or a catch-all word
 * ("Error:", "Traceback", "fatal:", "npm ERR!") or banner, or a `re:` regex that
 * compiles, does not match trivial text, and cannot backtrack for seconds: no quantified group
 * holding a quantifier or an alternation (`(\w+\s?)+`), at most two open-ended repeats, and at
 * most one of `.`, `\s`, `\w`…
 */
export function errorPatternProblem(pattern: string): string | null {
  if (!pattern.startsWith("re:")) {
    const t = pattern.trim();
    if (t.length < 5) return `error pattern too short to be specific: ${JSON.stringify(pattern)}`;
    // "Exit code 1" also matches exit 101 and 127, and every host prints one on each failure.
    if (EXIT_WRAPPER.test(t) || /^\(no output\)$/i.test(t) || /^(?:error\s+)?(?:command failed with|returned non-zero|process completed with) exit (?:code|status):? -?\d+\.?$/i.test(t)) return `error pattern names only an exit status, not the error: ${JSON.stringify(pattern)}`;
    // A bare "AssertionError" (or "Error:") ends every failed assertion: it names no particular error.
    if (/^(?:E\s+)?(?:[A-Za-z_][\w.]*)?(?:Error|Exception|Warning)\s*:?$/.test(t)) return `error pattern names only an exception class, not the error: ${JSON.stringify(pattern)}`;
    // Catch-all words, npm's prefix (npm 11: "npm error"), Python's banners and separator rules: the
    // whole pattern, so a pasted traceback that goes on to the error stays specific.
    if (/^(?:error|exception|warning|failed|failure|fatal|npm (?:err!?|error|warn)(?: code \d+)?|traceback(?: \(most recent call last\))?|during handling of the above exception, another exception occurred|the above exception was the direct cause of the following exception)\s*[:!]?$/i.test(t) ||
      /^[=_*#~-]{3,}(?:.*[=_*#~-]{3,})?$/.test(t)) return `error pattern names no particular error: ${JSON.stringify(pattern)}`;
    return null;
  }
  const source = pattern.slice(3).trim();
  let regex: RegExp;
  try {
    regex = new RegExp(source, "i");
  } catch (error) {
    return `invalid error pattern ${JSON.stringify(pattern)}: ${error instanceof Error ? error.message : String(error)}`;
  }
  const scan = repeats(source);
  if (scan.nested) return `error pattern can backtrack for minutes (a repeated group that repeats inside): ${JSON.stringify(pattern)}`;
  if (scan.open > 2 || scan.broad > 1) return `error pattern can backtrack for seconds (open-ended repeats in a row): ${JSON.stringify(pattern)}`;
  if (["", " ", "x", "0", "a b", "error"].some((probe) => regex.test(probe))) return `error pattern matches almost anything: ${JSON.stringify(pattern)}`;
  return null;
}

const BROAD = new Set([".", "\\s", "\\S", "\\w", "[^"]);

/**
 * Repeats outside character classes: `nested`, a group followed by *, + or {n,} / {n,m>1} that
 * itself holds a quantifier or an alternation; `open`, the open-ended *, + and {n,}; `broad`, those
 * of them repeating `.`, `\s`, `\S`, `\w` or a negated class.
 */
function repeats(source: string): { nested: boolean; open: number; broad: number } {
  const groups: boolean[] = []; // per open group: does it hold a quantifier or "|"?
  let inClass = false;
  let atom = ""; // what a quantifier here repeats
  let open = 0;
  let broad = 0;
  for (let i = 0; i < source.length; i++) {
    const c = source[i] as string;
    if (c === "\\") {
      if (!inClass) atom = source.slice(i, i + 2);
      i++;
      continue;
    }
    if (inClass) {
      if (c === "]") inClass = false;
      continue;
    }
    if (c === "[") {
      inClass = true;
      atom = source[i + 1] === "^" ? "[^" : "[";
    } else if (c === "(") groups.push(false);
    else if (c === "|" || c === "*" || c === "+" || (c === "{" && /^\{\d+,\d*\}/.test(source.slice(i)))) {
      if (groups.length) groups[groups.length - 1] = true;
      if (c === "*" || c === "+" || /^\{\d+,\}/.test(source.slice(i))) {
        open++;
        if (BROAD.has(atom)) broad++;
      }
    } else if (c === ")") {
      atom = c;
      const risky = groups.pop() ?? false;
      const next = source.slice(i + 1);
      const repeated = /^[*+]/.test(next) || /^\{\d+,(\d*)\}/.test(next) && !/^\{(\d+),\1\}/.test(next) && !/^\{\d+,1\}/.test(next);
      if (risky && repeated) return { nested: true, open, broad };
      if (risky && groups.length) groups[groups.length - 1] = true;
    } else atom = c;
  }
  return { nested: false, open, broad };
}

function checkErrors(errors: string[]): void {
  for (const pattern of errors) {
    const problem = errorPatternProblem(pattern);
    if (problem) throw new NoteError(problem);
  }
}

/** Create and save a new note. `text` becomes the body (first line = headline); secrets are masked. */
export function createNote(home: string, input: NewNote): Note {
  const clean = (s: string) => scrub(s, { longRuns: false }).text;
  const body = clean(input.text.trim());
  if (!body) throw new NoteError("empty note");
  checkErrors(input.errors ?? []);
  const note: Note = {
    id: randomId("n"),
    kind: input.kind ?? "note",
    project: input.project,
    private: input.private ?? false,
    at: nowIso(),
    source: input.source ?? "agent",
    tags: tagList((input.tags ?? []).map(clean)),
    errors: (input.errors ?? []).map(clean),
    evidence: (input.evidence ?? []).map(clean),
    tested: input.tested ?? false,
    replaces: input.replaces,
    body,
    path: "",
  };
  return saveNote(home, note);
}

/**
 * Upgrade metadata only, never the body: an explicit kind wins, tags, errors and evidence are
 * added, tested sticks. Callers must reject different bodies first. Null when nothing changed.
 */
export function upgradeNote(home: string, note: Note, input: Omit<NewNote, "text" | "project">): Note | null {
  checkErrors(input.errors ?? []);
  const clean = (s: string) => scrub(s, { longRuns: false }).text;
  const merged: Note = {
    ...note,
    kind: input.kind ?? note.kind,
    tags: tagList([...note.tags, ...(input.tags ?? [])].map(clean)),
    errors: [...new Set([...note.errors, ...(input.errors ?? []).map(clean)])],
    evidence: [...new Set([...note.evidence, ...(input.evidence ?? [])].map(clean))],
    tested: note.tested || input.tested === true,
  };
  return formatNote(merged) === formatNote(note) ? null : saveNote(home, merged);
}

/** Retire a note (history kept). With `by`, the replacement is linked both ways. */
export function retireNote(home: string, id: string, by?: string): Note {
  const { notes } = loadNotes(home);
  const note = findNote(notes, id);
  if (!note) throw new NoteError(`no note ${id}`);
  if (note.retired) throw new NoteError(`${note.id} is already retired`);
  let next: Note | undefined;
  if (by !== undefined) {
    next = findNote(notes, by);
    if (!next) throw new NoteError(`no note ${by}`);
    if (next.id === note.id) throw new NoteError("a note cannot replace itself");
    saveNote(home, { ...next, replaces: note.id });
  }
  return saveNote(home, { ...note, retired: nowIso(), replacedBy: next?.id });
}

/**
 * An active note with the same headline (ignoring case and spacing) that the writer can already
 * see: for a project note, the project's own notes and the global notes visible to it (untagged,
 * or sharing one of `tags`); for a global note, the untagged global notes.
 * Private requests match only private notes in the same project, never a public/global fallback.
 */
export function findSameHeadline(notes: Note[], text: string, project: string, tags: string[] = [], isPrivate = false): Note | undefined {
  const key = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
  const wanted = key(firstLine({ body: text }));
  if (!wanted) return undefined;
  const sees = (n: Note): boolean => {
    if (isPrivate) return n.private && n.project === project;
    if (n.project !== GLOBAL) return project !== GLOBAL && n.project === project;
    if (!n.tags.length) return true;
    return project !== GLOBAL && n.tags.some((t) => tags.includes(t));
  };
  return notes.find((n) => !n.retired && sees(n) && key(firstLine(n)) === wanted);
}

/** Whitespace is incidental; changed text must never be acknowledged as an identical write. */
export function differentBody(same: Note, text: string): boolean {
  const body = scrub(text.trim(), { longRuns: false }).text;
  return body.replace(/\s+/g, " ").trim() !== same.body.replace(/\s+/g, " ").trim();
}

/** Missing file evidence is advisory, never grounds for hiding or retiring a note. */
export function staleEvidence(note: Note, roots: string[]): boolean {
  if (!note.evidence.length) return false;
  const key = JSON.stringify([note.id, note.evidence, roots]);
  const now = Date.now();
  const cached = EVIDENCE_CACHE.get(key);
  if (cached && now - cached.at < EVIDENCE_TTL_MS) return cached.stale;
  const paths: string[] = [];
  for (const entry of note.evidence) {
    // Old evidence often carries a line number (`:N:C`, `#LN`, `(N,C)`), a symbol or test selector,
    // or a commit annotation. None is part of its filename; a symbol counts only after a `.ext`,
    // so `commit:abc` stays a scheme. Other schemes (events:, commit:, URLs) are not file evidence.
    const path = entry.trim().replace(/\s+\(.*\)$/, "").replace(/@[a-f\d]{7,40}$/i, "")
      .replace(/::.*$|(?::\d+){1,2}(?:-\d+)?$|#L\d+(?:-L?\d+)?$|(?<=\.[a-z\d]{1,16})(?:\(\d+(?:,\d+)?\)|:[A-Za-z_$][\w$.]*)$/i, "");
    if (/^[a-z][a-z\d+.-]*:/i.test(path) && !/^[a-z]:[\\/]/i.test(path)) continue;
    // A parent escape or a glob names no single file: unknown, never missing.
    if (path.split(/[\\/]/).includes("..") || /[*?[\]{}]/.test(path)) continue;
    const absolute = isAbsolute(path) || win32.isAbsolute(path);
    const filename = /(?:^|[\\/])[^\\/]+\.[a-z\d]{1,16}$/i.test(path);
    if (absolute || filename || /^[^\s]+[\\/][^\s]+$/.test(path) || /^(?:README|LICENSE|Makefile|Dockerfile)$/i.test(path)) paths.push(path);
  }
  const stale = paths.length > 0 && paths.every((path) => {
    if (isAbsolute(path) || win32.isAbsolute(path)) return !existsSync(path);
    return roots.length > 0 && roots.every((root) => !existsSync(resolve(root, path.replace(/\\/g, "/"))));
  });
  EVIDENCE_CACHE.set(key, { stale, at: now });
  return stale;
}
