# RLM_ROOT_CAUSE.md

## 1. What exact operation failed?

`fs.promises.rm(venv, { recursive: true, force: true })` inside
`ensureKernelPythonUncached()` in
`packages/coding-agent/src/core/kernel/bootstrap.ts` (both the live 0.7.3+patches tree
and the isolated 0.7.4-candidate+patches tree -- the file is byte-identical between the
two, confirmed via `diff`, zero output). Specifically the recursive delete fails to
unlink one file: `<kernel-venv>\Scripts\python.exe`.

## 2. Why did Windows return EPERM?

Because a second, independent, currently-running process has that exact file open as
its own executing interpreter image. Windows does not allow unlinking (or, in general,
exclusively opening for delete) a `.exe` file that is the running image of a live
process, unless that process explicitly opened itself with `FILE_SHARE_DELETE` (Python's
own `python.exe`/CPython launcher does not). `node:fs`'s `rm()` on Windows surfaces this
as `EPERM: operation not permitted, unlink '<path>'`, exactly the observed and
reproduced error text.

## 3. Why did it happen in the tested environment?

`ensureKernelPythonUncached()` recomputes a "runtime identity" (a content hash of
`prime-agent-runtime/pyproject.toml` + every `.py` file under `prime-agent-runtime/src/
rlm/`, via `resolveRuntimeIdentity()`/`hashRuntimeSource()`) on every single call,
including every fresh RLM child spawn. If that freshly recomputed identity (or the
fixed schema/ipykernel/snapshot/extra-uv-args/pythonSkills fields) does not match what
is recorded in the venv's own `.bootstrap-version` file, the code treats the venv as
stale and unconditionally wipes it (`rm(venv, {recursive:true, force:true})`) before
rebuilding from scratch. This "wipe and rebuild" logic makes NO check for whether
another live process (e.g. an already-running driver/child kernel that is itself using
that exact venv) currently has any file inside `venv` open. If one does -- as this
session's own driver kernel does, continuously, for the live shared venv -- the wipe
fails partway through on that one locked file.

Isolated reproduction (`RLM_EPERM_REPRO.md`) proved this exact mechanism directly: with
a real background process holding `Scripts\python.exe` open, an identity-mismatch
rebuild fails 3/3 with the exact reported error; with the same mutation but no holder,
it succeeds cleanly every time.

A secondary, compounding effect (consistent with, but not independently re-triggered in
this pass, the prior review's own field observation that the wedged venv contained
*only* `python.exe` -- no `Lib/`, no `pyvenv.cfg`, no `.bootstrap-version`): `fs.rm`'s
recursive delete removes a directory tree bottom-up/best-effort; when it hits the one
locked file it throws, but files/directories already deleted before that point stay
deleted. This leaves the venv in a half-wiped, permanently "not ready" state
(`hasIpykernel()`/`kernelReady()` will now fail immediately, since `Lib/site-packages`
is gone) -- so every subsequent spawn attempt re-enters the same
`hadVenv -> rebuilding -> rm() -> EPERM` path again, reproducing the failure
deterministically (3/3, not flaky) for as long as the original holder process (e.g. a
long-lived driver session's own kernel) remains alive. Once that holder process exits
and releases the handle, the next attempt's `rm()` succeeds and the venv self-heals --
consistent with the live install being observed in a fully healthy, fully-populated
state during this very pass (`STARTING_STATE.md`), despite the prior review having hit
the wedged failure days earlier in the same install.

## 4. Is the cause:

- [ ] Prime source bug in the sense of "wrong output" -- no
- [x] **Prime source bug in the sense of an unsafe concurrency/TOCTOU assumption**:
  yes -- `ensureKernelPythonUncached()`'s rebuild path assumes it has exclusive,
  uncontended access to the venv directory it is about to delete, with no detection of,
  or backoff/retry around, another live process's open handle on a file inside it.
- [ ] local Windows patch issue -- no; both local Windows patches
  (`bootstrap.ts` Scripts/python.exe path fix, `session-lease.ts` EPERM-as-lease-
  conflict handling) are present, correct, and unrelated to this exact code path (the
  session-lease patch already shows Prime's own authors are aware Windows can return
  spurious `EPERM` on directory operations elsewhere in this codebase, but that fix was
  never extended to the kernel-venv rebuild path).
- [x] **stale bootstrap state** -- a contributing/compounding factor: once the first
  collision partially wipes the venv, it stays wedged until the original holder exits.
- [ ] filesystem permission/ACL issue -- ruled out; the operation fails only in the
  presence of a live open handle, never due to ACL/ownership (reproduced and controlled
  for directly).
- [ ] antivirus/security interference -- ruled out; the isolated repro reproduces the
  identical error deterministically via a plain background Python process with no
  security-software involvement, and succeeds/fails purely as a function of that
  process's lifetime.
- [ ] socket conflict / agent-dir conflict -- ruled out; not exercised, not implicated.
- [x] **environment/design issue**: the live install's default, single shared
  `~/.prime/agent/kernel-venv` path (used by every kernel on the machine unless
  `PRIME_AGENT_KERNEL_VENV` is overridden) means a long-lived driver session's kernel and
  any newly spawned child kernel are, by default, contending for the same venv
  directory. This is a real, deliberate design choice (avoids re-provisioning a
  multi-hundred-MB venv per spawn) but it is exactly what makes the missing
  concurrency guard in point (1) above reachable in practice.
- [ ] unknown -- not applicable; root cause is established with direct, controlled,
  repeatable causal proof (3/3 fail with holder, 0/3 fail without holder, both versions).

## 5. Does it affect:

- only live 0.7.3: **no**
- isolated 0.7.3: **yes**, reproduced 3/3 under the collision condition
- isolated 0.7.4: **yes**, reproduced 3/3 under the identical collision condition,
  byte-identical error text and byte-identical source file
- both: **yes** -- this is common Prime bootstrap infrastructure, not a 0.7.4-specific
  regression. `bootstrap.ts` is byte-for-byte identical between the two trees (patches
  applied to both).

## 6. Is any Second Brain code involved?

No. The entire failing code path is inside Prime's own
`packages/coding-agent/src/core/kernel/bootstrap.ts`, upstream of any Second Brain
adapter, AutoInject, RTD, ledger, or telemetry code, and upstream of any RLM task
payload execution. No Second Brain file was read, written, or implicated in triggering,
reproducing, or explaining this failure.

## Root cause vs release-gate status (kept distinct, per the plan's own instruction)

- **Root cause: KNOWN**, not merely "unknown but transient" -- established via direct,
  controlled, repeated causal isolation (RLM_EPERM_REPRO.md, RLM_ENVIRONMENT_MATRIX.md).
- **Release gate status**: see RLM_073_PASS.txt / RLM_074_PASS.txt for the actual
  steady-state (non-collision) 3-consecutive-spawn gate results, which is the condition
  that matters for real RLM child usage during a normal session (no concurrent identity
  mutation event), and RLM_FIX_DIFF.txt for the minimum-safe-fix determination.
