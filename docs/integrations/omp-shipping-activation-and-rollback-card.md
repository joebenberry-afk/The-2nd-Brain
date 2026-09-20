# OMP shipping candidate — activation and rollback card

Status: pre-activation draft for independent review. No installation has been
performed. Authority: the current OMP autonomous completion mandate's
conditional local installation clause, effective only after this exact
candidate receives pre-activation acceptance.

## Candidate identity

- Worktree: `.worktrees/qualified-v2`, branch
  `brain/omp-native-6172a18-20260911`, sealed commit `5baa2a6` (functional
  commit `40d2218`).
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

## Causal-evidence binding (separately open item)

After activation, in the now-authorized actual Brain home, run the missing
governed trial for `governed_improvement_promotes_only_with_all_guards` so the
live ledger records a worker-independent causal observation binding the
current-subject promotion artifact (or apply a separately authorized re-point
of the two existing observations). Re-run
`scripts/verify_qualification.py --scope <omp-only overlay>` and record the
verdict.

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
