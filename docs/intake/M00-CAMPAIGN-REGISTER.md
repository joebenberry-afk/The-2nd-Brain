# M00 campaign register

Maintained across the M00 one-shot closure campaign. One row per requirement/finding. Evidence is
reused only for its exact subject and claim; later evidence supersedes earlier status only for the
same measured subject.

**Tracked evidence pack: `docs/intake/m00-evidence/`** — the bounded material these rows rest on, with
origin tree, path, revision and digest per copy (`MANIFEST.md`), plus `SESSION-READINESS.md`: the
environment facts a new session should read instead of rediscovering them by refusal. Reports under
`outputs/reports/**` are gitignored and do not survive a fresh worktree; the pack exists because a row
that says "see that report" is not a reference a later session can open.

**PRODUCTION ACTIVATION: NOT PERFORMED.** The live runtime is `.worktrees/qualified-v2`; the deployed
extension is unchanged.

## Verified starting state (2026-09-22)

| Item | Value | How verified |
| --- | --- | --- |
| Candidate worktree | `.worktrees/m00.3-producer-guard` | `git worktree add` off `827c3df` |
| Branch | `brain/m00.3-producer-guard` | `git log` |
| Integrated candidate | `1cee974` (producer + re-applied guard) | `git log --oneline` |
| Producer change | `brainstem/prime-extension/src/worker-result-bridge.ts` (`:43`, `:106`, `:126`), `src/index.ts` (`:1944`) | source |
| Guard re-application | `b32d034` = revert of `827c3df` (5 files, 396 insertions) | `git log` |
| Candidate `.venv` | created by the supported process (`python -m venv` + `uv pip install -e ".[dev]"`) | `sys.executable` = candidate venv |
| Candidate import origin | `…\m00.3-producer-guard\src\second_brain\__init__.py`, guard present, runtime tree **not** imported | interpreter probe |
| Extension suite | **763/763 pass** (`vitest run`), including the two that failed before the candidate venv existed | run log |
| Type check | `tsc --noEmit` clean | run log |
| Python acceptance matrix | **105 pass** (writer-admission, hermes, omp adapter) on the candidate interpreter | run log |
| Live runtime | imports `qualified-v2/src`, `_require_terminal_authority` **absent** | interpreter probe |
| Deployed extension | `index.ts` = `42b57b41c531a3a9…410b75a41` (unchanged all campaign) | sha256 |
| Resources before work | free RAM 1,332 MiB / 15,577 MiB; disk free 132.2 GiB | PowerShell measurement |
| Dependency space added | candidate `.venv` 82 MiB; `node_modules` junctioned (74 MiB, no new space) | `du` |

## Identity reconciliation (owner question: approval, inventory, or another file?)

| Identity | Source | Meaning |
| --- | --- | --- |
| `693c792950e2…8bf8af5397b4d` | `omp-host-patch-2026-09-19-successor/CANDIDATE-IDENTITY.json` | historical successor candidate (canary's expectation) |
| `7318c161ba27…bae00e850a` | `PRODUCTION-RECORD.json` (2026-09-20) | bytes that activation claim installed |
| `42b57b41c531…410b75a41` | current worktree **and** deployed | what runs now |
| manifest pinned by approval | `APPROVED-PRODUCTION.json` → `309f4091f4c9…e9520226` | approved manifest identity |
| manifest today | `4e9773742824…af959c68` | resealed in `215407d` |

**Verdict: RESEALED ≠ APPROVED.** `215407d` changed the manifest, `HASHES.txt` and the activation
script but **not** `index.ts`, and the manifest's `index.ts` entry now records
`sealed == installed == bound == 42b57b41…`. The only approval on record covers a different manifest
identity. The activation record also never matched its own candidate identity (`7318c161…` vs
`693c7929…`). `69af49c` (manager-ID collision fix) is retained by owner decision; historical records
are preserved unchanged. A **new** candidate identity is required for the final integrated subject.
Record: `outputs/reports/omp-successor-identity-20260922/RECONCILIATION.md` (candidate-local).

## Register

State vocabulary: `OPEN` / `IN_PROGRESS` / `EVIDENCED_IN_CANDIDATE` / `INDEPENDENTLY_REVIEWED` /
`BLOCKED_<dependency>` / `CLOSED_<subject>`.

| ID | Requirement / finding | Subject | Evidence | Verdict | State | Next executable step |
| --- | --- | --- | --- | --- | --- | --- |
| #3-P | Producer forwards attempt authority through private host transport | extension `worker-result-bridge.ts`, `index.ts` | 4 producer contract tests (`tests/worker-result-authority.test.ts`); 763/763 extension suite | not independently reviewed | `EVIDENCED_IN_CANDIDATE` | include in integrated review |
| #3-C | Terminal-evidence guard at both protected writes | `worker_protocol.record_worker_event` | acceptance matrix (10 rows); mutation sensitivity; Jev 8/8 (revision `01e4bdd`, pre-integration) | reviewed at `01e4bdd` (`incorrect` as mergeable alone, guard sound) | `EVIDENCED_IN_CANDIDATE` | re-review at `1cee974`+ |
| #3-R.1 | **Replay proof, Python side** (already executed): unauthorized duplicate writes no evidence; authenticated duplicate is idempotent | `worker_protocol.record_worker_event` | `test_terminal_event_without_token_is_refused_and_writes_no_evidence`, `test_duplicate_authenticated_terminal_event_is_idempotent` — both green in the 105-test candidate matrix | — | `EVIDENCED_IN_CANDIDATE` | treat as the durable-fact half of the replay proof |
| #3-R.2 | **Replay proof, extension leg** — corrected expectation: emission is permitted; the requirement is no unauthorized authoritative effect | `recoverWorkerResults`, `before_agent_start`, `emitWorkerCompletion` | `brainstem/prime-extension/tests/worker-result-replay.test.ts` (8 cases) + `tests/fixtures/omp_replay_state.py`; report `outputs/reports/m00.3-replay-authority-20260922/REPORT.md`; mutation: guard-removal 5 failed / reconstruction-removal 7 failed, bytes restored | read-only independent **audit** returned 9 PASS + 6 not-yet-demonstrated items, all six repaired (report §7); acceptance review still not obtained (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` blocks mutating dispatch in-session) | `EVIDENCED_IN_CANDIDATE` | obtain the producer/consumer/custody/replay review through an already-permitted route. Reports of these cases must use the separated status vocabulary (message received / authentication / authoritative record / worker outcome / ownership / recovery) rather than an internal event name — see `SESSION-READINESS.md` |
| #3-R.3 | **Journal-controlled admission reconstruction** | `index.ts` recovery branch for `second-brain.worker-admission-pending` | held under #4; read-only case now reproduced end-to-end (integrated evidence, `REPORT.md` §4.3) | — | `OPEN` under **#4** (M00 blocker: forged read-only completion) | close #4 issuance/observation authority; do not resolve under #3 |
| #3-R.4 | Tracking-state reconstruction is not new privileged admission (no issuance, no ownership, no execution start on the replay path) | `recoverWorkerResults` | `REPORT.md` §4.1; probe shows ownership/state unchanged | — | `EVIDENCED_IN_CANDIDATE` | include in #4 review |
| ADM | **Admission-issuer authority**: a caller able to invoke admission obtains the credential for the attempt it created | `cli.py:3371-3384`, `omp_adapter.py:65-79`, `:138-139` | **reproduced 2026-09-22**: `outputs/reports/m00.3-admission-issuance-20260922/` — `worker_context` returns an issued `callback_token` to the caller and that token completes the attempt; only gate is a payload-declared `role` | mechanism confirmed; closure blocked on issuer authentication | `OPEN` — narrowed to a **partial external blocker** (no trusted channel or OS-identity boundary between host and agent-controlled process; the mandate forbids adding accounts/ACLs/elevation) | keep attempt-scoped; do not treat `role`/`actor_trust` as authorization; do not describe no-self-approval as closed |
| #2a | Initiating schema-collision containment | `brain_schema`, `vmem` | `c017dc3`; qualification record with reviewer verdict at top | operational defect CLOSED | `CLOSED` (as scoped) | — |
| #2b | Canonical schema authority | `brain_schema`, `ledger`, `vmem`, `contracts` | increment 2026-09-22: `outputs/reports/m00.3-schema-authority-20260922/REPORT.md` — reserved-name ownership + mutation, import-time registration, VMem migration inside the authority transaction, the authority now decides the component transition (`component_shape`, incl. the version-2 header missing `prev_hash`), one DB-version source, stronger `schema_dump`, inherited lint/type gates repaired | earlier stronger claim still `incorrect`; increment not yet re-reviewed | `IN_PROGRESS` — 5 of 7 open items closed | remaining: test-strength items (strict-prefix fixture, VMem public reader, separate-process first open) and authority-chosen VMem column application. **Idempotency claims are split and now witnessed** (`MANIFEST.md`): logical idempotency (data + schema preserved) is evidenced, and reopening a current database is shown to commit no *content change* (observer-connection `data_version`, sensitivity-tested with a real content change). The witness's measured granularity is recorded: a same-value `UPDATE` with `rowcount == 1` does **not** move it, so "no writes at all" is still not claimed and needs instrumentation inside the tested connections; and needs instrumentation covering rolled-back work and non-database writes — `PRAGMA data_version` alone cannot carry it (it reports another connection's commits, is only meaningful before/after on the *same* connection) and `total_changes` counts one connection's row modifications; whatever witness is used must be tested with a deliberately introduced change |
| #4 | Trusted issuance, host observations, effective grants | `BrainHostProtocol`, bridge, adapters | issuance route reproduced (`m00-evidence/admission-issuance.md`); `m00-evidence/SESSION-READINESS.md` records the two evidence lines that must stay separate | issuer authentication isolated as a partial external blocker | `OPEN` | (a) distinguish **requester / credential issuer / observer / verifier** and enforce the issuance boundary, not just the consumer; (b) **read-only lane**: separate read-only from mutating requirements, then *demonstrate* the lane's effective restrictions — enable it only when they are enforced, never by exempting `reviewer`/`scout` by name, and never treat a role name or requested mode as permission; (c) read-only execution and trustworthy evidence are different properties — reported results still need identity/provenance checks before becoming authoritative; (d) the spawn refusal (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`) exercises the admission *capability* gate only and must not be cited as evidence for the completion guard |
| #5 | Repeatable settlement and truthful worker recording | worker lifecycle | **executed**: `outputs/reports/m00.3-worker-settlement-20260922/` — ten sequential mutating workers on one disposable worktree (all 10 `COMPLETED` + `released` + 1 result, successors admitted with no unlock/worktree change/restart/expiry wait) **and** the ownership/receipt/cancellation matrix: incomplete cleanup → `quarantined` + successor `WORKTREE_WRITER_BUSY`; cleanup receipt → `released` + successor admitted; duplicate receipt inert; restated sequence `RECEIPT_CONFLICT`; released attempt replayed without credential `UNAUTHORIZED_CALLBACK` and with credential idempotent; cancel-before-acceptance → `CANCELED`/`released` with a later completion refused `INVALID_TRANSITION`; cancel-after-acceptance `OUTCOME_CONFLICT` with the accepted outcome preserved | normal path and the named edges demonstrated | `IN_PROGRESS` | **added**: newer-owner exclusion (`WORKTREE_WRITER_BUSY` for the next attempt while one holds), post-release late receipt leaves the newer holder untouched, rebinding to a recycled native identity refused (`BINDING_MISMATCH`). Remaining: active descendants after a top-level result, delayed callbacks beyond the receipt replay, and a restart *between* acceptance and release (process restart itself is inherent in the fixture). The finalization/release question is resolved by naming both records and their guards (report §4): release never writes `settled_at`, `settled_at` never releases; observed `released` + `settled_at=NULL` after a fully evidenced completion |
| #6 | Episode/root-scoped accounting | `governor.py`, `sensors.ts` | root/descendant accounting and unknown-usage refusal already present: `_descendant_total_tokens` sums each unique ledger session rooted at `root_parent_session_id` once (`governor.py:841-870`) and `_session_total_tokens` **raises** on unknown usage rather than reporting zero (`:784-838`) | — | `OPEN` — dedupe blocked on a precondition | **first executable step: give the usage observation an identity.** `parse_telemetry_session` sums every `assistant_usage`/`model_invocation_completed` record with no identity check (`governor.py:301-345`), and the record is written as `v:3 assistant_usage` with provider/model/counters and **no request or message id** (`sensors.ts:1017-1058`); the host message shape is open and unnamed (`types/prime.d.ts:171-181`), so an id may be available and is not captured. Qualify the host's actual message shape first (live observation), then dedupe by that identity — a heuristic key (timestamp+session) is refused because it would drop genuinely billed retries. Then: reserve before admission, reconcile actuals, concurrency/restart, and keep `used == 65` untouched. |
| SB-ORCH-001 | Effective tool grant and enforcement | M00.3 register | `docs/requirements/M00.3_Phase_A_Host_Authority_Continuation.md:97` — "retain their actual open status unless separately and completely demonstrated"; `:201-202` lists the open HIGH set | — | `OPEN` | restate subject from the register, then repair to final bytes |
| SEC-AUTH-01 | Approval/issuance authority | M00.3 register | `M00.3_Phase_A_Host_Authority_Continuation.md:201-202`; `outputs/reports/m00.2-p2-lease-and-manifest-20260921/REPORT.md` (main tree) | — | `OPEN` | read the m00.2-p2 record for the original clause before restating anything |
| SEC-AUTH-02 | Trusted-memory authority | M00.3 register | `:97` — same retained-open status as SB-ORCH-001 | — | `OPEN` | as above |
| SEC-INTEGRITY-01 | Versioned ledger integrity, replay, migration provenance | M00.3 register | `:201-202`; `outputs/reports/m00.2-p2-lease-and-manifest-20260921/REPORT.md` (main tree) | — | `OPEN` | preserve historical ledger facts and explicit migration anchors |
| FSUPD-01 | Authorized activation bound to exact staged and installed bytes | M00.3 register | `:201-202`; directly implicated by the identity reconciliation above | — | `OPEN` | prove stage/installed subject binding in a disposable installation |
| SEC-SKILL-01 / SB-PROMOTION-004 | Approved skill bytes bound at consumption | M00.3 register | `:201-202` | — | `OPEN` | verify and consume the same approved bytes + required dependencies |
| SEC-HOOK-02 | Trusted hook execution rather than uncontrolled executable resolution | M00.3 register | `:201-202` | — | `OPEN` | qualify the actual executable/config/dependency path and environment, not a command string |
| DOC-14 | Fourteen module documents missing | `NOT_YET_AUTHORED / SOURCE_UNAVAILABLE` disposition | inherited | — | `RETAINED` | do not recreate from memory; use authorized roadmap substitutions; do not mark unseen clauses satisfied |

## Where the governing records live (subject reconciliation)

The register's own sources are **not all present in this candidate**:

| Source | Location | In candidate HEAD? |
| --- | --- | --- |
| `M00_OneShot_Closure_Mandate.md` | `docs/intake/` (main tree) | yes (it is the mandate) |
| `M00.3_Phase_A_Host_Authority_Continuation.md` | `docs/requirements/` (main tree) | **absent** — branch predates it |
| `m00.2-p2-lease-and-manifest-20260921/REPORT.md` | `outputs/reports/` (main tree, gitignored) | **absent** — reports are never copied into a fresh worktree |

Consequences, recorded rather than papered over: this candidate cannot self-document those findings, a
candidate seal cannot claim to include them, and any evidence pack must name the tree each reference
lives in. The FINDING IDS were also initially mis-stated as missing: they exist as records, they were
simply outside the candidate and outside the first search scope. Only the *clauses* remain to be read
from the two sources above.

## CORRECTION — my earlier #3-R claim was wrong (falsified by reading the rest of the branch)

I recorded that after a restart the admission map is empty, so journaled completions are "skipped,
never emitted". **That is false.** `recoverWorkerResults` reconstructs an admission from the journal
entry `second-brain.worker-admission-pending` and writes it into `workerAdmissionsByTask` and
`workerAdmissionsBySource` (`index.ts:1990-2013`), then `pendingWorkerTaskIds.add(...)`.

The reconstructed admission carries `taskId, attemptId, packetSha256, projectId, worktreeId,
accessIntent, parentSessionId, agent, toolCallId, sourceIndex, lifecycleRevision, callbackChain,
cleanupAccepted` — and **no `callbackToken`**, because the credential is never journaled.

So the real post-restart behaviour is: the journaled completion **is** emitted (the attemptId matches
the reconstructed admission), `emitWorkerCompletion` forwards `admission.callbackToken` = `undefined`,
the bridge omits the field, and the **Brain refuses it** for a mutating attempt. Fail-closed holds —
but at the **consumer**, not by host-side skipping, and the extension path throws
`BRAIN_WORKER_RESULT_NOT_ACCEPTED` on that refusal.

Consequences for the mandated replay requirements, stated against the code rather than against my
earlier summary:

> **Owner correction (2026-09-22), applied below and in the executed evidence:** the requirement is
> **zero unauthorized authoritative effects**, not zero completion emissions. A completion emitted
> without the attempt's credential and refused by the Brain satisfies it. Any earlier statement in
> this register that a fresh process must emit *nothing* is **superseded**; the executed test asserts
> exactly one emission whose credential is absent, plus the refusal and the unchanged durable state.

| Requirement | Status under the actual mechanism |
| --- | --- |
| no new authoritative terminal evidence without authority | **holds, and is now executed end-to-end** — the Brain refuses with `UNAUTHORIZED_CALLBACK`; nothing is written |
| no persisted callback secret | **holds** — the token is never journaled (asserted on the emitted options) |
| unauthenticated replay stays unverified, not failure/settlement | **holds for Brain state** (no fact created); the extension records a receipt failure (`extension_error`) and journals no acceptance, no worker failure, and no `worker_completed` mirror |
| no automatic re-admission of unresolved attempts | **holds as scoped**: recovery reconstructs *tracking state* from the journal (maps, pending set) and issues no credential, takes no ownership, and starts no execution — see #3-R.4. It is not a new privileged admission |
| no ownership release on restart | **holds** — asserted directly on `writer_ownership` before/after, including on an attempt whose outcome was already accepted |

### New finding for #4: journal-controlled admission reconstruction

Because the reconstructed admission is built from journal data (`taskId`, `attemptId`,
`packetSha256`, `accessIntent`, `projectId`, …) and **read-only attempts are exempt from the
completion guard by design** (admission mints them no authority), a caller who can write journal
entries could construct a read-only admission — `cleanupAccepted` is even set by the reconstruction
when `accessIntent === "read_only"` — and then have the host emit a read-only completion that the
Brain **accepts without any credential**. That is a source-authenticity boundary question, not an
attempt-credential one: it belongs under **#4** (trusted host observation), and it is the concrete
form of the "altered journal entry" check the owner asked for. Not to be resolved under #3, and #3
must not be described as establishing trustworthy host observation.

## Extension replay test recipe — EXECUTED (kept for provenance; the "zero invocations" line is superseded)

Discovered, then executed. The executed test is
`brainstem/prime-extension/tests/worker-result-replay.test.ts` (8 cases, green) with the fixture
`tests/fixtures/omp_replay_state.py`; results in
`outputs/reports/m00.3-replay-authority-20260922/REPORT.md`.

- **Entrypoint:** the extension factory (default export, `src/index.ts:794`). The test builds
  `pi = { on, emit, appendEntry } as unknown as ExtensionAPI` and calls `factory(pi, options)`.
- **Hook:** `before_agent_start` — one `recoverWorkerResults` call site sits inside it
  (`src/index.ts:2987` → call at `:3031`). Three other call sites exist (`:2175`, `:2301`, `:2372`).
- **Runner override:** `options.ompWorkerResultRunner` (`:778`, bound at `:1095`) — the seam captures
  every invocation and delegates to the real bridge, so the captured options are what the Brain saw.
- **Journal shape:** entries are read from `ctx.sessionManager.getEntries()`; the recovery loop
  accepts `customType === "second-brain.worker-result-pending"` with `fields.task_id`,
  `fields.packet_sha256`, `fields.status ∈ {completed, failed, cancelled}`, `fields.worker_agent`,
  plus top-level `attemptId` and `summary`.
- **~~Why the negative case needs no setup~~ (superseded):** the earlier claim that a fresh process
  must produce **zero** runner invocations is wrong on both counts. Recovery reconstructs the
  admission from `second-brain.worker-admission-pending`, the result entry then matches it, and the
  completion **is** emitted — without a credential. The executed observation is exactly one emission
  with `callbackToken === undefined` plus the consumer's refusal, not zero emissions. A journal with
  a result entry but **no** admission entry still emits nothing, and that case is asserted as a
  dependency control.

**Vacuity trap — resolved in the executed test.** A handler that never runs and a guard that refuses
are indistinguishable from an absence assertion alone. The test therefore (a) asserts the registered
handler exists, (b) asserts the positive side effects of a fully-executed hook (the emission and the
`second-brain.worker-result-pending` journal entry it writes), and (c) drives a deliberately
disconnected hook to show those reachability observations disappear — so the absence assertions
cannot pass vacuously.

The same-process live-admission fixture was not needed: the credential-present control replays the
identical captured payload with the attempt's real token through the same real bridge and consumer,
which proves the payload was binding-correct without driving the dispatch flow.

## Environment and constraints

- One heavy instrumented process tree at a time; stop new heavy work below 1 GiB available RAM.
- Each test run ≤ 30 minutes. Complete applicable suites on the final integrated candidate.
- Report/log budget: 512 MiB. Dependency space accounted separately (82 MiB venv + 74 MiB junction).
- No provider-backed test experiments or newly funded review calls; use already authorized review
  capacity, otherwise continue local work and report the budget dependency.
- Never touch the runtime worktree, installed extension, canonical database or production leases.
  Disposable homes/installations only; snapshots via a supported consistent mechanism (never a main
  DB file alone, never deleting WAL/SHM to make inspection work).

## Owner directive recorded (2026-09-22, usability review of this work)

Accepted diagnosis: the Brain's value this session came from guardrails and continuity, not speed, and
the dominant friction was **learning environmental facts by being refused** rather than being told them
earlier. The corrections are folded into the existing rows above and into
`docs/intake/m00-evidence/SESSION-READINESS.md`; **no new campaign and no new architecture.**

Standing process instruction: once the requirement and the next test are clear, execute them under the
one-shot — do not produce another planning packet per turn. Documentation in this register stays limited
to state a later session cannot re-derive: gates, verdicts, provenance, and the readiness facts.

## Resume checkpoint (2026-09-22, after the corrected replay semantics)

**Candidate:** `.worktrees/m00.3-producer-guard`, branch `brain/m00.3-producer-guard`, HEAD `f6e817f`
(on top of `e304aff`, `545133d`, `1cee974`). Worktree clean; `worker_protocol.py`
(`17997bcc…f3e4fac2`) and `index.ts` (`f2c95300…12749e6e`) unchanged, so the recorded mutation
baselines still name the current bytes.

**Done in this session**

- #3 replay, corrected expectation, executed end-to-end: `brainstem/prime-extension/tests/worker-result-replay.test.ts`
  (8 cases) + `tests/fixtures/omp_replay_state.py`; report
  `outputs/reports/m00.3-replay-authority-20260922/`; extension suite 771/771; mutation
  guard-removal 5 failed / reconstruction-removal 7 failed with exact byte restoration.
- Read-only independent **audit** of those artifacts: 9 PASS, 6 not-yet-demonstrated items, all six
  repaired (report §7). The **acceptance review** of producer/consumer/custody/replay is still open.
- #3-R.4: reconstruction is tracking-state only (no issuance, no ownership, no execution start).
- #2b increment: `outputs/reports/m00.3-schema-authority-20260922/` — reserved names unowned (+
  mutation), import-time registration, VMem migration inside the authority transaction, the authority
  now decides the component transition, one database-version source, stronger `schema_dump`,
  inherited ruff/pyright gate failures repaired. `ruff` and `pyright` clean; the 13-file Python set
  green.

**Environment constraints observed in this session (they will recur)**

- **Mutating subagent dispatch is refused by the loaded extension**
  (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`: this host advertises no settlement capability).
  Task-tool spawns that imply edits are blocked; read-only agents (e.g. `evidence-auditor`) are
  accepted. Work therefore proceeds inline, and the acceptance review needs an already-permitted
  route.
- Python must be run with `PYTHONHOME`/`PYTHONPATH` removed (the user-level `PYTHONHOME` points at a
  corrupted tree).
- Temp-tree cleanup can leave a directory behind when a spawned bridge still holds it as its cwd;
  the replay test reports the leftover instead of failing the suite.
- One fail-open telemetry warning (`telemetry write failed: ENOENT`) appears in the read-only replay
  case; recorded, not hidden.

**Next executable step**

1. #2b remaining debt (test strength; authority-chosen VMem columns) — optional for M00, listed in the
   #2b report.
2. **#4** trusted issuance and host observations: close the issuing route as well as the consumer
   (`ADM` row), including the open forged read-only completion finding (#3-R.3) now reproduced
   end-to-end.
3. **#5** settlement and truthful worker recording; **#6** episode/root-scoped accounting; then the §9
   security/deployment reconciliation and the cumulative evidence pack.
4. The acceptance review of #3 must be closed through a permitted route before the candidate can claim
   `M00_CANDIDATE_QUALIFIED`.

## #5 execution brief (from the mandate §7, with the code's current shape)

Requirement: one guarded finalization path for normal completion *and* completed-attempt
reconciliation. Required evidence is a trusted accepted outcome, authenticated executor settlement,
authenticated cleanup, prevention of further writes under the old attempt, and an exact current
ownership match. `COMPLETED + expired lease + result row` is not a substitute; lease expiry alone
never authorises release; a fully evidenced normal completion must not wait for expiry.

Where the code stands (read, not yet exercised as a packet):

- `worker_protocol.settle_task` (`:1973`) already demands `approved is True`, postcondition evidence,
  matching approved-review evidence, and a durably bound result before it writes `settled_at`. It
  accepts `COMPLETED` only, and is idempotent when `settled_at` already equals the current stamp.
- Ownership changes on two other paths: `ingest_worker_lifecycle` (`:1438`, `executor_settled and
  cleanup_complete` → `released`; `interrupted` or `executor_settled` alone → `quarantined`) and
  `record_worker_dispatch_failure` (`:1289`, unbound reservation only). These are the candidate
  "finalization paths" to reconcile into the guarded one.
- `reap` (`:2041`) quarantines expired writer authority and keeps legacy read-only reaping — it must
  not be the thing that releases a writer.
- `worker_recovery.py` carries the recovery proposals (`RELEASED`/`quarantined` vocabulary, the
  `_..._row` guard at `:242-257`) and is where restart-time recovery authority must stay missing
  rather than falsely succeed.

Evidence to produce: ten sequential local mutating workers on one disposable worktree/database, each
binding, executing, settling, cleaning up, releasing and permitting its successor without manual
unlock, worktree change, restart or expiry wait; plus the separate cases the mandate names (immediate
completion, outcome-before-cleanup, active descendants after a top-level result, cancellation before
and after acceptance, delayed callbacks, duplicate receipts, process/job-ID reuse, late dispatch
after revocation, restart, newer-owner protection). The `ADM` blocker (issuer authentication) does not
gate these: they run through the disposable fixture path already proven in
`outputs/reports/m00.3-replay-authority-20260922/`.

## Next executable step

1. **#3 independent review** — producer, consumer, credential custody and replay together, bound to the
   frozen bytes of this report. In-session subagent dispatch is refused by the loaded extension
   (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`), so this needs an already-permitted review route.
2. **#3-I real integration route** — the replay leg now runs the real hook, bridge and Python consumer
   against disposable state (`REPORT.md`); the remaining gap is the *packaged/installed* extension
   under a real OMP host launch, which is a different subject from the source factory.
3. **#3-M mutation** against the frozen integrated bytes — done for the replay subject (see §5 of the
   report); rerun for the final candidate after any further source change.
4. Then #2b, #4, #5, #6 in order, then the §9 security/deployment reconciliation and the cumulative
   evidence pack.
