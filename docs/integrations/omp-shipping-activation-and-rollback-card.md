> **Historical execution record only (2026-09-20).** The 2026-09-23
> orchestrator-removal mandate supersedes every installation, launcher,
> worker-settlement and rollback instruction below for current candidates.
> `scripts/run-omp-patched.ps1` and the host-patch campaign are retired from
> active tooling; do not run these commands against production. Sealed records
> preserve the original subject, not authorization for new bytes.

# OMP shipping candidate — activation and rollback card

Status: executed for the accepted candidate. Pre-activation acceptance
(round 21) and the local installation under the mandate's conditional
authorization are complete; the installed smoke suite, the executed rollback
rehearsal (2026-09-20,
`outputs/reports/omp-activation-20260920/rollback-rehearsal-executed.json`) and
the causal-evidence binding closure are recorded. Publication and tagging are
not authorized.

## Candidate identity

- Worktree: `.worktrees/qualified-v2`, branch
  `brain/omp-native-6172a18-20260911`, sealing commit `787b3d6` (functional
  commit `40d2218`; ledger subject `7fcd995a`).
- Host: `@oh-my-pi/pi-coding-agent-canary` (`omp/18.2.6`), six bound host files
  per `docs/integrations/omp-host-patch-2026-09-19/HASHES.txt`; 26-role
  identity inventory in `RUN-IDENTITIES.json`; sealing record in
  `SHIPPING-CANDIDATE-MANIFEST.json`.
- Adapter: `brainstem/prime-extension/src/{index,worker-lifecycle-bridge}.ts`
  and `types/prime.d.ts`.
- Brain code: `src/second_brain/*` in this worktree (installed via the project
  venv); production Brain home schema is already 24 — **no migration is
  required**.
- Evidence of record: instrumented campaign (Astra eight-object ACCEPTED) plus
  the clean-candidate decisive subset
  (`outputs/reports/omp-canary29g-shipping-20260920/`).

## Preconditions (read-only checks before touching anything)

1. No active OMP sessions for the target profile; no unresolved ownership:
   `worker_tasks` rows with `writer_ownership NOT IN ('released')` must be
   inspected and either settled by their owner or left untouched (never
   force-unlocked). If any remain unresolved, stop activation.
2. Record the current installed extension manifest and the retail package's
   bound-file hashes as the rollback baseline.
3. Backups: `python -m second_brain backup` for the production home plus file
   copies (extension dir, any config files to be edited). Preserve SQLite
   coherence (`-wal`/`-shm` via the project's backup path, not raw copies of a
   live database).
4. Rehearse the rollback on a disposable copy: restore the extension dir and
   patched files, confirm OMP starts and the stock refusal behaviour returns.

## Installation (only after pre-activation acceptance)

1. **Extension**: update `%USERPROFILE%\.omp\agent\extensions\second-brain`
   from this worktree with `scripts/install-prime-extension.ps1` (records the
   manifest; settings are not modified). Preserve the prior directory as
   `second-brain.pre-activation-<utc>`.
2. **Host**: apply the six sealed host files to the intended OMP launch tree
   with byte-identical copies:
   - patched source route: copy into the retail package
     `@oh-my-pi/pi-coding-agent/src/...` so a normal `bun <package>/src/cli.ts`
     launch loads the qualified bytes; verify each file hash equals
     `HASHES.txt`.
   - the stock `omp.exe` binary cannot load patched source and remains
     unmodified. Observed stock behaviour (rehearsed 2026-09-20,
     `outputs/reports/omp-activation-20260920/rollback-rehearsal-executed.json`):
     on stock v18.2.6 runtimes the extension takes its documented degraded
     `native_lifecycle` path — the Brain admits the mutating admission and holds
     the writer lease, cleanup is never proven, and no release is ever
     performed. The restored stock source refused the host dispatch with
     `WORKTREE_WRITER_BUSY`; the stock binary spawned the worker and the lease
     stayed held. The clean `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`
     refusal applies only to hosts with none of the three settlement sources.
     The qualified release path remains the accepted patched source host.
3. **Configuration**: enable `task.isolation.enabled` for the target profile
   only if normal mutating delegation is desired; write it through the
   supported settings surface with a backup, never by hand-editing derived
   state. Remove any residual `OM_CANARY_*` variables or launch flags from the
   normal (non-campaign) configuration; confirm none remain.
4. Record installed/loaded hashes and confirm they match the accepted
   deployment map.

## Installed smoke suite (fresh, normally launched OMP sessions)

Scratch project, normal APIs, target profile:
- Brain ON: AutoInject/context appears at the model boundary; a targeted recall
  works; advisory/shadow states unchanged.
- Read-only delegation returns a useful result; mutating isolated worker is
  admitted, edits, captures, and merges; its terminal receipt settles and
  ownership releases; an isolated successor is admitted afterwards.
- Restart/resume and compaction continuity for the scratch session.
- Durable state checked read-only; clean shutdown; no manual lease repair,
  emergency eval bypass, or external receipt helper used.

## Causal-evidence binding (closed 2026-09-20)

The missing governed trial ran against the live Brain: the accepted ledger was
re-bound onto the shipping subject (measured content preserved; identity and
provenance fields updated), the real promotion refusal path was re-run and
reproduced the accepted counterexample, and the live observation
`intv-0cee29ee1df3b59d812cc2e9` / `obs-e7bd9a8c6c1312bb7b4cb2da` binds the
current-subject promotion artifact. `scripts/verify_qualification.py` exits 0
against the shipping manifest/records and the OMP-only scope
(`outputs/reports/omp-shipping-ledger-20260920/strict-verdict-final.json`).

## Rollback

- Trigger: activation failure, smoke failure, or any required-behaviour
  regression.
- Steps: stop further production experimentation; restore the previous
  extension directory and the pre-activation host files (hash-verified);
  revert any configuration edit from its backup; confirm the qualified
  capability is absent (a stock route with the installed extension leaves the
  writer lease held, never a release; a stock host with no settlement source
  refuses with `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`) and a normal
  session start.
- Database: no migration occurred; do **not** restore an old database over
  subsequent live writes. If data restoration is ever required, use a coherent
  project-supported backup and state the exact point in time.
- Report the actual rollback state, including any files or records that could
  not be restored.

## Successor corrections (2026-09-20, independent audit follow-up)

The text above is the activation record as executed and is not rewritten. These corrections
supersede its file lists and references; the installed package is unchanged and nothing here
re-activates or re-installs anything.

1. **The host delta is thirteen files, not six.** Section "Installation" step 2 says six sealed
   host files; the actual applied delta is 6 bound + 1 added + 6 changed =
   `docs/integrations/omp-host-patch-2026-09-19/DEPLOYMENT-MANIFEST.json`. That manifest is now the
   single source for installation, verification and rollback; read it instead of a hand-maintained
   list (`python scripts/generate_omp_deployment_manifest.py --check` reports whether the installed
   bytes still match it).
2. **The pre-install extension backup lives under the extension source root**, not the Brain home:
   `.worktrees/qualified-v2/backups/20260920-014215-831-prime-extension-pre-install` (26 files,
   `install.json` + the prior extension). The earlier reference to a same-named directory under the
   Brain home `backups/` does not resolve; the prior extension bytes are also preserved at
   `outputs/reports/omp-activation-20260920/rollback/installed-extension/` (25 files).
3. **The qualified launch route is explicit.** The package's own `omp` command maps to
   `dist/cli.js`, a bundle without the worker-cleanup patch, so a bare `omp` is not the qualified
   route. Use `powershell -NoProfile -File scripts/run-omp-patched.ps1 <args>`: it verifies all
   thirteen host files and all twenty-six extension files against the deployment manifest and
   refuses to start on any mismatch before running `bun <package>/src/cli.ts`.
4. **Known open gates after this audit** (see `docs/integrations/second-brain-omp-audit-review/`
   for the findings, evidence and the Brain-side reconciliation): the successor host module
   `docs/integrations/omp-host-patch-2026-09-19/host/attempt-settlement.ts` (audit F-06) is a
   candidate and is **not** installed; production-path lifecycle behaviour on the launcher and
   automatic prose recall still require their own qualification runs.
