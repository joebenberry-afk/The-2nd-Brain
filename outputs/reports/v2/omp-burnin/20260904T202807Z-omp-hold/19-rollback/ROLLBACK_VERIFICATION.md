# Rollback Verification

## Candidate

- Branch: `brain/v2-omp-qualification`
- Candidate SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- Qualified comparison baseline: `4af64affdf4f1ec07b9483b67f440394d2853b32`
- State backup: `backups/backup-20260904-171420-294131`

## Checks

1. The baseline commit object exists locally.
2. The baseline is an ancestor of the candidate (`git merge-base --is-ancestor`
   returned success); the candidate can be reverted without rewriting the
   comparison baseline.
3. The backup manifest is format 2, records a prequalification runtime SHA,
   SQLite schema 21, a DB SHA-256, and all canonical roots. It excludes
   rebuildable runtime/telemetry roots as specified by the backup contract.
4. The current candidate passes `second_brain doctor` with 19 checks and a clean
   build identity.
5. The real restore command was run against a fresh isolated target:

   ```text
   brainctl restore --home C:/tmp/omp-final-rollback \
     .../backups/backup-20260904-171420-294131
   ```

   Restore completed successfully. Post-restore verification found all 89
   manifest-listed canonical files present with exact SHA-256 matches, the DB
   hash equal to the manifest, and SQLite `PRAGMA integrity_check = ok`.

A doctor run against the bare restored state reports one expected layout failure:
the backup intentionally excludes `brainstem/` and other runtime roots. It also
passes version, config, Python, SQLite, migrations, and identity checks. A
production rollback therefore restores canonical state and then redeploys the
runtime checkout; it does not pretend that a state-only backup contains the
executable/runtime tree.

## Result

**PASS for rollback source and canonical-state restoration.** The baseline commit
and byte-verifiable state backup are available, and the restore path was executed
successfully in isolation. The expected runtime re-deployment step is explicit
and documented rather than hidden.
