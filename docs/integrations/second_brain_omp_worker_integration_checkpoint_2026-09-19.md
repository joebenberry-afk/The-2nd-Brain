# Second Brain — OMP worker-integration checkpoint (2026-09-19)

Tracked index for the worker-settlement/worker-recovery repair. The detailed
evidence package lives in the campaign reports directory; this file exists so
the acceptance state is not held only in gitignored receipts.

## Verified and committed (qualified-v2 worktree)

| Commit | Change | Evidence |
| --- | --- | --- |
| `3968429` | Settlement observation hardening in the Brain adapter | journals every observation and any lifecycle rejection; no silent receipt failure |
| `c5acfd7` | Operator recovery command | `src/second_brain/worker_recovery.py`, CLI `worker-plane lease-inspect\|lease-quiesce\|lease-recover`; 6 focused tests |
| `0686d44` | Interrupted-attempt recovery without false settlement | live demo on the real attempt: dry run `release-permitted`, apply `ownership-released-for-interrupted-attempt`, receipt `43531a7e`, state `UNRESOLVED`, `logical_outcome` untouched, `executor_settled=false`, `cleanup_complete=false` |
| `38d8243` | Recovery evidence handling hardening | canonical generation compare; `resource_coverage: operator-asserted` stated in the receipt |
| `968848b` | No outcome before acceptance | unaccepted/running snapshot no longer maps to `completed`; `tsc --noEmit` clean |

Canary host (not yet installed): `omp/18.2.6`, profile `canary-settlement`.
`src/task/worktree.ts` sha256 `36b3f3c9625ee1745e7f29b43ff025c1725523ec77282a490f5af4b8f6773d14`
(prior `4c34bab2e1dd118a4924debab9093e16622a60abe7f1887c8161a2adcccf62af`).

## Host-side fix applied in the canary

`cleanupIsolation` now **fails closed**: `isoStop` is awaited without swallowing,
its failure is retained, directory removal is still attempted but never allowed
to hide a failed stop, and the handle rejects if either step failed. Expected
aggregate effect (per the executor's own contract): the accepted task outcome is
preserved, the isolation **cleanup** is marked failed, `releasePermitted` stays
false and ownership stays **protected**.

## Outstanding — integration queue

1. Astra's barrier patch: one promise bridged from the actual cleanup
   success/rejection; timeout and a stale sentinel must fail closed, never count
   as release. Includes one-shot and deferred routing: the one-shot `finally`
   currently calls `cleanupHandle` directly past the barrier; the deferred branch
   re-registers a deduped pending key and nothing resolves `isolationRelease`;
   both cleanup paths resolve in `finally` even on rejection.
2. Recovery hardening (Astra's findings, accepted, not yet integrated): strict
   generation (refuse unknown, compare without truthiness, no generationless
   exemption); a separately recorded complete resource census, with recovery
   requiring a bound quiescence attestation for every listed resource rather than
   a caller subset; interrupted receipts recorded in `worker_recovery_events`
   without incrementing `lifecycle_sequence`; `BEGIN IMMEDIATE` before recovery
   reads.
3. Re-audit the omp15 release once strict generation lands: that attempt had no
   recorded host generation, so under the hardened rule it could not have been
   released. The release remains valid evidence that the interrupted path works
   end to end without false success; it is not evidence that the hardened binding
   rule was satisfied.

## Demonstrations still owed

- A→B→C controlled deferred cleanup: real resource pending → successor refused
  through normal dispatch/admission → release signal → actual cleanup completes →
  host observation durably accepted → ownership released → successor admitted.
- Cancellation requested during demonstrably active work, with no premature
  release and eventual release after genuine settlement.
- Identical-parameter Brain-ON/OFF comparison; isolated edit with real
  capture/commit and integration; read-only, session and concurrency regressions
  (independent repositories and linked worktrees kept as separate claims).
- Instrumentation removal, sealed host/adapter/configuration identities, fresh
  independent acceptance, then the existing activation-card preconditions.

## Retained facts

- Ordinary editing workers and automatic successor release: demonstrated
  (omp12 two successive workers, omp13, omp14) with `COMPLETED`, `released`,
  `executor_settled=1`, `cleanup_complete=1`.
- Interrupted-observation protection and blocked successor: demonstrated
  (omp15 refused `WORKTREE_WRITER_BUSY`, file unmodified, still refused after
  lease expiry).
- Explicit isolation routing reaches the native runner and an available Windows
  backend: demonstrated (policy pass, `isolation:owned`, backend candidates
  `[5,7]`, candidate 7 started; candidate 5 fails with ProjectedFSLib missing).
- Item-only isolation normalization: upstream behaviour is correct; the earlier
  loss was local instrumentation, restored; regression 4 pass with no seam.
- Production profile untouched; no push, tag or publication.

## Independent review payload (preserved verbatim)

`docs/integrations/astra_worker_integration_review_2026-09-19.json` — the
independent reviewer's structured audit, preserved unedited so integration needs
no re-derivation:

- `q1_verdict`: `ONLY_ACCEPTED_OUTCOME_RECONCILIATION` — settlement reconciliation
  is supported; the interrupted-ownership release path was judged not yet safe,
  with four named defects: a resource list inferred from existing attestations
  cannot detect an omitted resource; a missing generation can match a missing
  generation; generation `0` is collapsed by truthiness; and the transition
  consumes the host lifecycle sequence.
- `q1_patch_text` (~20 KB): exact replacement text for `worker_recovery.py` —
  `_generation`, `_interrupted_row`, `_inventory_binding`, `_write_recovery_event`,
  a census recorder, and replacements for `release_interrupted_attempt()` and
  `recover()`. The contract it enforces: a separately recorded **complete**
  resource census (operator inspection with method and observation, never a
  fabricated host inventory) whose resource set the release request cannot
  shrink; a census without evidence of completeness must not be recorded; no new
  table or dependency.
- `q1_tests`: 3 focused cases.
- `q2_patch_text` (~8 KB): the barrier patch bridging one promise from the actual
  cleanup success/rejection, with timeout and a stale sentinel failing closed.
- `required_evidence_for_abc`: 8 items the A→B→C run must capture.
- `risks_or_false_success_paths`: 11 named risks.

Reviewer's explicit constraint on the interrupted row: if its `host_generation`
is NULL, the strict contract **refuses** release; an independently preserved
launch/binding record identifying that exact attempt and generation is required
first. Neither an operator-selected generation nor `None == None` establishes it.
