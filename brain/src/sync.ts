/** Git sync of the Brain home, and sharing a note across projects. */
import { spawnSync } from "node:child_process";
import { existsSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
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

  // Find the SYNC_PATHS that exist on disk
  const existingPaths: string[] = [];
  for (const path of SYNC_PATHS) {
    if (existsSync(join(home, path))) {
      existingPaths.push(path);
    }
  }

  // Build pathspecs with exclude for private notes
  const pathspecs = [...existingPaths, ":(exclude,glob)notes/*/private/**"];

  // Stage the files with pathspecs
  const addResult = spawnSync("git", ["-C", home, "add", "-A", "--", ...pathspecs], {
    encoding: "utf8",
  });
  if (addResult.status !== 0) {
    throw new SyncError(`Failed to stage files: ${addResult.stderr}`);
  }

  // Check if there are staged changes (check only the allowed paths)
  const diffResult = spawnSync("git", ["-C", home, "diff", "--cached", "--quiet", "--", ...pathspecs], {
    encoding: "utf8",
  });
  const hasChanges = diffResult.status !== 0;

  let committed = false;
  if (hasChanges) {
    // Write pathspecs to a temp file for git commit
    const tempFile = join(tmpdir(), `brain-pathspecs-${process.pid}-${Math.random().toString(16).slice(2)}`);
    const pathspecContent = pathspecs.join("\0");
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

  if (pullResult.status !== 0) {
    // On failure, abort the rebase
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
