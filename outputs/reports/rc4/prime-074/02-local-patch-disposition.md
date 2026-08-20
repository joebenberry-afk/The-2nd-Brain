# 02 — Local Patch Disposition (0.7.3 → 0.7.4)

## Method

Compared `packages/coding-agent/src/core/kernel/bootstrap.ts` and
`packages/coding-agent/src/core/session-lease.ts` between the real `v0.7.3`
and `v0.7.4` git tags directly (`git diff v0.7.3 v0.7.4 -- <files>`), then
verified our two local patches apply cleanly (`git apply --check`, then
`git apply`) against a real, isolated `v0.7.4` worktree
(`C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`, detached
at commit `af0b8e00b9f704e834787fd321065ca78281f2aa`,
`chore(release): prepare v0.7.4 (#1569)`).

## Result: `git diff v0.7.3 v0.7.4` for BOTH target files is EMPTY

Upstream made **zero changes** to either file between v0.7.3 and v0.7.4 —
these two files are byte-identical across both tags.

## Patch A — Windows virtualenv Python bootstrap path

- **0.7.3 reason**: `bootstrapVenv`/`ensureKernelPythonUncached` in
  `bootstrap.ts` hardcoded `path.join(venv, "bin", "python")` (POSIX-only);
  on Windows the real venv layout is `<venv>/Scripts/python.exe`. Also adds
  `windowsHide: process.platform === "win32"` to a bootstrap child-process
  spawn to suppress a console-window flash on Windows.
- **0.7.4 upstream behavior**: unchanged — `git show
  v0.7.4:.../bootstrap.ts | grep "bin.*python"` still shows the same two
  bare `path.join(venv, "bin", "python")` call sites, no `win32`/`Scripts`
  handling anywhere near them.
- **Still required?** **YES.**
- **Exact hunk (unchanged, reapplied verbatim)**: see
  `outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`
  (bootstrap.ts hunk).
- **Test evidence**: `git apply --check` against the real `v0.7.4` worktree
  returned exit 0 (clean, zero conflicts); `git apply` (not `--check`)
  applied the SAME diff successfully, confirmed via `git diff --stat`
  showing exactly the expected 2-file, +9/-2-line change in that isolated
  worktree.

## Patch B — session lease EPERM handling (Windows)

- **0.7.3 reason**: `acquireSessionLease` in `session-lease.ts` only
  treated `EEXIST`/`ENOTEMPTY` as a recoverable existing-lease-directory
  conflict when `renameSync` fails; on Windows, a still-locked/racing
  directory can surface as `EPERM` instead, which was previously
  (incorrectly) treated as a hard, unrecoverable error.
- **0.7.4 upstream behavior**: unchanged — the same
  `if (code !== "EEXIST" && code !== "ENOTEMPTY") { throw error; }` line
  is present verbatim in `v0.7.4`'s `session-lease.ts` at the equivalent
  location. (A DIFFERENT, unrelated `EPERM` check exists elsewhere in the
  same file — `isProcessAlive()`'s POSIX `process.kill(pid, 0)` liveness
  probe — that is not the lease-directory-rename path this patch targets,
  and was not touched by this patch in 0.7.3 either.)
- **Still required?** **YES.**
- **Exact hunk (unchanged, reapplied verbatim)**: see
  `outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`
  (session-lease.ts hunk).
- **Test evidence**: same `git apply --check`/`git apply` verification as
  Patch A, in the same isolated `v0.7.4` worktree — clean, zero conflicts.

## Disposition summary

Both local Windows patches remain necessary on 0.7.4 (upstream did not fix
either regression) and both are cleanly, mechanically reapplicable with
zero merge conflicts — no manual rebasing or adaptation was needed. The
isolated `v0.7.4` worktree now carries both patches applied
(`git status --short` shows exactly the same 2 modified files as the known
0.7.3 baseline), ready for the build/qualification steps that follow.
