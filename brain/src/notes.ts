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
import { existsSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { scrub } from "./scrub.ts";
import { nowIso, randomId, writeAtomic } from "./util.ts";

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
const ORDER = ["id", "kind", "at", "source", "tags", "errors", "evidence", "tested", "replaces", "replaced_by", "retired"];

/** First non-empty body line without leading "#", at most 160 chars. */
export function headline(note: Pick<Note, "body">): string {
  const line = note.body.split("\n").find((l) => l.trim()) ?? "";
  const text = line.replace(/^#+\s*/, "").trim();
  return text.length > 160 ? text.slice(0, 159) + "…" : text;
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

function parseInlineList(raw: string): string[] {
  const inner = raw.trim().slice(1, -1).trim();
  if (!inner) return [];
  return inner.split(",").map((part) => parseScalar(part)).filter((part) => part !== "");
}

/** Parse frontmatter into scalars and lists. Unknown keys are kept; malformed lines throw. */
export function parseFrontmatter(text: string): { fields: Map<string, string | string[]>; body: string } {
  const normalized = text.replace(/^﻿/, "").replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) throw new NoteError("missing frontmatter");
  const end = normalized.indexOf("\n---", 4);
  if (end < 0) throw new NoteError("unterminated frontmatter");
  const head = normalized.slice(4, end);
  const afterFence = normalized.indexOf("\n", end + 1);
  const body = afterFence < 0 ? "" : normalized.slice(afterFence + 1);
  const fields = new Map<string, string | string[]>();
  let listKey: string | null = null;
  for (const line of head.split("\n")) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const item = /^\s+-\s?(.*)$/.exec(line);
    if (item && listKey !== null) {
      (fields.get(listKey) as string[]).push(parseScalar(item[1] ?? ""));
      continue;
    }
    const pair = /^([A-Za-z_][\w-]*):(?:\s+(.*))?$/.exec(line);
    if (!pair) throw new NoteError(`bad frontmatter line: ${line.slice(0, 80)}`);
    const key = pair[1] as string;
    const value = (pair[2] ?? "").trim();
    if (value === "") {
      fields.set(key, []);
      listKey = key;
    } else if (value.startsWith("[") && value.endsWith("]")) {
      fields.set(key, parseInlineList(value));
      listKey = null;
    } else {
      fields.set(key, parseScalar(value));
      listKey = null;
    }
  }
  return { fields, body: body.replace(/^\n+/, "") };
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
    tags: asList(fields.get("tags")),
    errors: asList(fields.get("errors")),
    evidence: asList(fields.get("evidence")),
    tested: asScalar(fields.get("tested")) === "true",
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
    replaces: note.replaces,
    replaced_by: note.replacedBy,
    retired: note.retired,
  };
  const lines = ["---"];
  for (const key of ORDER) {
    const value = values[key];
    if (LIST_KEYS.has(key)) {
      const items = (value as string[]).filter((v) => v.trim() !== "");
      if (!items.length) continue;
      lines.push(`${key}:`);
      for (const item of items) lines.push(`  - ${scalarOut(item.replace(/\s*\n\s*/g, " "))}`);
    } else if (typeof value === "string" && value !== "") {
      lines.push(`${key}: ${scalarOut(value.replace(/\s*\n\s*/g, " "))}`);
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

function readDirNotes(dir: string, project: string, isPrivate: boolean, out: Note[], errors: string[]): void {
  let names: string[];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith(".md")).sort();
  } catch {
    return;
  }
  for (const name of names) {
    const path = join(dir, name);
    try {
      const note = parseNote(readFileSync(path, "utf8"), path, project, isPrivate);
      if (`${note.id}.md` !== name) throw new NoteError(`id ${note.id} does not match file name`);
      out.push(note);
    } catch (error) {
      errors.push(`${path}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

/** Every note under the home, sorted by id. Unreadable files are reported, never fatal. */
export function loadNotes(home: string): { notes: Note[]; errors: string[] } {
  const notes: Note[] = [];
  const errors: string[] = [];
  let projects: string[];
  try {
    projects = readdirSync(notesRoot(home), { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith("."))
      .map((d) => d.name)
      .sort();
  } catch {
    return { notes, errors };
  }
  for (const project of projects) {
    readDirNotes(noteDir(home, project, false), project, false, notes, errors);
    readDirNotes(noteDir(home, project, true), project, true, notes, errors);
  }
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

export function findNote(notes: Note[], id: string): Note | undefined {
  return notes.find((n) => n.id === id);
}

/** Write a note to the file its project/private flags say; removes the old file when it moved. */
export function saveNote(home: string, note: Note): Note {
  const path = join(noteDir(home, note.project, note.private), `${note.id}.md`);
  writeAtomic(path, formatNote(note));
  if (note.path && note.path !== path && existsSync(note.path)) rmSync(note.path);
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

/** Create and save a new note. `text` becomes the body (first line = headline); secrets are masked. */
export function createNote(home: string, input: NewNote): Note {
  const clean = (s: string) => scrub(s, { longRuns: false }).text;
  const body = clean(input.text.trim());
  if (!body) throw new NoteError("empty note");
  const note: Note = {
    id: randomId("n"),
    kind: input.kind ?? "note",
    project: input.project,
    private: input.private ?? false,
    at: nowIso(),
    source: input.source ?? "agent",
    tags: input.tags ?? [],
    errors: (input.errors ?? []).map(clean),
    evidence: input.evidence ?? [],
    tested: input.tested ?? false,
    replaces: input.replaces,
    body,
    path: "",
  };
  return saveNote(home, note);
}

/** Retire a note (history kept). With `by`, the replacement is linked both ways. */
export function retireNote(home: string, id: string, by?: string): Note {
  const { notes } = loadNotes(home);
  const note = findNote(notes, id);
  if (!note) throw new NoteError(`no note ${id}`);
  if (note.retired) throw new NoteError(`${id} is already retired`);
  if (by !== undefined) {
    const next = findNote(notes, by);
    if (!next) throw new NoteError(`no note ${by}`);
    if (by === id) throw new NoteError("a note cannot replace itself");
    saveNote(home, { ...next, replaces: id });
  }
  return saveNote(home, { ...note, retired: nowIso(), replacedBy: by });
}

/** An active note in `project` (or global) whose headline equals the headline of `text`, ignoring case and spacing. */
export function findSameHeadline(notes: Note[], text: string, project: string): Note | undefined {
  const key = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
  const wanted = key(headline({ body: text }));
  if (!wanted) return undefined;
  return notes.find((n) => !n.retired && (n.project === project || n.project === GLOBAL) && key(headline(n)) === wanted);
}
