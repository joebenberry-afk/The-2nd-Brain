# M00 campaign register

## Active candidate: orchestrator removal (2026-09-23)

**Status:** `M00_ORCHESTRATOR_REMOVAL_IN_PROGRESS`; NOT QUALIFIED;
production NOT ACTIVATED. This register and
[`Second_Brain_M00_OneShot_Closure_Mandate.md`](Second_Brain_M00_OneShot_Closure_Mandate.md)
form one acceptance contract under the
[`Orchestrator Removal Mandate`](Second_Brain_Orchestrator_Removal_Mandate_2026-09-23.md).
The orchestration-free v3 roadmap is
[`Second_Brain_V3_Orchestration_Free_Roadmap_2026-09-23.md`](Second_Brain_V3_Orchestration_Free_Roadmap_2026-09-23.md).
All older native/governed directions below are dated historical evidence.

### Boundary and legacy behavior

The harness owns agents, models, tools, task admission, STOP, retries,
cancellation and completion. Brain retains memory, context, skills, source
and delivery provenance, its own resource limits, and passive usage. No
governed or test-only execution engine may remain. Explicit worker operations
in `omp-routing` and Hermes hooks refuse `ORCHESTRATION_REMOVED` before
opening a Brain home. `brainctl stop`, `worker-plane`, and retired governor
budget operations return nonzero inert refusals. Unregistered Hermes worker
tools and `llm_request` model middleware cannot reactivate the engine. Old
orchestration config and known v2 worker resource keys do not assign host
authority; unrelated retained config stays validated.

Candidate-only source changes and isolated tests are permitted. Historical
migrations 0014, 0022–0028, worker receipts/outbox/reservations and sealed
host-patch records stay byte/data-preserved, not settled or refunded. A
candidate manifest is a byte comparison, never protected approval.

### Finding disposition by exact subject

| Finding | Retired subject | Applicable retained subject/status |
|---|---|---|
| M00-CORD-01/02, SB-ORCH-001, #3/#4/#5 | Coordinator custody, effective-grant worker admission, leases/settlement: `RETIRED_BY_PRODUCT_SCOPE — NOT PROVEN` | Native host noninterference and memory/context consumer integrity: `OPEN` until real path qualified. |
| SEC-AUTH-01 | Worker issuer only: retired, not fixed | Protected approval and caller-authored verification action: `OPEN`. |
| SEC-AUTH-02 | Worker completion/observer-only authority: retired | `remember --grade VERIFIED`, origin, policy lane and trusted-memory authorization: `OPEN`. |
| SEC-INTEGRITY-01 | Active worker settlement branch retired | Ledger chain, replay and migration integrity: `OPEN`. |
| SEC-SKILL-01 / SB-PROMOTION-004 | None of approved skill consumption | Evaluation, protected approval, exact consumed bytes/dependencies: `OPEN`. |
| FSUPD-01 / FSPATH-03 | Patched-host activation/rollback retired without qualification | Extension install, approval, copy and rollback: `OPEN`; installer tests do not prove protected approval. |
| FSLNCH-02 | Patched-host launcher retired; original seal retained | No current patched launcher to qualify. |
| SEC-HOOK-02 | No general retirement | Retained hooks/process executable trust: `OPEN`. |
| SB-PROMPT-002 / 003 | Worker task-context renderer retired | Project-ID model-visible sinks remain subject to validation; retrieved content has no instruction authority: `OPEN` for integrated proof. |
| SEC-DEP-01 | No security waiver | Current dev lockfile advisory state: `OPEN` until assessed. |
| Aggregate usage reader | No orchestration subject | `OPEN` (retained, pre-existing): `governor.parse_telemetry_session` reports `0` for counters a completed invocation omitted (`usage={}`), against the module's own honesty rule; the strict `_session_total_tokens` reader raises. Recorded, not waived, not fixed in this removal candidate. |
| `scripts/run_p3_promotion_campaign.py` | Not an orchestration subject | Retained operator-invoked evaluation harness (operator-frozen model env; no Brain admission/lease/settlement; vendor CLI owns permissions). Scope-boundary header added; any future Brain-authority reach from it is a defect. |
| #2a/#2b, #6, DOC-14 | Agent reservation/admission retired | Schema/recovery, honest passive usage and missing DOC-14 source: `OPEN` where applicable. |

An `OPEN` retained HIGH blocks qualification; no row treats removal as an
historical PASS. The original September 21 audit and former M00 negative
results remain unchanged.

### Test-retirement mapping

| Retired active tests | Removed requirement and entry point | Retained proof |
|---|---|---|
| Python `test_worker_*`, writer-admission controller cases, `test_orchestration`, `test_native_orchestration` | Worker task packet, lease, settlement, recovery and test-governed switch (`worker_protocol`, `worker_recovery`) | `test_omp_adapter`/`test_cli` inert refusals; `test_migration_chain` held/unresolved historical rows; `test_ledger`, `test_handoff`, `test_vmem` memory recovery. |
| Python `test_model_routing*`, governor reservation/lifecycle cap tests, scout launcher tests | Brain model choice, agent budget admission, spawned scout | `test_autoinject` retrieval classification/useful delivery; `test_governor` passive dedupe/unknowns; `test_scout` local evidence maps. |
| Hermes worker/result/correction and middleware cases | Brain persistent-worker launch, model rewrite, completion authority | `test_hermes_adapter` actual native model usage, skills, memory, raw result and early refusal. The earlier seven reported Hermes failures concerned the retired worker subject, not a passing historical result. |
| TS orchestration guards, budget/worker/STOP bridges and their probes | Controller factory, native settlement observer, alternate governed factory | `host-noninterference.test.ts`, retained wiring/context/Lean/prefix tests and actual native harness review. |
| `test_omp_canary_tools` live successor-identity and activation tests | Host-patch campaign, launcher and settlement watchers | `test_release_history` binds the original `budget-bridge.ts` Git blob and sealed records to their original revision; `test_prime_installer` exercises disposable extension copy/rollback and candidate byte drift. Current candidate receives its own identity. |
| P4 `driver_worker` and `failed_worker` scenarios | Repository worker-plane CLI | Remaining memory/cache/backup/session scenarios in P4 qualification and its verifier. |

The user's earlier Python run reported 2,373 passed / 7 skipped / 8 failed;
that is prior-subject evidence, not this candidate's result. The seventh
skip is the POSIX write-bit test on Windows ACLs, retained for POSIX; six
governed-subprocess skips are retired with the removed engine. The seven
reported Hermes failures and the one historical-canary failure belonged to
retired subjects and were dispositioned above, not re-pinned. On the frozen
removal commit the retained suites are green
(`orchestrator-removal-gate-20260923.md`); that is a candidate-local result,
not production or qualification.

### Gate and preservation ledger

Executed evidence for the frozen removal commit `ce15820` is recorded in the
tracked pack: `docs/intake/m00-evidence/orchestrator-removal-gate-20260923.md`
(exact subject digest, commands, results, limits).

- Test-home audit and subprocess origin pinning preceded the suite. A previous
  real-home telemetry contact was observed read-only; no before-state exists,
  so canonical write preservation cannot be retrospectively proved. Do not
  restore, migrate, or mutate live state to disguise the gap.
- Frozen-subject results: ruff clean, pyright `0 errors`, Python
  **2108 passed / 1 skipped / 0 failed** under a disposable home, extension
  `tsc --noEmit` and ESLint clean, extension suite **26 files / 600 tests
  passed**; every disposable home was still empty afterwards.
- Directly executed refusal and retained-path checks (exact commands and
  outputs in the evidence document §2.1): all five retired CLI families exit 2
  with `ORCHESTRATION_REMOVED` and leave an absent/nonexistent home untouched;
  `init` → `remember` → `recall` → `autoinject shadow` all succeed in a
  disposable home with no task admission involved.
- Independent review: a read-only implementation verifier returned
  `UNDEMONSTRATED` (its agent type could not execute commands) while
  confirming statically that the retired modules are gone and no alternate
  switch remains; a read-only security pass independently reproduced the
  aggregate-usage coercion and classified the promotion campaign script as
  operator-invoked evaluation. Further child spawns are refused by the
  **installed production extension**
  (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`), so independent runtime
  coverage stays partial and is reported as such.
- Complete the source/config/test/docs cutover, then run isolated Python/TS,
  package and DB checks with hashes tied to exact candidate bytes.
- Check native single/batch task, hub, model, tool, cancellation and memory
  consumer behavior through the real host surface. Static proof alone does
  not establish those interactions. Only a read-only installed-CLI probe was
  performed; `M00-NATIVE-ORCH-01` stays `OPEN`.
- Freeze a local commit stack preserving pre-existing attribution. Independent
  read-only review must see the actual candidate plus results. A material
  correction invalidates affected checks and requires a new subject.
- Resolve retained applicable HIGHs before declaring the finite gate passed.
  No production activation or Stage 1 v3 claim follows from an incomplete gate.

## Historical campaign record — superseded, preserved verbatim below

Earlier identities, pass counts, deferrals and governed-track instructions
belong to their dated subjects only. They are not an alternative runtime or
the current acceptance checklist.

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

## Reservation lifecycle: implemented and tested in the Brain; extension call site NOT yet switched (2026-09-22)

Implemented exactly the model the owner specified — capacity returns only on proven-unused evidence,
uncertainty stays a liability, no unconditional refund:

| Element | State |
| --- | --- |
| `migrations/0027_budget_reservation_lifecycle.sql` | `episode_id`, `cancelled_at`, `cancel_reason`, `resolved_at`, `resolution`, `actual_tokens` |
| `governor.cancel_budget_reservation(..., evidence=...)` | refuses without `evidence="proven_unused"`; idempotent (`already_cancelled`, no second refund); refuses a consumed reservation |
| `governor.mark_budget_reservation_unresolved` | keeps the liability, records the reason |
| `governor.reconcile_budget_reservations` | decides from durable evidence only: no attempt row → `cancelled_unused` (`NO_ATTEMPT_RECORDED`); native binding or non-SUBMITTED → consumed; SUBMITTED without a binding → **unresolved**, liability kept |
| `governor.reserve_budget` | explicit `cap <= 0` always refuses with no default fallback; outstanding is **episode-scoped** |
| `governor._episode_host_sessions` | shared by spend accounting and reservation liability, so a later session in the same root episode adds liability instead of resetting it |
| `governor.list_budget_reservations` | the *outstanding* view: cancelled and consumed rows excluded |
| `tests/test_budget_reservation_lifecycle.py` | **11 passed** — the owner's ten cases plus the two reconcile branches (bound → consumed, unbound → unresolved) |

**Not done, and deliberately not claimed:** the extension still calls `consumeReservation(...)` on the
preparation-failure branch (`src/index.ts`, the `OMP_BATCH_PREPARATION_FAILED` path), which resolves the
reservation as consumed rather than cancelling it with proven-unused evidence. That is the correct *effect*
in that branch but the wrong *route* under the owner's rule, and the `cancelBudget` bridge step is the
next edit. Nothing is claimed closed for the reservation feature until that swap lands and its
evidence-gated cancellation is exercised through the wiring.

**Still mine to do, in the owner's order:** the four `test_writer_admission.py` migration-pin updates
(toward an expected ordered migration set + current schema version + migration 25/26 semantics, with the
24→25→26, 25→26, 26→no-op and interrupted-migration upgrade paths); #6 summing readers on the same
episode/root accounting; the #2b test-strength items; the bounded independent-verification-route
investigation; final integrated suites; then cumulative review. Gate results on the current bytes:
pytest 21 passed across the three touched modules, `ruff` one remaining finding, `pyright` 6 errors (at
least one in my outbox test's fixture loader) — to be cleared before any review.

**Evidence-strength labels kept as instructed:** the two `test_worker_protocol.py` failures are recorded as
**reproduced on the comparison subject / not attributable to this patch** (file-copy isolation at
committed bytes), never as "pre-existing" without an earlier baseline run, and they keep their exact
signatures in the record. The ten-worker result keeps its scope: repeatable finalization through the
tested route only — it does not demonstrate trusted issuance or descendant coverage.

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

## Reservation wiring closed through the real route, and two defects it exposed (2026-09-22)

**Candidate:** branch `brain/m00.3-producer-guard`, commits `2dc8f26`, `507ad95`, `68bce68` plus the
reader work below. Author-executed, as before: no independent executor is available in this session.

**The route is closed.** `OMP_BATCH_PREPARATION_FAILED` no longer consumes its reservation. It calls
`cancelBudget` (new bridge) → `governor cancel-budget-reservation` with `evidence="proven_unused"`,
which the Brain requires before it returns capacity. The proof that this branch runs before any
billable/native dispatch is carried on both sides: the host call is blocked (`{block: true}`), so no
tool ran, and the durable attempt row the reconciler reads as "dispatch observed" does not exist.

`tests/reservation-integration.test.ts` drives the **real** factory → real bridges → real governor CLI
against a disposable home, and establishes the owner's chain plus its controls:

| Case | Result |
| --- | --- |
| reserve → preparation fails → no dispatch → cancel(`proven_unused`) → `cancelled_unused` | pass; row `resolution='cancelled_unused'`, `cancel_reason='OMP_BATCH_PREPARATION_FAILED'`, no `worker_tasks` row |
| duplicate preparation-failure handling → no second refund | pass; the late dispatch is refused `BRAIN_WORKER_BUDGET_RESERVATION_CANCELLED` before preparation, one row, one refund |
| preparation succeeds → cancellation unavailable → normal consume | pass; reservation stays open, consumed once with `resolution='consumed'` |
| cancellation bridge fails → no local capacity restore | pass; row stays uncancelled, the next claim is refused, the failure is recorded |

The other side of the route is now refused at the Brain too: `reserve_budget` refuses to reopen a
resolved reservation (`RESERVATION_CANCELLED` / `RESERVATION_CONSUMED`), and the reservation bridge
fails closed on every Brain-side refusal instead of only on an exhausted cap.

**Defect 1 — the reservation claimed a fresh full role cap.** Found by the integration test, not by
inspection: the extension reserved without `--tokens`, so the Brain reserved `worker_tokens` outright.
Since the cap covers all worker usage in the episode, `used + outstanding + requested > cap` refused
**every** dispatch as soon as the session had recorded any usage. An untargeted claim is now the
*remaining* allowance (`cap - used - outstanding`); a remainder of zero refuses like any exhausted cap.

**Defect 2 — a descendant session charged a smaller book than its root's.** Found by the #6 reader
tests: `_episode_host_sessions` scoped liability by *downward* lookup only, so a nested worker who
asked for capacity saw `{itself}` and could book a fresh cap while its root already held one (measured:
root holding 80 of a 100 cap, child granted 80 more). It now resolves the **root** from the asking
session's own ledger (`root_parent_session_id` names the root, not the immediate parent) and charges
the root episode; a declared root that cannot be resolved to a host session is unreadable bookkeeping
and fails closed rather than becoming a smaller book. Two further accounting holes in the same path
were closed with it: one descendant with no telemetry at all used to zero the *whole* episode's spend,
and an episode that could not be resolved raised out of the admission path into the bridge's
fail-open transport branch (a silent allowance) instead of refusing.

**Jev (supplementary, guidance only).** `jev_decide` was asked which book a descendant must charge,
with the measured overbooking case, the owner's "across root/descendants" clause and the isolated-root
counterexample in evidence. It selected `root-episode-strict` at 0.96 with all three requirements
supported (`keep-subtree-scope` contradicted). The decision agreed with the defect the tests had
already exposed; it did not establish it. No claim in this section rests on that probability.

**Migration version pins replaced by what the versions mean.** `tests/test_writer_admission.py` derived
its expectations from the real migration set (`_migrations_after(version)`) instead of pinning `[23,24]`,
and `tests/test_migration_chain.py` now establishes: contiguous unique numbers through the head; the
reservation table and its one-reservation-per-(session, task) rule at 25; the additive notification
outbox at 26 (a pre-existing row survives with `notification_pending = 0`); the reservation lifecycle
columns at 27 (existing reservations keep NULL lifecycle fields); the ordered remainder applied exactly
once from 24/25/26; the no-op at the head with a sensitivity control for the fingerprint witness; and a
version interrupted inside its own transaction rolling back to nothing applied and resuming to exactly
one canonical result once the real bytes are restored.

**#6 readers now answer the admission question.** `check_budget` reports episode-scoped `used` **and**
`outstanding`, with `available = cap - used - outstanding` (raw arithmetic: negative means overbooked);
`state` stays spend-based on purpose, because a booking the worker may never spend must not block the
driver's own tools. `list_budget_reservations` and `reconcile_budget_reservations` are episode-scoped
for the same reason. The status reader is read-only: it does not create or migrate the reservation
ledger as a side effect of being asked. Unknown usage stays `used=None` / `available=None` /
`ACCOUNTING_UNAVAILABLE`, with the liability still reported; **deliberate and pinned asymmetry:** a
session with *no telemetry at all* is unknown to the reader but a resolved zero to admission
(`test_a_session_without_telemetry_is_unknown_to_the_reader_and_zero_to_admission`), because reading
absence as unknown would refuse the first worker of every fresh session. Reader evidence covers root +
descendant sessions, an unrelated episode, cancelled-vs-unresolved liability, consumed-vs-usage
double counting, a duplicate billable observation (the `used == 65` witness), a restart through a
separate CLI process, and the read-only guarantee.

**Static analysis cleared, attributions as measured:** `ruff` clean; `pyright` 0 errors (all six were
candidate-owned: two over-long lines and one fixture-loader annotation pattern in each of the two new
suites); `tsc` and `eslint` clean.

Gates on the current bytes: extension **786 passed / 37 files**, `pytest tests/test_budget_reservation_lifecycle.py
tests/test_governor_reservations.py tests/test_governor.py` **87 passed**, `tests/test_migration_chain.py
tests/test_writer_admission.py tests/test_migrations_property.py` **46 passed**.

**Still open, and not claimed:** independent execution of any of the above; the remaining #2b
test-strength items (strict-prefix fixture, VMem public reader, separate-process first open); the
`contracts._calibration_pairs` / `scripts/run_paired_economics.py` readers, which answer a *different*
question (chars-per-token calibration and study economics) and already dedupe by usage identity, so they
were deliberately left alone rather than folded into the budget book; and the bounded
independent-verification-route investigation.

## Verification pass: interpreter resolution, failure attribution, and two more measured fixes (2026-09-22)

**Interpreter resolution is part of the subject, and it was wrong by default.** The candidate
worktree's `.venv` was created *from* the main repository's venv (`pyvenv.cfg` records
`executable = C:\...\The-Second-Brain\.venv\Scripts\python.exe`). Invoked by a **relative** path it
reports that main venv as `sys.executable`, whose `site-packages/_editable_impl_second_brain.pth`
points at the **sibling `qualified-v2` worktree**; every subprocess spawned as `sys.executable` with a
sanitized environment then imports that sibling's source rather than the candidate's. Invoked by
**absolute** path the same interpreter resolves `...\m00.3-producer-guard\src\second_brain\__init__.py`
(both probes recorded side by side). Measured consequence: `tests/test_v1_p4_qualification.py` (5
cases) raised `Qualification runtime source mismatch: expected ...m00.3-producer-guard\src\second_brain\__init__.py,
got '...qualified-v2\src\second_brain\__init__.py' using ...The-Second-Brain\.venv\Scripts\python.exe`
under the relative invocation and passes under the absolute one. The guard behaved correctly: it
refused to qualify a runtime whose source was not the candidate's. **Every gate reported below was
produced with the absolute candidate interpreter and `PYTHONPATH=src`.** The extension bridge tests
are unaffected: `reservation-integration.test.ts` pins `SECOND_BRAIN_PYTHON` to that interpreter, and
a bridge-conditions probe (cwd elsewhere, `PYTHON*` stripped) resolves the candidate's source.

**Defect: concurrent first open of the shared control database could kill the caller.** Found by
`test_concurrent_reservations_cannot_both_pass` failing in a full run (`JSONDecodeError` from a child
that produced no stdout). Reproduced deterministically: `PRAGMA journal_mode=WAL` answers
SQLITE_BUSY *immediately* when the transition cannot take its exclusive lock — the busy timeout does
not defer it, because the two connections may be converting from different modes — so the loser died
with `sqlite3.OperationalError: database is locked` at `db.py:44`. Measured **14 crashes in 200
concurrent first opens** on a quiet machine. Fixed with a bounded retry (then continue, because
journal mode is a tuning choice) plus `busy_timeout` before the first locking statement; after,
**0 crashes in 100 iterations** with exactly one grant each. `ledger.py` already had this convention
for its own burst-resilience fix, so the retry was consolidated into one helper (`db.ensure_wal`)
with the policy difference stated at each call site (the ledger requires WAL; the control database
does not). The ledger's budget also rose from 0.3s to 1s.

**Migration/schema reader work (committed earlier in this pass).** `check_budget` reports
episode-scoped `used` **and** `outstanding` with `available = cap - used - outstanding`, read-only;
`list_budget_reservations`/`reconcile_budget_reservations` are episode-scoped; the episode is resolved
**upward** to the declared root and an unresolvable root fails closed; spend is resolved per host
session so one telemetry-less descendant cannot zero the episode. Two overbooking/fail-open defects
this exposed are recorded in the commit `d6b8686` message. `tests/test_migration_chain.py` replaced
version pins with what 25/26/27 mean. `db.ensure` replays a component's registered **index**
statements when their own name is free, so every strict prefix of the registered DDL converges
(without it the new prefix test fails; verified by temporary revert).

**Inherited failures — exact signatures, attributed by file-copy isolation at `09f394e`** (my three
changed source files reverted to that commit's bytes, no stash; identical signatures before and
after, so none of them is attributable to this session's work):

| Test and exact signature | Attribution |
| --- | --- |
| `test_worker_lifecycle.py::test_worker_event_terminal_aliases_emit_result_telemetry[task_completed\|task_failed\|worker_cancelled\|worker_canceled]` → `assert 'failed' == 'ok'` (line 95) | inherited; cause located: `hermes_adapter.handle_worker_event` **deliberately** refuses terminal events with `failure_code: COMPLETION_AUTHORITY_UNAVAILABLE` ("Hermes has no authenticated completion authority") — the campaign's recorded external dependency (#4), which these tests predate |
| `test_worker_protocol.py::test_context_handoff_reuses_unchanged_and_emits_changed_delta` → `KeyError: 'context_metadata'` | inherited (also recorded earlier) |
| `test_worker_protocol.py::test_result_hash_and_correction_lifecycle_are_canonical` → `COMPLETION_AUTHORITY_UNAVAILABLE` vs `UNAUTHORIZED_WORKER` | inherited (also recorded earlier) |
| `test_orchestration.py::test_missing_worker_is_explicit_and_correlated` → `COMPLETION_AUTHORITY_UNAVAILABLE` vs `WORKER_UNAVAILABLE` | inherited |
| `test_omp_canary_tools.py::test_approved_successor_identity_matches_live_files` → `candidate drift: brainstem/prime-extension/src/budget-bridge.ts` | inherited + **by design**: 11 of the 40 bound files were already drifted at `09f394e` and the same 11 at HEAD (`budget-bridge.ts`, `index.ts`, `injection-slots.ts`, `ledger-mirror.ts`, `native-settlement.ts`, `sensors.ts`, `worker-context-bridge.ts`, `worker-result-bridge.ts`, `activate_omp_successor.py`, `cli.py`, `promotion.py`). No file entered or left that set; two of them drifted further. The identity was **not** resealed: §8 is explicit that candidate seals are not production approvals. Owner re-approval is the unlocking action |
| `test_v1_p4_qualification.py` (5 cases) → `Qualification runtime source mismatch …` | environment/configuration, see above; passes with the candidate interpreter |

**Jev (supplementary).** `jev_decide` on the descendant-scope question selected `root-episode-strict`
(0.96, 3/3 requirements supported) — it agreed with a defect the tests had already exposed. `jev_gate`
over the integrated source patch returned **`action: escalate`**, composite 0.792, `safe_to_apply`
0.4, with **9 claims verified, 0 contradicted, 0 unsupported, 3 needs_review** (the three are the
extension-side cancel/refusal/unclaimed-cap defect claims, supplied to it as prose rather than raw
output). No claim was contradicted. The gate is recorded as a review input and was not re-asked for a
nicer answer; it is not independent execution.

### Gates on the frozen subject

- `pytest` (candidate interpreter, `PYTHONPATH=src`), targeted: **87** (budget/governor), **46**
  (migration chain + writer admission + migration properties), **24** (brain schema), **155**
  (reservations/lifecycle/schema/migration/admission/governor), **146** (ledger/db/backup/schema/
  reservations).
- extension (`vitest`, candidate config): **786 passed / 37 files**, `tsc` clean, `eslint` clean.
- `ruff check src tests scripts`: clean. `pyright`: **0 errors**.
- concurrency measurement: 2 concurrent reservations, 100 iterations, **0 crashes, exactly one grant
  each**.
- full suite on the frozen subject (`ab4f97d`, candidate interpreter, `PYTHONPATH=src`):
  **2357 tests collected, 8 failures, no other test failed**. The eight are exactly the
  attributed set above: 4 `test_worker_lifecycle` terminal-alias cases, 2 `test_worker_protocol`,
  1 `test_orchestration`, 1 `test_omp_canary_tools` successor-drift (inherited/by design).
  The concurrency flake and the five environment errors from the first two runs are gone: the
  first was fixed (`db.ensure_wal`), the second was interpreter resolution (`sys.executable`
  loading the sibling `qualified-v2` worktree). No candidate regression is present in this run.

### Still open, unchanged

Independent execution of any of this (the standing gap: `task`/`feature-implementer`/
`integration-engineer` dispatch refused, read-only verifiers have no execution tools); owner
re-approval of the successor identity after a legitimate extension/source change; and the deliberate
decision to leave `contracts._calibration_pairs` and `scripts/run_paired_economics.py` outside the
budget book — they answer different questions (chars-per-token calibration, study economics) and
already dedupe by usage identity.

## M00-CORD-01 — root coordinator from authenticated runtime lineage (2026-09-22)

**Required invariant.** Coordinator authority MUST bind to the authenticated root execution
identity of an episode. Model, provider, display name, role text, and caller-supplied
`coordinator` flags MUST NOT independently grant it. M00 supports root coordinator and worker
only; delegated/subtree coordinators are out of scope. Root binding must commit before
dispatch/reservation, survive a proven continuation, and never be recreated by a worker when
the binding is absent or corrupt.

| Boundary | Current mechanism | M00 disposition |
| --- | --- | --- |
| Root/child observation | Extension `index.ts:595-606,1076-1092` follows native transcript breadcrumbs; `:3990-3993` obtains the current session and root | Useful correlation, not authenticated against a same-user process that can alter transcripts or call the CLI |
| Role creation | `index.ts:1605-1608` resolves `ctx.model` against `driver-orchestrator.ts` model lists; `worker-context-bridge.ts:210-226` sends `role`, model, and session ID on stdin | Model is metadata, not an authority source; adding `gpt-6-sol` to an allowlist is not this fix |
| Admission check | `omp_adapter.py:69-95` accepts payload `role` and synthesizes an identity; `contracts.py:666-697` checks its `role_profile` against `COORDINATOR_ROLES` | Self-declared role can both reject a real root and accept a worker; replace only after host origin is authenticated |
| Durable worker record | `worker_protocol.py:808-954` writes the attempt under `BEGIN IMMEDIATE`, records `host_session_id`, and returns its callback credential | Transactionality/exclusion exist, but no authenticated episode-coordinator binding precedes issuance |
| Budget and release | `governor.py:1184-1263` reserves by session/task/episode; `worker_protocol.py:1435-1441` releases on authenticated settlement and cleanup | Preserve these separate guards; a caller-supplied session ID must not become coordinator authority |
| Other host / review | `hermes_adapter.py:524-529,613-618,1062-1067,1214-1219,1295-1300` and `contracts.py:861-863` use declared role checks | Do not silently exempt Hermes or reclassify its worker as root |
| Recovery | `index.ts:1990-2013` reconstructs tracking from journal; `worker_protocol.py:855-865` accepts exact read-only duplicate attempts | Journal reconstruction is not authenticated rebind; missing coordinator identity must refuse privileged work |

**M00-CORD-02 — harness/version-independent semantics.** Brain Core MUST derive
coordinator authority from a normalized runtime-lineage contract, never from a
harness version/class name, model, provider, or adapter-selected role. The contract is
`episode_id`, `runtime_instance_id`, `parent_runtime_instance_id` (null for root),
`root_runtime_instance_id`, and optional `attempt_id` (a worker execution, not a
fabricated root attempt). The adapter translates host lineage into these identifiers
and supplies separately authenticated provenance; it may not assert that an actor is
coordinator. Core binds the proven root runtime instance once per episode and compares
the authenticated caller against that immutable binding for coordinator-only actions.
Workers carry the root identifier for correlation, never its authority. Recovery
requires proof that the resumed instance continues that binding, not a name/role guess.
Binding must commit before privileged admission or reservation; concurrent first
admissions resolve to one immutable root. Missing, corrupt, or unauthenticated lineage
refuses privileged work. The OMP adapter's native session ID maps to
`runtime_instance_id` and its root to `root_runtime_instance_id`; those OMP details
must not be encoded in the Core authority predicate. A repeated normalized lineage
must yield the same decision under different OMP versions and under different
harness adapters. No OpenCode/Hermes adapter can be declared qualified merely by
passing the same fixture through a synthetic translator.

**Current blocker, not waived.** The installed OMP 18.2.9 `ExtensionContext`
(`src/extensibility/extensions/types.ts:428-520`) exposes a read-only session manager, model,
and bounded async-job snapshot, but no authenticated root/child actor proof or protected
issuer channel. The candidate bridge advertises `authenticated_observation_source:false`,
`effective_tool_grant:false`, `execution_census:false`
(`brainstem/prime-extension/bridge/brain-host-bridge.ts:251-269`). The executable admission
reproduction in `outputs/reports/m00.3-admission-issuance-20260922/REPORT.md:7-35`
shows a caller can send `role=driver`, obtain the callback token, and complete its own
attempt. Transcript paths, role flags, and a first-writer-wins row cannot authenticate that
caller. Same-user agent shell access can invoke the CLI directly. This mandate prohibits
provisioning the required separate OS identity/ACL/service or changing production; no
candidate-local model allowlist, JSON flag, shared secret, or DB claim resolves it.

**Gate:** `M00-CORD-01` OPEN / `M00_PARTIAL_EXTERNAL_BLOCKER`. The owner selected
the **protected host API** route, with no OS-account provisioning. The selected API must
provide host-origin root/child identity and an issuer channel inaccessible to agent-controlled
shell/CLI; selection does not mean OMP 18.2.9 already provides it. The installed context
interface above does not expose those capabilities, and a same-user process can still invoke
the existing CLI. Once the protected route exists, implement durable binding, one predicate,
worker propagation, restart proof, race/spoof matrix, and paired DeepSeek/GPT-6 Sol
reservation regressions. No production activation or historical approval change occurred.
Jev's bounded option comparison selected the protected-host-boundary approach over a model
allowlist or transcript-only first-writer binding (supplementary decision input, not a
security proof).

### M00.4-A host-boundary investigation (OMP 18.2.9; no coordinator behavior changed)

The normalized producer contract is `TrustedRuntimeLineage { episode_id, runtime_id,
parent_runtime_id|null, root_runtime_id, spawn_id|null, issuer_id, issuer_generation,
sequence, attestation }`. A trusted host-side `TrustedLineageIssuer` alone may report
`root_created`, `child_spawned`, `runtime_rebound`, or `runtime_terminated`; Brain Core
validates the registered issuer and lineage before binding authority. CLI fields and
role labels are untrusted. This refines the identifiers in M00-CORD-02; neither an
OMP-specific ID nor a bus frame itself constitutes attestation.

| Boundary | Observed seam | Consequence |
| --- | --- | --- |
| Root session | Installed `session-manager.ts:1490-1510` mints the session header; `sdk.ts:3441-3474` registers the runtime before constructing its prompt | The registration point can observe a root candidate, but an opaque transcript/session header does not authenticate its caller |
| Structured child | `structured-subagent.ts:632-656` reserves the child ID, `:485-487` supplies parent agent ID; `executor.ts:3708-3801` carries child ID, parent, depth, and shared observability bus into SDK construction | Parent and child are known before first child prompt; the host may issue a private spawn record there, then bind it to the exact registered runtime |
| Runtime reuse | `agent-registry.ts:146-176` provides a registration/CAS against an exact parked ref; `sdk.ts:3454-3477` can reclaim a dead ref or revive one | Runtime ID alone cannot identify a generation. Rebind must check the exact ref and issuer generation; delayed revivals and reclaimed IDs cannot inherit authority |
| Public events | `extensions/types.ts:1501-1502` exposes `pi.events`; `extensions/loader.ts:179-197,438-453,490-513` gives extensions the shared mutable `EventBus`; `utils/event-bus.ts:3-49` permits emitting lifecycle frames | Internal origin of the normal lifecycle event does **not** make the bus an authenticated source |

The event boundary was exercised without modifying source: an extension loaded by the
installed loader called `pi.events.emit("task:subagent:lifecycle",
{id:"forged-child",status:"started",parentToolCallId:"forged-parent"})`; a listener on
the same bus received that exact frame. This demonstrates an extension can synthesize
an equivalent accepted *bus event*, not that it forged a yet-unimplemented protected
attestation. A model-facing shell/CLI already reaches the admission route as separately
reproduced above; do not assume arbitrary extension loading into an existing session
from that shell without a separate proof.

**Smallest replaceable host seam:** add a private, typed issuer hook at SDK runtime
registration, paired with structured-child allocation/parent capture and exact-ref
revival/termination transitions. It must authenticate its producer independently of
`pi.events`, transcript fields, SDK caller-supplied role/parent options, and CLI input;
issue monotonic generation/sequence-bound attestations; and expose semantic capability
discovery to the adapter. A host SDK embedder can supply options, so registration alone
is not a protected principal. No installed extension-context API currently supplies
the required issuer custody, and same-user shell access makes a file/DB/shared-secret
shim insufficient by itself. Until a host implementation demonstrates a channel
inaccessible to agent-controlled execution and a verifier for the attestation, advertise
lineage capability unavailable and refuse privileged admission. Do not infer protection
from an in-process event bus, model label, or proposed interface. M00.4-A remains
investigated, not implemented; M00-CORD-01 remains blocked, production unchanged.

### M00.4-B — issuer custody, trusted bootstrap, verifier contract (design only)

**Threat boundary and observed gap.** Model/tool input, public CLI, public event-bus
producers, and SDK identity options are untrusted. The accepted #4 requirement also
demands protection against parent/worker execution; arbitrary hostile extension code
running in the same unrestricted host process is a stronger adversary that an
unexported module, private field, in-process callback, or ordinary process split does
not exclude. Installed OMP loads project-local extensions without a trust gate
(`extensions/types.ts:461-519`), exposes the mutable shared bus (`:1501-1502`), and
offers no protected lineage issuer in `ExtensionContext` (`:428-520`). The current
Brain CLI admission sends the issued callback token back to its caller
(`omp_adapter.py:69-139`); the disposable reproduction is recorded above. Neither
same-user files/pipes nor source/manifest hashes establish a caller boundary. No
existing trusted supervisory issuer-bootstrap path has been identified in this
installed host/candidate; `host_protocol.py:325-367` verifies *static advertisement
bytes* against a qualified identity, not a runtime signer or the process presenting
an operation. Thus hostile in-process extensions and same-user CLI access remain
explicit unsatisfied custody conditions, not silently excluded threats.

**Proposed authority chain, contingent on a protected supervisory channel.**
1. A supervisor outside agent/extension-controlled execution authorizes an episode
   launch and registers an issuer identity plus verifier material with Brain through
   a separately authenticated administrative path. A public CLI/SDK payload cannot
   register or replace that identity or present its own verification key. The current
   code has no demonstrated path with this property; do not implement a pretend
   bootstrap from configuration text or the existing advertisement digest.
2. The supervisor's root-launch record, *not* `parent=null`, model, or SDK `agentKind`,
   identifies the sole root candidate. A successful exact runtime registration
   (`sdk.ts:3441-3477`) binds it to episode, runtime object/generation, and issuer.
   Registration failure or interrupted persistence creates no coordinator binding.
3. Structured-child allocation (`structured-subagent.ts:632-656`) takes the actual
   allocating session/ref as parent; its root comes from that ref's previously verified
   lineage. On successful exact child registration, compare the allocation/spawn
   record to the registered ref (`executor.ts:3708-3801,3829-3861`). Never certify
   caller-supplied `parentAgentId`, `agentId`, root, or `taskDepth` by signing them.
   A child learns lineage for accounting only; it cannot acquire root authority.
4. Revival uses the exact parked-ref CAS and the same proven logical lineage but a
   new execution generation (`agent-registry.ts:167-176`; `executor.ts:3880-3919`).
   Reclaimed IDs, mismatched ref/session, overlapping generations, termination, or
   incomplete registration invalidate old execution evidence. Monotonic issuer
   generation and sequence cannot be reset by replayed JSON.
5. The issuer attests host-owned facts in the normalized `TrustedRuntimeLineage`
   envelope from M00.4-A, with explicit event kind, recipient=Brain, purpose=lineage,
   and exact runtime generation. The verifier first authenticates a previously
   registered issuer and its active generation; then checks integrity, purpose,
   recipient, episode, root/parent consistency, runtime identity, event ordering,
   and current registration. **Authentic lineage ≠ coordinator eligibility ≠
   authorization of a particular operation.** Core permits a coordinator-only
   admission/reservation only if the request arrives through the protected channel
   for the currently bound root execution and matches the intended episode/runtime
   and operation; a copied root attestation presented by a child or public CLI is
   insufficient. Duplicate evidence is idempotent, conflicting evidence refuses.
   Bind the root once in the existing Brain state transaction before issuing an
   attempt credential or reserving budget; preserve current ownership/receipt guards.
   Missing/stale/unverifiable evidence fails closed and a retry cannot mint a second
   authority. No JWT framework or parallel authority database is proposed.

**Exact candidate patch scope after custody/bootstrap authorization, not applied:**

| File / seam | Minimal intended edit | Revert |
| --- | --- | --- |
| Host `src/task/structured-subagent.ts:632-656`, `src/task/executor.ts:3708-3801,3880-3919` | Host-owned parent/spawn capture and generation-checked rebound, not user option certification | Revert isolated host patch; preserve existing task behavior |
| Host `src/sdk.ts:3441-3477`, `src/registry/agent-registry.ts:146-176,191-217` | Bind exact registered ref to supervised launch/spawn records and lifecycle generation, expose protected producer only if custody proven | Revert isolated host patch; existing registry CAS remains |
| Candidate `brainstem/prime-extension/bridge/brain-host-bridge.ts:22-46,232-269` | Advertise semantic trusted-lineage capability only on verified protected route; map OMP fields to normalized facts, never become issuer | Revert candidate bridge change |
| Candidate `src/second_brain/host_protocol.py:27-87,325-440,445-557` | Add capability negotiation and registered-issuer envelope verification separate from static advertisement qualification | Revert candidate protocol change and its migration |
| Candidate `src/second_brain/omp_adapter.py:69-139`, `src/second_brain/worker_protocol.py:808-954`, `src/second_brain/governor.py:1184-1263` | Replace role-only authorization with verified current-root operation; atomically commit immutable root binding before issuance/reservation using existing state/transactions | Revert candidate adapter/core/schema changes via supported DB rollback; never downgrade live state |

The host edit cannot safely be a candidate bridge alone: extension code shares host
privileges. A protected producer/verifier may require a genuinely isolated supervisor
or host facility inaccessible to agent and hostile extension execution. The owner
has not authorized installed-host changes, accounts/ACLs/elevation, or production
changes. Without a proven existing protected supervisory path, this remains a
conditional patch map, **not implementation-ready custody**.

**Disposable adversarial matrix (planned, not executed):** legitimate supervised root
and genuine child; caller-selected root/parent options; forged public lifecycle
frame; self-registered issuer/key; child presenting authentic root evidence; replay
across episodes and runtimes; duplicate delivery without second grant; stale evidence
after revival and reused ID; absent issuer; failed registration and interruption
between registration and durable binding; conflicting sequence/generation; unchanged
authority after role/model/version-label changes. Positive controls must reach
the real admission/reservation sink; negative controls verify no credential, reservation,
or binding. Fault injection checks rollback and retry idempotency. Use only disposable
fixtures under already authorized limits; do not patch the installed host or spend on
provider-backed tests for this design packet.

**Next executable boundary:** first obtain a concrete protected supervisory issuer
and Brain bootstrap/verifier channel, with demonstrated access denial for agent CLI
and, if in scope, hostile in-process extensions. Only then authorize candidate host
and product-code edits plus the matrix above and an independent review through an
already-permitted route. `UNAUTHORIZED_COORDINATOR` must not be bypassed to procure
a reviewer; no independent review occurred in this packet. M00-CORD-01 remains
`BLOCKED` / `M00_PARTIAL_EXTERNAL_BLOCKER`; coordinator behavior and production
activation unchanged.

### M00.4-C local access/custody preflight (not a vertical slice)

The separately supplied `docs/intake/execution-preflight.json` describes a **Linux**
session without the Windows candidate checkout; its `BLOCKED_SOURCE_ACCESS` verdict
does not describe this workstation. Here the candidate register, Brain source, tests,
and installed OMP 18.2.9 source are readable. The remote SHA in that record is not
substituted for local candidate bytes. Engineering permission is recorded in the
owner's M00.4-C instruction; it is not a runtime credential.

Local source review finds `--trusted-extension` resolves explicit paths and disables
normal extension discovery (`main.ts:1597-1614,2148-2170`), but it does not isolate
agent tool/eval execution or protect an issuer/Brain verifier. The candidate has no
existing restricted-token/AppContainer/protected-supervisor route in the inspected
Brain/extension sources. Native disposable same-user probe: a parent Bun process wrote
only `nonsecret-fixture` to an OS-temp file, spawned another Bun process under user
`Joseph`, and the child read it successfully (exit 0); the temp directory was removed.
That proves a same-user *file* is not custody here; it does not prove whether a
separately configured Windows isolation profile could satisfy the full requirement.

**Result:** source access is available in this session, but no protected issuer
enrollment, root launch, runtime-bound privileged request route, or verifier custody
has been demonstrated. A private signer, trusted-extension allowlist, or same-user
file/pipe must not be promoted to a working vertical slice. Candidate host/Brain
runtime edits, fixture admission, adversarial matrix, native containment
qualification, and independent review remain **not performed**. The next dependency
is a permitted, demonstrably isolated agent executor plus protected supervisor/Brain
state and IPC (or an existing host facility with equivalent guarantees), including
actor binding when root and child share a process. This packet does not authorize
global OS changes or an installed-host patch. M00-CORD-01 remains blocked.

### M00.4-C continuation — fixture-qualified component only (2026-09-22)

Candidate: `.worktrees/m00.3-producer-guard` (not installed). Added
`src/second_brain/runtime_lineage.py`, control migration
`src/second_brain/migrations/0028_runtime_lineage.sql`, and
`tests/test_runtime_lineage.py`; updated `tests/test_migration_chain.py`.
Rollback: revert these candidate files and the test edit; on disposable databases
restore a pre-0028 backup rather than dropping tables from a live database.

`verify_lineage` checks an HMAC fixture envelope against an independently supplied
issuer ID/key/generation, recipient, purpose, episode, exact actor runtime,
request ID, and runtime generation. It rejects unenrolled identity, altered
fields, copied evidence with the wrong actor, and stale generations under the
supplied fixture context. `register_lineage` joins the **existing control DB**
transaction, refuses conflicting root/runtime records, checks registered child
parentage, and supports duplicate evidence and rollback on interruption.
`require_root_actor` refuses a registered child's coordinator claim.
The caller must first authenticate the actor, verify the envelope, and hold a
write transaction; this component does not establish or enforce that caller
boundary on its own. No issuer enrollment API or CLI admission bypass was added.

Evidence: `tests/test_runtime_lineage.py` and `tests/test_migration_chain.py`
**9 passed** with candidate interpreter and `PYTHONHOME`/`PYTHONPATH` removed;
`ruff check` and `pyright` on the candidate verifier passed (test import style
subsequently corrected). This is **candidate component verification under fixture
trust assumptions**, not protected bootstrap, native caller authentication,
genuine-child qualification, or admission/reservation integration. No independent
review was obtained. The first test invocation without clearing the environment
resolved migration files from a different tree and failed 5/7; the corrected
candidate interpreter run initially failed only because the migration-chain test
expected no version after 27, then passed 9/9 after covering 28.

Still blocked: M00.4-B selects a protected supervisory channel but identifies
no implementable existing mechanism for protected issuer enrollment, signer
custody, authenticated actor context, or trust-state integrity against the
same-user caller and hostile in-process extensions. A trusted-extension allowlist
and ordinary same-user file were not qualified; no restricted-token or
AppContainer experiment was performed because neither is the selected route.
The awaited host integration cannot safely pass actor identity or issuer key
through the public CLI/extension bus; connecting this verifier to that route
would manufacture authority. Runtime rebound/termination, monotonic sequence,
atomic coupling to credential issuance/reservation, and the root/child vertical
slice remain unimplemented dependencies of that protected route. Existing role
admission remains unsafe and is not declared qualified. `M00-CORD-01` stays
`BLOCKED` / `M00_PARTIAL_EXTERNAL_BLOCKER`; production and leases untouched.

### M00.4-C next bounded component checkpoint (2026-09-22)

Candidate HEAD `901ab302f37ca06b3dac0c4057d7c88adbb9bda6`,
worktree `.worktrees/m00.3-producer-guard`; uncommitted changes are
`src/second_brain/runtime_lineage.py`,
`src/second_brain/migrations/0028_runtime_lineage.sql`,
`src/second_brain/governor.py`, `src/second_brain/worker_protocol.py`,
`tests/test_runtime_lineage.py`, `tests/test_runtime_lineage_rebind.py`,
`tests/test_migration_chain.py`, and this register. Existing
`tmp_t03_probe.txt` was not touched.

Migration 0028 was qualified through `db.migrate` on fresh disposable
databases and a version-27 disposable predecessor carrying a synthetic
outstanding attempt, task metadata, and unresolved reservation. Those
rows survive migration/reopen; `db.connect` reports foreign keys enabled
on the checked connections (0028 itself defines no foreign keys).
Duplicate registration is idempotent; conflicting registration refuses
without `REPLACE`. The original interruption test injects a Python
rollback; a new owned child process calls the actual verifier and
registration function, exits with `os._exit(0)` before commit, and
reopen finds no binding. This is process-exit recovery, not power-loss
or hostile direct-file-write qualification.

`runtime_rebound` now compares the active exact predecessor and
generation under the registration transaction, advances the active
runtime one generation, and retains the immutable episode root.
Stale, worker-origin, and competing continuations refuse; two disposable
writer connections racing from one generation produce one winner.
The existing unresolved reservation survives and can be reconciled
after continuation. Model/provider fields do not enter the authority
predicate. This proves only fixture-signed continuation against
fixture-supplied actor context; no native exact-ref revival is proven.
Termination and reclaimed-ID invalidation remain open.

The public unauthenticated `reserve_budget` and
`admit_worker_attempt` routes now refuse **new work for an episode
already present in `episode_roots`** under their own `BEGIN IMMEDIATE`
transaction. Existing exact-reservation consumption remains available.
This is a negative fail-closed candidate increment, **not positive
authority-to-reservation or authority-to-issuance coupling**: there is
no protected actor channel to supply the positive route, and a
same-user caller with direct database access can still corrupt or
fabricate trust state. Other legacy unbound episodes retain their
existing role-based admission behavior and are not qualified by this
work. A prior verified envelope cannot be promoted to an authorized
reservation Boolean.

Author-run result: focused migration, lineage, budget lifecycle, and
writer admission tests **71 passed**; `ruff check` and targeted
`pyright` on changed Python files **passed**. Workspace-wide
`pyright` separately reported two existing optional-member errors at
`tests/test_brain_schema.py:516`; not changed here. Fixture testing
does not establish custody or native qualification. Independent
review was not obtained through an authorized route. Rollback:
revert the candidate code/tests/register edits; for disposable
version-28 databases restore a consistent pre-28 backup, never
delete live tables or downgrade canonical state.

Custody dependency remains the M00.4-B protected supervisory issuer
bootstrap and private producer/Brain request channel, bound to the
actual host runtime ref, inaccessible to model-controlled root/child
execution and hostile same-process extensions; the verifier/trust DB
must resist direct modification by that caller. The installed OMP
context does not expose this channel; making it requires a protected
host capability or an isolated supervisor beyond the authorized
candidate-local edits. No selected implementable Windows primitive
was recorded in M00.4-B, so no substitute file/restricted-token/
AppContainer mechanism was silently introduced. No installed-host
change, production enrollment, lease release, activation, push,
merge, or tag. `M00-CORD-01` remains
`BLOCKED` / `M00_PARTIAL_EXTERNAL_BLOCKER`.

### M00.4-D disposable Windows custody experiment (2026-09-22)

Separately authorized fixture-only scope; **no candidate product code
changed** and the prior 71-test component gate was not rerun.
Supervisor: current non-elevated Python process; target: a restricted
version of its own primary token made by `CreateRestrictedToken` with
`DISABLE_MAX_PRIVILEGE` and a `BUILTIN\Users` restricting SID.
`IsTokenRestricted` returned true. A second `Everyone` restricting
SID was tried only to isolate executable access. Only OS-temp
`brain-custody-*` objects received ACL changes; neither existing
desktop nor window station permissions were changed.

Control: unrestricted `CreateProcessAsUserW` launched the system
`cmd.exe` and wrote `baseline` to the fixture allowed directory
(exit 0). Unrestricted supervisor read the fixture issuer file.
The restricting-SID token, impersonated on the fixture thread with
`RevertToSelf` in `finally`, read the explicitly permitted fixture
file; reading the issuer file and writing the trust file each failed
with access denied (Python errno 13), and `OpenProcess` for
`PROCESS_VM_READ|PROCESS_VM_WRITE|PROCESS_DUP_HANDLE` against the
supervisor PID failed with Win32 error 5. Trust-file contents
remained unchanged. This probes that token's object access checks;
it does **not** prove a launched restricted executor can operate.

Launch attempt: `CreateProcessAsUserW` returned a process handle for
the `BUILTIN\Users` token, but the restricted `cmd.exe`/`whoami.exe`
ended during initialization with `0xC0000022` (access denied),
including a newly created fixture desktop. The `Everyone` variant
ended `0xC0000142` (DLL initialization failed); impersonation also
denied reading system executable/DLL files under that variant.
Attempting a **named** new window station returned Win32 error 5;
Microsoft documents naming stations as administrators-only. An
unnamed fixture-owned station and newly created desktop allowed
process creation, but the target still ended `0xC0000022` before its
permitted `echo` operation. The precise startup access failure
inside this process has **not** been isolated; do not attribute it
to a specific ACL or privilege without further evidence.

Verdict: **NO EXECUTABLE CUSTODY DEMONSTRATION**. The allowed target
operation did not complete, so no pipe/request channel, root/child
separation, generation expiry, bootstrap defense, Bun/Python tool
route, hostile-extension defense, or general same-user defense was
tested. The direct token impersonation denials are narrower evidence
only. Next prerequisite is a reproducible non-elevated restricted
target that starts on a fixture-owned desktop while preserving the
protected-object denials; otherwise a separately authorized
isolation capability. No privilege escalation, alternate unrestricted
fallback for the target, installed-host change, or production
activation. Fixture processes terminated; owned objects/handles
are cleaned after recording these results. `M00-CORD-01` remains
blocked; independent acceptance absent.

### M00.4-D restricted-token launch-viability A/B/C (2026-09-22)

Owner-authorized **disposable fixture-only** continuation on the 18.2.10
host; no product, installed OMP, canonical Brain, account, service,
production ACL, or tracing change. A separate non-elevated Python fixture
supervisor created `C:\Users\Public\Documents\brain-custody-abc-37_itcg_`
and a restricted version of its primary token with
`DISABLE_MAX_PRIVILEGE` and `BUILTIN\Users` (`S-1-5-32-545`) as its
restricting SID; `IsTokenRestricted` was true. The fixture root granted
Users RX, `work` and `temp` granted Users M, the fixture issuer file
granted only the ordinary user and SYSTEM full access, and the fixture
trust file granted Users read but not write. These ACLs were changed
**only inside the newly created fixture directory**. `CreateProcessAsUserW`
used the absolute system `cmd.exe`, a noninheriting-handle launch, a
15-second child wait, and `GetExitCodeProcess`; no privileged tracing.

| Run | Working directory | Environment | Window station / desktop | Creation; PID | Child exit; command completed |
| --- | --- | --- | --- | --- | --- |
| A | fixture `work` | inherited | inherited | success; 33772 | `0xC0000022`; no |
| B | fixture `work` | explicit Unicode block with `SystemRoot`, `windir`, `SystemDrive`, `COMSPEC`, system `PATH`, and fixture `TEMP`/`TMP` | inherited | success; 46376 | `0xC0000022`; no |
| C | fixture `work` | same as B | new unnamed station `Service-0x0-ab735$` and new desktop `CustodyFixtureabadc41634` | success; 684 | `0xC0000022`; no |

For C the fixture station DACL granted the ordinary user `0x37f`
and restricting Users `0x123`; the fixture desktop DACL granted the
ordinary user `0x1ff` and restricting Users `0xc3`. The station and
desktop handles were closed after the children exited. These are the
**tested rights**, not a finding that they are sufficient for startup.
`CreateProcessAsUserW` succeeding in all three runs did not mean any
child initialized sufficiently to complete `cmd.exe /d /c exit 0`.
There is no evidence identifying the particular denied startup resource.

Stop condition fired at C. No permitted-write command, post-launch
issuer read, trust write, supervisor VM read/write, or handle-duplication
check was attempted under this configuration; the *earlier*
impersonation denials above are not a substitute for simultaneous
runnable-process denials. No Bun/Python target, actor binding, root/child
authority, request channel, reservation coupling, or OMP integration
was tested. The three exited child handles and station/desktop were
closed, and the fixture directory and probe script were removed;
the fixture removal check returned true. Jev supplementary
claim-versus-evidence audit verified the negative custody conclusion
and contradicted claims that the current directory was isolated as
cause or that runnable execution plus four denials were proved.
Independent agent review was attempted but the coordinator returned
`UNAUTHORIZED_COORDINATOR`; no independent review is claimed.
Verdict: **NO EXECUTABLE CUSTODY DEMONSTRATION**. Startup access tracing
would require separate authorization; it was not invoked.
`M00-CORD-01` remains **BLOCKED**.

### M00.4-D token-construction localization D0 (2026-09-22)

Separately authorized non-elevated, disposable continuation. The A/B/C
experiment above was not rerun. A new fixture under
`C:\Users\Public\Documents\brain-custody-token-4omqccpq` reproduced
Run C's fixture ACL design: Users RX on the root, Users M on `work`
and `temp`, ordinary user/SYSTEM only on the fixture issuer file,
and Users read but not write on the fixture trust file. It used
an explicit Unicode environment with fixture `TEMP`/`TMP`, fixture
`work` cwd, and a new unnamed station
`Service-0x0-ab735$`/desktop `CustodyFixture0df2dd66b3`.
The station granted owner `0x37f` and Users `0x123`; the desktop
granted owner `0x1ff` and Users `0xc3`. No existing object ACL,
global policy, account, service, installed host, product code, or
canonical Brain state was changed.

**D0:** `CreateRestrictedToken` with `DISABLE_MAX_PRIVILEGE`,
zero disabled SIDs and zero restricting SIDs.
`IsTokenRestricted` returned **false** for this privilege-stripped
token. `CreateProcessAsUserW` for absolute system
`cmd.exe /d /c exit 0` succeeded (PID 14880); after waiting,
`GetExitCodeProcess` returned `0x00000000`. With the **same D0 token
and configuration**, `cmd.exe /d /c echo
custody-control>permitted-output.txt` succeeded (PID 34176,
exit `0x00000000`) and the fixture file contained
`custody-control`. No handles were inherited.

Direct impersonated D0-token access checks then returned
**allowed**, not denied, for all protected operations:
issuer-secret read, trust-state write access request,
supervisor `PROCESS_VM_READ`, `PROCESS_VM_WRITE`, and
`PROCESS_DUP_HANDLE`. The trust file was not modified and its
contents remained unchanged. These checks establish that this
*runnable* privilege-only variant **does not** provide custody;
they are not a launched-child attack demonstration. The exact
startup denial in earlier restricting-SID runs remains unidentified.
In particular, D0 versus C does not isolate the choice of
`BUILTIN\Users` from the presence of *any* restricting SID.

The instruction to **stop at the first runnable configuration**
fired at D0; D1 (deny-only groups), D2 (`S-1-5-12` restricting SID),
and optional D3 (SAFER) were **not run**. No claim about their
behavior or about the unique cause of C's failure follows.
The two D0 children exited, station/desktop/token handles closed,
and the entire fixture, including the probe script, was removed
(removal check true). Jev's supplementary audit supported the
D0 launch fact and rejected D0 custody, but marked the asserted
unique cause of the earlier failure unsupported; deterministic
results above govern. No Bun/Python, actor binding, root/child,
request-channel, reservation, OMP integration, elevation, or
startup tracing was attempted. **M00-CORD-01 remains BLOCKED**.

### M00 continuation — schema authority and replay integrity (2026-09-22)

Candidate remains `.worktrees/m00.3-producer-guard`; HEAD
`18c9372b56c1801511b6103abb3c4dfe192eaf73` consists of
`901ab302f37ca06b3dac0c4057d7c88adbb9bda6` plus #2b commit
`3b744ac` and replay commit `18c9372`. The earlier lineage work and
this register remain uncommitted; this is **not** a frozen or
independently executed final bundle.

**#2b correction to the earlier row:** the strict-prefix, public VMem
reader, separate-process first-open, and content-change idempotency
witness tests were already committed (`tests/test_brain_schema.py`).
`VMemStore._init_db` now uses the authority's `component_shape` to choose
only registered additive columns and refuses unsupported shapes.
The first neighborhood run caught a real concurrent WAL transition
failure in VMem; it now calls the existing bounded `db.ensure_wal`
helper. A reviewer found a late-import schema-cache regression:
Ledger-first import left an empty fifteen-column VMem predecessor
accepted without four required columns. A disposable subprocess
reproduced 15 → 15 and an assertion failure. `brain_schema.register`
now invalidates both derived caches under an `RLock`; cache construction
and publication share that lock, while stale explicit registry
snapshots neither read nor publish the current cache. The same
subprocess then observed 15 → 19 and `component_shape == current`.
One cold-process regression covers late import, stale snapshots,
migration and reopen; an unsupported VMem column is refused and
preserved. The separate-process race test passed in five subsequent
isolated invocations. Author-executed neighborhood suite
(`test_brain_schema`, `test_vmem`, `test_vmem_coverage`,
`test_vmem_live_integration`, `test_ledger`, `test_governor`,
`test_backup`, `test_migrations_property`, `test_db`,
`test_writer_admission`, `test_cleanup_t61`, `test_contracts`,
`test_worker_recovery`) passed. Read-only independent source review
rejected the initial cache edit twice, then accepted the bounded
correction; it did **not** run these tests. #2b is evidenced in this
working candidate, not independently executed or cumulatively accepted.

**SEC-INTEGRITY-01 partial increment:** `LedgerStore.replay` now
requires a full-from-genesis chain check that ignores the mutable
`last_verified_seq` watermark. Its tampered-checkpointed-event test
failed before this change (`DID NOT RAISE BrainError`) and passed
after. The CLI `ledger verify` now also requests full-chain integrity:
a disposable real CLI smoke returned exit 0 with
`integrity.hash_chain_ok:true` / `replay_ok:true` on the clean event,
then exit 1 with both fields false after a checkpointed payload was
altered. The default incremental `integrity()` and `checkpoint_ledger`
still trust the mutable watermark. This increment does **not** repair
the payload-only chain or provide versioned full-envelope migration.
**SEC-INTEGRITY-01 stays OPEN.**

**Authority and identity correction:** the separate installed
structural-role extension `index.ts` hashes
`0412eac3b857952a32bed1c311f622324b1224a90f8e8df0b1a9774a08947a84`;
the older `qualified-v2` source hashes
`42b57b41c531a3a9f113e7e28531b24d540609808b6e8ee3d5fefe9410b75a41`.
The role branch `brain/structural-coordinator-role` at `cc4cbb8`
classifies an unlisted root model as driver, but transcript-path
ancestry does **not** authenticate an episode actor or protect
credential issuance. Candidate `omp_adapter._prepare_worker_context`
still consumes a caller-supplied role and returns the attempt token;
the host bridge advertises neither an authenticated observation source
nor an execution census. Independent read-only evidence audit marked
the structural role claim PASS **only for functional classification**,
authenticated M00-CORD-01 FAIL, and positive protected admission
UNDEMONSTRATED. Jev's supplementary claim audit agreed with that
separation (two verified, two contradicted); neither substitutes for
runtime proof. D0 remains runnable but without custody. **M00-CORD-01,
#4 and the cumulative candidate gate remain BLOCKED/OPEN.** Production
activation, lease recovery and canonical-state migration were not
performed by this continuation; the installed extension is no longer
identical to the older historical digest, so the old register statement
that deployed extension bytes are unchanged is historical, not a
current preservation observation.

**HIGH-finding source correction:** the original clauses for
`SEC-INTEGRITY-01`, `FSUPD-01`, `SEC-SKILL-01`/
`SB-PROMOTION-004`, and `SEC-HOOK-02` are in the main tree's ignored
`outputs/reports/security-audit-20260921/REPORT.md:25-28`, for older
audited subjects. The earlier register citation to
`docs/requirements/M00.3_Phase_A_Host_Authority_Continuation.md:201-202`
does not resolve (that file ends at line 109); no closure follows from
the corrected provenance. These four HIGH gates remain open on the
candidate until their exact conditions are independently established.

### M00.4-D — disposable OMP 18.2.10 host-copy preflight

The owner authorized changes **only** in an isolated, disposable OMP
source copy, not the installed runtime, production state, accounts,
services, elevation, or machine-wide ACLs. The source package is
`C:\Users\assas\.bun\install\global\node_modules\@oh-my-pi\pi-coding-agent`
(`package.json` version `18.2.10`); its `omp` bin points to
`dist/cli.js`, whereas the copied source entry is `src/cli.ts`.

Driver created
`C:\Users\assas\AppData\Local\Temp\m00-host-18210-rLR6Ei` with a copied
`package.json`, 1,505 source files (17.0 MiB), and the source-mode docs
index. Its sibling/vendor dependencies are junctioned to the installed
global `node_modules` tree and were treated as inputs, not OS-enforced
read-only objects; the copied host is the only `pi-coding-agent` on
its module lookup path. Source SHA-256 comparison covered all 1,505 files:
zero mismatches. Installed and copied `src/sdk.ts` both hash
`25aa43f60b8e7b04993897b3a6d9dc177972c831418bd91369b2e696719bead7`.
With cwd at the disposable stage, `USERPROFILE` and `HOME` set to its
`userhome`, `LOCALAPPDATA` set under that home, `PI_CONFIG_DIR=m00-stage`,
and no inherited `XDG_DATA_HOME`, `PYTHONHOME`, or `PYTHONPATH`, the
actual invocation `C:\Users\assas\.bun\bin\bun.exe
<stage>\global\node_modules\@oh-my-pi\pi-coding-agent\src\cli.ts
--version` exited 0 and printed `omp/18.2.10`; stderr empty with
`PI_DEBUG_STARTUP=1`. The stage home has a new `.bun` cache and `.omp`
agent directory. This proves launchability of the copied **source**
subject without a provider call, not child execution, an issuer, or
custody. The package's build scripts require missing monorepo siblings;
the prebuilt `dist/cli.js` was neither copied nor rebuilt. Free
physical memory before launch was 1,408,500 KiB.

Independent read-only host-source research identified the SDK
registration and structured-child allocation points but no protected
issuer. Independent architecture review found extension factories and
tools execute in the unrestricted host address space; private TS
fields, host-source hooks, signatures whose key shares that process,
and same-user subprocesses cannot deny a hostile in-process extension
the issuer/state. The only tested runnable restricted child (D0)
retained issuer read, trust-state write, process VM read/write and
handle-duplication access. The denying variants did not start the
executable (`0xC0000022`); denial without runnable work is not custody
proof. Review proposes one bounded **unperformed** D2
restricted-token parent/worker canary with fixture-only objects as
the next falsification, requiring separate authorization beyond the
source-copy grant. No protected API was added to the copy: that would
claim a boundary the permitted launch cannot establish.
`M00-CORD-01` and the cumulative qualification remain OPEN.

### Candidate-local HIGH repairs and limits (2026-09-22)

**SEC-INTEGRITY-01 candidate:** shared schema v3 adds a domain-separated
SHA-256 chain over all stored event-envelope columns; integrity and
checkpoint verify from genesis rather than trusting `last_verified_seq`,
and replay rejects a broken chain before projection. The v1/v2 transition
checks the old payload chain where present, snapshots committed predecessor
data, retains historical event cells, marks derived pre-migration provenance
as unauthenticated, and commits the new column/origin/version atomically.
New events have a NULL archived `prev_hash`; v3 reopen does not repair
missing envelope hashes. A v2 predecessor, interruption before commit,
snapshot readback, new append, reopen and VMem-only v2 upgrade passed
focused tests. Headerless ledger history was reproduced as incorrectly
adopted by VMem before the authority guard, then refused without restamping.
Metadata-only event tampering and forged watermark regressions failed
before the candidate fix and pass afterward. The ledger/schema suites
passed 88/88; VMem 70/70; migration-chain 8/8; Ruff check passed and
Pyright reported zero errors/warnings. Unkeyed hashes provide consistency,
not authenticated authorship or protection against a writer who can
rewrite DB, hashes and snapshots. This is candidate-local evidence, not
independent HIGH closure or production migration.

**SEC-HOOK-02 scoped candidate repair:** managed Claude, Codex, and
Antigravity templates/installer commands bind the system PowerShell
executable and absolute installed runner script. Codex replaces its own
single marker block instead of retaining an old bare executable; unrelated
TOML is preserved. The disposable `agy plugin install` and App copy
were both checked against target script/hook hashes; repeat install was
idempotent. Native CMD invocations from a hostile cwd and PATH returned
`{}` without executing the hostile `powershell.cmd` or project runner.
Pester installer suite passed 4/4. A read-only static reviewer accepted
scoped managed-command identity, not arbitrary unmanaged hooks,
uncontrolled transitive subprocesses, or cumulative M00 acceptance.
Disposable hook/plugin smoke fixtures were removed; no real user hook
configuration was installed.

**JeV supplementary audit:** given the focused test outputs, source
hashing behavior, and host-copy custody result, JeV assigned probability
0.81 to the *candidate-local tamper-evidence improvement* and 0.03 to
*complete M00 qualification including protected issuer custody*. This
judgment cannot replace deterministic checks or independent acceptance.
`M00-CORD-01`, remaining HIGH findings and the cumulative M00 gate stay
OPEN; production activation and canonical-state changes remain unperformed.

### Subsequent candidate repair and adverse review (2026-09-22)

**SEC-INTEGRITY-01:** the independent static ledger reviewer found a
SQLite-affinity mismatch on append and an unbound retained legacy-origin
marker. Both were reproduced as focused red regressions. Append now hashes
the stored values returned by SQLite; migrated v3 origins bind the prior
origin text by digest. The focused ledger/schema/VMem suites passed with
these corrections. This is tamper evidence, not authenticated authorship;
old v1 writers must be quiesced for a rollout. Native v3 manifest rebuild,
copied-ledger origin and external authorship remain unaccepted.

**SEC-SKILL-01 / SB-PROMOTION-004:** independent read-only review of the
earlier candidate returned FAIL. It found an approved status line could be
rewritten to model-visible instructions without changing the normalized
hash; unapproved descriptors and Python/TS Lean kernel/nudge bypassed the
hydration gate. The status-line attack was reproduced red, then fixed by
normalizing only complete lifecycle values; it now refuses the changed
body. Descriptors and both Lean consumers now check current reviewed text
before exposing it. The Python Lean cache-hit regression alters the body
without changing mtime/size and is refused; TS warm-cache and missing
review regressions refuse. The review also found no passing evaluation
record or required-dependency binding, and frontier approvals can be
self-minted by a same-user agent. Those obligations and SEC-AUTH-01 remain
OPEN; local content consistency is not protected approval. Re-review of
the corrected bytes is requested; the adverse verdict is retained for its
earlier subject.

**FSUPD-01:** independent read-only review of the earlier activation script
returned FAIL: approval-record TOCTOU, governed preflight only after
installation, overwrite of a preexisting sealed production record,
unchecked manifest-generator identity, and no same-user Windows custody
in the private TEMP stage. The candidate now captures each approval
record once, checks generator identity, preflights the approved host/
extension surface before backup or install, refuses an existing production
evidence destination, and targets a new candidate evidence directory.
Six disposable activation tests passed, including preflight refusal,
sealed-record preservation, install and rollback. The actual historical
APPROVED-SUCCESSOR record refuses this changed script with exit 1 and
creates no pack; no production file was touched. Same-user staging,
approval-minting authority, external races, compatible operational
rollback and fresh owner approval remain OPEN. No production activation
was attempted. Re-review of corrected bytes is requested.

**Focused integration checks:** Python pytest selection covering skill,
promotion, adapters, Lean, activation, ledger, schema and VMem passed
(396 tests; the `-q` runner printed 396 dots). TS Vitest candidate config
passed 62 targeted Lean/cache/injection-placement tests. Ruff check,
Pyright (0 errors/warnings), ESLint and `tsc --noEmit` passed. The
whole 2,375-collected Python suite did not complete: prior run timed
out after six failures. Five named failures arise when tests reset a
schema version while the user-owned uncommitted `0028_runtime_lineage.sql`
table remains present; the successor identity test detects a stale
historical approval subject. These are not waived as green.

**Supplementary JeV:** on focused checks, earlier adverse reviews, and
the host-copy D0 custody result, JeV returned 0.89 for *candidate-local
fail-closed improvements* and 0.02 for *complete M00 qualification*.
Neither number closes a HIGH or substitutes independent execution.
`SB-ORCH-001`, `SEC-AUTH-01/02`, `M00-CORD-01`, and the cumulative M00
gate remain OPEN. D2 restricted-token parent/worker canary requires
separate owner authorization; no real approval, canonical-state write,
production install or activation was performed.

### Final candidate-only checks and stop boundary (2026-09-22)

**FSUPD-01:** a later independent static review still returned FAIL for
the intermediate activation script: its manifest inherited only the
predecessor's partial hash inventory and could consume an ambient delta.
The candidate now derives all 13 governed host and every approved extension
binding from the approved hash map, supplies an explicit empty delta, and
checks manifest schema, runtime roots, counts, and each sealed/installed/bound
hash after generator write/check. It then rechecks the governed installation.
A disposable negative test with the real generator refuses an unapproved
extension source and rolls back; the activation suite passes 9/9.
This correction has **not** received a new independent acceptance review.
The historical approval still refuses the changed activation script before
creating a pack (exit 1); the candidate production-evidence destination
remains absent. No real host install or production activation was attempted.

**SEC-SKILL-01 / SB-PROMOTION-004:** the same-reviewed-text lifecycle/status
gate and Hermes/Lean consumption regressions pass locally. A requested
independent re-review of these corrected bytes could not complete because
the reviewer provider returned HTTP 429. Missing independently established
passing evaluation and dependency binding, plus caller-mintable frontier
approval, remain open; local consistency must not be called protected
approval.

**Final checks:** a focused Python selection of activation, skill,
Skill Forge, Lean, adapters, ledger and VMem passed 293/293. The full
candidate Vitest run passed 37 files and 787 tests. Ruff check, Pyright
(0 errors/warnings), ESLint and `tsc --noEmit` passed after the latest
code changes. The prior whole-Python-suite timeout and its six failures
remain adverse evidence, not a green full-suite claim. No changes were
made to the user-owned runtime-lineage migration or historical approval.

**Disposition:** `M00_PARTIAL_EXTERNAL_BLOCKER`, not candidate-qualified.
`M00-CORD-01`, `SB-ORCH-001`, `SEC-AUTH-01/02`, the unresolved
`SEC-INTEGRITY-01` authorship/provenance, `SEC-SKILL-01` evaluation and
protected review, `FSUPD-01` protected approval/staging and operational
rollback, transitive `SEC-HOOK-02`, and final integrated independent
acceptance remain OPEN. Owner action: authorize the separate disposable D2
restricted-token parent/worker canary and provide a non-agent-controlled
host capability and approval/receipt issuer for the *exact* candidate
subject. A fresh review and compatible candidate bundle are then required;
neither the source-copy grant nor local hashes authorize activation.

### Authorized disposable D2 custody canary (2026-09-22)

The owner authorized the previously recorded D2 only, with fixture-owned
objects and a stop-on-failure boundary. Probe SHA-256
`01d024d1db96685f80d096bf620162edd1860a0692f76e9beca06cbe6fa56150`
ran from `C:\Users\Public\Documents\brain-m00-d2-rQF8yy`. The probe
constructed a `CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)` token with
one restricting SID, `S-1-5-12`; `IsTokenRestricted` returned true.
The fixture alone received the owner/restricting-SID file ACLs and an
unnamed fixture window station/desktop with the previously recorded
`0x37f`/`0x123` and `0x1ff`/`0xc3` rights. The first attempt with a named
station returned Win32 error 5 at `CreateWindowStationW`; after using
the previously tested unnamed-station pattern, station and desktop
creation succeeded, but `CreateProcessAsUserW` returned Win32 error 5
(`ERROR_ACCESS_DENIED`) before a child PID was produced. No command ran,
no permitted work output was written, and no child-origin issuer read,
trust write, supervisor-memory access, or handle-duplication attempt
occurred. This is **D2 launch failure, not custody proof**; the denied
startup resource was not isolated. Both attempts closed their token
and station/desktop handles. The entire disposable fixture and probe
were removed (`fixture_removed: true`).

The authorized D2 path stops here: no D1/D3 variant, startup tracing,
new isolation framework, production/canonical mutation or authority
claim. `M00-CORD-01` and all previously listed HIGH and acceptance gates
remain OPEN. A protected non-agent-controlled issuer/channel remains
necessary; a restricted token that cannot launch is not an alternative.

### Existing host/platform authority capability assessment (read-only)

OMP 18.2.10's disposable **source** copy was inspected, not patched or
executed for this assessment. Extensions are imported and their factories
called in the host process (`src/extensibility/extensions/loader.ts:416-452`);
the extension API exposes the host namespace (`types.ts:1198-1199`).
Structured children are built by `createAgentSession` in the same process
(`src/task/executor.ts:3783-3805,3829-3833`), while
`AgentRegistry.register` replaces a ref by ID without an issuer check
(`src/registry/agent-registry.ts:146-165`). The context's async-job snapshot
(`src/extensibility/extensions/types.ts:428-445`) supports correlation,
not authenticated root, child, request or generation facts. The candidate
bridge accordingly advertises `authenticated_observation_source:false`,
`effective_tool_grant:false`, and `execution_census:false`
(`brainstem/prime-extension/bridge/brain-host-bridge.ts:251-269`).
This is a bounded 18.2.10 source/API conclusion, not a proof about all
future OMP releases or every bundled-only code path.

Windows named pipes can expose a peer **process** ID, but their DACL grants
access by token, not by OMP's in-process root/worker identity
(Microsoft: `https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid`;
`https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights`).
A same-user, in-process hostile extension can act as the same OMP process;
a pipe, private JS state, native module key in that same address space, or
host-side registry string cannot independently distinguish it. Windows
AppContainer isolates an *entire application process*, rather than
protecting one component inside it
(`https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation`).
Process VM read/write and handle duplication are explicit process rights
(`https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights`);
D0 observed them allowed, while D2 never launched. AppContainer deployment
plus a distinct trusted supervisor would be a new, separately authorized
host/process architecture and still needs OMP-origin lineage proof. No
currently demonstrated, already-exposed host or authorized platform
primitive supplies the full protected issuer/channel.

**Decision boundary:** freeze restricted-token trials. Do not promote a
same-process native signer, same-user broker token, named pipe, or OS PID
to protected M00 authority. An upstream OMP primitive is useful only if
it also establishes custody against model-controlled extensions; SDK
hooks alone cannot do so. Under the present grant, report protected
coordinator issuance **unsupported on this host configuration**, keep
privileged delegation fail-closed, and retain `M00_PARTIAL_EXTERNAL_BLOCKER`.
Whether to change M00 acceptance to permit an explicitly unsupported
capability is an owner decision, not an inferred HIGH closure. No new
isolation experiment, enrollment, or production change occurred.
