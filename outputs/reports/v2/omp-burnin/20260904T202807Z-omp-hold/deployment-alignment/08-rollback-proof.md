# Deployment Alignment — Rollback Proof

## Procedure

1. Restored the manual pre-deployment backup
   (`pre-deploy-backup-20260904T235135/second-brain/`, 24 files, manifest in
   `02-backup-manifest.md`) over `~/.prime/agent/extensions/second-brain` by
   deleting the then-current (candidate) directory and copying the backup
   back byte-for-byte.
2. Recomputed SHA-256 for all 24 restored files and compared against the
   original pre-deployment manifest hashes captured in step 2 of this
   alignment pass.
3. Result: **24/24 files byte-exact match, 0 mismatches.** Rollback to the
   original pre-deployment deployed bytes is proven.
4. Re-ran the canonical installer twice to return the final state to the
   qualified candidate (`da37094f3114098072610fa9464ec6cca880f23f`):
   - Default target (`~/.prime/agent/extensions/second-brain`) —
     Manifest SHA-256 `f16a4e35edbf04550a9b2c164b7d92a65275e6471e72798c6ee101e9d4b29cff`.
   - Corrected auto-discovery target
     (`~/.omp/agent/extensions/second-brain`) — same Manifest SHA-256
     `f16a4e35edbf04550a9b2c164b7d92a65275e6471e72798c6ee101e9d4b29cff`.

## Verdict

Rollback is proven independently of Git history (it restores the actual
deployed bytes previously captured on disk), and the final active deployment
at both the legacy and the corrected auto-discovery paths is the qualified
candidate source (`da37094`), not the temporary rollback state or the
diagnostic copy. The installer's own automatic pre-install backups
(`backups/20260904-195341-363-…`, `backups/20260904-200145-476-…`,
`backups/20260904-200333-544-…`, `backups/20260904-200336-557-…`) provide a
further, independent rollback path for any of these transitions.
