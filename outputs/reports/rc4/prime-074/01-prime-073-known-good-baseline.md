# 01 — Prime 0.7.3 Known-Good Baseline (Rollback Reference)

## Installation type

Git checkout at `C:\Tools\prime-agent`, npm workspace (not an npm-registry
global install). Remote: `origin =
https://github.com/PrimeIntellect-ai/prime-agent.git`.

## Exact version identity

- `git describe --tags` -> `v0.7.3` (clean tag match, HEAD is exactly the
  v0.7.3 release commit).
- `git rev-parse HEAD` -> `61131b2d195ba7a67a4ce8ac60bb10cecae07b67`
  (`chore(release): prepare v0.7.3 (#1492)`).
- `git branch --show-current` -> (working tree checked out directly at this
  commit; no named local branch was created for 0.7.3 prior to this
  qualification pass — the tag/SHA above is the unambiguous anchor).
- `package.json` / `packages/coding-agent/package.json` `"version"` field:
  `0.7.3`.
- Runtime env identity: `PRIME_AGENT_BUILD_ID=v0.7.3-dirty` (the `-dirty`
  suffix reflects the two known local Windows patches below, not an
  unknown/unverified build).

## Local working-tree modifications on top of v0.7.3 (uncommitted)

Exactly two files, both narrow Windows-compatibility patches (full hunks
preserved verbatim below and in
`outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff` for exact
reapplication):

### Patch A — Windows kernel-venv Python bootstrap path
`packages/coding-agent/src/core/kernel/bootstrap.ts`:
- adds `windowsHide: process.platform === "win32"` to the kernel bootstrap
  child-process spawn options,
- adds a `kernelPythonPath(venv)` helper that resolves to
  `<venv>/Scripts/python.exe` on `win32`, `<venv>/bin/python` elsewhere,
  replacing two previously POSIX-only `path.join(venv, "bin", "python")`
  call sites (`bootstrapVenv`, `ensureKernelPythonUncached`).

### Patch B — session lease EPERM handling (Windows)
`packages/coding-agent/src/core/session-lease.ts`:
- extends the existing-lease-conflict detection in `acquireSessionLease`
  to also treat `EPERM` as a conflict (not a hard failure) specifically
  when `process.platform === "win32"` AND the target directory already
  exists — previously only `EEXIST`/`ENOTEMPTY` were treated as
  recoverable conflicts, which is insufficient on Windows where a
  still-locked/racing directory can surface as `EPERM` instead.

Neither patch has been committed to the Prime repo; both are uncommitted
working-tree diffs on top of the exact `v0.7.3` tag commit.

## Package manager / lockfile state

- npm workspaces (`packages/*` plus 4 extension-example workspaces).
- `package-lock.json` `lockfileVersion: 3`, root package `prime-agent@0.7.3`,
  `@earendil-works/pi-coding-agent@^0.7.3` pinned.
- No changes to `package-lock.json`/`package.json` beyond the two `.ts`
  source patches above.

## Toolchain versions (this machine, at baseline)

- Node: `v26.7.0`
- npm: `11.19.0`
- Python (kernel venv, Second Brain side): the repo's own `.venv` under
  `The-Second-Brain\.venv\Scripts\python.exe`, Python 3.13.7 (from prior
  pilot evidence: `platform win32 -- Python 3.13.7, pytest-9.1.1`).

## Global install / extension sync location

- Global extension discovery directory (unchanged across this whole
  qualification campaign): `C:\Users\assas\.prime\agent\extensions\second-brain\`
  (plain file copy, not a symlink — synced manually from
  `brainstem/prime-extension/src/` before each pilot).
- Global agent dir: `C:\Users\assas\.prime\agent` (env
  `PRIME_AGENT_CODING_AGENT_DIR`).
- jiti TS-transpile cache: `%TEMP%/jiti` (cleared before each pilot sync).

## Relevant environment variable NAMES (values never recorded)

`PRIME_AGENT_BUILD_ID`, `PRIME_AGENT_LAUNCHER_PATH`,
`PRIME_AGENT_CODING_AGENT_DIR`, `PRIME_AGENT_INTERNAL_SESSION_LEASES`,
`PRIME_AGENT_INTERNAL_DAEMON_WORKER`,
`PRIME_AGENT_INTERNAL_DAEMON_WORKER_TOKEN`,
`PRIME_AGENT_INTERNAL_DAEMON_WORKER_ACTIVE_SESSION_ID`,
`PRIME_AGENT_INTERNAL_DAEMON_WORKER_RECOVERY_JOURNAL`,
`PRIME_AGENT_INTERNAL_ORPHAN_PROCESS_JOURNAL`,
`PRIME_AGENT_INTERNAL_SESSION_LEASE_OWNER_ID`,
`PRIME_AGENT_INTERNAL_DAEMON_SUPERVISOR_SOCKET`, `SECOND_BRAIN_HOME`,
`RLM_DEPTH`, `RLM_MAX_DEPTH`, `RLM_SESSION_DIR`,
`RLM_GLOBAL_HARNESS_STATE_DIR`, `RLM_HARNESS_STATE_DIR`.

## Critical operational constraint discovered during this qualification pass

**The live `C:\Tools\prime-agent` installation is the SAME installation
currently executing the active Prime Agent daemon that is running this
very orchestration session** (confirmed via `PRIME_AGENT_LAUNCHER_PATH`
pointing at this checkout, and `PRIME_AGENT_INTERNAL_DAEMON_WORKER=1`
identifying this session as a daemon worker of that same install). This
means:

- The 0.7.3 -> 0.7.4 upgrade **must not be performed by mutating this live
  checkout in place** while it is actively serving this (or any other
  concurrent) session — doing so risks interrupting the daemon supervisor,
  other concurrent sessions/workers sharing it, and this qualification
  session itself.
- **Rollback procedure (executable)**: from a clean shell with no active
  daemon workers depending on the checkout, `cd C:\Tools\prime-agent`,
  `git checkout 61131b2d195ba7a67a4ce8ac60bb10cecae07b67` (or `git checkout
  v0.7.3`), then reapply Patch A and Patch B exactly as recorded above
  (`git apply outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`
  from the Second Brain repo, or manually reapply the two hunks), then
  restart the daemon through its normal supervised restart path. This has
  NOT been destructively tested against the live daemon in this pass (see
  Section 20 disposition) to avoid interrupting active sessions; the exact
  commit/tag and patch diffs ARE independently verified present and
  resolvable right now, which is the load-bearing rollback guarantee.
- Given this constraint, the actual 0.7.4 upgrade-and-compatibility-test
  work in this qualification MUST use an **isolated clone/worktree** of
  the Prime Agent repository, built and run independently of the live
  daemon, rather than mutating `C:\Tools\prime-agent` in place. See the
  isolation plan recorded in this same `prime-074/` report set.
