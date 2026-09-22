# M00 campaign register

Maintained across the M00 one-shot closure campaign. One row per requirement/finding. Evidence is
reused only for its exact subject and claim; later evidence supersedes earlier status only for the
same measured subject.

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
| #3-R | **Restart replay**: journal without valid authority creates no new terminal evidence; accepted facts and ownership preserved; no secret persistence; no auto re-admission; replayed duplicates inert | host journal + `worker_recovery` path | — | — | `OPEN` | **next**: reproduce replay in disposable state, then implement fail-closed reconciliation against durable facts |
| #3-I | Real producer→consumer path (extension → bridge → `omp_adapter` → `record_worker_event`) with deterministic fixtures | candidate OMP installation | extension-side "real factory" lifecycle tests cover the extension leg only | — | `OPEN` | build the candidate OMP launch/loader route; distinguish fixture transport from production entrypoint |
| #3-M | Mutation re-run against **these** integrated bytes, with exact-byte restore | candidate | earlier run was against `01e4bdd` bytes | — | `OPEN` | after #3-R/#3-I land, so the mutation covers final bytes |
| #3-V | Credential custody on the accepted-mutating route (sentinels; model-visible output, logs, exceptions, telemetry, transcripts, journals) | extension + adapter | source audit: every token site host-internal; child/spawn path never carries it | — | `EVIDENCED_IN_CANDIDATE` (source) | sentinel run on the real route |
| ADM | **Admission-issuer authority**: a caller able to invoke admission obtains the credential for the attempt it created | `cli.py:3371-3384`, `omp_adapter.py:65-79`, `:138-139` | reproduced reading; `WORKTREE_WRITER_BUSY` proves exclusion on that path only | — | `OPEN` (explicit M00.3 blocker) | belongs to #4; #3 must not be described as closing no-self-approval |
| #2a | Initiating schema-collision containment | `brain_schema`, `vmem` | `c017dc3`; qualification record with reviewer verdict at top | operational defect CLOSED | `CLOSED` (as scoped) | — |
| #2b | Canonical schema authority | `brain_schema`, `ledger`, `vmem`, `contracts` | debt ledger in `schema-bootstrap-20260921/QUALIFICATION.md` | reviewer: `incorrect` for the stronger claim | `OPEN` | after #3: one authority for identity/legal transitions; deterministic registration; one version source per namespace; `events_fts` reserved-name conflict; per-missing-table DDL rule; deepen schema comparison; interrupt/compete-open tests; legacy reopen idempotency |
| #4 | Trusted issuance, host observations, effective grants | `BrainHostProtocol`, bridge, adapters | — | — | `OPEN` | after #2b: close the issuing route, not only the consumer; smallest enforceable candidate-local mechanism |
| #5 | Repeatable settlement and truthful worker recording | worker lifecycle | — | — | `OPEN` | after #4: one guarded finalization path; ten sequential mutating workers on one disposable worktree |
| #6 | Episode/root-scoped accounting | budget layer | — | — | `OPEN` | after #5: dedupe same billable request, not all requests; reserve before admission |
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

## Environment and constraints

- One heavy instrumented process tree at a time; stop new heavy work below 1 GiB available RAM.
- Each test run ≤ 30 minutes. Complete applicable suites on the final integrated candidate.
- Report/log budget: 512 MiB. Dependency space accounted separately (82 MiB venv + 74 MiB junction).
- No provider-backed test experiments or newly funded review calls; use already authorized review
  capacity, otherwise continue local work and report the budget dependency.
- Never touch the runtime worktree, installed extension, canonical database or production leases.
  Disposable homes/installations only; snapshots via a supported consistent mechanism (never a main
  DB file alone, never deleting WAL/SHM to make inspection work).

## Next executable step

1. **#3-R restart replay** — reproduce a journal-only replay in disposable state, then implement
   fail-closed reconciliation against durable facts (no persisted secrets, no auto re-admission, no
   ownership release, duplicates inert).
2. **#3-I real integration route** — exercise the candidate extension/bridge/adapter/Python path with
   deterministic fixtures, naming exactly which route is qualified.
3. **#3-M mutation** against the frozen integrated bytes, then **#3-review** covering producer,
   consumer, custody and replay together.
4. Then #2b, #4, #5, #6 in order, then the §9 security/deployment reconciliation and the cumulative
   evidence pack.
