# RLM_EPERM_REPRO.md

## Method (fully isolated, zero live-daemon contact)

The prior external review's failure was reported as:

```
Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink
'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
```

occurring while spawning a fresh RLM sub-agent from the live 0.7.3 driver session, with
the reviewing session's own kernel (which uses that exact shared file as its own running
interpreter) identified as the one process holding the file open.

Per the user's directive, this pass did NOT touch the live shared kernel-venv
(`C:\Users\assas\.prime\agent\kernel-venv`) to test this. Instead, the exact same code
path was exercised end-to-end against a fully isolated, disposable copy of the Prime
bootstrap mechanism:

1. Source: the pre-existing disposable `throwaway-073` worktree
   (`C:\Users\assas\.prime-074-compat\throwaway-073`, exact v0.7.3 commit
   `61131b2d195ba7a67a4ce8ac60bb10cecae07b67`, `node_modules` already installed from a
   prior pass) and the pre-existing isolated `prime-074` candidate worktree
   (`C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`, exact v0.7.4 commit
   `af0b8e00b9f704e834787fd321065ca78281f2aa`). Both had the two known local Windows
   patches applied (`outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`,
   `git apply --check` verified clean before applying).
2. Scratch kernel-venv locations, entirely outside `~/.prime/agent`:
   `C:\Users\assas\.prime-eperm-repro\venvA` (for the 0.7.3 worktree) and
   `...\venvB` (for the 0.7.4 worktree), selected via the real
   `PRIME_AGENT_KERNEL_VENV` env-var override that `bootstrap.ts`'s own
   `getKernelVenvDir()` honors (`packages/coding-agent/src/core/kernel/bootstrap.ts`).
3. The REAL Prime bootstrap entrypoint was invoked directly and unmodified via
   `node_modules/.bin/tsx packages/coding-agent/src/core/kernel/bootstrap-cli.ts`,
   which calls the exact same exported `ensureKernelPython()` the live daemon calls
   on every kernel/child spawn. No source files were edited to run this test; only the
   pre-existing local Windows patches (identical to what live/candidate run) were
   applied, exactly as documented in the prior review.

## Step-by-step repro (v0.7.3, `throwaway-073` + patches, `venvA`)

1. Fresh bootstrap of `venvA` from a clean, unmutated worktree -> succeeded
   (`✓ ready`, `kernel python: ...\venvA\Scripts\python.exe`).
2. Spawned `venvA\Scripts\python.exe -c "import time; time.sleep(300)"` as a real,
   independent background process (PID 46748) -- this simulates "a kernel is currently
   running from this venv", the exact condition the prior review found live. Verified via
   `Get-CimInstance Win32_Process` that the process was alive and running from that exact
   file.
3. Appended one comment line to `prime-agent-runtime/pyproject.toml` in the worktree --
   this is a legitimate, minimal content change to the file that
   `resolveRuntimeIdentity()` hashes into the venv's recorded identity
   (`bootstrap.ts`, `hashRuntimeSource()` explicitly hashes `pyproject.toml` plus every
   `.py` file under `src/rlm/`), simulating any real one-time drift between when a
   long-lived kernel was bootstrapped and when a later spawn recomputes the identity.
4. Re-ran `bootstrap-cli.ts` against the SAME `venvA`, holder process (2) still alive.

Result -- 3/3 deterministic reproductions, byte-identical to the reported failure:

```
› setting up python kernel (one-time, ~30s)…
rebuilding kernel venv
Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink
'C:\Users\assas\.prime-eperm-repro\venvA\Scripts\python.exe'
```

(raw logs: `raw/step2-collision-attempt-1.log` .. `-3.log`, copied from
`C:\Users\assas\.prime-eperm-repro\logs\step2-*.log`)

## Negative control (causality proof)

Killed the holder process (PID 46748, confirmed terminated and confirmed no other
process referenced `venvA` via `Get-CimInstance`), mutated `pyproject.toml` again the
same way, re-ran the identical `bootstrap-cli.ts` command against the identical `venvA`
(still in its "identity now stale" state from step 3/4 above):

```
› setting up python kernel (one-time, ~30s)…
rebuilding kernel venv
✓ ready
kernel python: C:\Users\assas\.prime-eperm-repro\venvA\Scripts\python.exe
```

Same "rebuilding kernel venv" (destructive `rm()`) code path, same identity-mismatch
trigger, only difference is no other process held the file open -> clean success. This
isolates the causal variable precisely: the destructive rebuild itself is fine; the
EPERM occurs if and only if another live process currently has `Scripts\python.exe`
open at the moment of `rm()`.

## Step-by-step repro (v0.7.4 candidate, `prime-074` + patches, `venvB`)

Repeated the identical procedure (fresh build -> spawn holder -> mutate
`prime-agent-runtime/pyproject.toml` -> re-run) against the isolated v0.7.4 candidate
worktree and a separate scratch venv (`venvB`). Result: 3/3 identical failures,
byte-identical error text (only the venv path differs):

```
rebuilding kernel venv
Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink
'C:\Users\assas\.prime-eperm-repro\venvB\Scripts\python.exe'
```

(raw logs: `raw/074-collision-1.log` .. `-3.log`)

## Cleanup performed

- Both holder processes killed.
- `prime-agent-runtime/pyproject.toml` reverted (`git checkout --`) in both worktrees;
  both worktrees left in their canonical patched-only state
  (`git status --short` shows only the 2 known Windows patch files modified, matching
  the prior review's baseline for these directories).
- Scratch venvs (`venvA`, `venvB`) left under `C:\Users\assas\.prime-eperm-repro\` for
  inspection; not inside `~/.prime/agent`; no live path touched.
- The live shared kernel-venv (`C:\Users\assas\.prime\agent\kernel-venv`) was never
  written to, deleted from, or otherwise touched by this reproduction.

## Whether it occurs before or after "child process creation"

It occurs during kernel/interpreter *provisioning*, before any RLM child task code
would ever run -- specifically inside `ensureKernelPythonUncached()`'s destructive
`rm(venv, { recursive: true, force: true })` call
(`packages/coding-agent/src/core/kernel/bootstrap.ts`), which fires when the requesting
process's freshly-recomputed runtime/schema identity does not match the venv's recorded
`.bootstrap-version`. This is upstream of any Second Brain code, upstream of any
RLM task payload, and upstream of the daemon's own child-process spawn machinery for the
task itself -- it is purely a Node `fs.rm` racing a live Windows file handle.
