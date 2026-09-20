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

## Drain repair: fence design, and two more false-signal hazards

Reviewer findings after the preserved patch was judged unsafe verbatim:

- The preserved drain (a) removed fulfilled terminal entries before producer
  quiescence, (b) swallowed drain failure, (c) let the adapter's `result=false`
  path fulfill, so a refusal would read as success, and (d) let a
  `session_shutdown` timer unsubscribe at 30s, abandoning owned work. It is being
  re-derived with exact stronger anchors rather than substituted.
- `AsyncJobManager.dispose()` returns after ~3s and clears `#jobs` even when
  `jobsSettled=false`, so a later `waitForAll`/`waitForOwnerJobs` can falsely see
  empty. This is the same false-signal class as an empty `pendingJobIds` list: an
  empty set must never be read as quiescence, and the manager's own clear must not
  be usable as a fence.
- The parser hides Python rejections as `RECEIPT_MISMATCH` with no echoed
  identity, so a refusal is indistinguishable from a transport failure.
  Reconciliation is feasible because ingest supports idempotent same-payload
  resend keyed by attempt + sequence + receipt SHA - but identity must derive from
  the existing receipt and a lost ack is recorded unknown-then-reconciled, never
  assumed accepted or assumed failed.

Fence mechanism (concrete, race-free by construction): call
`manager.dispose(...)`, immediately capture `manager.waitForAll()` before dispose's
first await resumes and clears `#jobs`, and await that captured completion during
the final observer drain; `dispose` synchronously marks `#disposed`, so no new job
can register after the capture. Also await `agent.waitForIdle` plus in-flight
handlers. Native cleanup stays represented by retained observed
attempts/subscriptions through their terminal callback or unsubscribe.

Scope limit stated by the reviewer and carried here: this proves the ROOT session
fence. A shared child manager needs an owner-scoped fence rather than a post-clear
list lookup, and that is a separate qualification - not something the root proof
implies.

## Drain scope decision (reviewer, final for this repair)

- Root session fence: `manager.dispose()` plus an immediate `manager.waitForAll()`
  captured before the first await clears the job set - GROUNDED, and the basis of
  the drain.
- Shared/child manager: `waitForOwnerJobs()` called after the parent's ~3s dispose
  clear is NOT grounded. The reviewer will not label it proven.
- Minimal fail-closed behaviour instead: for sessions that registered observers,
  report the shared-manager producer fence as UNAVAILABLE rather than reporting a
  completed drain. An unavailable fence is an explicit incomplete outcome, never a
  silent success - the same rule that applies to a rejected, timed-out or
  never-entered chain.
- A universal owner-scoped manager fence would require an additional job-manager
  change. That is out of scope for this observer repair and is recorded as a
  separate qualification, not as proven work.
- Isolation cleanup does NOT need modification for this observer repair, so the
  qualified cleanup/barrier layer stays frozen.

## Universal producer fence (reviewer, supersedes the root-only capture)

The reviewer found a small, universal fence that closes the clear-while-pending
hole for root AND child sessions, so the "report unavailable" fallback is no
longer the ceiling:

- In `async/job-manager.ts`, retain `job.promise -> ownerId` in a SEPARATE map
  until that exact promise settles, and never clear it during dispose or
  diagnostic eviction. The existing set may still be cleared for its own reasons;
  the retained map is what makes quiescence provable.
- Expose `waitForProducers(ownerId?)` that loops the ACTUAL retained promises and
  inspects `allSettled` results, so a rejected producer is a reported failure
  rather than an omission.
- Final session drain order: agent idle / in-flight handlers, then the
  owner/all-native-producer fence, then the dynamic subscription and callback
  drains.

Explicit non-requirement preserved: receipt work is never a native-cleanup
prerequisite. The forbidden circle - native cleanup waiting on the settled-receipt
RPC while that RPC requires native cleanup to finish - stays closed.

Status: design accepted; patch text still to be applied. Root fence
(dispose + immediate waitForAll) remains grounded and is retained as the
fallback ordering guarantee if the retained-map fence lands after it.

## Line-ending constraint on patch application and sealing

The reviewer verified that the target host files are CRLF in the working tree, so
anchors and replacements must carry explicit `\r\n`; an LF-only verbatim replace
would silently fail to match. This matters twice over: for faithful application of
its change set, and for the seal, where the recorded identity must be the exact
bytes that ship. The driver's own patches wrote LF-normalised content into some
files, so a mixed-ending state is possible and must be normalised deliberately -
not left as an accident - before hashes are recorded as final.

Rule carried forward: measure endings per file before applying reviewer patch text,
apply with the file's own ending, and confirm the byte count changed as expected;
never assume a string replace matched because the command exited zero.

## Adapter requirement: per-subscription group lifetime (reviewer)

Each task-tool subscription needs ONE lifetime promise covering every prepared
mutating admission of that call. Every returned snapshot callback carries that
promise, and the registered disposer resolves it only when all of those exact
admissions have `cleanupAccepted`; otherwise it rejects, including on expiry.

Why it is required: without it, a mixed batch - one accepted/observed writer plus
one writer whose observations never arrived - can still look successfully drained.
That is the partial-evidence-read-as-complete class again, this time at batch
granularity.

Boundary preserved: this is NOT isolation cleanup. `observeWorkerAttempt` still
publishes and performs its RPC normally and does not await the group lifetime, so
no cleanup/RPC cycle is introduced. The group lifetime is session-owned observer
work, drained by the fence described above - never registered as native cleanup.

## Applied and re-qualified (2026-09-19, driver run)

- `8ccddd4` applied the reviewer's 23 CRLF-exact edits with zero drift: callback
  contracts returned through the session, the retained producer map plus
  `waitForProducers` in `job-manager.ts`, session-owned observer work drained
  after native teardown, the adapter's per-subscription lifetime promise, the
  bridge refusal diagnostics, and the pre-quit diagnostic. Receipt and
  observer-lifetime promises are never registered as native cleanup.
- Adapter gates on the applied subject: eslint clean, `tsc --noEmit` clean,
  vitest **740/740** (33 files). The one stale case was the lost-acknowledgement
  test; it now asserts the accepted contract - exactly one identical-payload
  reconciliation resend (4 lifecycle invocations when the ack is lost, 3
  otherwise) with the durable sequence keys unchanged at `[1, 2, 3]`
  (`1264cd4`).
- Next executable action: the A->B->C controlled deferred-cleanup run on the
  deferred/isolation route against this subject (attemptId, generation,
  cleanupOperationId, barrier identity, census id and successor id recorded in
  each of the eight required evidence objects), plus the paired
  A->B-failure->not-C false-success twin. Then the R1-R12 race matrix,
  instrumentation removal, sealing, and fresh independent acceptance.

## Readiness fixes after the live review (2026-09-19, driver run)

The applied drain set passed the review as faithfully applied, but the review
returned NOT READY for the A->B->C demonstration and named two blockers plus one
ownership gap. The fixes below are applied to the canary candidate.

- **Pre-acquisition obligation (blocker).** `isolation-runner.ts` classified
  `{acquisitionComplete: true, isolationHandleAllocated: false,
  registeredCleanupWork: 0}` before acquiring the handle, so a fresh identity
  returned `none` and the route threw before isolation even started. It now
  reuses the real settlement handle (`opts.baseOptions.settlement`), classifies
  under that attempt's actual attemptId/generation, declares the cleanup
  obligation it is registering (`registeredCleanupWork: 1`), and keeps the
  required assertion. The barrier identity is no longer `agentId` + generation 0.
- **Filtered-observation lifetime (P1).** A mixed call whose snapshots arrived
  only for a read-only sibling returned `undefined`, so a rejected writer group
  was invisible to the host drain. The filtered branch now returns the
  subscription lifetime, which the host records as subscription work only -
  never as a writer receipt and never as release authority.
- **Host validation narrowed.** `observeAttemptSettlement` no longer re-checks
  every tracked snapshot for `releasePermitted`. The returned subscription
  promise already resolves only after every prepared writer's cleanup is proven
  and rejects on incomplete detach/expiry; the removed loop mis-applied writer
  validation to filtered read-only siblings and could false-fail a healthy
  mixed call.
- Gate results: adapter eslint clean, `tsc --noEmit` clean, vitest **741/741**
  (new regression: "returns the subscription lifetime for a filtered read-only
  sibling"); host `bun test tests/host-patch` 35/35. The canary `check:types`
  script is unavailable here (`tsgo` not installed); oxlint on the edited host
  files reports pre-existing warnings only.
- Still open from the review, in order: finish the identity-bound cleanup
  fixture (hold-begin/release-signal protocol, one-shot/fallback cleanup and
  post-run capture gating, retained-path rejection of the original signal),
  qualify the real host/adapter boundary (retained producers after timed-out
  disposal, delayed RPC, refusal, successful reconciliation, double-unknown,
  mixed/no-observation cases), refresh the executed-candidate manifest with the
  identities the review listed, then run A->B->C and its false-success twin.
  Latent-only items: the async check/use gap in `releaseWhenProven` /
  `releaseEligible`, and freezing/copying the barrier identity.

## Fixture and terminal paths landed (2026-09-19, driver run)

- Identity-bound hold: `awaitReleaseSignal()` reads the settlement's real
  attemptId/generation, emits `isolation:hold-begin:<binding>` (agentId,
  attemptId, generation, cleanupOperationId, holdFile) to the trace, refuses a
  pre-existing hold prefix as a stale sentinel, waits for the exact
  nonce-bound signal file, and rejects the original signal on timeout. Expiry
  never becomes release, and no work is faked in place of real capture/commit/
  cleanup.
- Route gating: the hold gates the deferred release path, the direct cleanup
  branch, the deferred-cleanup chain, and post-run capture in the main flow.
- Terminal paths: a retained workspace, an early failure with no release path,
  and a failure before a handle existed all reject the original signal instead
  of leaving the canonical barrier pending forever; `acquisitionComplete` is no
  longer claimed before acquisition.
- Gate results: host lint 0 errors; host tests 35/35; adapter gates unchanged
  (eslint, tsc, vitest 741/741).
- Review round 2 (same day): the deadline is re-checked with a monotonic bound
  after the signal lookup (a late signal still rejects); every hold failure
  terminates the original signal regardless of which consumer awaits it;
  retained workspaces reject even when a deferred-cleanup promise exists; the
  deferred chain observes the hold without waiting for its producer; sentinel
  checks use lstat and require a regular signal file; `releaseBase` is
  documented as outside the gate.

### Boundary tests, delta verification and candidate manifest (same day)

- Adapter boundary regressions added and green (vitest **744/744**): a single
  lost acknowledgement reconciles successfully through the identical-payload
  resend; host-owned work stays pending through a delayed lifecycle RPC and
  after its return until cleanup is proven; a read-only-only call registers no
  observer obligation.
- Host producer-lifetime gate added and green (`bun test tests/host-patch`
  **36/36**, 5 files): a producer retained by the manager survives a timed-out
  dispose and `waitForProducers` still awaits it.
- Fresh Astra verification of `ce40bb5`: deadline acceptance edge PASS (now
  `>=` at the bound), hold rejection propagation PASS, retained+deferred
  settlement PASS, previous counterexamples A and B closed, and no
  false-success or healthy-run false-negative found in the reviewed delta.
- Executed-candidate manifest:
  `docs/integrations/omp-host-patch-2026-09-19/CANDIDATE-MANIFEST.json` binds
  subject commit `2f0ae14`, host/adapter/Brain artifact hashes, the fixture
  protocol, gate results and the explicit UNAVAILABLE host type check, plus
  the fields that must be re-bound at run start.
- Remaining: run the A->B->C demonstration and false-success twin against the
  manifest candidate (re-hash at run start), then cancellation/concurrency,
  Brain ON/OFF and ordinary-workflow regressions, instrumentation removal,
  sealing and fresh acceptance. The release causal-evidence binding remains a
  separately tracked open item.

### Live-proof preparation and home-isolation requirement (same day, later)

- Candidate re-hash against `CANDIDATE-MANIFEST.json`: **matches** (all five
  host artifacts and both adapter artifacts byte-equal; recorded as
  `manifest_matches_candidate: true`).
- Launch recipe reconstructed from the preserved canary traces
  (`%TEMP%/omp-canary25/boot.txt`, profile `canary-settlement`, fixture repo
  `%TEMP%/omp-canary25/consumer-a`, session under
  `~/.omp/profiles/canary-settlement/agent/sessions/`): supervisor session on
  the canary package with `--profile canary-settlement` and the qualified-v2
  extension, `OM_CANARY_BOOT` trace, `OM_CANARY_FORCE_ISOLATED=1` for the
  explicit isolation request, and `OM_CANARY_HOLD_RELEASE_UNTIL` as the
  identity-bound hold prefix. `boot.txt` shows the exact ordering the A->B->C
  coordinator must observe (begin -> obligation -> isolation:owned ->
  backend:started -> barrier:resolved -> isolation:released).
- Compliance finding: the earlier canary runs wrote their worker rows into the
  **live production home** (`worker_tasks` here contains the RoughRabbit task
  `omp-2cb75c...`). The demonstration must not repeat that. Required before
  launch: a disposable Brain home via `SECOND_BRAIN_HOME=<temp home>` plus
  `SECOND_BRAIN_PYTHON=<project venv python>` (the lifecycle bridge otherwise
  resolves `<home>/.venv/Scripts/python.exe`, which a fresh home lacks), the
  fixture repo registered in that home, and the post-exit durable read from
  that home's `db/brain.sqlite` - never the production database.
- Open before launch: confirm the exact `-e` extension path used by the canary
  (assumed `.worktrees/qualified-v2/brainstem/prime-extension/src/index.ts`)
  and initialize the disposable home (schema v24 + project registration) so
  A, B and C all run against it.

### Isolated A->B->C demonstration — result (2026-09-19, later)

Environment: disposable home `%TEMP%/omp-canary26-home` (schema v24, doctor
20/20, `SECOND_BRAIN_PYTHON` = project venv), fixture repo
`%TEMP%/omp-canary26/consumer-a` registered only there (`omp26-canary-a`),
canary profile `canary-settlement`, qualified-v2 extension, manifest-bound
candidate (re-hash PASS). Baselines:
`outputs/reports/omp-canary26-demo-20260919/preflight.json`.

| Step | Evidence |
|---|---|
| A admitted under the real settlement identity with a required obligation | `begin:WorkerA` -> `obligation:route=deferred:kind=required:attempt=39324:1:WorkerA:generation=1` |
| A completed and merged its fix | task `omp-8d7ea2c2...` COMPLETED; pytest 1 passed; fixture calc.py corrected |
| Successor refused while ownership held | B -> `WORKTREE_WRITER_BUSY` |
| Identity-bound hold released by the coordinator, not the model | exact nonce-bound signal path created after the B-refusal marker; `isolation:hold-release` 0.4 s later |
| Real cleanup completed, barrier resolved, ownership released | `isolation:released` + `barrier:resolved` 19:50:02Z; final receipt seq 4 has `executor_settled=true, cleanup_complete=true` |
| Successor admitted after release and completed | follow-up session: `ActualAardwolf` admitted, pytest 1 passed; task `omp-5eae5c7f...` COMPLETED 19:51:23Z |
| Production untouched | `production_unchanged: true` (before/after checksums equal); durable read from the disposable DB only |

Open observation for the reviewer (not adjudicated): the release path finished
~8 minutes after the signal, at parent-session teardown; the first supervisor
had already stopped waiting, and its C dispatches were correctly refused at
that time. The successor succeeded only in a follow-up session after the
release. Question: is release-at-teardown the expected contract for kept-alive
workers, or is a same-session release trigger missing? Raw traces:
`%TEMP%/omp-canary26/boot.txt` (positive run), `boot-c.txt` (successor
session); evidence JSON:
`outputs/reports/omp-canary26-demo-20260919/post-exit.json`.

Remaining: false-success twin in a fresh disposable home (hold active, no
signal -> cleanup proof stays incomplete, ownership retained, successor
refused), Astra review of the eight evidence objects, then the rest of the
qualification sequence. `check:types` remains UNAVAILABLE; the causal binding
remains separately open.

### False-success twin (fresh disposable environment) — PASS (2026-09-19)

Environment: fresh home `%TEMP%/omp-canary27-home` (schema v24, doctor 20/20,
0 tasks / 0 receipts before), fresh fixture repo `omp27-canary-a`, same
manifest-bound candidate, hold prefix set with **no coordinator and no signal**.

| Assertion | Evidence |
|---|---|
| A ran and its logical outcome was accepted | task `omp-a8a33090...` COMPLETED |
| No successful final settlement | receipts seq 1-3 all `cleanup_complete=false` (seq 2-3 `executor_settled=true`) |
| Cleanup never progressed without the signal | `hold-begin` present; no `hold-release`, `barrier:resolved` or `isolation:released` |
| No teardown shortcut or synthetic success | observer drain reported `timed out`; process exited nonzero |
| Ownership protected past teardown | follow-up session successor -> `WORKTREE_WRITER_BUSY` |
| Production untouched | `production_unchanged: true` after both sessions |

Raw traces: `%TEMP%/omp-canary27/boot-twin.txt`, `boot-twin-c.txt`; evidence:
`outputs/reports/omp-canary27-twin-20260919/{preflight,post-exit}.json`.

Together with the positive run (`8384620`) this completes the paired core
safety demonstration: eventual durable release on the happy path, and retained
protection with a refused successor when the cleanup prerequisite is never
satisfied. Astra's separate verdicts (positive-evidence acceptance; keepAlive
release contract) are requested and pending; cancellation/concurrency and
ordinary-workflow qualification follow.

### Astra verdicts and corrections (2026-09-19, later)

**Q1 evidence validity: REJECT for the full eight-object acceptance claim;**
the narrower identity-consistent chain is supported. Gaps to capture before
full acceptance: physical cleanup events (`isoStop` outcome, directory removal,
retained decision, barrier object token); teardown chronology (drain
start/end, pre-quit, actual exit timestamp/code); durable DB checkpoints after
receipt 1 and after the terminal callback; manifest additions
(attempt-settlement/observer-type identities, recorded run-start rehash). The
originally cited successor was **not isolated** (`boot-c` records
`isolated=null`). Corrected with a fresh isolated successor run
(`boot-c2.txt`): `route:policy:enabled=true:isIsolated=true`,
`begin:CanaryC2Pytest` -> `obligation:route=deferred:kind=required:
attempt=38020:1:CanaryC2Pytest` -> `backend:started:candidate=7`; task
`omp-cc1359b0...` COMPLETED. The disposable DB now holds 3 COMPLETED tasks and
`production_unchanged` remains true. Accurate label: **isolated A -> refusals
-> terminal receipt -> isolated successor admitted in a follow-up session.**
The twin's successor refusal is ownership-level and route-independent, but its
trace is likewise labeled non-isolated for accuracy.

**Q2 keepAlive contract: lifecycle-scoped (Contract A), intended.** The
release callback is adopted at task completion and invoked only at lifecycle
release (parent teardown or explicit release); parking alone does not release
(`registry/agent-lifecycle.ts`; `task/executor.ts:3060-3075`). The early
hold-begin came from the post-run gate (`task/isolation-runner.ts:634-637`),
not from `releaseIsolation`, so there was no eight-minute stall inside a
running release body. Same-session successors are not expected under Contract
A: demonstrations must end/release the owning session and wait for the
accepted terminal receipt before dispatching the successor. No release-timing
changes until a different contract is explicitly specified.

### Qualification rerun runbook (next increment; evidence only)

Goal: produce the acceptance-quality package Astra asked for, against the
already-demonstrated behaviour. No candidate changes unless a real defect
appears. Instrumentation additions are test-only, `OM_CANARY_BOOT`-gated, and
removed before sealing.

1. **Run-start rehash**: re-hash the manifest-listed host/adapter/Brain
   artifacts before launch and record `run-start-rehash.json` with the
   comparison result and timestamp (read-only).
2. **Durable checkpoints**: read-only snapshots of the disposable DB taken
   after receipt seq 1 and after the terminal callback, stored with row
   contents and checksums.
3. **Physical cleanup evidence**: trace `cleanup:start` / `cleanup:stop` /
   `cleanup:remove` (with outcomes, including the retained decision) around
   `cleanupIsolation(handle)` and the memoized `cleanupHandle` result.
4. **Barrier diagnostic identity**: use the barrier's stable logical identity
   (`attemptId`, `generation`, `cleanupOperationId`) as the token and trace it
   at create (`barrier:armed:<identity>`), settle
   (`barrier:settled:<identity>`) and await (`barrier:awaited:<identity>`).
   Never a memory address or address-derived value.
5. **Teardown chronology**: observer-drain start/end/abandoned, pre-quit
   marker, and the actual process exit timestamp and code (zero and nonzero
   both recorded deterministically).
6. **Isolated successor**: same flags as the C2 run
   (`OM_CANARY_FORCE_ISOLATED=1`, `OM_CANARY_ISOLATION=1`), with the recorded
   admission and `route:policy:isIsolated=true` line.
7. **Package** the raw artifacts under the existing evidence layout and submit
   the eight-object acceptance question to Astra.

Robustness campaign after acceptance: cancellation at the agreed boundaries;
concurrent/repeated recovery attempts; stale-completion and cross-attempt
protection; Brain ON/OFF; read-only worker behaviour; ordinary
edit->capture->commit; session continuation; instrumentation removal with a
decisive rerun; sealing and fresh acceptance. `check:types` remains
UNAVAILABLE and the causal-evidence binding remains separately open.

### Instrumentation rule and checklist for the qualification rerun (binding)

The `OM_CANARY_BOOT` instrumentation must be **observational only**. It may
record: `isoStop` result; retained-vs-removed decision; memoized cleanup
result; barrier logical identity; drain boundaries; pre-quit; exit
timestamp/code. It must not await anything production would not await,
introduce a synchronization point, change cleanup ordering, change release
eligibility, add retries, or alter timeouts. Astra must be able to state:
"instrumentation adds observations but introduces no new authority or
dependency" before the package is accepted.

Planned trace points (test-only, removed before sealing):

- `cleanupHandle`: `cleanup:start`, `cleanup:stop:ok|error:<msg>`,
  `cleanup:remove:ok|error`, `cleanup:retained:<dir>` around
  `cleanupIsolation(handle)` / the memoized result.
- Barrier: `barrier:armed:<attemptId>|<generation>|<cleanupOperationId>` after
  a `required` classification; `barrier:settled:<identity>:state=...` on both
  resolve and reject; `barrier:awaited:<identity>` before the bridge awaits.
- Drain boundaries: `observer-drain:start|end|abandoned` (host
  `#drainSettlementObservers`, test-only) with the source tool-call id.
- `pre-quit` marker at the final drain point. The actual exit timestamp/code
  is captured by the launcher wrapper (no host edit needed).

DB checkpoints are launcher-side and read-only: a watcher copies the
disposable DB at the moment receipt seq 1 first appears and at terminal
settlement, producing `state-1`/`state-2` snapshots with checksums. No
candidate instrumentation is involved in the checkpoints.

Acceptance ordering remains: instrumented rerun -> Astra eight-object review ->
instrumentation removal -> decisive subset rerun -> robustness campaign ->
sealing -> fresh acceptance. `check:types` and the causal-evidence binding
stay separate throughout.

### Instrumentation implemented (2026-09-19, continuing)

Runner trace points are in place: cleanup:start, cleanup:stop:ok|error, and
arrier:armed|awaited|settled:<attemptId>|<generation>|<cleanupOperationId>
(the stable tuple at all three points). Lint clean; host tests 36/36.
Behavior unchanged: append-only observations, gated on OM_CANARY_BOOT.

Remaining instrumentation for the evidence-complete rerun: per-step
isoStop/directory-removal traces inside worktree.ts cleanupIsolation, drain
boundaries (observer-drain:start|end|abandoned) in the host session drain,
and the pre-quit marker. Exit code/timestamp and the DB checkpoints are
launcher-side. For this rerun the instrumented runner identity in HASHES.txt
supersedes the manifest's runner hash; CANDIDATE-MANIFEST.json remains the
pre-instrumentation behavior reference and both identities are preserved in
git history.

## Evidence-complete isolated campaign — ACCEPTED (2026-09-20)

Candidate: HEAD `ed96ca5` (instrumented), worktree `.worktrees/qualified-v2`.
Evidence root:
`outputs/reports/omp-canary29-evidence-20260919/` (`RUN-INDEX.json`,
`preflight.json`, `twin-preflight.json`, four run directories).

Three interrupted/rescinded attempts are preserved as diagnostic history and
are NOT qualification evidence: `attempt-1-setup-failed` (fresh fixture had no
commit; `git worktree add: invalid reference: HEAD`), `attempt-2-positive-
patch-not-applied` and `attempt-3-positive-native-crlf-refusal` (captured
patch refused by the native applier). Each attempt's durable state was
truthful (no unearned settlement) and each prompted a scoped repair, reviewed
by Astra: fixture baseline commit + watcher snapshot discipline (`7b6eea7`),
cache hygiene (`95aabce`), and LF fixture creation with the proven native
CRLF cause (`ed96ca5`).

Accepted positive run: session-1 (isolated A `41108:1:WorkerA` admitted,
required deferred obligation, B refused `WORKTREE_WRITER_BUSY`, identity-bound
hold observed by the external coordinator, coordinator signal created,
physical cleanup with the exact tuple, barrier resolved, Contract A release,
terminal receipt seq 4 `executor_settled=true cleanup_complete=true`, drains
and pre-quit, exit 0, `Applied patches: yes`, fixture repaired and green) and
session-2 (isolated successor `45024:1:CourageousHarrier` admitted after
release, pytest 1 passed, terminal receipt seq 4, exit 0).

Accepted false-success twin: twin-1 (no signal; hold timed out at 600 s,
barrier rejected, no cleanup events, ownership `quarantined`,
`cleanup_complete=0`, nonzero exit) and twin-2 (successor refused
`WORKTREE_WRITER_BUSY`, no new task, exit 0). Production selected-column
checksums unchanged across both campaigns.

Independent acceptance: Astra `ACCEPTED` — all eight required objects accepted
with raw citations, `campaign_contract_satisfied: true`, no blockers
(verdict at `%TEMP%/omp-canary29-review/astra-eight-object-verdict.json`).

Residual conditions for final qualification (from the acceptance): remove
qualification instrumentation/hold controls through the accepted change
process and bind the release bytes; seal the campaign artifacts and resolve
stale pre-run manifest fields; activation remains subject to its own gate.

### Scoped ledger state and the causal-evidence binding (2026-09-20)

`scripts/verify_qualification.py --scope docs/superpowers/plans/2026-09-19-second-brain-v2-omp-only-scope.json`
against the OMP-only assembly records (`outputs/reports/omp-only-release-assembly-20260919/`)
reports **68/68 scoped gates and 12/12 requirements covered**, with exactly one
failing check: `qualification_ledger: governed promotion evidence is not bound
to a worker-independent causal observation`. The verifier requires the
promotion-gate artifact to be referenced by exactly one causal observation in
the live Brain (`v2_observations` joined to `v2_interventions`) whose
`_evidence` matches path/sha256/feature/source_commit/source_tree/config and
whose `target_ref` matches. The live ledger's two real-trial observations
(`intv-ddda44bd233a4d5fa35f73c2`) reference the 2026-09-08/09 artifacts, not
the current-subject rebind. The 2026-09-19 receipt records that closing it
requires either a renewed governed trial recording its own causal observation
(a live-ledger write) or re-pointing the recorded observations — both live
Brain writes. Under this mandate those writes belong to the authorized
activation phase (controlled installed-runtime operations in the actual Brain
home), so the binding is scheduled after installation rather than bypassed.

`check:types` was resolved with the project's actual pinned toolchain:
`@typescript/native-preview 7.0.0-dev.20260707.2` (tsgo) from the v18.2.6
catalog. A full v18.2.6 workspace with the lockfile-pinned toolchain and the
candidate sources passes (`bun run check:types`, exit 0, zero diagnostics),
with all six bound host files byte-identical to HASHES.txt; the earlier
isolated single-package environment and its dependency-resolution artifacts
remain recorded for transparency.

### Local activation and installed smoke (2026-09-20, later)

Astra pre-activation verdict `PRE_ACTIVATION_READY` for the sealed candidate
(`cb2807c`, functional `40d2218`). Under the mandate's conditional local
authorization:

- Installed: extension (26 files, installer manifest
  `381f3e75...`) into `~/.omp/agent/extensions/second-brain`; the complete
  canary-vs-retail host source delta (7 additional files) into the retail
  package, making the installed `src` tree byte-identical to the sealed
  canary; `task.isolation.enabled: true` added to the default profile config
  (backup preserved). No `OM_CANARY_*` variables persist.
- Backups and rollback: `second_brain backup` exit 0; rollback copies of the
  extension, host files and config; a disposable behavioral rollback rehearsal
  restored the pre-activation extension and host into a throwaway tree (all
  hashes match, the added file removed, restored host starts `omp/18.2.6`).
- Installed smoke (normal launches, seams disabled): isolated mutating worker
  settled with the patch applied (exit 0); read-only delegation returned a
  useful result and an isolated successor was admitted with `1 passed`
  (exit 0); `--continue` resume recalled the successor result (exit 0);
  installed compaction demonstrated (seven compaction records, model-reported
  `compacted: true` with continuity detail, exit 0); advisory/shadow states
  captured read-only (no new promotions; `verified-config-read-reuse` stays
  shadow). Production records are scoped to project `omp-smoke-20260920`.
- Astra round-22 verdict: `INSTALLED_EVIDENCE_ACCEPTED_WITH_OPEN_COMPLETION_CHECKS`.
  Open: targeted Brain recall at the model boundary (gate exercised but no
  brief rows with the tested models; the underlying search returns the
  intended memory), and the separately tracked causal-evidence binding plus
  the shipping-subject ledger rebind; final `OMP_SECOND_BRAIN_READY` report
  after both close. Non-blocking follow-ups: read-only task-row accounting and
  failed-to-cancelled terminal outcome arbitration.
- Report: `outputs/reports/omp-activation-20260920/ACTIVATION-REPORT.md`.


### check:types resolved (2026-09-20)

Ran `tsgo -p tsconfig.json --noEmit` with the pinned dev build in an isolated
environment built from the v18.2.6 config chain and the pinned global install.
Differential against the unpatched published source: the candidate originally
added one real error (`isolation-runner.ts:427` lost `handle` narrowing inside
a trace thunk, fixed by capturing the narrowed backend outside the thunk); the
remaining seven errors are dependency-resolution artifacts identical in the
unpatched source. After the fix and after instrumentation removal the candidate
has zero specific errors. Evidence:
`outputs/reports/omp-canary29-evidence-20260919/check-types/`.

### Instrumentation and hold removal + clean-candidate decisive subset (2026-09-20)

Commits `eb65308` (campaign traces removed from isolation-runner 17 statements,
worktree 9 calls plus helper and traceContext parameter, agent-session
traceDrain/counters/describeCanaryFailure, main pre-quit block) and `40d2218`
(hold fixture removed: the clean run proved the external coordinator depended
on the removed hold-begin trace to learn the nonce-bound signal path, so the
hold is instrumentation-bound fixture forcing, not shipping behaviour). The
stripped worktree.ts matches the earlier derived baseline except for two blank
lines after the first import (semantic equivalence, not literal byte
identity); the worktree module marker was part of the removed helper block
while the job-manager/attempt-settlement/structured-subagent/index markers and
route/owner-jobs traces are retained as pre-existing gated seams. Edited files
were deliberately normalised back to CRLF. Host tests 36/36 (independently
re-run by the reviewer); lint 0 errors executed as `bun x oxlint` from the host
package directory.

Decisive subset on the clean candidate (`omp-canary29g-shipping-20260920`,
fresh home/fixture, no hold, no coordinator): session-1 isolated A
(`41876:1:SecondBrainCanaryA`) COMPLETED/released/settled/cleanup with receipts
1-4 terminal true/true, B refused `WORKTREE_WRITER_BUSY`, patch applied and
fixture green, exit 0; session-2 isolated successor
(`17044:1:VerifyCalc`) COMPLETED/released/settled with terminal receipt, its
run reported `1 passed`, exit 0; watcher captured state-1 and state-2 in both;
production checksums unchanged. The reviewer accepted this as the decisive
subset and recorded the honest labels: session-1/post-exit.json includes both
tasks (state-2.sqlite is the uncontaminated terminal snapshot), fine-grained
teardown traces come from the instrumented campaign, and the runs enabled the
isolation seams.

Sealing record: `docs/integrations/omp-host-patch-2026-09-19/SHIPPING-CANDIDATE-MANIFEST.json`
supersedes the instrumented-planning fields, binds both campaigns, preserves
the derived-baseline limitation and labels the checksum scope. Reviewer verdict
`PRE_ACTIVATION_BLOCKED` on two items: the mandatory host `check:types` is
parity-verified but not passing, and the sealing metadata had to be
reconciled (done by this manifest). A full pinned v18.2.6 workspace run is
being prepared to obtain a passing exact-candidate type check or a documented
exception decision.



