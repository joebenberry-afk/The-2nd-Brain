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
import { dirname, isAbsolute, join, resolve, win32 } from "node:path";
import { createHash } from "node:crypto";
import { scrub } from "./scrub.ts";
import { claimPath, nowIso, randomId, retrying, slug, tagList, withClaim, withClaims, writeAtomic } from "./util.ts";

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
  /** File path=12hex snapshots; absent on legacy notes. */
  evidenceSha?: string[];
  /** Verified to work; only tested notes are pushed when a tool fails. */
  tested: boolean;
  /** Who verified it (see TESTERS); unset on notes tested before it was recorded. */
  testedBy?: string;
  /** ISO time it was verified. */
  testedAt?: string;
  /** Normalized body and error patterns when tested; absent means legacy trusted. */
  testedSha?: string;
  /** The one host whose tools produce this note's errors ("omp" | "claude-code"); unset, every host. */
  host?: string;
  /** Date or ISO instant from which the note is out of date (OKF `stale_after`). */
  staleAfter?: string;
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

const LIST_KEYS = new Set(["tags", "errors", "evidence", "evidence_sha"]);
const ORDER = ["id", "kind", "at", "source", "tags", "errors", "evidence", "evidence_sha", "tested", "tested_by", "tested_at", "tested_sha", "host", "stale_after", "replaces", "replaced_by", "retired"];

/**
 * Who verified a note, lowest trust first: `convert` (a V3 grade), `agent` (its own claim),
 * `capture` (a failed command that later passed), `owner` (`brain tested <id>`).
 */
export const TESTERS = ["convert", "agent", "capture", "owner"] as const;
export type Tester = (typeof TESTERS)[number];

/** Why a `stale_after` value cannot be used, or null: a date, or an ISO instant with an offset. */
export function staleAfterProblem(value: string): string | null {
  const shape = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value);
  const day = Date.parse(`${value.slice(0, 10)}T00:00:00Z`);
  if (!shape || Number.isNaN(day) || Number.isNaN(Date.parse(value)) || new Date(day).toISOString().slice(0, 10) !== value.slice(0, 10)) {
    return `stale_after ${JSON.stringify(value)} is not a date (YYYY-MM-DD) or an ISO time with an offset`;
  }
  return null;
}

/** True from the note's `stale_after` instant on (a date means its start, UTC); a bad value never expires. */
export function expired(note: Pick<Note, "staleAfter">, now = Date.now()): boolean {
  if (!note.staleAfter || staleAfterProblem(note.staleAfter)) return false;
  return now >= Date.parse(note.staleAfter.length === 10 ? `${note.staleAfter}T00:00:00Z` : note.staleAfter);
}

/** The note as verified by `by` now. */
export function markTested(note: Note, by: Tester, roots: string[] = []): Note {
  // A file the roots cannot resolve (checked out elsewhere) keeps the hash taken where it was verified.
  const fresh = evidenceHashes(note.evidence, roots);
  const pathOf = (entry: string) => entry.slice(0, entry.lastIndexOf("="));
  const resolved = new Set(fresh.map(pathOf));
  const evidenceSha = [...(note.evidenceSha ?? []).filter((entry) => !resolved.has(pathOf(entry))), ...fresh];
  return { ...note, tested: true, testedBy: by, testedAt: nowIso(), testedSha: testedHash(note), evidenceSha };
}

/** Whitespace is incidental; error-pattern edits invalidate verification too. */
export function testedHash(note: Pick<Note, "body" | "errors">): string {
  const normalize = (text: string) => text.replace(/\s+/g, " ").trim();
  return createHash("sha256").update(JSON.stringify([normalize(note.body), note.errors.map(normalize)])).digest("hex").slice(0, 12);
}

export function testedCurrent(note: Note): boolean {
  return note.tested && (!note.testedSha || note.testedSha === testedHash(note));
}

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
    ...(fields.has("evidence_sha") ? { evidenceSha: asList(fields.get("evidence_sha")) } : {}),
    tested: asScalar(fields.get("tested")) === "true",
    testedBy: asScalar(fields.get("tested_by")),
    testedAt: asScalar(fields.get("tested_at")),
    ...(asScalar(fields.get("tested_sha")) ? { testedSha: asScalar(fields.get("tested_sha")) } : {}),
    // Hand-written: "OMP" still means omp. `brain check` reports a value that is no host.
    host: asScalar(fields.get("host"))?.trim().toLowerCase() || undefined,
    staleAfter: asScalar(fields.get("stale_after")),
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
    evidence_sha: note.evidenceSha ?? [],
    tested: note.tested ? "true" : undefined,
    tested_by: note.tested ? note.testedBy : undefined,
    tested_at: note.tested ? note.testedAt : undefined,
    tested_sha: note.tested ? note.testedSha : undefined,
    host: note.host,
    stale_after: note.staleAfter,
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
      out.push({ ...note, tags: [...note.tags], errors: [...note.errors], evidence: [...note.evidence], ...(note.evidenceSha ? { evidenceSha: [...note.evidenceSha] } : {}) });
    } catch (error) {
      errors.push(`${path}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

/** Notes by id, the first of a duplicated id kept; the others are reported. */
function uniqueById(notes: Note[], errors: string[]): Note[] {
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
  return unique.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
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
  return { notes: uniqueById(notes, errors), errors };
}

/**
 * The notes of the global and one project's directories only (public and private), for hot paths
 * that show a caller nothing else (`visibleTo` still decides which of them). Other projects'
 * directories are neither listed nor stat'ed, and their cached entries stay as they were. A
 * project name that is not a plain directory name loads everything.
 */
export function loadVisibleNotes(home: string, project: string): { notes: Note[]; errors: string[] } {
  if (!project || project === "." || project === ".." || /[\\/]/.test(project)) return loadNotes(home);
  home = resolve(home);
  const previous = NOTE_CACHE.get(home);
  const current = new Map<string, CachedNote>();
  const notes: Note[] = [];
  const errors: string[] = [];
  const dirs = new Set<string>();
  for (const name of [...new Set([GLOBAL, project])].sort()) {
    for (const isPrivate of [false, true]) {
      const dir = noteDir(home, name, isPrivate);
      dirs.add(dir);
      readDirNotes(dir, name, isPrivate, notes, errors, previous, current);
    }
  }
  const merged = new Map<string, CachedNote>();
  const before = new Map<string, CachedNote>();
  for (const [path, cached] of previous ?? []) (dirs.has(dirname(path)) ? before : merged).set(path, cached);
  if (!previous || before.size !== current.size || [...current].some(([path, cached]) => before.get(path) !== cached)) EVIDENCE_CACHE.clear();
  for (const [path, cached] of current) merged.set(path, cached);
  NOTE_CACHE.set(home, merged);
  return { notes: uniqueById(notes, errors), errors };
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

/** The claim on note `id`, case-folded because ids are file names: one lock per note, whoever spells it how. */
const noteClaim = (home: string, id: string) => claimPath(home, `note-${id.toLowerCase()}.lock`);

/** A file holding note `id` outside `known` (the paths this save writes and replaces), if there is one. */
function strayCopy(home: string, id: string, known: string[]): string | undefined {
  let projects: string[];
  try {
    projects = readdirSync(notesRoot(home), { withFileTypes: true }).filter((d) => d.isDirectory() && !d.name.startsWith(".")).map((d) => d.name);
  } catch {
    return undefined;
  }
  for (const project of projects) {
    for (const isPrivate of [false, true]) {
      const path = join(noteDir(home, project, isPrivate), `${id}.md`);
      if (existsSync(path) && !known.some((k) => k === path || sameFile(k, path))) return path;
    }
  }
  return undefined;
}

/**
 * Write a note to the file its project/private flags say; removes the old file when it moved. The
 * whole write and removal run under the note's cross-process claim. A save whose `note.path` snapshot
 * is stale (another process moved the note since it was loaded) throws, writing nothing, instead of
 * leaving the note in two folders. Read-modify-write callers use updateNote, which reloads under the claim.
 */
export function saveNote(home: string, note: Note): Note {
  if (!SAFE_ID.test(note.id) || note.id.includes("..")) throw new NoteError(`unsafe note id ${JSON.stringify(note.id)}`);
  if (note.project !== slug(note.project)) throw new NoteError(`not a project id: ${JSON.stringify(note.project)} (use ${slug(note.project)})`);
  const path = join(noteDir(home, note.project, note.private), `${note.id}.md`);
  return withClaim(noteClaim(home, note.id), () => {
    // A new note (no path yet) has nothing to be stale against and skips the scan.
    const stray = note.path ? strayCopy(home, note.id, [path, note.path]) : undefined;
    if (stray) throw new NoteError(`${note.id} also exists at ${stray} (another process moved or copied it, or it is a duplicate); nothing was written — remove the extra copy or reload the note, then try again`);
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
  });
}

/**
 * Run `fn` holding the cross-process claim on note `id` (as pasted): reload the note inside `fn`,
 * change it, and save it, so a concurrent move or edit is never overwritten from a stale snapshot.
 * An id no note can have has no claim; `fn` then finds nothing to change.
 */
export function withNoteClaim<T>(home: string, id: string, fn: () => T): T {
  const query = idQuery(id);
  return SAFE_ID.test(query) ? withClaim(noteClaim(home, query), fn) : fn();
}

/**
 * Change note `id` as it is on disk now: under the note's claim it is reloaded, `change` returns its
 * new state (null when nothing changes), and that is saved before any other process can touch it.
 * Every read-modify-write of one note goes through here or withNoteClaim. Throws NoteError when
 * there is no such note.
 */
export function updateNote(home: string, id: string, change: (fresh: Note) => Note): Note;
export function updateNote(home: string, id: string, change: (fresh: Note) => Note | null): Note | null;
export function updateNote(home: string, id: string, change: (fresh: Note) => Note | null): Note | null {
  return withNoteClaim(home, id, () => {
    const fresh = findNote(loadNotes(home).notes, id);
    if (!fresh) throw new NoteError(`no note ${id}`);
    const next = change(fresh);
    return next && saveNote(home, next);
  });
}

export interface NewNote {
  text: string;
  project: string;
  kind?: Kind;
  tags?: string[];
  errors?: string[];
  evidence?: string[];
  /** Known checkout roots for resolving evidence at write time; never persisted. */
  evidenceRoots?: string[];
  tested?: boolean;
  /** Recorded when `tested`; omitted, the verifier stays unrecorded. */
  testedBy?: Tester;
  staleAfter?: string;
  source?: string;
  private?: boolean;
  replaces?: string;
  /** A caller-derived id (`n-` + 10 hex), for writes that must stay idempotent across processes. */
  id?: string;
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

/** The one masking every written note field goes through (create, upgrade, V3 convert). */
export function maskText(text: string): string {
  return scrub(text, { longRuns: false }).text;
}

function checkErrors(errors: string[]): void {
  for (const pattern of errors) {
    const problem = errorPatternProblem(pattern);
    if (problem) throw new NoteError(problem);
  }
}

/** Mask error patterns; a pattern that is valid raw but invalid once masked (`re:password=(\d+)`) is refused so its writer rewords it. */
export function cleanErrors(errors: string[]): string[] {
  checkErrors(errors);
  return errors.map((pattern) => {
    const masked = maskText(pattern);
    const problem = masked === pattern ? null : errorPatternProblem(masked);
    if (problem) throw new NoteError(`error pattern changed by secret masking (${problem}); reword it without the credential: ${JSON.stringify(masked)}`);
    return masked;
  });
}

function checkStaleAfter(value: string | undefined): void {
  const problem = value === undefined ? null : staleAfterProblem(value);
  if (problem) throw new NoteError(problem);
}

/** Create and save a new note. `text` becomes the body (first line = headline); secrets are masked. */
export function createNote(home: string, input: NewNote): Note {
  const clean = maskText;
  const body = clean(input.text.trim());
  if (!body) throw new NoteError("empty note");
  if (input.id !== undefined && !/^n-[0-9a-f]{10}$/.test(input.id)) throw new NoteError(`invalid note id ${input.id}`);
  const errors = cleanErrors(input.errors ?? []);
  checkStaleAfter(input.staleAfter);
  const tested = input.tested ?? false;
  const note: Note = {
    id: input.id ?? randomId("n"),
    kind: input.kind ?? "note",
    project: input.project,
    private: input.private ?? false,
    at: nowIso(),
    source: input.source ?? "agent",
    tags: tagList((input.tags ?? []).map(clean)),
    errors,
    evidence: (input.evidence ?? []).map(clean),
    tested,
    testedBy: tested ? input.testedBy : undefined,
    testedAt: tested && input.testedBy ? nowIso() : undefined,
    staleAfter: input.staleAfter,
    replaces: input.replaces,
    body,
    path: "",
  };
  const roots = [...(input.evidenceRoots ?? []), home];
  const stamped = tested ? { ...note, testedSha: testedHash(note) } : note;
  const hashes = evidenceHashes(note.evidence, roots);
  return saveNote(home, { ...stamped, ...(hashes.length ? { evidenceSha: hashes } : {}) });
}

/**
 * Upgrade metadata only, never the body: an explicit kind and stale_after win, tags, errors and
 * evidence are added, tested sticks with its first verifier. Callers must reject different bodies
 * first. The upgrade is applied to the note as it is on disk under its claim; one that was retired
 * or whose body changed since `note` was loaded throws instead of being overwritten. Null when
 * nothing changed.
 */
export function upgradeNote(home: string, note: Note, input: Omit<NewNote, "text" | "project">): Note | null {
  const errors = cleanErrors(input.errors ?? []);
  checkStaleAfter(input.staleAfter);
  const clean = maskText;
  const roots = [...(input.evidenceRoots ?? []), home];
  const hashes = evidenceHashes((input.evidence ?? []).map(clean), roots);
  return updateNote(home, note.id, (fresh) => {
    if (fresh.body !== note.body || fresh.retired !== note.retired) throw new NoteError(`${note.id} changed since it was read; nothing was written, look at it again`);
    const heldHashes = new Set((fresh.evidenceSha ?? []).map(entry => entry.slice(0, entry.lastIndexOf("="))));
    const merged: Note = {
      ...fresh,
      kind: input.kind ?? fresh.kind,
      tags: tagList([...fresh.tags, ...(input.tags ?? [])].map(clean)),
      errors: [...new Set([...fresh.errors, ...errors])],
      evidence: [...new Set([...fresh.evidence, ...(input.evidence ?? [])].map(clean))],
      evidenceSha: [...(fresh.evidenceSha ?? []), ...hashes.filter(entry => !heldHashes.has(entry.slice(0, entry.lastIndexOf("="))))],
      staleAfter: input.staleAfter ?? fresh.staleAfter,
    };
    const upgraded = !fresh.tested && input.tested === true ? (input.testedBy ? markTested(merged, input.testedBy, roots) : { ...merged, tested: true, testedSha: testedHash(merged) }) : merged;
    return formatNote(upgraded) === formatNote(fresh) ? null : upgraded;
  });
}

/** Retire a note (history kept). With `by`, the replacement is linked both ways. Both notes are claimed while it runs. */
export function retireNote(home: string, id: string, by?: string): Note {
  const claims = [id, by].flatMap((q) => (q !== undefined && SAFE_ID.test(idQuery(q)) ? [noteClaim(home, idQuery(q))] : []));
  return withClaims(claims, () => {
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
  });
}

/**
 * An active note with the same headline (ignoring case and spacing) that the writer can already
 * see: its own notes and global notes with no scoping tags, or a matching project tag.
 * `brief` is a behavior tag, not a project scope.
 * Private requests match only private notes in the same project, never a public/global fallback.
 */
export function findSameHeadline(notes: Note[], text: string, project: string, tags: string[] = [], isPrivate = false): Note | undefined {
  const key = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
  // Stored headlines were masked on write: compare the masked text.
  const wanted = key(firstLine({ body: maskText(text.trim()) }));
  if (!wanted) return undefined;
  const sees = (n: Note): boolean => {
    if (isPrivate) return n.private && n.project === project;
    if (n.project !== GLOBAL) return project !== GLOBAL && n.project === project;
    if (n.tags.every((t) => t === "brief")) return true;
    return n.tags.some((t) => t !== "brief" && tags.includes(t));
  };
  return notes.find((n) => !n.retired && sees(n) && key(firstLine(n)) === wanted);
}

/** Whitespace is incidental; changed text must never be acknowledged as an identical write. */
export function differentBody(same: Note, text: string): boolean {
  const body = maskText(text.trim());
  return body.replace(/\s+/g, " ").trim() !== same.body.replace(/\s+/g, " ").trim();
}

/** Missing file evidence is advisory, never grounds for hiding or retiring a note. */
export function staleEvidence(note: Note, roots: string[]): boolean {
  if (!note.evidence.length) return false;
  const key = JSON.stringify([note.id, note.evidence, roots]);
  const now = Date.now();
  const cached = EVIDENCE_CACHE.get(key);
  if (cached && now - cached.at < EVIDENCE_TTL_MS) return cached.stale;
  const paths = note.evidence.map(evidencePath).filter((path): path is string => !!path);
  const stale = paths.length > 0 && paths.every((path) => {
    if (isAbsolute(path) || win32.isAbsolute(path)) return !existsSync(path);
    return roots.length > 0 && roots.every((root) => !existsSync(resolve(root, path.replace(/\\/g, "/"))));
  });
  EVIDENCE_CACHE.set(key, { stale, at: now });
  return stale;
}

/** A single safe file reference, stripped of evidence annotations. */
function evidencePath(entry: string): string | undefined {
  const path = entry.trim().replace(/\s+\(.*\)$/, "").replace(/@[a-f\d]{7,40}$/i, "")
    .replace(/::.*$|(?::\d+){1,2}(?:-\d+)?$|#L\d+(?:-L?\d+)?$|(?<=\.[a-z\d]{1,16})(?:\(\d+(?:,\d+)?\)|:[A-Za-z_$][\w$.]*)$/i, "");
  if (/^[a-z][a-z\d+.-]*:/i.test(path) && !/^[a-z]:[\\/]/i.test(path)) return undefined;
  if (path.split(/[\\/]/).includes("..") || /[*?[\]{}]/.test(path)) return undefined;
  return isAbsolute(path) || win32.isAbsolute(path) || /(?:^|[\\/])[^\\/]+\.[a-z\d]{1,16}$/i.test(path) || /^[^\s]+[\\/][^\s]+$/.test(path) || /^(?:README|LICENSE|Makefile|Dockerfile)$/i.test(path) ? path : undefined;
}

const FILE_HASH_CACHE = new Map<string, { signature: string; sha: string; mtime: number }>();
const CRLF = Buffer.from("\r\n");
function evidenceFile(path: string, roots: string[]): { sha: string; mtime: number } | undefined {
  const files = isAbsolute(path) || win32.isAbsolute(path) ? [path] : roots.map(root => resolve(root, path.replace(/\\/g, "/")));
  for (const file of files) {
    try {
      const stat = statSync(file, { bigint: true });
      if (!stat.isFile()) continue;
      const signature = `${stat.mtimeNs}:${stat.size}`;
      const cached = FILE_HASH_CACHE.get(file);
      if (cached?.signature === signature) return cached;
      const bytes = readFileSync(file), hash = createHash("sha256");
      let start = 0, end = bytes.indexOf(CRLF);
      while (end >= 0) { hash.update(bytes.subarray(start, end)).update("\n"); start = end + 2; end = bytes.indexOf(CRLF, start); }
      hash.update(bytes.subarray(start));
      const value = { signature, sha: hash.digest("hex").slice(0, 12), mtime: Number(stat.mtimeNs) / 1_000_000 };
      if (FILE_HASH_CACHE.size >= 2000) FILE_HASH_CACHE.clear();
      FILE_HASH_CACHE.set(file, value);
      return value;
    } catch { /* Missing or unreadable evidence never prevents a note write or host session. */ }
  }
  return undefined;
}

export function evidenceHashes(evidence: string[], roots: string[]): string[] {
  return [...new Set(evidence.flatMap(entry => {
    const path = evidencePath(entry), file = path && evidenceFile(path, roots);
    return path && file ? [path + "=" + file.sha] : [];
  }))];
}

/** With after, only a changed file modified after verification invalidates a known fix. */
export function changedEvidence(note: Note, roots: string[], after?: string): boolean {
  const since = after ? Date.parse(after) : undefined;
  return (note.evidenceSha ?? []).some(entry => {
    const match = /^(.*)=([a-f\d]{12})$/i.exec(entry);
    const path = match && evidencePath(match[1]!);
    const file = path && evidenceFile(path, roots);
    return !!file && file.sha !== match![2]!.toLowerCase() && (since === undefined || Number.isNaN(since) || file.mtime > since);
  });
}
