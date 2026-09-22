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
| #5 | Repeatable settlement and truthful worker recording | worker lifecycle | **executed**: `outputs/reports/m00.3-worker-settlement-20260922/` — ten sequential mutating workers on one disposable worktree (all 10 `COMPLETED` + `released` + 1 result, successors admitted with no unlock/worktree change/restart/expiry wait) **and** the ownership/receipt/cancellation matrix: incomplete cleanup → `quarantined` + successor `WORKTREE_WRITER_BUSY`; cleanup receipt → `released` + successor admitted; duplicate receipt inert; restated sequence `RECEIPT_CONFLICT`; released attempt replayed without credential `UNAUTHORIZED_CALLBACK` and with credential idempotent; cancel-before-acceptance → `CANCELED`/`released` with a later completion refused `INVALID_TRANSITION`; cancel-after-acceptance `OUTCOME_CONFLICT` with the accepted outcome preserved | normal path and the named edges demonstrated | `IN_PROGRESS` | **added**: newer-owner exclusion (`WORKTREE_WRITER_BUSY` for the next attempt while one holds), post-release late receipt leaves the newer holder untouched, rebinding to a recycled native identity refused (`BINDING_MISMATCH`). Remaining: (a) **active descendants after a top-level result is ABSENT as a release-blocking observation** — the host bridge advertises `execution_census: false` with `census_scope_complete: false` (`bridge/brain-host-bridge.ts:263-265,290-292,348-373`), and `native-settlement.ts:97-160` reacts only to post-finalization lifecycle frames, so a still-running descendant produces no frame and nothing is recorded: an inventory, not proof that no writers remain; (b) delayed callbacks beyond the receipt replay; (c) restart between acceptance and release **executed**: `phase --phase accept` and `phase --phase release` are separate processes, and the release still lands (`held` -> `released`) because it is derived from durable state, not from in-process continuity (report §3b). The finalization/release question is resolved by naming both records and their guards (report §4): release never writes `settled_at`, `settled_at` never releases; observed `released` + `settled_at=NULL` after a fully evidenced completion |
| #6 | Episode/root-scoped accounting | `governor.py`, `telemetry.py`, `sensors.ts` | identity dedupe landed and witnessed: `telemetry.usage_identity` (response_id/api_request_id/uuid, field-prefixed) is applied by `parse_telemetry_session`, `_session_total_tokens` (**the budget gate**), `session_usage` and `operational_report`; the extension records **one canonical form** — `sha256:<hex of the host id>` — because branching between verbatim and digested forms put raw and encoded text in one namespace and let a literal `sha256:<hex>` id collide with another response's encoding (an independent auditor found this in my first attempt; pinned in `tests/sensors.test.ts`); root/descendant accounting and unknown-usage refusal unchanged | source-audited (DedupeAudit: claims 1-4 PASS after repair, claim 5 bound by 58 passing governor tests + digests, no reviewer disagreement) | `IN_PROGRESS` | open, with anchors: (a) **no capacity is reserved before a budget-consuming admission**; (b) `check_budget` fails **open** (`state: OK` + `used=None` + `error=ACCOUNTING_UNAVAILABLE`) and Claude Code records have no numeric `total_tokens`, so the cap cannot protect that path; (c) `scripts/run_paired_economics.py:aggregate_telemetry` **repaired** (same identity rule — the auditor correctly rejected my 'outside the runtime path' framing: the claim was repository-wide, so it is repaired rather than re-scoped); one reader remains, `contracts._calibration_pairs:311,353`, which the auditor distinguishes as measurement pairing rather than the same billing-sum defect; (d) a response observed under two *different* id field names (`response_id` vs `api_request_id`) counts twice by design — merging id spaces would be a guess that could drop a bill, so it is recorded rather than inferred; Hermes records themselves are identifiable via their top-level `api_request_id`; (e) `used == 65` witness untouched and passing; (f) inherited lint outside the declared scope: `scripts/activate_omp_successor.py:193` E501 (pre-existing, not touched by this campaign, `ruff check src tests` stays clean) |
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

## Finish condition assessment (2026-09-22)

Label: **M00_PARTIAL_EXTERNAL_BLOCKER** — not `M00_CANDIDATE_QUALIFIED`. **Production activation: NOT PERFORMED.**

Evidence for the candidate, bound to the commits in this file and to `docs/intake/m00-evidence/`:
extension suite **772/772** (35 files, run from `brainstem/prime-extension`); the applicable Python set
**426 passed / exit 0** (15 files: schema, writer admission, ledger, vmem ×3, governor, telemetry ×2, backup,
migrations property, db, cleanup, contracts, worker recovery); `ruff` and `pyright` clean; `tsc` and
`eslint` exit 0; the replay cases with their mutations; the ten-worker sequence and the
ownership/receipt/cancellation matrix; the #2b increment with its mutation; the issuance-chain
reproduction.

**Correction (Jev, 2026-09-22).** The first version of this paragraph quoted "398 passed" — a figure
measured *before* the accounting change — as though it were bound to the committed bytes. Jev returned
that claim `contradicted` (0.68, confidence 0.51); it was right, the number was stale, and it has been
re-measured above on the current bytes. Digests of the three files whose behaviour this paragraph
covers, at commit `b886cf5` + the identity repair: `governor.py` `66ab9b22…`, `telemetry.py`
`98739b5f…`, `sensors.ts` `32138ef2…` (the first two thirds-of-hash prefixes shown; full values in the
session transcript). Note the auditor's earlier binding evidence named the pre-repair digests — that
binding covered the intermediate state, and these supersede it for the current one.

Gates that are genuinely open, each with what would close it:

| Gate | State | What closes it |
| --- | --- | --- |
| #3 acceptance review | audit done (9 PASS, 6 gaps repaired, then 2 more found and repaired); no *acceptance* review | an independent review of producer + consumer + custody + replay through a route this session lacks (mutating dispatch is refused by the host's own capability gate) |
| #4 issuance | reproduced; issuer authentication isolated | a trusted channel or OS-identity boundary between host and agent process — outside this boundary's constraints |
| #4 read-only lane | **PARTIALLY CLOSED 2026-09-22** — executed: a `read_only` claim cannot authenticate an authoritatively mutating attempt (Python: identical `UNAUTHORIZED_CALLBACK` with and without the claim, real credential still completes; extension: same test green). **Still open:** the *host's* declared `access_intent` at admission is what decides whether writer admission is required (`omp_adapter.py:111`, `:115`; `worker_protocol.py:755`), so a lying host is not independently detected | an enforcement mechanism that can be demonstrated, not a declared role — this is the #4 issuance boundary, unchanged |
| #5 descendants after a top-level result | **absent as an observation**: the host bridge advertises `execution_census: false` and only reacts to post-finalization frames, so a live descendant records nothing | a census-backed observation that a finished top-level result has no live descendants, or an explicit refusal to release without one |
| #5 restart between acceptance and release | **CLOSED 2026-09-22** — executed: accept in process A with no release (`COMPLETED, held, 1 result`), release in process B (`accepted`, `released, 1 result`), second release idempotent, replay of the released completion changing nothing; plus a pre-commit kill under a held write lock leaving **no** partial record and a retry committing exactly once | done |
| #6 reserve before admission | **IMPLEMENTED AND WIRED 2026-09-22** — atomic check+reserve (`governor.reserve_budget`, one `BEGIN IMMEDIATE`), CLI refusal exits 3, bridge `blocksDispatch` on `BUDGET_EXHAUSTED`/`ACCOUNTING_UNAVAILABLE`, called before `safeWorkerContextRunner`, consumed at the three finished/cleanup sites plus read-only acceptance; 6 Python tests + bridge case + 29 guard tests green | one stub-seam test that asserts the *wiring* (a blocking reservation stops a dispatch; cleanup consumes) — named, not yet written |
| #6 fail-open cap | **DECIDED AND IMPLEMENTED 2026-09-22** — the *check* keeps its documented fail-open (`used: None` + `ACCOUNTING_UNAVAILABLE`); the *reservation* fails closed on genuinely unresolvable accounting, while a session with no telemetry is a **resolved zero** (the `FileNotFoundError` → `used = 0` fix, found by direct observation that fail-closed-first refused every fresh session) | done; the resolution is recorded as a policy decision, not an accident |
| #6 remaining summing readers | `contracts._calibration_pairs`, `scripts/run_paired_economics.py` | the same identity rule, or a recorded authorized exclusion |
| cumulative qualification | **not claimed** — a frozen-subject pass is still blocked by the missing independent review of the new reservation code (three execution-capable roles refused by the host's settlement gate; the read-only verifier role has no execution tools) | an execution-capable independent verification of the reservation work on one frozen subject |

Per the mandate §10 this is a legitimate interim result: the candidate is honest about its boundaries,
and the remaining gates are named with their closure conditions rather than waived.

## Acceptance verification (2026-09-22) — read-only, and what it changed

An independent `implementation-verifier` reviewed the #3 subject (producer, consumer, custody,
replay) through the read-only lane it *could* use: **FAIL on the evidence criterion, UNDEMONSTRATED on
the four runtime criteria** because its harness exposes no execution. It did not reproduce an
unauthorized write or a credential disclosure, and it is recorded as an evidence verdict, not a
runtime one.

Two of its findings were real and are repaired, not argued with:

1. **A vacuous assertion in my own test.** The "no false `worker_completed` mirror" check read the
   telemetry store, but `mirror(...)` (`src/index.ts:883`) is fire-and-forget into the ledger-mirror
   engine and writes no telemetry record — so the assertion could never fail. It is removed, with a
   comment naming where the real sink is, and the mirror sink is now recorded as **not asserted by
   that file** rather than claimed clean. Same failure mode as the witness that could not fail
   (report §4) and the stale test count Jev caught: the check, not the code, was the weak link.
2. **A false provenance claim in my own evidence pack.** `MANIFEST.md` said the closure mandate was
   "tracked in this worktree"; it exists only in the main checkout. Corrected in place, with the
   correction visible.

Findings recorded open rather than repaired here:

- **Intermediate state not covered**: "terminal lifecycle accepted, attempt result still absent" is
  not reproduced by any case.
- **Untested disclosure path**: runner options carry the raw credential into the extension, and the
  downstream error path serializes arbitrary error strings without secret redaction
  (`sensors.ts:833-837`). Source argues it is not reached on the refusal path; no test proves it.
- **Constructed journals**: the replay cases build journal entries rather than capturing them from a
  host, so fidelity of the construction is assumed, not measured.

## Owner decisions and the corrected blocker classification (2026-09-22)

**Budget policy — DECIDED (policy closed, feature open).** Refuse new billable dispatch when the
applicable cap cannot be satisfied from authoritative accounting or an authoritative conservative
bound; reserve before dispatch **atomically** with the check; preserve existing numerical limits,
outstanding liabilities and root/descendant accounting; **no** automatic fail-open, **no** default
allowance for an explicit zero, **no** session/episode reset evasion. In-flight work under a valid
reservation keeps its accounting and completes/cleans up; a budget refusal must not release writer
ownership or fabricate settlement. Authorized non-billable local work (tests, inspection, recovery
diagnostics) stays available. **The decision authorizes no additional spending**, and the feature
remains open until implemented and demonstrated with local fixtures.

**Blocked ≠ satisfied.** The ledger's five blocked rows are **five unresolved acceptance gates**; the
`blocked` label says nothing about whether an authorized next step exists. Corrected split:

| Gate | Kind | Next executable step |
| --- | --- | --- |
| Ledger-mirror destination assertion | **executable** | assert the real mirror sink with a positive case and a mutation control |
| "Terminal accepted, attempt result absent" | **executable** | controlled failure at the write boundary; rollback or a documented pending state |
| Credential-bearing error serialization | **executable**, partly done | sentinel scan of recorded destinations now exists (below); still to do: force failures through the downstream handling with the sentinel |
| Journal fidelity vs the actual producer | **executable** | capture a journal from the candidate producer in disposable state and compare with the fixtures |
| Reserve-before-admission | **executable** (policy now fixed) | implement atomic check+reserve, keep refusal non-releasing |
| Trusted issuer channel | external — host/security primitive | identify the exact missing primitive or the separately required authorization |
| Host descendant census | external — observation/coverage capability | incomplete visibility must stay explicitly incomplete |
| Independent **runtime** verification | capability, not source authority | bounded verification surface: a verifier invoking bounded recipes and receiving its own results; **no** unrestricted mutation or production writer lease |

**Evidence distinctions to keep** (they must not be merged into one verdict):

```
Author-executed runtime evidence:      available where actually run
Independent source/artifact review:    obtained; adverse
Independent runtime execution:         not demonstrated
Authenticated verification attestation: not demonstrated
```

**Executed on this instruction:** a credential scan over every destination the replay route records
(journal, telemetry, returned outcomes, dispatch failures, refusal error string) for a real sentinel,
9/9 green. Its first version carried a *senseless* positive control — it pointed at a surface where the
sentinel cannot appear, because recovery never reconstructs the credential — and that control failed
after being committed (commit `a6e1910`); corrected forward rather than rewritten, and the honest scope
is recorded in the test: the assertion guards against a future change that starts threading the
credential into a record, and the search's sensitivity is proven against a string that does contain it.

## Handover: the ledger-mirror gate, ready to execute (2026-09-22)

Context reached its limit mid-task; this is the exact next operation, with the anchors it needs, so it
resumes without rediscovery.

**What was established for this gate:**

- `mirror(...)` (`src/index.ts:883`) is the only path that writes a completion mirror, and it is called
  from `emitWorkerCompletion` **after** the consumer accepts — `if (!outcome.ok) throw` precedes it, so
  in the current code a refused completion cannot reach the mirror at all. The gate is therefore about
  proving that property *and* that it is observable.
- `mirror(...)` → `mirrorFireAndForget` (`src/ledger-mirror.ts:447`) → `mirrorEvent` (`:410`), which
  spawns the Brain CLI with the record JSON on **stdin**, resolves fail-open, and retries **exactly
  once** after `MIRROR_RETRY_DELAY_MS`. It returns no promise to the caller, so the test must observe
  the destination rather than await a handle.
- The destination is the session's ledger: `state/sessions/<internal_session_id>/ledger.sqlite`
  (`internal_session_id` from the host session id), events keyed by the mirror `kind`
  (`worker_completed`). The disposable fixture already provides that home.

**The operation to implement** (unit of work, not a framework):

1. **Positive**: reuse the credential-present control (already in the file) so a completed attempt is
   accepted; poll the ledger, bounded (≈5 s, 100 ms steps, exit on first match), for exactly one
   `worker_completed` **correlated to that `task_id`**. A correlated-by-absence-of-poll is not a pass.
2. **Refusal**: the unauthenticated replay case; poll the same way for **no `worker_completed` for
   that attempt's `task_id`**, while explicitly allowing a refusal diagnostic to exist — the
   prohibition is a false authoritative completion, not an empty ledger.
3. **Mutation control**: execute the erroneous application path, not a direct row insert — call the
   real exported `mirrorEvent` with kind `worker_completed` and the refused attempt's fields, then
   require the step-2 query to find it, i.e. the assertion must fail once the regression exists.
4. Record the producer/route identity of the observed record (which kind, which attempt) so the
   evidence names what was captured.

**Then, in the owner's order**: interrupted terminal recording (does the terminal write and the result
row share one transaction? prove rollback or a documented durable pending state); credential-error
forcing through the real credential-bearing path (the sentinel scan already in place stays separate);
journal fidelity captured from the candidate producer; then reserve-before-dispatch under the decided
fail-closed policy, tested with zero allowance, unresolved accounting, concurrency, duplicate
observations and restart with outstanding reservations.

**Fix-forward commits to name in any report:** `a6e1910` is the historical failing-test subject (a red
control that was committed); `1da6871` is the correction. Qualification subjects must cite the latter,
never the former.

## Ledger-mirror gate: CLOSED (five elements executed, 2026-09-22)

The earlier "unresolved finding" is **retracted as a product defect** and replaced by the measured
account below. Cause of that false red: my own query selected the wrong destination path and then
matched the wrong shape — not the mirror, and not a fail-open `ok`.

**What the recorded evidence shows.** The completion mirror's CLI is
`python -m second_brain ledger append --session <host> --stdin-json`, which requires a complete
`BrainLifecycleEvent` (`event_type`, `event_id`, `timestamp`, `surface_visibility`, `ignorable`,
`payload` — `cli.py:3624` → `contracts.py:1178`). Hand-made envelopes therefore crash the CLI; that
was a probe defect and is recorded so it is not repeated. The destination is the **host session's**
ledger, `state/sessions/<internal_session_id>/ledger.sqlite`, and the fixture now creates that
session (the CLI refuses implicit initialization).

**Producer and consumer records are distinguishable, and that was the real anomaly.** For an accepted
completion the host ledger holds two `worker_completed` rows:
`{"child_omp_agent_id":…,"child_omp_session_file":null,"packet_sha256":…,"status":"completed","task_id":…,"worker_agent":"worker","worker_model":null}`
(the extension's mirror, worker fields verbatim) and
`{"event":"completed","result_sha256":…,"state":"COMPLETED","task_id":…,"updated_at":…}`
(the consumer's own authoritative record). My earlier "duplicate mirror" was this conflation. The
probe now classifies rows `mirror-attributed` vs `other-writer`, and one probe supplies both the count
and the diagnostics so an assertion can never disagree with the evidence printed beside it.

**Gate closure — all five, executed on candidate bytes:**

| Element | Result |
| --- | --- |
| Accepted-handler positive | PASS — dispatch observed; exactly 1 mirror-attributed record for the attempt |
| Refused-handler negative | PASS — no `worker_completed` mirror dispatched and no matching record |
| Real destination/query control | PASS — real `mirrorEvent` with the real envelope; record found at the real destination |
| Application-path mutation | DETECTED — mirror moved above the acceptance guard (`src/index.ts:1946`/`:1960`), and the same refusal test failed: *"no completion mirror dispatched for a refused attempt: expected [ { …(6) } ] to have a length of +0 but got 1"* |
| Exact restored candidate | PASS — `git checkout -- src/index.ts`, clean status, all three cases green |

**Method note for later mutation runs:** compare source identity with `Path.read_bytes()`; python
text-mode hashing plus EOL normalization under `.gitattributes` produced a spurious hash mismatch
(`506334e0…` disk vs `5645bdef…` blob) that git status independently proved harmless.

Test file: `brainstem/prime-extension/tests/worker-completion-mirror.test.ts` (`itSlow`, 60s per case,
real fixture subprocesses, disposable candidate state only). No runtime readback was added to the
product: the probe is test-side.

## Interrupted terminal acceptance/result recording: EXECUTED (2026-09-22)

Fixture seam used: `tests/fixtures/omp_replay_state.py` — `phase --phase accept` and `--phase release` are
deliberately separate processes ("running them as two invocations *is* a restart between acceptance and
release"), and `probe` reports durable state (`state`, `writer_ownership`, `attempt_results`, digest
presence).

**1. Pre-commit interruption (deterministic, not timing-based).** A held SQLite write lock
(`BEGIN IMMEDIATE`) blocked the accepting process *before* commit — verified alive and blocked after
2.5s — then it was killed. Durable state afterwards:
`state=WORKING, writer_ownership=held, attempt_results=0` → **no partial terminal record**, no result row,
no lost or prematurely released ownership. The same accept retried in a fresh process then succeeded
(`ok=true, status=completed`) and the state became `COMPLETED, held, attempt_results=1` → the interrupted
recording resumes and commits **exactly once**.

**2. Post-acceptance interruption (process boundary).** accept in process A, no release; probe:
`COMPLETED, held, attempt_results=1` → the accepted fact is durable and ownership is **not** released
prematurely. release in process B (fresh, persisted state only): `ok=true, status=accepted`; probe:
`COMPLETED, released, attempt_results=1` → released, still exactly one result row.

**3. Idempotency and non-regression.** A second release returned `ok=true, accepted, COMPLETED` with the
state unchanged; replaying the released attempt's own completion returned `ok=true, completed` and
changed nothing (`COMPLETED, released, attempt_results=1`).

**Rejected as non-evidence, recorded so it is not repeated:** an earlier attempt to interrupt mid-write by
killing at randomized offsets across 8 runs proved nothing — the accept window is ~231 ms dominated by
interpreter startup, and even a 2 ms kill landed *after* commit (`COMPLETED` every time). Timing-based
kills do not reach the commit boundary; the write lock does.

**Answered (settlement mapper, file:line):** the completion write set is **one atomic transaction**
(`src/second_brain/worker_protocol.py:1618→1788`, `conn.commit()` at `:1788`). There is **no durable
PENDING/recording state** anywhere on the Python side — the lifecycle states carry no PENDING member
(`contracts.py:529-533`) — so nothing half-recorded exists to resume: a pre-commit kill leaves the row
untouched (SQLite rollback), a post-commit kill leaves the state and the result durable together. The
durable state a crash *does* leave is the pre-terminal row (`{SUBMITTED,WORKING,UNRESOLVED}`,
`lifecycle_sequence=-1`), which `worker_recovery._interrupted_row` (`worker_recovery.py:223-257`,
predicate `:246-249`) reads back and `inspect_attempt` surfaces as `unresolved_conditions`
(`:128-186`). Recording a terminal result does **not** release ownership: it only renews the lease
(`worker_protocol.py:1743-1748`, written `:1755`); release requires an authenticated native receipt
carrying `executor_settled AND cleanup_complete`, otherwise `quarantined` (`:1435-1441`).

## The interrupted-recording window is post-commit, and it is the advisory ledger emit (2026-09-22)

The mapper's inference was testable, so it was tested. `record_worker_event` commits at
`worker_protocol.py:1788` and only then calls `_emit_worker_event` at `:1818` — outside the
transaction, with no `try/except`. Forcing that emit to raise (test-side patch of the module symbol,
no product change) produced:

| Observation | Result |
| --- | --- |
| Caller response | `{status: failed, failure_code: RESULT_UNAVAILABLE}` |
| Durable Brain state | `state=COMPLETED`, `writer_ownership=held`, 1 attempt receipt, packet digest matches |
| Session ledger | `worker_completed`/`result_corrected` events = **0** — the emit was lost in the window |
| `verify_result_binding(home, task, packet, real receipt sha)` | **`None`** (bound) |
| Replay of the same completion, emit working | `{status: completed}`; ledger still **0**; binding still `None`; no duplicate receipt |

**Classification, with the limits stated.** The accepted fact survives, ownership is neither released
nor leaked, and replay is idempotent — so this is **not** an authority or atomicity gap. For
attempt-bound tasks `verify_result_binding` short-circuits on the attempt receipt (`:661-673`) and
never reaches the ledger read (`:691-699`), which is consistent with the ledger being an advisory
mirror — the same posture as the extension's own fire-and-forget, fail-open completion mirror. What
remains open is narrower and is recorded rather than fixed:

- **Label asymmetry (finding, honest-accounting boundary).** The caller is told `RESULT_UNAVAILABLE`
  while the recording actually committed. It is fail-safe because replay is idempotent, but the label
  does not distinguish *committed* from *failed* as the acceptance criteria require the system to.
- **Lost ledger emit is not repaired**: nothing re-emits the completion event after an idempotent
  replay, so the audit trail keeps the gap. Acceptable only while the ledger is documented as
  advisory; if any consumer treats a ledger completion event as authority, that consumer is wrong and
  should be corrected to consult the receipt.

Both are recorded as M00 findings under the honest-accounting/source-authority boundary. Neither is
repaired by a product change here: the mandate forbids imposing synchronous readback on runtime
appends, and the replay already demonstrates no-duplicate, no-authority-loss behavior.

## Altered-journal downgrade check: EXECUTED, no downgrade (2026-09-22)

Requirement: a journal label must not decide whether an authoritatively mutating attempt needs
authentication. The authoritative decisions read the **persisted row's** `access_intent`
(`worker_protocol.py:984`, `:1151-1152`, `:1222`, `:1265`) — written once at admission (`:896`) — not a
journal entry. Executed against a persisted mutating attempt whose completion claimed `read_only`:

| Case | Response | Durable state |
| --- | --- | --- |
| claim `read_only`, **no credential** | `failed / UNAUTHORIZED_CALLBACK` | `WORKING, held, 0 results` |
| claim `read_only`, real credential | `completed` | `COMPLETED, held, 1 result` |
| claim `mutating`, no credential (control) | `failed / UNAUTHORIZED_CALLBACK` (identical code) | `WORKING, held, 0 results` |

The claim neither authenticates nor blocks: refusal is identical to the honest-claim control, and the
credentialed path still completes. Extension side, same result:
`tests/worker-completion-mirror.test.ts` → *"does not let a journal claiming read_only bypass
authentication"* passes (no dispatch, no mirror record, attempt not terminal, no result row, ownership
held). **#3 may take its narrow verdict on this point.**

**Still #4 source/host authority, and not made harmless by the above:** the Brain decides whether
writer admission is required from the host's declared `access_intent` at admission
(`omp_adapter.py:111`, `:115`; `worker_protocol.py:755` requires attempt-bound admission only for
mutating claims). A host that claims `read_only` while doing mutating work is not independently
detected by that gate. That is a trust decision about the admission issuer, not about the journal, and
it stays open under #4.

## #5 guarded finalization: ten-worker sequence and the ownership/receipt edges EXECUTED (2026-09-22)

Fixture: `tests/fixtures/omp_replay_state.py sequence --count 10` and `edges`, both on fresh disposable
homes (`omp-session`), no manual unlock, no worktree change, no restart, no expiry wait.

**Ten sequential local mutating workers on one worktree and one database:** `iterations=10`, and every
iteration reports `completion_status=completed`, `lifecycle_status=accepted`, `state=COMPLETED`,
`writer_ownership=released`, `attempt_results=1`; failure codes empty; task ids `w-1 … w-10`. Each
worker bound, executed, settled, cleaned up, released and permitted its successor.

**Ownership and receipt edges** (raw response codes):

| Case | Observed |
| --- | --- |
| settled without cleanup | accepted; then `writer_ownership=quarantined` |
| successor while quarantined | `failed / WORKTREE_WRITER_BUSY` |
| cleanup receipt completes | accepted → `writer_ownership=released` |
| successor after release | admitted (`edge-b`) |
| duplicate receipt | accepted, state unchanged |
| regressing sequence | `rejected / RECEIPT_CONFLICT` |
| replay without credential | `failed / UNAUTHORIZED_CALLBACK` |
| replay with credential | completed; first attempt still `COMPLETED/released/1` |
| cancellation before acceptance | `CANCELED`, `released`; later completion `INVALID_TRANSITION` |
| cancellation after acceptance | `rejected / OUTCOME_CONFLICT`; accepted outcome not rewritten |
| fourth writer while one held | `failed / WORKTREE_WRITER_BUSY` |
| late receipt after release | accepted; the *new* holder untouched (`WORKING/held`) — newer-owner protection |
| reused native id rebind | `rejected / BINDING_MISMATCH` |

This covers the mandate's named cases for immediate completion, outcome-before-cleanup, cancellation
before/after acceptance, delayed (late) callbacks, duplicate receipts, process/job-ID reuse,
late dispatch after revocation, newer-owner protection, and restart (separately: the two-process
`phase` experiments above). **One named case has no executed evidence: "active descendants after a
top-level result."** Its code is mapped — observers are armed in the spawn path
(`src/index.ts:1864-1883`), and on `session_shutdown` an attempt that still awaits cleanup keeps the
observer alive with a 30s expiry that only detaches (`:4430-4455`, comment: *"Expiry only detaches
observers: it never releases an unproven lease"*), while a cleaned-up attempt disposes immediately and
journals `observer-complete`. No test covers `observer-incomplete`/`observer-complete`/`observer-expired`
at all (grep over `tests/*.test.ts`). Testing it requires arming the observer through the real spawn
event, whose driving pattern already exists in `tests/worker-result-replay.test.ts`; a blind test would
risk passing vacuously, so it is recorded as a gap with its location instead of guessed.

**Release-gate finding (structural, cross-checked against the code):** for attempt-bound mutating
attempts, ownership release has exactly one gate — an authenticated native receipt carrying
`executor_settled AND cleanup_complete` (`worker_protocol.py:1435-1441`); recording a terminal result
only renews the lease (`:1743-1748`, written `:1755`), `reap` quarantines and never releases
(`:2041`, `:2072-2079`), and `record_worker_dispatch_failure` releases only an unbound reservation
(`:1261-1268`, `:1289-1292`). `settle_task` (`:1973-2029`) is a later approval transaction over an
already-recorded result and is not an ownership path. So the "single guarded finalization path" holds
for ownership: the other two names are distinct *purposes* (lease renewal, unbound-reservation cleanup),
not competing release gates.

## Jev adjudication of the closed-gate claims (2026-09-22)

`jev_verify`, seven claims batched against raw evidence excerpts (code lines, experiment output,
vitest output). Result: **7 verified, 0 contradicted, 0 unsupported, 0 flagged for review**.

| Claim | Verdict (confidence) |
| --- | --- |
| Terminal state + `worker_attempt_results` row commit in one transaction | verified (0.81) |
| Pre-commit kill leaves no partial terminal record; ownership still held | verified (1.00) |
| A `read_only` claim does not change authentication for a persisted mutating attempt | verified (1.00) |
| A refused completion yields no mirror dispatch and no mirror record | verified (1.00) |
| Ten sequential workers released and permitted successors without expiry wait | verified (0.99) |
| Ownership release requires an authenticated receipt with `executor_settled AND cleanup_complete` | verified (1.00) |
| The ledger emit is post-commit and its loss does not change the binding verdict | verified (1.00) |

Honest weighting: the weakest is the transaction claim at 0.81 — the evidence shows a single
`conn.commit()` with `rollback` on exception and the emit after `conn.close()`, which *supports* one
transaction without proving no second implicit one elsewhere in the write set. That is exactly what
the independent verifier's C4 checks by reproduction, so it is not accepted on the model's word.
Per the repository's Jev rules, these verdicts direct further investigation; they do not replace the
deterministic tests or the independent verifier, and they are not used here to close anything on their
own.

## Reserve-before-dispatch: Brain-side capability DELIVERED AND TESTED, extension gate NOT YET WIRED (2026-09-22)

Owner policy (register line 370) is "implement atomic check+reserve, refusal non-releasing". What is
now in the candidate and executed:

| Element | State |
| --- | --- |
| `migrations/0025_budget_reservations.sql` | new table + unique `(session_id, task_id)` index |
| `governor.reserve_budget / consume_budget_reservation / list_budget_reservations` | implemented |
| `governor reserve-budget \| consume-budget-reservation \| budget-reservations` CLI | implemented; a refusal exits **3** so a caller can fail closed without parsing stdout |
| `tests/test_governor_reservations.py` | 6 passed |
| `budget-bridge.reserveBudget` + case in `tests/budget-caps.test.ts` | 4 passed (file), including the new case |

Evidence of the acceptance items: check and reservation share one `BEGIN IMMEDIATE`, so two concurrent
`reserve-budget` processes for 80 of a 100 cap cannot both succeed (test asserts exactly one reserved
row); a reservation survives a process boundary, is idempotent per `(session, task)` (re-reserving does
not consume twice), is consumed exactly once, and a refused reservation writes **no** row — so it cannot
release or alter writer ownership. `check-budget` semantics are unchanged and still report spend, not
reservations. Gates: `ruff` clean, `pyright` 0 errors, `tsc` clean, vitest 9 passed, pytest 6 passed.

**Policy decision recorded, because it changed the first draft:** a session with no telemetry yet is a
**resolved zero** (`FileNotFoundError` from `_session_total_tokens` → `used = 0`), not unresolvable
accounting. Treating it as unavailable made the first worker of every fresh session unrestartable —
observed directly (`reserved: false, reason: ACCOUNTING_UNAVAILABLE` on an empty home). Genuinely
unreadable or malformed usage still fails closed and refuses. In the bridge, `BUDGET_EXHAUSTED` and
`ACCOUNTING_UNAVAILABLE` set `blocksDispatch`; a transport failure reports `RESERVATION_UNAVAILABLE`
without blocking, which preserves the availability semantics the existing check bridge already has.

**NOW WIRED (same session, after the capability commit).** The extension reserves immediately before
`safeWorkerContextRunner` — the first budget-consuming step of a dispatch — through a new
`budgetReserver` seam, and a blocking refusal returns `{block: true, reason: BRAIN_WORKER_BUDGET_*}`,
records an `omp_worker_budget_refused` routing record, writes **no** admission, and touches no
ownership. Consumption is wired at the three sites that mean "finished": the dispatch-failure
acceptance (`:1258`), the live cleanup acceptance (`:1470`), and the recovered cleanup acceptance
(`:2070`), plus the accepted-completion path **for read-only attempts only** (`admission.cleanupAccepted`
is true from admission for them, so the cleanup transition would never fire and their reservation would
leak). A mutating attempt keeps its accounting until the cleanup facts arrive, which is the policy.
Consumption is fail-soft and idempotent: an error is recorded and never fails the completion.

Gates on the wired candidate: `tsc` clean, `eslint` clean on the touched files, and **29 tests across 5
guard files green** (`worker-completion-mirror`, `budget-caps`, `worker-result-replay`,
`worker-result-authority`, `native-settlement`) — so the settlement guard behaviour the rest of this
campaign depends on is unchanged.

**Honest remaining gap on this item:** the bridges are tested and the guard paths are tested, but no test
yet asserts the *wiring* itself — that a blocking reservation stops a dispatch at the call site, and that
a cleanup transition actually consumes. That is a stub-seam test through the spawn path, and it is the
next step for this item. It is not claimed as demonstrated.

**Delegation note:** mutating workers are unavailable in this session — both `task` and
`feature-implementer` dispatches were refused by the harness with
`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` — so per the mandate's fallback the authorized driver
implemented this in the isolated candidate. Read-only specialists (`scout`, `implementation-verifier`)
dispatch normally; the verifier has **no execution tools**, so its verdicts on executed claims were
UNDEMONSTRATED by construction (useful static corroboration, no reproduction). An execution-capable
verifier is still outstanding for the new reservation evidence.

## Independent verification availability, measured today (2026-09-22)

Required independent review of the new code is **unavailable in this session**, and the attempts are
recorded rather than asserted:

| Attempt | Result |
| --- | --- |
| `implementation-verifier` (read-only reviewer role) | dispatched; reported it has **no process-execution tool** (its own capability listing showed only Jev MCP devices) → every executed claim came back UNDEMONSTRATED by construction |
| `task` (general-purpose) | dispatch refused: `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` |
| `feature-implementer` | dispatch refused: `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` |
| `integration-engineer` | dispatch refused: `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` |
| `scout` (read-only research) | dispatches normally; produced the settlement mapping and the spawn recipe — analysis only, no execution |

So the harness currently permits **read-only research agents** and refuses **worker-settling agents**. That
is why the reservation work was implemented by the authorized driver in the isolated candidate (the
mandate's named fallback for unavailable mutating workers), and why the executor/author distinction is
kept explicit here: the tests and the mutation/restore evidence are author-executed and are labelled as
such, never as independent execution. An execution-capable independent verifier remains outstanding for
the reservation work and must not be claimed as satisfied.

## Reserve-before-dispatch: the wiring itself is now tested, and the test found a leak (2026-09-22)

The stub-seam wiring tests the previous entry named as missing now exist in
`tests/wiring.test.ts` and drive the real spawn path (`tool_call` with `input.agent = "scout"`, the
read-only roster entry, plus `makeCtx()`; the recipe's key detail is that an absent `agent` sends the
call down the mutating path where the settlement-capability guard blocks it — which is exactly the
`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` the harness returned for worker dispatches).

| Test | Asserts |
| --- | --- |
| "blocks the dispatch when the budget reservation is refused, before any preparation" | `{block: true, reason: BRAIN_WORKER_BUDGET_BUDGET_EXHAUSTED}` from the reserve seam, and the context runner is **never called** — the refusal short-circuits before the first budget-consuming step |
| "returns the reservation when the dispatch never happens" | a preparation failure consumes the reservation, so repeated failures cannot exhaust the cap |

**The second test found a real leak in the wiring I had just written:** on preparation failure the code
released previously prepared admissions but never freed the *failing* item's reservation, so every failed
preparation stranded capacity until the cap was gone. Fixed in `src/index.ts` by consuming the item's
reservation in that branch, with the reason spelled out in a comment. This is the kind of defect the
missing test was hiding, which is why the gap was recorded rather than assumed benign.

**Also fixed, and it was a real regression I introduced:** my consumption calls reached the *real*
governor bridge during tests, which failed and appended extension-error records, breaking
`wiring.test.ts` "attributes a completion to the worker whose manager job id it names" (expected no
records, got 4). Isolated by stashing my uncommitted work (still failed) and then checking out the
pre-wiring `index.ts` at `b4c161a` (**passed**), which proved the wiring caused it. Fix: `loadFactory`
now defaults the two new seams the same way it already defaulted `budgetRunner`, so a test that does not
care about budget never touches the real bridge.

**Gates on the current candidate:** full extension suite **781 passed / 36 files** (was 772 before this
work), `tsc` clean, `eslint` clean, `ruff` clean, `pyright` 0 errors, `pytest tests/test_governor_reservations.py`
6 passed. Still author-executed, not independently verified — the independent-execution availability table
above stands.

## STOP DECISION (2026-09-22) — M00_PARTIAL_EXTERNAL_BLOCKER

Candidate: branch `brain/m00.3-producer-guard`, HEAD `821a8f1ab5b9c5943d29182fc45b85cec928ddb4`, clean tree. **Production activation: NOT PERFORMED. No
canonical-state mutation, no lease release, no approval rewrite, no new spending.**

**Executed today, each with evidence recorded above:** the ledger-mirror gate (accepted positive,
refused negative, real destination control, application-path mutation detected, exact restored bytes);
interrupted terminal recording (pre-commit kill under a held write lock leaving no partial record;
two-process accept/release; release idempotency; replay-after-release changing nothing); the post-commit
window experiment with its two recorded findings; the altered-journal downgrade check on both sides of
the boundary; the #5 ten-worker sequence and the ownership/receipt/cancellation/late-callback/reused-id
matrix; reserve-before-dispatch (capability, wiring, wiring tests, plus a leak the new test found and a
regression it exposed); and a Jev adjudication of seven milestone claims (all verified, none
contradicted). Gates on the frozen subject: extension **781 passed / 36 files**, `tsc`, `eslint`, `ruff`
clean, `pyright` 0 errors, `pytest tests/test_governor_reservations.py` 6 passed.

**Terminal condition demonstrated (not asserted):** the required independent review is **unavailable in
this session**, measured — `task`, `feature-implementer` and `integration-engineer` dispatches are all
refused by the host's own gate with `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`, and the
`implementation-verifier` role that does dispatch has no process-execution tool (it returned
UNDEMONSTRATED by construction and supplied only static corroboration). Everything executed here is
therefore **author-executed** and labelled as such; no author result is presented as independent
execution. The external dependencies recorded earlier also stand: a trusted issuance channel between
host and agent process (#4), a census-capable host bridge (`execution_census: false` today, which is why
no executed case exists for "active descendants after a top-level result"), and an independent runtime
execution surface.

**Smallest specific actions that unlock the remainder:**

1. Grant an execution-capable **independent** verification route (a permitted worker-settling dispatch, or
   a verifier role with a shell) and re-run the four reservation claims plus the mirror gate on the frozen
   subject. That alone is what stands between this candidate and a cumulative-qualification claim.
2. For #4: a trusted issuance channel or OS-identity boundary between host and agent process — without it
   the host's declared `access_intent` remains the only thing deciding whether writer admission is
   required.
3. For the descendants gate: a host bridge advertising an execution census, or an explicit refusal to
   release without one.

**Executable work that remains and is NOT blocked** (recorded so it is not mistaken for a closed gate):
the #6 remaining summing readers (`contracts._calibration_pairs`, `scripts/run_paired_economics.py`)
under the same identity rule, and the #2b test-strength items (strict-prefix fixture, VMem public reader,
separate-process first open). Neither was started today; both are small and independent of the blocked
routes.

## Bounded STOP decision invoked (2026-09-22)

`second_brain stop decide` (P3.6) was invoked with the current session/task identity and returned:

```json
{"decision": "stop", "continuation_forbidden": true, "completion_condition_state": "blocked",
 "reason_code": "M00_PARTIAL_EXTERNAL_BLOCKER", "session_id": "2026-09-22T10-44-39-421Z_01a0c8b7-bb7d-7622-aee8-4ceb20ed7e94",
 "task_id": "m00-recursive-completion", "stop_id": "m00-stop-20260922", "sequence": 1,
 "final_substantive_event": "821a8f1 wiring tests + leak fix; 781/781 extension tests green"}
```

`--verification-state blocked`, `--completion-condition-state blocked`, `--triggering-condition` naming the
measured unavailability of independent review.

**Stated honestly:** it was invoked against a **disposable Brain home**, not the canonical one, because this
campaign's boundaries forbid canonical-state mutation (no production activation, no canonical writes). The
machine therefore evaluated and recorded the decision in a throwaway store; the durable campaign record is
this register and the commit history, and the decision's content is reproduced verbatim above. A driver
permitted to write canonical state can re-invoke the same command with the same arguments against the real
home.

## STOP scope reconciled, and the post-commit recording/delivery defect repaired (2026-09-22)

**STOP scope reconciliation.** Inspected through permitted interfaces: `continuation_forbidden` is
**computed and printed only** (`cli.py:3793`, `:3808`) and the decision writes a ledger event
(`stop-<id>`); **no code path reads a stop decision**, so the record is evidence, not a lock. Nothing was
deleted, overwritten, or evaded, and no alternate home was used to dodge enforcement. The supported
supervisory act is therefore the owner's direction in this correction — continued isolated
implementation permitted, qualification still blocked — which is what is being acted on. The record and
its inputs remain unchanged.

**The defect was silent loss, and that is worth stating precisely.** `_emit_worker_event` ended in
`except Exception: return` — a failed ledger append was swallowed, so the caller was told the completion
succeeded while the notification was gone. My earlier reproduction of a *false failure* came from
replacing the whole emitter with a raiser, which is not the shipping shape. Both shapes are now covered:

- `migrations/0026_worker_notification_outbox.sql` adds `notification_event_key`,
  `notification_pending`, `notification_delivered_at` to `worker_task_meta`.
- The outbox intent (`notification_pending = 1`, with `session_id` preserved via `COALESCE`) commits **in
  the same transaction** as the terminal fact, so the notification is reconstructible from durable state.
- `_emit_worker_event` now **reports** `delivered` / `already_delivered` / `pending` instead of
  swallowing. `record_worker_event` returns `recording: committed` with `notification: delivered|pending`,
  and `omp_adapter` exposes both, so a committed recording can never read as a failed result and a lost
  notification can never read as delivered.
- `reconcile_worker_notifications(home, task_id=…)` rebuilds the payload from the committed row
  (`terminal_notification_payload`), and because the ledger event id is a content hash of that payload
  and `events.event_id` is `UNIQUE`, a repeated delivery is detected as a duplicate — delivery, not an
  error — rather than becoming a second logical event.
- `tests/test_worker_notification_outbox.py` (4 passed): interruption at the **real** append point
  (`LedgerStore.append_events` fails, emitter reports pending, recording committed, no
  `RESULT_UNAVAILABLE`); reconciliation delivers it through durable state only; a second reconciliation
  over an already-recorded event is duplicate-safe (one event, pending cleared); the uninterrupted path
  reports `delivered`.

Two defects in my own patch were found and fixed by these tests rather than by inspection: the outbox
upsert originally created the meta row with a **NULL `session_id`**, which the emitter preferred over the
request session and so suppressed delivery; and an inserted `return "delivered"` landed *after* the
`except` branch's return, making success unreachable and mislabelling every delivery as pending.

**Worktree accident, disclosed.** A `git stash push` of mine failed on an untracked path, but a `;` in
the same command line still ran `git stash pop`, which applied a **pre-existing stash from another
branch** (`epitaxy: pre-switch…`) into this worktree, leaving five conflicted files and 72 untracked
`memory/semantic/mem-*.md` copies. Repaired: the unintended application was reverted file by file with
`git checkout HEAD --` (my own two sources excluded), the accidentally applied untracked copies removed,
and the **stash entry left intact** so that work is preserved. `tmp_t03_probe.txt` is not mine and was
left alone. The `;`-after-`&&` habit is what caused it; no stash was popped since.

**Pre-existing failures, not mine (isolated by file copy, no stash):** with both of my changed files
reverted to committed bytes, `tests/test_worker_protocol.py::test_context_handoff_reuses_unchanged_and_emits_changed_delta`
(`KeyError: 'context_metadata'`) and `::test_result_hash_and_correction_lifecycle_are_canonical`
(`COMPLETION_AUTHORITY_UNAVAILABLE` vs `UNAUTHORIZED_WORKER`) still fail. Left exactly as found. Also
outstanding and **mine to update**: four migration-pin assertions in `tests/test_writer_admission.py`
expect `[23,24]`/`[24]` and now see the legitimate `25`/`26`.

**Still executable, not done:** the reservation fails-before/passes-after proof with the owner's four
distinctions (cancel exactly once when genuinely unused; preserve exposure when dispatch is uncertain; no
unconditional refund in `finally`; duplicate recovery and newer-request protection); the migration-pin
updates; the #6 summing readers; the #2b test-strength items; and a bounded investigation of an existing
independent-verification route (not by retrying the refused roles).

## RESUME CAPSULE — ledger-mirror trace (2026-09-22, context exhaustion)

**State:** candidate worktree `.worktrees/m00.3-producer-guard`, branch `brain/m00.3-producer-guard`.
Verify `HEAD` and cleanliness before continuing; the last commits are `ffabe8a` (mirror gate WIP) and
this capsule's commit. Register is authoritative; no other file needs re-deriving.

**What the trace established (each item is measured, not inferred):**

1. `mirror(...)` (`src/index.ts:883`) is the only completion-mirror path and runs **after** the
   consumer accepts (`if (!outcome.ok) throw` precedes it) — so a refused completion cannot reach it.
   The refused-completion case of `tests/worker-completion-mirror.test.ts` passes on both evidence
   kinds (no dispatch, no record).
2. The mirror's CLI is `python -m second_brain ledger append --session <host> --stdin-json`, and it
   requires a **complete** `BrainLifecycleEvent`: `event_type`, `event_id`, `timestamp`,
   `surface_visibility`, `ignorable`, `payload` (`cli.py:3624` → `contracts.py:1178`). Hand-made
   envelopes therefore crash the CLI — a fixture/probe defect, **not** evidence about the mirror. Do
   not probe this destination with hand-built payloads; use the real `mirrorEvent` builder.
3. The destination is the **host session's** ledger, `state/sessions/<internal_session_id>/ledger.sqlite`
   where `internal_session_id = ledger.internal_session_id(host_session_id)`; the fixture now creates
   that session (`tests/fixtures/omp_replay_state.py`), because the CLI refuses implicit
   initialization. In the trace home that path held **0 events** after hand-made probes.
4. Open question, unresolved: the control's `mirrorEvent` returned `ok: true` while the query found no
   matching record. So one of these holds — (a) it appends elsewhere, (b) the stored payload shape
   does not match the query's `LIKE`, (c) `ok` is fail-open and nothing landed. **(c) is a defect.**

**Next operation, exactly (one edit + one run, no new framework):**

In `tests/worker-completion-mirror.test.ts`, in the destination-control case, immediately *after*
`result.ok` is asserted, dump the destination instead of querying it:

```
for each state/sessions/*/ledger.sqlite:
    SELECT event_type, substr(payload_json,1,200) FROM events ORDER BY rowid DESC LIMIT 3
```

plus the child process's own stdout/stderr if the seam can expose it. Decide (a)/(b)/(c) from what is
actually stored — then, in order: fix the query to the real shape (b) and re-run; or point the query at
the real destination (a) and re-run; or, if (c), repair `mirrorEvent` so `ok` requires an observable
append (do **not** add a synchronous readback to every runtime append — that is a qualification
concern, not a runtime one), then re-run. Then run the application-path mutation: make the refusal path
mirror completion (a controlled edit in disposable candidate state only) and require the refused case to
fail; restore exact bytes and require it to pass again.

**Then the remaining executable queue (unchanged order):** interrupted terminal acceptance/result
recording (establish shared transaction or documented durable pending state); forced credential-bearing
error handling through the real path (the sentinel scan already in place stays separate evidence);
journal fidelity captured from the actual candidate producer; integrated producer/adapter/consumer
replay qualification; atomic reserve-before-dispatch under the decided fail-closed policy (zero
allowance, unresolved accounting, concurrency, duplicate observations, restart with outstanding
reservations).

**Honest classifications to preserve:** `a6e1910` is a historical red subject (corrected by `1da6871`);
author execution ≠ independent execution; the adverse acceptance verdict against `2f42873` stands and
must be revisited, not waived, against the corrected subject. External and still unavailable: trusted
issuer primitive, host descendant census, independent runtime execution surface.

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
