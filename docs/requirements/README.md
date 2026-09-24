# docs/requirements — the current requirements set

Only files in this folder state current requirements. Everything else under `docs/` is
reference, archive or harness documentation. Presence here is not a claim about
implementation — it says what the project currently requires, or currently reports.

Reorganized 2026-09-21 from a classification of every file under `docs/`; each move kept the
original filename, so nothing was renamed and nothing was deleted.

> **On the V3 branch** this folder was copied in without the reorganization that produced it.
> Four files the tables below list here live elsewhere: the V4.2 implementation plan is at the
> repository root, and the v2 OMP-only release contract, the worker-integration checkpoint and
> the shipping activation card are under `docs/integrations/`.

## Authority chain

| Layer | Document | What it grants |
|---|---|---|
| Implementation authority | `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md` | what the completed v4.2 build must satisfy (`AGENTS.md` L9-11, `INDEX.md` L5) |
| Validation authority | `The_Second_Brain_v4_3_Proof_and_Validation_Test_Plan.md` — **external**, `C:\Users\assas\Downloads\`, sha256 `EE8F245D…` | what counts as proof for v4.3. No in-repo copy; the digest lives in `proof/manifest.json` |
| v2 requirement register | `../superpowers/plans/2026-09-02-second-brain-v2-implementation.md` | 12 requirements / 74 gate clauses. The OMP-only release contract calls it "the canonical Gate-text authority" |
| Release contract | `Second_Brain_v2_OMP_Only_Release_Contract_2026-09-19.md` | the OMP-only scope; retires 6 of the 74 clauses |
| Operative status | `Second_Brain_OMP_Status_2026-09-19.md` | what is installed, verified and deliberately bounded |
| Forward program | `Second_Brain_V3_Roadmap_2026-09-21.md`, `Second_Brain_V3_First_Session_Prompt_2026-09-21.md`, `M00.3_Phase_A_Host_Authority_Continuation.md` | the current campaign and its stop conditions |

## Clause count is 68, not 74

Archived plans still say 74 gate clauses. The OMP-only release contract names itself the
successor scope and retires six universal-control-plane clauses, so the operative count is
**68**. This is a scope decision recorded in a later document, not a defect in the earlier
one; when you read an archived plan, expect 74.

## Current-authority files

| File | Governs | Basis |
|---|---|---|
| `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md` | the v4.2 build | named implementation authority in `AGENTS.md` and `INDEX.md` |
| `Second_Brain_v2_OMP_Only_Release_Contract_2026-09-19.md` | release scope, gate-clause count | successor scope per its own header |
| `Second_Brain_OMP_Status_2026-09-19.md` | installed state, deliberate boundaries | status note dated 2026-09-19 |
| `00_MASTER_ROADMAP.md` | the 14-module / 56-packet register | module register still referenced by the v3 roadmap §1.3 |
| `Second_Brain_V3_Roadmap_2026-09-21.md` | the forward program | latest dated roadmap |
| `Second_Brain_V3_First_Session_Prompt_2026-09-21.md` | the bounded first session (M00.1) | execution prompt for the roadmap |
| `M00.3_Phase_A_Host_Authority_Continuation.md` | the current host-authority work | newest dated work directive |
| `second_brain_omp_worker_integration_checkpoint_2026-09-19.md` | worker integration state | integration checkpoint |
| `omp-shipping-activation-and-rollback-card.md` | installation state and rollback | **later record** than the activation proposals; per `AGENTS.md` L12 the later record wins, pending owner confirmation (D-5) |
| `2026-09-21-decision-v3-deterministic-kernel.md` | the v3 architecture direction: a small deterministic kernel with services around it, extracted from the existing Brain rather than rewritten | owner decision **D-6**, recorded 2026-09-21 |
| `2026-09-21-requirement-verification-execution.md` | independent runtime verification requires a constrained host capability; until it exists, agent verdicts are source/artefact-level and must be labelled so | owner directive, recorded 2026-09-21 |

## Supersession log

Format: `<archived file> superseded by <promoted file>, <date>`. Written only during
promotion (see `../intake/README.md`).

**Precedence rule:** *later, more specific evidence supersedes earlier status only for the
exact subject it re-measures.* An older statement stays historically true for its own
timestamp; it must not be read as a current status where a later record re-measured that
subject.

| Superseded | By | Date | Subject |
|---|---|---|---|
| `Second_Brain_OMP_Status_2026-09-19.md` — boundary 5, "Full v1/v2 release remains HOLD" | `omp-shipping-activation-and-rollback-card.md` (2026-09-20 conditional installation, citing the executed rollback rehearsal) | 2026-09-21 | installation/activation status **only**; every other boundary and gate still stands on its own latest subject-specific evidence |

The superseded statement was left in place, marked, rather than deleted: it was true at
2026-09-19, and the marking is what prevents the canonical set from presenting two
contradictory current statuses.

## Promotion log

No file has been promoted out of `docs/intake/` yet. One document entered this folder by
owner decision instead of by promotion:

| File | Entry | Date |
|---|---|---|
| `2026-09-21-decision-v3-deterministic-kernel.md` | authored directly into `requirements/` by the owner's decision (D-6), because it *is* a current requirement rather than a proposal; carries the same front matter a promoted file would | 2026-09-21 |

## Intake log

One line per item held in `docs/intake/`, so a refusal is not re-litigated:

| Item | Held because | Date |
|---|---|---|
| `docs/intake/2026-09-21-plan-verification-execution-design.md` | gate 1 fails: `authority: proposed`. It is a design proposal written at the owner's request and referenced by `2026-09-21-requirement-verification-execution.md`; promote only if the owner accepts it as the design of record | 2026-09-21 |

## Owner decisions — recorded 2026-09-21

All four were put to the owner and answered; none is silently resolved by an agent.

| # | Decision | Recorded outcome |
|---|---|---|
| **D-4** | the 14 module documents (`docs/modules/M00..M13`) and the other missing roadmap targets | **`NOT_YET_AUTHORED / SOURCE_UNAVAILABLE`.** Do not reconstruct or invent them. The v3 roadmap remains the bounded operative source where that substitution was already authorized. |
| **D-5** | installation status: 2026-09-19 HOLD vs the 2026-09-20 conditional-installation record | The **later record governs for installation/activation status only**. The HOLD statement is kept as history and marked superseded in place (`Second_Brain_OMP_Status_2026-09-19.md`, boundary 5); other unresolved gates stay governed by their own latest subject-specific evidence. Precedence rule recorded in the supersession log above. |
| **D-6** | architecture direction | **Small deterministic kernel**, adopted incrementally by extracting stable lifecycle, authority, capability, identity and state-transition semantics from the existing Brain and reusing existing services. Explicitly **not** a rewrite. See `2026-09-21-decision-v3-deterministic-kernel.md`. |
| **D-8** | §95 baseline benchmark suite ("12-task suite", deferred in milestone-02) | **Run it**; convert deferred evidence into measured evidence, within existing resource and test boundaries, with no provider spending or production mutation introduced merely to obtain a green result. Any portion that turns out to need either is stopped and recorded rather than weakened. **Status: in progress** — see `../../outputs/plans/baseline-benchmark.md` and the report pack for the measured runs. |

Five further items were answered outside that table and are recorded where they belong: the
stale capability record was quarantined (`../../outputs/reports/capability-record-quarantine-20260921/`);
**D-1** (v4.2 plan moved into this folder with its three pointer sites updated), **D-3**
(byte-identical duplicates archived rather than deleted) and **D-7** (at-risk material listed
in `../README.md`) followed the classification's defaults; and the new structural requirement
for independent runtime verification is recorded in
`2026-09-21-requirement-verification-execution.md`.
