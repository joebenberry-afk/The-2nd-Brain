/**
 * Which project a working directory belongs to. No registration is needed: the id falls out of
 * the git remote or the repository folder. `projects.json` in the Brain home is optional and only
 * adds aliases (extra paths, a remote) and tags:
 *
 *   { "projects": { "second-brain": { "paths": ["C:/work/brain"], "remote": "github.com/o/r",
 *                                     "tags": ["typescript", "omp"] } } }
 *
 * Resolution: BRAIN_PROJECT → projects.json path (longest prefix) → projects.json remote →
 * git remote repo name → git root folder name → cwd folder name.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { GLOBAL, type Note } from "./notes.ts";
import { slug } from "./util.ts";

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

export function loadProjects(home: string): Record<string, ProjectEntry> {
  try {
    const data: unknown = JSON.parse(readFileSync(join(home, "projects.json"), "utf8"));
    const projects = (data as { projects?: unknown })?.projects;
    return projects && typeof projects === "object" ? (projects as Record<string, ProjectEntry>) : {};
  } catch {
    return {};
  }
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

function tagsOf(entry: ProjectEntry | undefined): string[] {
  return Array.isArray(entry?.tags) ? entry.tags.filter((t): t is string => typeof t === "string") : [];
}

export function resolveProject(home: string, cwd: string, env: NodeJS.ProcessEnv = process.env): Project {
  const projects = loadProjects(home);
  const explicit = env.BRAIN_PROJECT?.trim();
  if (explicit) return { id: explicit, tags: tagsOf(projects[explicit]), root: null };

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
  if (best) return { id: best.id, tags: tagsOf(projects[best.id]), root: root ?? resolve(cwd) };

  const remote = root ? gitRemote(root) : null;
  if (remote) {
    const key = normalizeRemote(remote);
    for (const [id, entry] of Object.entries(projects)) {
      if (typeof entry.remote === "string" && sameRepo(normalizeRemote(entry.remote), key)) {
        return { id, tags: tagsOf(entry), root };
      }
    }
    const name = key.split("/").pop() ?? "";
    const id = slug(name);
    return { id: id === GLOBAL ? "global-project" : id, tags: tagsOf(projects[id]), root };
  }
  const id = slug(basename(root ?? resolve(cwd)));
  return { id: id === GLOBAL ? "global-project" : id, tags: tagsOf(projects[id]), root: root ?? resolve(cwd) };
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
