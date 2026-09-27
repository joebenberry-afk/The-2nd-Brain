/**
 * Which project a working directory belongs to. No registration is needed: the id falls out of
 * the git remote or the repository folder. `projects.json` in the Brain home is optional and only
 * adds aliases (extra paths, a remote) and tags:
 *
 *   { "projects": { "second-brain": { "paths": ["C:/work/brain"], "remote": "github.com/o/r",
 *                                     "tags": ["typescript", "omp"], "aliases": ["the-2nd-brain"] } } }
 *
 * Resolution: BRAIN_PROJECT → projects.json path (longest prefix) → projects.json remote →
 * git remote repo name → git root folder name → cwd folder name. Tags are the declared ones plus
 * the stack implied by manifest files at the root (package.json → node, pyproject.toml → python, …).
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { GLOBAL, type Note } from "./notes.ts";
import { slug, tagList } from "./util.ts";

export interface Project {
  id: string;
  tags: string[];
  /** The git root (or cwd) the project was resolved from; null when set explicitly. */
  root: string | null;
}

export interface ProjectEntry {
  paths?: string[];
  remote?: string;
  tags?: string[];
  /** Other ids this project resolves from (a renamed repo, a fork, another folder name). */
  aliases?: string[];
}

/** Comparable path: forward slashes, no trailing slash, case-folded for Windows paths. */
export function normalizePath(value: string): string {
  const text = value.trim();
  if (/^[A-Za-z]:[\\/]/.test(text) || text.includes("\\")) {
    return text.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  }
  return text.replace(/\/+$/, "") || "/";
}

/** `git@github.com:o/r.git` / `https://user@github.com/o/r` → `github.com/o/r`. */
export function normalizeRemote(url: string): string {
  let text = url.trim();
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

/**
 * projects.json, with every key and alias slugged the way derived ids are — so all ways of naming
 * a project agree, and no synced key can point notes/ or work/ outside the home.
 */
export function loadProjects(home: string): Record<string, ProjectEntry> {
  let raw: unknown;
  try {
    raw = (JSON.parse(readFileSync(join(home, "projects.json"), "utf8")) as { projects?: unknown } | null)?.projects;
  } catch {
    return {};
  }
  if (!raw || typeof raw !== "object") return {};
  const projects: Record<string, ProjectEntry> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== "object") continue;
    const entry = value as ProjectEntry;
    const aliases = Array.isArray(entry.aliases) ? entry.aliases.filter((a): a is string => typeof a === "string").map(slug) : undefined;
    projects[slug(key)] = { ...entry, ...(aliases ? { aliases } : {}) };
  }
  return projects;
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

/** The `origin` URL of the repository at `root`, read from git config without running git. */
export function gitRemote(root: string): string | null {
  try {
    const dotgit = join(root, ".git");
    let gitdir = dotgit;
    if (statSync(dotgit).isFile()) {
      const target = readFileSync(dotgit, "utf8").split("gitdir:")[1]?.trim();
      if (!target) return null;
      gitdir = resolve(root, target);
      const common = join(gitdir, "commondir");
      if (existsSync(common)) gitdir = resolve(gitdir, readFileSync(common, "utf8").trim());
    }
    const config = readFileSync(join(gitdir, "config"), "utf8");
    const section = /\[remote "origin"\]([\s\S]*?)(?:\n\[|$)/.exec(config);
    const url = section ? /^\s*url\s*=\s*(.+)$/m.exec(section[1] ?? "") : null;
    return url?.[1]?.trim() ?? null;
  } catch {
    return null;
  }
}

/** Stack tags implied by files at the project root, so shared notes and kits find projects without setup. */
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
function canonical(projects: Record<string, ProjectEntry>, derived: string): string {
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
 * can never leave notes/ or work/ — and mapped through aliases.
 */
export function projectById(home: string, id: string, cwd: string): Project {
  const projects = loadProjects(home);
  const derived = slug(id);
  const canonicalId = canonical(projects, derived === GLOBAL ? "global-project" : derived);
  const root = gitRoot(cwd);
  return { id: canonicalId, tags: tagsOf(projects[canonicalId], root), root };
}

export function resolveProject(home: string, cwd: string, env: NodeJS.ProcessEnv = process.env): Project {
  const projects = loadProjects(home);
  const explicit = env.BRAIN_PROJECT?.trim();
  if (explicit) return projectById(home, explicit, cwd);

  const here = normalizePath(resolve(cwd));
  let best: { len: number; id: string } | null = null;
  for (const [id, entry] of Object.entries(projects)) {
    for (const declared of Array.isArray(entry.paths) ? entry.paths : []) {
      if (typeof declared !== "string" || !declared.trim()) continue;
      const root = normalizePath(declared);
      if ((here === root || here.startsWith(root + "/")) && (!best || root.length > best.len)) {
        best = { len: root.length, id };
      }
    }
  }
  const root = gitRoot(cwd);
  if (best) return { id: best.id, tags: tagsOf(projects[best.id], root ?? resolve(cwd)), root: root ?? resolve(cwd) };

  const remote = root ? gitRemote(root) : null;
  if (remote) {
    const key = normalizeRemote(remote);
    for (const [id, entry] of Object.entries(projects)) {
      if (typeof entry.remote === "string" && sameRepo(normalizeRemote(entry.remote), key)) {
        return { id, tags: tagsOf(entry, root), root };
      }
    }
    const derived = slug(key.split("/").pop() ?? "");
    const id = canonical(projects, derived === GLOBAL ? "global-project" : derived);
    return { id, tags: tagsOf(projects[id], root), root };
  }
  const derived = slug(basename(root ?? resolve(cwd)));
  const id = canonical(projects, derived === GLOBAL ? "global-project" : derived);
  return { id, tags: tagsOf(projects[id], root ?? resolve(cwd)), root: root ?? resolve(cwd) };
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
