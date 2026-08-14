# Safety, promotion, transfer, and recovery evidence

Focused regression suites passed: `70 passed` across promotion, skillforge
security review, immune rollback, backup/restore, and cross-model transfer.
The cases include stale frontier approval refusal, incomplete active-skill
refusal, placeholder/lifecycle mismatch rejection, malicious-skill static
review, guarded rollback/double-rollback behavior, stale WAL/SHM restore
handling, and both-fail/one-overlap transfer non-certification.

An isolated eight-worker SQLite stress wrote 200 semantic memories:

```json
{
  "workers": 8,
  "per_worker": 25,
  "written": 200,
  "rows": 200,
  "integrity_check": "ok",
  "foreign_key_check": [],
  "wall_seconds": 1.2393
}
```

These are mechanism and recovery results, not evidence of automatic Brain use.
No malicious artifact was sent to Prime, no production Brain home was used by
the stress run, and no learning was allowed to affect the candidate.

Remaining limitations: crash injection during every filesystem/SQLite commit,
real autonomous Prime capture/learning, cross-model transfer uplift, and
cross-project leakage still require a verified C2/C3 integration path and
fresh paired task data.
