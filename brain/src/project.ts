/**
 * Which project a working directory belongs to. No registration is needed: the id falls out of
 * the git remote or the repository folder. `projects.json` in the Brain home is optional and only
 * adds aliases (extra paths, a remote) and tags:
 *
 *   { "projects": { "second-brain": { "paths": ["C:/work/brain"], "remote": "github.com/o/r",
 *                                     "tags": ["typescript", "omp"], "aliases": ["the-2nd-brain"] } } }
 *
 * Resolution: BRAIN_PROJECT → projects.json path (longest prefix) → projects.json remote →
 * git remote repo name → main checkout folder name (a linked worktree names its main checkout) →
 * (no git) the nearest folder at or above cwd, below the user's home folder, that projects.json
 * names → cwd folder name. Tags
 * are the declared ones plus the stack implied by manifest files at the root (package.json → node,
 * pyproject.toml → python, …).
 */
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, win32 } from "node:path";
import { GLOBAL, type Note } from "./notes.ts";
import { slug, tagKey, tagList, writeAtomic } from "./util.ts";
import { scrub } from "./scrub.ts";

export interface Project {
  id: string;
  tags: string[];
  /** The git root, declared path or registered folder (else cwd) the project was resolved from; null when none is known. */
  root: string | null;
  /** The declared `paths` folder when a git repo inside it is the root; registered docs also resolve there. */
  docRoot?: string;
}

export interface ProjectEntry {
  /** Explicit repo-relative Markdown plan files; never auto-discovered. */
  docs?: string[];
  paths?: string[];
  remote?: string;
  tags?: string[];
  /** Other ids this project resolves from (a renamed repo, a fork, another folder name). */
  aliases?: string[];
}

/** Comparable path: forward slashes, no trailing slash, case-folded for Windows paths. */
export function normalizePath(value: string): string {
  const text = value.trim();
  if (/^[A-Za-z]:[\\/]/.test(text) || text.includes("\\") || text.startsWith("//")) {
    return text.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  }
  return text.replace(/\/+$/, "") || "/";
}

/**
 * Resolve junctions/symlinks through the nearest existing ancestor, so a path that does not exist
 * (yet) under a junction still lands under its target; registrations offline stay lexical.
 */
function canonicalPath(value: string): string {
  let head = resolve(value);
  const rest: string[] = [];
  for (;;) {
    try {
      return normalizePath([realpathSync.native(head), ...rest].join("/"));
    } catch {
      const parent = dirname(head);
      if (parent === head) return normalizePath(value);
      rest.unshift(basename(head));
      head = parent;
    }
  }
}

/** `git@github.com:o/r.git` / `https://user@github.com/o/r` → `github.com/o/r`. */
export function normalizeRemote(url: string): string {
  let text = url.trim().replace(/\\/g, "/");
  // A local path (C:/repos/app.git, //nas/git/app.git) keeps only its folders; no scp-style ":".
  if (/^[A-Za-z]:\//.test(text) || text.startsWith("//")) return text.replace(/^[A-Za-z]:/, "").replace(/^\/+/, "").replace(/\/$/, "").replace(/\.git$/, "").toLowerCase();
  text = text.replace(/^[a-z+]+:\/\//, "");
  text = text.replace(/^[^@/]+@/, "");
  if (/^[^/]+:[^/]/.test(text)) text = text.replace(":", "/");
  text = text.replace(/\/$/, "").replace(/\.git$/, "");
  return text.toLowerCase();
}

/** Same repository: equal remotes, or the same `owner/repo` behind a different host (mirror, proxy). */
function sameRepo(a: string, b: string): boolean {
  if (a === b) return true;
  const tail = (s: string) => s.split("/").slice(-2).join("/");
  return a.split("/").length >= 3 && b.split("/").length >= 3 && tail(a) === tail(b);
}

/** Windows device names: git cannot index notes/con/…, so no project may take one as its id. */
const RESERVED = /^(?:con|prn|aux|nul|com\d|lpt\d)$/;

/** A name slugged into a project id: never "global" (the shared scope) nor a device name. */
export function idFor(name: string): string {
  const d = slug(name);
  return d === GLOBAL ? "global-project" : RESERVED.test(d) ? `${d}-project` : d;
}

/**
 * projects.json, with every key and alias slugged the way derived ids are — so all ways of naming
 * a project agree, and no synced key can point notes/ or work/ outside the home.
 */
export function loadProjects(home: string): Record<string, ProjectEntry> {
  let raw: unknown;
  try {
    raw = (JSON.parse(readFileSync(join(home, "projects.json"), "utf8").replace(/^\uFEFF/, "")) as { projects?: unknown } | null)?.projects;
  } catch {
    return {};
  }
  if (!raw || typeof raw !== "object") return {};
  const projects: Record<string, ProjectEntry> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== "object") continue;
    const entry = value as ProjectEntry;
    const aliases = Array.isArray(entry.aliases) ? entry.aliases.filter((a): a is string => typeof a === "string").map(idFor) : undefined;
    const id = idFor(key);
    projects[id] = { ...entry, ...(aliases ? { aliases } : {}) };
  }
  return projects;
}

/**
 * Give project `id` the tag `tag` in projects.json, editing the file as written (unknown keys,
 * other entries and key spelling kept). False when it already has the tag. Throws, touching
 * nothing, when projects.json exists but is not `{ "projects": { … } }`.
 */
export function addProjectTag(home: string, id: string, tag: string): boolean {
  if (scrub(tag).scrubbed || scrub(tagKey(tag)).scrubbed) throw new Error("tag contains a credential; choose a non-secret tag");
  // An old id listed as an alias tags its owner: a key named like the alias would take the repo back.
  id = canonical(loadProjects(home), id);
  const file = join(home, "projects.json");
  let data: { projects: Record<string, unknown> } = { projects: {} };
  if (existsSync(file)) {
    const parsed: unknown = JSON.parse(readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
    const inner = (parsed as { projects?: unknown } | null)?.projects;
    if (!inner || typeof inner !== "object" || Array.isArray(inner)) throw new Error(`${file}: expected { "projects": { … } }`);
    data = parsed as { projects: Record<string, unknown> };
  }
  const key = Object.keys(data.projects).find((k) => idFor(k) === id) ?? id;
  const entry = data.projects[key];
  if (entry !== undefined && (!entry || typeof entry !== "object" || Array.isArray(entry))) throw new Error(`${file}: project ${key} is not an object`);
  const current = entry as Record<string, unknown> | undefined;
  const tags = Array.isArray(current?.tags) ? (current.tags as unknown[]) : [];
  if (tags.some((t) => typeof t === "string" && tagKey(t) === tagKey(tag))) return false;
  data.projects[key] = { ...current, tags: [...tags, tagKey(tag)] };
  writeAtomic(file, JSON.stringify(data, null, 2) + "\n");
  return true;
}

/** An existing Markdown file contained in the checkout, including after symlink resolution. */
export function projectDocPath(root: string | null, path: string): string | undefined {
  if (!root || !path || isAbsolute(path) || win32.isAbsolute(path) || /[:\r\n\0#]/.test(path) || !/\.md$/i.test(path)) return undefined;
  const portable = path.replace(/\\/g, "/");
  if (portable.split("/").includes("..")) return undefined;
  const file = resolve(root, portable);
  try {
    const rel = relative(realpathSync(root), realpathSync(file));
    if (!rel || rel === ".." || rel.startsWith("../") || rel.startsWith("..\\") || isAbsolute(rel) || !statSync(file).isFile()) return undefined;
    return file;
  } catch {
    return undefined;
  }
}

/**
 * A registered doc: stored relative to the declared folder when a repo inside it is the root (docs
 * listed before that were stored against the root, hence the fallback).
 */
export function docFile(project: Project, path: string): string | undefined {
  const inWorktree = worktreeSpelling(project.root, project.docRoot, path);
  return (inWorktree ? projectDocPath(project.root, inWorktree) : undefined)
    ?? projectDocPath(project.docRoot ?? project.root, path) ?? (project.docRoot ? projectDocPath(project.root, path) : undefined);
}

/**
 * A path spelled against the declared folder, as the linked worktree `root` spells it: docs are
 * stored against the folder (so against the main checkout inside it), but a worktree reads its own copy.
 */
export function worktreeSpelling(root: string | null, docRoot: string | undefined, path: string): string | undefined {
  if (!root || !docRoot || !path || isAbsolute(path) || win32.isAbsolute(path)) return undefined;
  const main = mainCheckout(root);
  if (main === root) return undefined;
  try {
    const rel = relative(realpathSync.native(main), resolve(realpathSync.native(docRoot), path.replace(/\\/g, "/")));
    return rel && !rel.startsWith("..") && !isAbsolute(rel) ? rel.replace(/\\/g, "/") : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Register one explicit document without changing unrelated project configuration. It is stored
 * relative to the declared folder when there is one (so it resolves from every repo inside it),
 * spelled as on disk (so a case-sensitive checkout finds it), and only once.
 */
export function addProjectDoc(home: string, project: Project, path: string): boolean {
  // As typed, the path is relative to the root in use (a repo inside the declared folder, a worktree).
  const target = projectDocPath(project.root, path) ?? projectDocPath(project.docRoot ?? null, path);
  if (!target) throw new Error("doc must be an existing relative .md file inside the project root");
  if (scrub(path).scrubbed) throw new Error("doc path contains a credential");
  const file = join(home, "projects.json");
  let data: { projects: Record<string, unknown> } = { projects: {} };
  if (existsSync(file)) {
    const parsed: unknown = JSON.parse(readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
    const inner = (parsed as { projects?: unknown } | null)?.projects;
    if (!inner || typeof inner !== "object" || Array.isArray(inner)) throw new Error(file + ': expected { "projects": { … } }');
    data = parsed as { projects: Record<string, unknown> };
  }
  const key = Object.keys(data.projects).find(k => idFor(k) === project.id) ?? project.id;
  const entry = data.projects[key];
  if (entry !== undefined && (!entry || typeof entry !== "object" || Array.isArray(entry))) throw new Error(file + ": project " + key + " is not an object");
  const current = entry as Record<string, unknown> | undefined;
  if (current?.docs !== undefined && (!Array.isArray(current.docs) || !current.docs.every(d => typeof d === "string"))) throw new Error(file + ": " + key + ".docs must be a list of strings");
  const docs = (current?.docs ?? []) as string[];
  // Stored against the declared folder, else the main checkout: a file in a linked worktree is
  // stored as the checkout's, since the worktree goes away. docRoot contains the main checkout.
  // realpathSync.native returns the on-disk case on Windows.
  const root = realpathSync.native(project.root!);
  const main = realpathSync.native(mainCheckout(root));
  const base = realpathSync.native(project.docRoot ?? main);
  const onDisk = (doc: string) => {
    const file = realpathSync.native(doc);
    const rel = relative(root, file);
    return relative(base, rel.startsWith("..") || isAbsolute(rel) ? file : join(main, rel)).replace(/\\/g, "/");
  };
  const normalized = onDisk(target);
  if (docs.some(d => { const f = docFile(project, d); return f ? onDisk(f) === normalized : normalizePath(d) === normalizePath(normalized); })) return false;
  data.projects[key] = { ...current, docs: [...docs, normalized] };
  writeAtomic(file, JSON.stringify(data, null, 2) + "\n");
  return true;
}

/** The nearest directory at or above `cwd` that contains a `.git` entry. */
export function gitRoot(cwd: string): string | null {
  let dir = resolve(cwd);
  for (;;) {
    if (existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** The git directory shared by all worktrees of the checkout at `root` (a linked worktree's .git is a file). */
function gitCommonDir(root: string): string | null {
  try {
    const dotgit = join(root, ".git");
    if (!statSync(dotgit).isFile()) return dotgit;
    const target = readFileSync(dotgit, "utf8").split("gitdir:")[1]?.trim();
    if (!target) return null;
    const gitdir = resolve(root, target);
    const common = join(gitdir, "commondir");
    return existsSync(common) ? resolve(gitdir, readFileSync(common, "utf8").trim()) : gitdir;
  } catch {
    return null;
  }
}

/** The main checkout of the repo at `root`: itself, unless `root` is a linked worktree. */
function mainCheckout(root: string): string {
  const common = gitCommonDir(root);
  return common && basename(common) === ".git" ? dirname(common) : root;
}

/** The `origin` URL of the repository at `root`, read from git config without running git. */
export function gitRemote(root: string): string | null {
  try {
    const gitdir = gitCommonDir(root);
    if (!gitdir) return null;
    const config = readFileSync(join(gitdir, "config"), "utf8");
    const section = /\[remote "origin"\]([\s\S]*?)(?:\n\[|$)/.exec(config);
    const url = section ? /^\s*url\s*=\s*(.+)$/m.exec(section[1] ?? "") : null;
    return url?.[1]?.trim() ?? null;
  } catch {
    return null;
  }
}

/** Stack tags implied by files at the project root, so shared notes find projects without setup. */
const MARKERS: ReadonlyArray<readonly [string, string]> = [
  ["package.json", "node"],
  ["tsconfig.json", "typescript"],
  ["pyproject.toml", "python"],
  ["requirements.txt", "python"],
  ["setup.py", "python"],
  ["Cargo.toml", "rust"],
  ["go.mod", "go"],
  ["pom.xml", "java"],
  ["build.gradle", "java"],
  ["build.gradle.kts", "java"],
  ["Gemfile", "ruby"],
  ["composer.json", "php"],
  ["deno.json", "deno"],
  ["pubspec.yaml", "dart"],
];

export function inferTags(root: string | null): string[] {
  if (!root) return [];
  const tags = new Set<string>();
  for (const [file, tag] of MARKERS) if (existsSync(join(root, file))) tags.add(tag);
  return [...tags];
}

/** The declared id a derived id belongs to: itself, or the project that lists it as an alias. */
export function canonical(projects: Record<string, ProjectEntry>, derived: string): string {
  if (projects[derived]) return derived;
  const owner = Object.entries(projects).find(([, e]) => Array.isArray(e.aliases) && e.aliases.includes(derived));
  return owner ? owner[0] : derived;
}

function tagsOf(entry: ProjectEntry | undefined, root: string | null = null): string[] {
  const declared = Array.isArray(entry?.tags) ? entry.tags.filter((t): t is string => typeof t === "string") : [];
  return tagList([...declared, ...inferTags(root)]);
}

/**
 * A project named explicitly (BRAIN_PROJECT, --project): slugged like every derived id — so it
 * can never leave notes/ or work/ — and mapped through aliases. When cwd resolves to that project
 * anyway, its root (a declared or registered folder) comes with it.
 */
export function projectById(home: string, id: string, cwd: string): Project {
  const projects = loadProjects(home);
  const canonicalId = canonical(projects, idFor(id));
  const auto = resolveProject(home, cwd, {}); // empty env: no BRAIN_PROJECT, so no recursion
  if (auto.id === canonicalId) return auto;
  const root = gitRoot(cwd);
  return { id: canonicalId, tags: tagsOf(projects[canonicalId], root), root };
}

export function resolveProject(home: string, cwd: string, env: NodeJS.ProcessEnv = process.env): Project {
  const projects = loadProjects(home);
  const explicit = env.BRAIN_PROJECT?.trim();
  if (explicit) return projectById(home, explicit, cwd);

  const here = canonicalPath(resolve(cwd));
  let best: { len: number; id: string; path: string } | null = null;
  for (const [id, entry] of Object.entries(projects)) {
    for (const declared of Array.isArray(entry.paths) ? entry.paths : []) {
      if (typeof declared !== "string" || !declared.trim()) continue;
      const root = canonicalPath(declared);
      if ((here === root || here.startsWith(root + "/")) && (!best || root.length > best.len)) {
        best = { len: root.length, id, path: declared };
      }
    }
  }
  const root = gitRoot(cwd);
  if (best) {
    const declared = resolve(best.path);
    // A git repo inside the declared folder stays the root: See: lines, evidence and edited paths are
    // relative to it. Docs registered against the declared folder resolve through docRoot. A linked
    // worktree of the declared checkout (.claude/worktrees/x) is that checkout, not a repo inside it.
    const inner = root !== null && canonicalPath(mainCheckout(root)).startsWith(canonicalPath(best.path) + "/");
    return { id: best.id, tags: tagsOf(projects[best.id], root ?? declared), root: root ?? declared, ...(inner ? { docRoot: declared } : {}) };
  }

  const remote = root ? gitRemote(root) : null;
  if (remote) {
    const key = normalizeRemote(remote);
    for (const [id, entry] of Object.entries(projects)) {
      if (typeof entry.remote === "string" && sameRepo(normalizeRemote(entry.remote), key)) {
        return { id, tags: tagsOf(entry, root), root };
      }
    }
    const id = canonical(projects, idFor(key.split("/").pop() ?? ""));
    return { id, tags: tagsOf(projects[id], root), root };
  }
  const idOf = (dir: string) => canonical(projects, idFor(basename(dir)));
  if (!root) {
    // Without git, a subfolder (the hook's cwd after `cd scripts`) belongs to the nearest folder
    // projects.json names (an id or alias). Never the home folder or above: one note from ~ must not
    // claim every folder beneath it.
    const top = canonicalPath(homedir());
    const belowHome = (dir: string) => { const at = canonicalPath(dir); return at !== top && !top.startsWith(at + "/"); };
    for (let dir = resolve(cwd); dirname(dir) !== dir && belowHome(dir); dir = dirname(dir)) {
      const id = idOf(dir);
      if (projects[id]) return { id, tags: tagsOf(projects[id], dir), root: dir };
    }
    const id = idOf(resolve(cwd));
    return { id, tags: tagsOf(projects[id], resolve(cwd)), root: resolve(cwd) };
  }
  // A linked worktree (<repo>/.claude/worktrees/<name>) is named after its main checkout; it stays
  // the root, so edited paths and See: anchors are relative to the checkout in use.
  const id = idOf(mainCheckout(root));
  return { id, tags: tagsOf(projects[id], root), root };
}

/**
 * Whether a caller in `project` sees `note`: its own project's notes, untagged global notes, and
 * tagged global notes that share a tag with the project. `null` project sees global notes only.
 */
export function visibleTo(note: Note, project: Project | null): boolean {
  if (note.project === GLOBAL) {
    if (!note.tags.length) return true;
    return project !== null && note.tags.some((t) => project.tags.includes(t));
  }
  return project !== null && note.project === project.id;
}
