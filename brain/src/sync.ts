/** Git sync of the Brain home, and sharing a note across projects. */
import { spawnSync } from "node:child_process";
import { existsSync, writeFileSync, rmSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { hostname, tmpdir } from "node:os";
import { findNote, loadNotes, saveNote, type Note, GLOBAL } from "./notes.ts";
import { nowIso, slug } from "./util.ts";

export class SyncError extends Error {}

export const SYNC_PATHS = ["notes", "kits", "work", "projects.json"] as const;

export interface SyncResult {
  committed: boolean;
  pulled: boolean;
  pushed: boolean;
  message: string;
}

export function sync(home: string, opts?: { message?: string; push?: boolean }): SyncResult {
  // Check if it's a git repository
  const result = spawnSync("git", ["-C", home, "rev-parse", "--git-dir"], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new SyncError(`${home} is not a git repository`);
  }

  // The SYNC_PATHS that exist on disk or are tracked (so deleting all of notes/ is committed too)
  const existingPaths: string[] = [];
  for (const path of SYNC_PATHS) {
    const tracked = spawnSync("git", ["-C", home, "ls-files", "-z", "--", path], { encoding: "utf8" }).stdout;
    if (existsSync(join(home, path)) || tracked) existingPaths.push(path);
  }

  // Build pathspecs with exclude for private notes. With no Brain path on disk there is nothing to
  // commit — and an exclude-only pathspec would mean "everything else", so it is never used.
  const pathspecs = [...existingPaths, ":(exclude,glob)notes/*/private/**"];
  const stage = existingPaths.length > 0;

  let hasChanges = false;
  if (stage) {
    const addResult = spawnSync("git", ["-C", home, "add", "-A", "--", ...pathspecs], { encoding: "utf8" });
    if (addResult.status !== 0) throw new SyncError(`Failed to stage files: ${addResult.stderr}`);
    // Staged changes within the Brain paths only
    const diffResult = spawnSync("git", ["-C", home, "diff", "--cached", "--quiet", "--", ...pathspecs], { encoding: "utf8" });
    hasChanges = diffResult.status === 1;
    if (diffResult.status !== 0 && diffResult.status !== 1) throw new SyncError(`git diff failed: ${diffResult.stderr}`);
  }

  let committed = false;
  if (hasChanges) {
    // Write pathspecs to a temp file for git commit
    const tempFile = join(tmpdir(), `brain-pathspecs-${process.pid}-${Math.random().toString(16).slice(2)}`);
    // Exactly the staged Brain files: a directory with no tracked file (notes/ holding only
    // private notes, an empty kits/) would make git reject the whole pathspec.
    const staged = spawnSync("git", ["-C", home, "diff", "--cached", "--name-only", "--relative", "-z", "--", ...pathspecs], { encoding: "utf8" });
    const pathspecContent = staged.stdout.split("\0").filter(Boolean).map((f) => `:(literal)${f}`).join("\0");
    writeFileSync(tempFile, pathspecContent);

    try {
      const message = opts?.message || `brain: sync ${hostname()} ${nowIso()}`;
      const commitResult = spawnSync(
        "git",
        [
          "-C",
          home,
          "commit",
          "--pathspec-from-file",
          tempFile,
          "--pathspec-file-nul",
          "-m",
          message,
        ],
        { encoding: "utf8" },
      );
      if (commitResult.status !== 0) {
        throw new SyncError(`Failed to commit: ${commitResult.stderr}`);
      }
      committed = true;
    } finally {
      // Clean up temp file
      try {
        rmSync(tempFile, { force: true });
      } catch {
        // Ignore cleanup errors
      }
    }
  }

  // Get the upstream branch
  const upstreamResult = spawnSync(
    "git",
    ["-C", home, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
    { encoding: "utf8" },
  );

  const upstream = upstreamResult.stdout.trim();
  let pulled = false;
  let pushed = false;

  if (!upstream || upstream === "@{u}") {
    // No upstream branch
    const message = committed ? "committed locally; no upstream branch" : "nothing to sync; no upstream branch";
    return {
      committed,
      pulled,
      pushed,
      message,
    };
  }

  // Pull with rebase
  const pullResult = spawnSync("git", ["-C", home, "pull", "--rebase", "--autostash"], {
    encoding: "utf8",
  });

  if (pullResult.status !== 0 && !(rebaseInProgress(home) && resolveWorkConflicts(home))) {
    spawnSync("git", ["-C", home, "rebase", "--abort"], { encoding: "utf8" });
    throw new SyncError(pullResult.stderr.slice(0, 500));
  }
  pulled = true;

  // Push if not disabled
  if (opts?.push !== false) {
    const slash = upstream.indexOf("/");
    const remote = slash > 0 ? upstream.slice(0, slash) : "";
    const branch = slash > 0 ? upstream.slice(slash + 1) : "";
    if (!remote || !branch) {
      throw new SyncError(`Cannot parse upstream: ${upstream}`);
    }

    const pushResult = spawnSync("git", ["-C", home, "push", remote, `HEAD:${branch}`], {
      encoding: "utf8",
    });
    if (pushResult.status !== 0) {
      throw new SyncError(pushResult.stderr);
    }
    pushed = true;
  }

  // Build the message
  const parts: string[] = [];
  if (committed) parts.push("committed");
  if (pulled) parts.push("pulled");
  if (pushed) parts.push("pushed");
  const message = parts.length > 0 ? parts.join(", ") : "nothing to sync";

  return { committed, pulled, pushed, message };
}

function git(home: string, ...args: string[]): { status: number | null; stdout: string } {
  const r = spawnSync("git", ["-C", home, ...args], { encoding: "utf8", env: { ...process.env, GIT_EDITOR: "true" } });
  return { status: r.status, stdout: r.stdout ?? "" };
}

function rebaseInProgress(home: string): boolean {
  return ["rebase-merge", "rebase-apply"].some((name) => {
    const path = git(home, "rev-parse", "--git-path", name).stdout.trim();
    return path !== "" && existsSync(isAbsolute(path) ? path : join(home, path));
  });
}

/** A working state's recency: the plan's `at:` first, the auto section's `auto_at:` second. */
function stampOf(text: string): string {
  return `${/^at:\s*(\S+)/m.exec(text)?.[1] ?? ""} ${/^auto_at:\s*(\S+)/m.exec(text)?.[1] ?? ""}`;
}

/**
 * A rebase stopped only on working-state files (work/*.md) is resolved, not aborted: a working
 * state is a snapshot, so the side with the newer `at` wins. Any other conflict → false.
 */
function resolveWorkConflicts(home: string): boolean {
  for (let round = 0; round < 50 && rebaseInProgress(home); round++) {
    // Paths relative to the home, which may be a subdirectory of the repository
    const conflicted = git(home, "diff", "--name-only", "--relative", "--diff-filter=U").stdout.split("\n").filter(Boolean);
    if (!conflicted.length || !conflicted.every((f) => f.startsWith("work/"))) return false;
    for (const file of conflicted) {
      const upstream = git(home, "show", `:2:./${file}`);
      const local = git(home, "show", `:3:./${file}`);
      const keep =
        upstream.status !== 0 ? local.stdout : local.status !== 0 ? upstream.stdout : stampOf(local.stdout) > stampOf(upstream.stdout) ? local.stdout : upstream.stdout;
      writeFileSync(join(home, file), keep);
      git(home, "add", "--", file);
    }
    git(home, "rebase", "--continue");
  }
  return !rebaseInProgress(home);
}

export function shareNote(home: string, id: string, tag: string): Note {
  const { notes } = loadNotes(home);
  const note = findNote(notes, id);

  if (!note) {
    throw new SyncError(`unknown note ${id}`);
  }

  if (note.private) {
    throw new SyncError("private notes cannot be shared");
  }

  if (note.retired) {
    throw new SyncError("retired notes cannot be shared");
  }

  const normalizedTag = slug(tag);
  let updated = note;

  // If the note is project-scoped, move it to global
  if (note.project !== GLOBAL) {
    updated = {
      ...note,
      project: GLOBAL,
    };
  }

  // Add the tag if not already present
  if (!updated.tags.includes(normalizedTag)) {
    updated = {
      ...updated,
      tags: [...updated.tags, normalizedTag].sort(),
    };
  }

  return saveNote(home, updated);
}
