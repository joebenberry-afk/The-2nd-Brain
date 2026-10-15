/** "Did you mean": the closest existing paths after a read/edit/search names one that is missing. */
import { existsSync, readdirSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { cutToTokens } from "./util.ts";
import { FIX_BUDGET } from "./capture.ts";

/** Tools that take a path; bash is left out (its paths sit inside a command). */
const PATH_TOOL = /^(?:read|edit|write|grep|glob|find|ast_grep|ast_edit|lsp|Read|Edit|MultiEdit|NotebookEdit|Grep|Glob|LS)$/;
// Path errors only: "String to replace not found in file" names a file that exists.
const MISSING = /\bpath\b[^\n]*\bnot found\b|^not found:|file not found|does not exist|no such file|ENOENT/im;
const SKIP_DIRS: Record<string, true> = { node_modules: true, target: true, dist: true, build: true, out: true, __pycache__: true, venv: true, "site-packages": true };
const MAX_FILES = 20_000;
const MAX_DIRS = 2_000;
// Git and the walk share this wall-clock budget. The hint is only a courtesy, and it runs inside the
// host's tool_result: a listing that took 7-25 s froze the whole host, not just one call.
const LIST_MS = 150;
const CACHE_MS = 60_000;

const listCache = new Map<string, { at: number; files: string[] }>();

/** Whether `path` is `base` or lies below it. */
function within(base: string, path: string): boolean {
  const rel = relative(base, path);
  return !/^\.\.(?:[\\/]|$)/.test(rel) && !isAbsolute(rel);
}

/** A drive root, or the home or temp folder or a parent of one: listing it lists the machine, not a project. */
function machineWide(root: string): boolean {
  if (dirname(root) === root || within(root, tmpdir())) return true;
  try { return within(root, homedir()); } catch { return false; } // no home folder: nothing to protect
}

/**
 * Files under `root`, relative with forward slashes: Git's view when there is one, else a walk.
 * Both stop at `budgetMs`; a listing cut short is kept (and cached) as it is.
 */
function listFiles(root: string, budgetMs: number): string[] {
  const cached = listCache.get(root);
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.files;
  const deadline = performance.now() + budgetMs;
  let files: string[] | undefined;
  if (budgetMs > 0) {
    const git = spawnSync("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], { cwd: root, encoding: "utf8", timeout: Math.ceil(budgetMs), maxBuffer: 16 * 1024 * 1024, windowsHide: true });
    // A listing cut off by the timeout or the buffer still holds whole paths up to its last NUL.
    const listed = git.stdout ? git.stdout.slice(0, git.stdout.lastIndexOf("\0") + 1) : "";
    if (git.status === 0 || listed) files = listed.split("\0").filter(Boolean).slice(0, MAX_FILES);
  }
  if (!files) {
    files = [];
    const queue = [""];
    // Directories count however empty they are, so a tree of folders alone is bounded too.
    for (let at = 0; at < queue.length && at < MAX_DIRS && files.length < MAX_FILES && performance.now() < deadline; at++) {
      const dir = queue[at]!;
      let entries;
      try { entries = readdirSync(join(root, dir), { withFileTypes: true }); } catch { continue; }
      for (const entry of entries) {
        const rel = dir ? `${dir}/${entry.name}` : entry.name;
        if (entry.isDirectory()) {
          if (!entry.name.startsWith(".") && SKIP_DIRS[entry.name] !== true) queue.push(rel);
        } else if (files.push(rel) >= MAX_FILES) break;
      }
    }
  }
  listCache.set(root, { at: Date.now(), files });
  return files;
}

function distance(a: string, b: string): number {
  if (Math.abs(a.length - b.length) > 3) return 99;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) row[j] = Math.min(prev[j]! + 1, row[j - 1]! + 1, prev[j - 1]! + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = row;
  }
  return prev[b.length]!;
}

const stem = (name: string) => name.replace(/\.[^.]+$/, "");

/**
 * How much `candidate` looks like the missing path; 0 when it does not. Replayed on 14 days of
 * real misses, substring matches and deep look-alikes in unrelated folders (a cached tldr page for
 * CLAUDE.md) were noise, so a candidate needs a close name and at most three folders the missing
 * path does not share.
 */
function score(wantName: string, wantDirs: string[], candidate: string): number {
  const parts = candidate.toLowerCase().split("/");
  const name = parts.pop()!;
  const shared = parts.filter(part => wantDirs.includes(part)).length;
  if (parts.length - shared > 3) return 0;
  let base: number;
  if (name === wantName) base = 100;
  else if (stem(name) === stem(wantName) && stem(wantName).length >= 3) base = 70;
  else {
    const d = distance(name, wantName);
    if (d > Math.max(1, Math.floor(wantName.length / 6))) return 0;
    base = 60 - d * 10;
  }
  return base + shared * 5 - parts.length * 0.1;
}

/** The deepest part of `path` that exists. */
function existingAncestor(path: string): string {
  let current = path;
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) return current;
    current = parent;
  }
  return current;
}

const slash = (path: string) => path.replace(/\\/g, "/");

/**
 * A hint for a failed tool call that named a missing path: up to three similar existing paths, or
 * the entries of the deepest existing folder. Empty when the error is something else, the path
 * exists (a selector problem, which the fix notes cover), or nothing similar is found. The search
 * is best-effort within `listMs`: a large tree gives a partial listing, a machine-wide folder none.
 */
export function pathHint(tool: string, path: string | undefined, error: string | undefined, cwd: string, listMs = LIST_MS): string {
  if (!path || !error || !PATH_TOOL.test(tool) || !MISSING.test(error) || /^[a-z][\w+.-]*:\/\//i.test(path)) return "";
  // Read selectors (":50-80", ":raw") follow the file name; a drive colon sits in the first segment.
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  const clean = (path.slice(0, cut + 1) + path.slice(cut + 1).replace(/:.*$/, "")).replace(/[\\/]+$/, "");
  if (!clean) return "";
  const target = resolve(cwd, clean);
  if (existsSync(target)) return "";
  const inside = within(cwd, target);
  const anchor = existingAncestor(target);
  // Outside the working directory only a specific folder is searched, never a drive or home root.
  const root = inside ? cwd : anchor;
  if (!inside && slash(anchor).split("/").filter(Boolean).length < 4) return "";
  const files = machineWide(root) ? [] : listFiles(root, listMs);
  const dirs = new Set<string>();
  for (const file of files) for (let at = file.indexOf("/"); at > 0; at = file.indexOf("/", at + 1)) dirs.add(file.slice(0, at));
  const wantName = basename(clean).toLowerCase();
  const wantDirs = slash(relative(root, target)).toLowerCase().split("/").slice(0, -1);
  const ranked = [...files, ...dirs]
    .map(candidate => ({ candidate, score: score(wantName, wantDirs, candidate) }))
    .filter(item => item.score >= 30)
    .sort((a, b) => b.score - a.score || a.candidate.length - b.candidate.length)
    .slice(0, 3)
    .map(item => item.candidate + (dirs.has(item.candidate) ? "/" : ""));
  // Inside the working directory the search root is it, so candidates are already cwd-relative.
  if (ranked.length) return cutToTokens(`Brain: ${slash(clean)} does not exist; closest${inside ? "" : ` under ${slash(anchor)}/`}: ${ranked.join(", ")}`, FIX_BUDGET);

  // Nothing similar: what the deepest existing folder below the search root holds.
  if (anchor === root || !statSync(anchor, { throwIfNoEntry: false })?.isDirectory()) return "";
  let entries: string[];
  try { entries = readdirSync(anchor, { withFileTypes: true }).filter(e => !e.name.startsWith(".")).map(e => e.name + (e.isDirectory() ? "/" : "")).sort(); } catch { return ""; }
  if (!entries.length) return "";
  return cutToTokens(`Brain: ${slash(clean)} does not exist; ${slash(relative(cwd, anchor))}/ holds: ${entries.join(", ")}`, FIX_BUDGET);
}
