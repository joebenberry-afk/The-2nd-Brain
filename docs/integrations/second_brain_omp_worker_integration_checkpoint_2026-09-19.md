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

## Accepted execution order (authoritative target for closure)

The three invariants to satisfy: **complete resource knowledge → independently
bound generation → proven cleanup completion.** The omp15 release must not be
treated as proof of the hardened mechanism; it proved the path can work, not the
stricter identity/completeness conditions.

1. Land the resource-census contract first: independently recorded, evidence-backed,
   immutable for the recovery attempt, with the release request allowed only to
   select the entire census. Test an omitted resource, an attempted subset release,
   a nonexistent census and a census lacking completeness evidence.
2. Land generation/binding hardening with it: `NULL` generation fails closed,
   generation `0` stays a legitimate generation rather than becoming falsey,
   recovery requires a separately preserved launch/binding record, and
   `None == None` never qualifies as identity.
3. Run the recovery tests before touching the barrier, adding regressions for the
   four review findings: omitted resource, missing-vs-missing generation,
   generation `0`, and lifecycle sequence consumed by recovery.
4. Then apply the cleanup barrier as a separate change with narrow semantics:
   exactly one promise, resolved only by actual cleanup success, rejected on
   cleanup failure, timeout, stale sentinel or duplicate/late settlement; the
   barrier must not infer ownership or completeness.
5. Run the A→B→C proof before broad regression testing, capturing all eight
   required evidence objects as a mechanically inspectable artifact rather than a
   prose summary — the proof that admission/ownership → cleanup → successor
   release occurs in the intended order.
6. Only after A→B→C passes, attack cancellation and concurrency: cancel during
   each boundary, cleanup→cancel, cleanup-success→release, timeout, process
   interruption, duplicate callback and stale callback.
7. Then Brain ON/OFF and ordinary-workflow regression: read-only dispatch,
   ordinary edit→capture→commit, parallel read-only work, session continuation and
   the existing worker admission cases, proving the hardened path did not turn
   normal operation into a serialization bottleneck.
8. Instrumentation removal is the final functional mutation: rerun the small
   qualification subset after removal to show ordering is unchanged, then seal
   hashes/identities and hand the exact candidate to a fresh independent reviewer.

Closure rule: do not stop at "tests pass". Stop only when the hardened census +
generation + barrier contracts are implemented, the complete A→B→C evidence
package exists, adversarial cancellation/concurrency cases pass, instrumentation
is removed, identities are sealed, and a fresh independent reviewer accepts the
exact sealed candidate — or that reviewer explicitly concludes closure is
impossible under the available OMP interfaces.

Architectural note carried forward (v3, not this campaign's scope): a resource
census is an authoritative evidence object while "this worker owns these
resources" is a derived claim; recovery must not reconstruct authoritative
evidence from derived rows. Unknown is a distinct state, not a wildcard. Once
something becomes a release/settlement boundary it should collapse into a narrow
deterministic state machine with explicit terminal states.

## Cleanup barrier increment (module + integration seam + host wiring)

- `cleanup-barrier.ts`: one canonical promise per cleanup operation; narrow success
  (only the authoritative completion resolves); aggressive fail-closed failure
  (rejection, timeout, cancellation, identity mismatch, duplicates, late
  settlement); duplicate and late settlement are explicit and observable.
- `barrierFor()` makes identity continuity structural: dispatch and release ask
  by identity and receive the same object, so a reconstructed barrier cannot
  become an alternate release authority. `releaseWhenProven()` awaits the barrier,
  revalidates immediately before permitting, and never merely reads a state.
- Gates: B1-B12 (12) plus I1-I10 and the negative "cleanup function returned is
  not cleanup completion" case. `bun test tests/host-patch` -> 27 pass, 0 fail.
- Host wiring: `isolation-runner.ts` registers `cleanupBarrier.promise` with
  `trackCleanups` and settles that same barrier from the real
  `isolationRelease.promise` outcome, which now propagates a failed `isoStop`
  thanks to the fail-closed cleanup. The test-only hold delays when cleanup
  starts; it no longer authorises anything.

Scope note (honest): the deferred route is wired. The one-shot route's release
uses `releaseBase` and performs no isolation cleanup, so it currently has nothing
to settle; when it does, it must go through the same gate. A→B→C has not been run
against this wired candidate - that is the next step, and only then does it count.

Patch artifacts for the sealed package live beside this file
(`omp-host-patch-2026-09-19/`), with `HASHES.txt` recording the loaded identities.

## Cleanup-obligation classification (O1-O5) and the one-shot question

The two facts stay distinct: **cleanup required and proven complete** versus
**cleanup not required for this execution**. `kind: "none"` is only produced from
authoritative route evidence, never inferred from a missing barrier, and never
manufactured as an already-resolved barrier. The release gate accepts exactly two
proof forms: authoritative CLEANUP_NOT_REQUIRED, or an exact resolved barrier;
`assertNoDowngrade` forbids turning a required obligation into none later.

One-shot classification is established from the route's own code, not by
assumption: `onRelease: opts.baseOptions.keepAlive === false ? releaseBase :
releaseIsolation`, and `releaseBase` is `opts.baseOptions.onRelease?.() ??
Promise.resolve()` - it never touches the isolation handle. Only the deferred
route reaches `cleanupIsolation(handle)` through `cleanupHandle()`. So a one-shot
execution has no isolation cleanup obligation by construction; any other
registered cleanup work still forces `required` through
`registeredCleanupWork > 0`, and on that evidence the classifier requires a
barrier rather than permitting release.

Gates: O1 none-with-release, O2 one-shot owning a resource cannot be none,
O3 unfinished required barrier fails closed, O4 deferred releases only through the
exact resolved barrier, O5 no downgrade. `bun test tests/host-patch` -> 32 pass,
0 fail.

Next: the production A->B->C run on the deferred/isolation path against commit
`5fec750` plus its paired A->B-failure->not-C false-success twin, capturing
Astra's eight required evidence objects and recording attemptId, generation,
cleanupOperationId, barrier identity, census id and successor id in each. Then the
race matrix R1-R12, instrumentation removal, sealing and independent acceptance.

## Review round: five findings, four fixed (hashes refreshed)

1. Deferred branch registered the same resource name a second time, which
   trackCleanups skips as a duplicate, so the canonical barrier stayed pending
   forever on that route. Fixed: the deferred chain settles the same barrier, with
   route and retention recorded in the trace.
2. A retained workspace skipped cleanupIsolation but still resolved the release,
   presenting a skipped cleanup as a proven one. Fixed: the skip is now traced as
   `cleanup:skipped:retainedWorkspace` and is not evidence of teardown.
3. releaseWhenProven/releaseEligible awaited even a synchronous revalidation,
   opening a turn in which a queued microtask could cancel or supersede the
   attempt. Fixed: a synchronous decision keeps permit() adjacent to the check.
   (Both helpers still have no production callers - latent, not the RoughRabbit
   cause.)
4. A second one-shot classification with zero counts could return none while a
   canonical required barrier already existed; assertNoDowngrade was never called
   in production. Fixed: classification is idempotent - an existing canonical
   barrier wins - with gate O6 added.
5. createCleanupBarrier is documented as the non-canonical raw constructor; the
   wiring still keys the barrier on agentId/generation 0 rather than the real
   settlement attempt identity. NOT fixed, recorded as an open gap.

Hashes now: cleanup-barrier.ts, isolation-runner.ts and worktree.ts as recorded in
omp-host-patch-2026-09-19/HASHES.txt. Gates: 33 pass, 0 fail.

## Review round 2 — cause localized, and a correction to my one-shot claim

**RoughRabbit cause (reviewer, code-supported inference):** the adapter's
post-shutdown lifecycle RPCs are unowned asynchronous work. The snapshot callback
discards its promise (`void Promise.resolve(observe(...))`) and the registry's
subscriber contract is `void`; `AgentSession.#doDispose` records `session_exit` at
its start, `print-mode.ts:305` awaits that disposal, and `main.ts:2359` calls
`postmortem.quit` -> `process.exit`. Being alive when a synchronous observer runs
does not ensure survival through the later multi-second Python RPC (receipt 1 took
~2.87s). Raw journal: rev1 at 15:57:29.424Z, receipt 1 accepted 32.558Z,
session_exit 32.592Z, rev2 34.416Z, rev3/4 settled+releasePermitted 34.645/34.652Z.
Ruled out: the running-status filter, the revision guard, a barrier deadlock, a
Brain refusal, and "revisions map to running".

**Proposed fix (not applied):** make the observer contract
`void | Promise<void>`, have the session own returned observer work in a drain
map, and drain AFTER native job/cleanup disposal but BEFORE `postmortem.quit`.
Explicitly: never register the Brain receipt promise as isolation cleanup, or the
settled receipt would depend on its own prerequisite.

**Correction to my one-shot claim.** I recorded that a one-shot execution has no
cleanup obligation, arguing from `releaseBase` never touching the isolation
handle. The reviewer's verdict is `HAS_CLEANUP_OBLIGATION`, citing
`structured-subagent.ts:487` forwarding `request.keepAlive`, `:657-663` creating
the attempt settlement handle, and `:685-696` invoking the isolated subprocess.
So the one-shot route is a supported execution path that can own cleanup work;
`kind: none` must rest on per-execution evidence (no handle, no registered work),
never on the route name. Gates O1/O6 encode the conservative direction but O1's
scenario should be re-read in this light before the one-shot production proof.

**Reviewer's interim notes already satisfied:** keep the extra `await
cleanupHandle()` (done) and keep throwing on `handle && retainWorkspace` (done).
**Still to apply:** prefer settling `isolationRelease` from the deferred chain
rather than adding a second barrier-settlement path, and drop the duplicate
`trackCleanups` registration.

## Corrected obligation rule and single settlement path

Classification now follows THIS execution's acquired resources and registered
work, never the route's name: `none` requires affirmative evidence that no
handle was allocated and no cleanup work was registered, AND that the acquisition
boundary was actually passed. Incomplete resource knowledge fails closed to
`required`. The historical O1 result is preserved but no longer qualifies the
corrected behaviour; its fixture has been re-expressed with per-execution
evidence, and O7/O8 were added for the acquisition boundary and for the retired
one-shot exemption.

The deferred branch now drives `isolationRelease` from the deferred chain
(`completion.then(isolationRelease.resolve, isolationRelease.reject)`) and the
parallel barrier-settlement path was removed, so one canonical barrier and one
settlement path remain.

Still to apply: the reviewer's observer-ownership/drain patch (session-owned
observer work drained after native cleanup and before postmortem.quit), with the
constraint that the receipt promise is never registered as isolation cleanup.
