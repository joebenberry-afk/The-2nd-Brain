# Second Brain — Orchestrator Removal Mandate

**Date:** 2026-09-23  
**Direction:** Remove Second Brain's orchestration product surface; do not maintain a disabled implementation.  
**Execution boundary:** Candidate-only changes, tests, local commits, and independent review. No production activation, canonical-state migration, push, tag, global OS change, or installed-host patch.  
**Status:** Execution instruction derived from the user's direction, not an implementation or qualification result.

## 1. Product decision

Second Brain is a harness-independent memory, context, knowledge, skills, and reuse system. The native harness owns agent creation, model selection, delegation, tools, execution permissions, scheduling, cancellation, retries, and task lifecycle.

Remove Brain's orchestrator rather than improving its handoff, maintaining native/governed dual modes, or preserving a test-only governed runtime. This instruction supersedes the previous choice to keep governed orchestration runnable through test switches. Orchestration improvements are out of the v3 product scope, not postponed prerequisites.

Agents may still use shared Brain knowledge, receive automatic context, retrieve approved skills, and write memory through authorized interfaces. Multiple native agents using Brain is supported consumption of a shared service, not permission to rebuild an agent controller.

Keep core behavior version-independent. Normalize host-specific inputs behind adapters. Do not bind core semantics to OMP/OpenCode/Hermes versions, internal classes, event names, role labels, or model/provider identities. Exact artifact identities still matter for testing; version independence is not an exemption from qualification.

## 2. Authority and source precedence

The user's September 23 report describes the latest candidate: extension 786 passed / 6 skipped / 0 failed; Python 2,373 passed / 7 skipped / 8 failed. The report attributes eight failures to earlier work, with four explicitly rerun against committed HEAD. These are reported results, not independently reproduced results in this document. The Python suite is not green.

The current local worktree is the implementation source of truth. The report identifies `.worktrees/m00.3-producer-guard`; verify the repository, branch, interpreter, and actual files before editing. Do not mistake the parent checkout's prompt for the candidate identity.

Archived roadmap/register copies are historical planning evidence. Where they demand orchestration repair, this product decision supersedes that demand. Preserve their historical verdicts and failed evidence rather than rewriting history as successful qualification.

Proceed with the candidate-local removal and the bounded work below without requesting another authorization merely to remove the retired feature. Existing restrictions on production, protected state, paid work, and privileged execution remain in force.

## 3. Immediate containment and preservation

Before another suite runs, fix `worker-context.test.ts` and audit the relevant test setup and child-process launches for real-home fallback. Every test that can load Brain must use an explicit disposable home, candidate source/interpreter, isolated working files, and isolated configuration. Clear inherited `PYTHONPATH` and `PYTHONHOME` before deliberately supplying any candidate-local import path. Apply the isolation to subprocesses, not just the parent runner. Assert the resolved import origin and data-home path.

Check the possible earlier real-home contact using read-only, consistent evidence. Do not restore an old backup over legitimate newer state. Distinguish no intentional activation from proof of no data writes. If no suitable before-state exists, report that retrospective preservation is not proven. This investigation must not become a new orchestration project.

Inventory tracked and untracked candidate changes, including pre-existing lineage and skill-approval work. Preserve other authors' changes and identify dependencies. Do not use blanket staging, destructive resets, or cleanup of unknown files. Record a compact patch/hash manifest; do not create redundant repository, database, or worktree copies merely for documentation.

## 4. Remove the execution-control surface

Remove executable implementations, imports, registrations, prompts, hooks, command wiring, packaging, and active tests whose sole purpose is:

- Brain driver/orchestrator/coordinator role creation, model allowlists, or privileged coordinator admission.
- Agent/worker dispatch, task scheduling, lifecycle mirroring, completion authority, replay authority, execution leases, reservation/settlement, cleanup barriers, or worker resurrection.
- Brain enforcement of native tool access, model/role assignment, worker budgets, or host task STOP/cancellation policy.
- Protected coordinator issuer/bootstrap/custody work that exists exclusively to support these removed operations.
- Native/governed mode selection, `governedOrchestrationForTests`, `worker_protocol._GOVERNED_FOR_TESTS`, and equivalent alternate activation paths.

Use dependency analysis, not filename deletion. A module named `governor`, `worker_context`, `contracts`, or `lineage` may also contain retained functionality. Extract or preserve that functionality, then remove the retired branches. Do not preserve a working retired engine because a shared helper is useful.

Do not replace the engine with a wrapper scheduler, second supervisor, native-handoff controller, or a renamed cognitive executive. Do not patch native harnesses to replace guarantees that Brain no longer offers.

### Retain only minimal compatibility where necessary

Unregister retired APIs wherever possible. A still-reachable legacy command may be a small inert refusal returning an explicit removed/unsupported result, with no dispatch, privilege grant, fabricated completion, reservation, or data mutation. It must not import or initialize the retired engine. No environment variable, config option, CLI argument, or test flag may reactivate it.

Ordinary memory/context loading must not require orchestration configuration. A missing legacy `mode` must not break loading. Old orchestration-only configuration may produce a bounded deprecation diagnostic but cannot activate execution governance. Preserve validation of unrelated retained settings. Specify the compatibility behavior and test it once; do not retain two runtime profiles.

Do not drop historical orchestration tables, receipts, artifacts, or migrations simply to remove runtime code. Retain them as historical data where needed, without active enforcement. Do not fabricate completion, settlement, release, or refunded capacity for old rows. Any future production cutover must account for live work and current data without destructive downgrade; that does not authorize rebuilding a census or custody subsystem in this campaign.

## 5. Preserve the useful Brain

Preserve automatic context injection, retrieval, canonical memory, provenance, knowledge/source discovery, project/session isolation, approved skill consumption, safe reuse, compaction checkpoints, and recovery of memory/context.

Preserve concurrent memory-write integrity, retained data-access authorization, source freshness checks, honest evidence, schema ownership, ledger integrity, hooks, and exact-byte skill/activation approval. A session or project identifier is correlation data, not automatically an authorization credential. Retrieved or learned content is not authority.

Preserve passive usage/cost accounting: available native usage records, deduplication, supported session/project correlation, explicit coverage limitations, and unknown usage recorded as unknown. Remove agent spend reservations and execution admission. Brain must not advertise enforceable native task budgets after removal.

Preserve resource limits for Brain's own work: retrieval/context size, cache/index memory, local computation, storage, and explicitly authorized maintenance. These limits may constrain Brain operations, not allocate or govern native agents.

Preserve the user's actual STOP/pause instructions and native permission decisions. Retiring a Brain task-control gate does not authorize continuing a stopped task or bypassing a permission denial. Controls over Brain's own protected writes remain applicable.

## 6. Test disposition: less dead code, not a misleading green result

Delete active tests that exclusively require the removed product feature. Record a compact retirement mapping: test or test group, retired requirement, removed entry point, and any retained invariant moved to another test. Git and existing evidence retain history; do not maintain hundreds of obsolete tests or copy their engine into fixtures.

Do not keep the 12 governed subprocess tests permanently skipped as an active roadmap obligation. Classify them individually. Their orchestration-only replay/completion proofs are retired, not passed. Where they also prove retained memory durability, injection delivery, or context recovery, replace that coverage against the retained shipping path. Account separately for the additional seventh Python skip reported by the user; do not silently include it among the six governed Python skips.

Handle the eight reported failures individually:

**Hermes: seven tests.** If a test exclusively expects Brain-governed completion authority that no longer exists, retire it with its requirement. If it checks retained memory/provenance behavior, keep and correct the retained contract without accepting unauthenticated completion as authoritative evidence. Optional observation of a native result must remain explicitly non-authoritative where that is all the adapter can establish. Do not build a Hermes coordinator issuer to finish this removal.

**Historical canary: one test.** Preserve the historical `budget-bridge.ts` identity and its original evidence. Determine whether the test belongs to the historical release subject or to an active candidate contract. Bind historical replay to its historical bytes; give an applicable candidate test its own current subject. Do not repin or delete historical evidence to manufacture a pass.

**Migration 0028 and skill approval.** Retain tests for any remaining schema/data and approved-byte obligations. `IF NOT EXISTS` alone does not establish that an existing table has the required shape or that data is preserved. Do not undo retained protections just to simplify the test inventory.

Add narrow shipping-path tests for no orchestration activation, default/legacy-config loading, removal refusals, preserved core behavior, and native operation without Brain execution admission. Run real subprocess integration against disposable homes where required. Unit tests behind alternate switches cannot qualify shipping behavior.

A retained applicable test failure remains a failure, even if inherited. Report executed, failed, skipped, retired, and historical-only populations separately. Every retained skip needs its own reason and qualification impact.

## 7. Reclassify requirements and HIGH findings by subject

Update `docs/intake/Second_Brain_M00_OneShot_Closure_Mandate.md`, `docs/intake/M00-CAMPAIGN-REGISTER.md`, and the actual active roadmap/acceptance sources together. Verify paths in the checkout. Do not only append a note while leaving contradictory active requirements elsewhere.

For a finding exclusively about the removed orchestration surface, use a disposition such as `RETIRED_BY_PRODUCT_SCOPE — NOT PROVEN`, supported by removal/reachability evidence. This is not a fix verdict and not retrospective qualification.

Retire orchestration-only obligations in `M00-CORD-01`, coordinator-specific `M00-CORD-02` semantics, and `SB-ORCH-001` where their actual subjects are removed. Preserve the general version-independent architecture principle. Split mixed `SEC-AUTH-01/02` clauses: coordinator issuance can retire; approval/trusted-memory authority for retained capabilities cannot.

Keep non-orchestration HIGHs applicable, including relevant portions of `SEC-INTEGRITY-01`, `FSUPD-01`, `SEC-SKILL-01` / `SB-PROMOTION-004`, and `SEC-HOOK-02`. Do not retire a vulnerability merely because its reproduction used an old worker route if a retained route can still reach the same dangerous sink.

Supersede the previous native/governed transition gate with one finite removal gate. Do not demand future governed support, protected worker issuance, or historical orchestration qualification as prerequisites for v3 memory development.

## 8. Freeze and independently review the actual candidate

Produce a reviewable local commit or commit stack containing the complete candidate dependency set. Preserve attribution of pre-existing changes. The reviewer must receive the exact source tree, relevant generated/package bytes, interpreter/dependency identity, configuration, and test results—not an older HEAD that omits working-tree fixes.

A post-test code change creates a new test subject. Re-run affected verification and issue a new manifest instead of carrying a previous pass forward unqualified. Reuse unchanged, applicable evidence where its dependencies still match.

Use an available native review route, without Brain orchestration, and honor the reviewer's real execution permissions. Review must be independent of the author. Distinguish static review from independently executed checks. An unavailable reviewer or test environment stays an explicit gap; never invent approval or weaken permissions to acquire a favorable verdict.

## 9. One bounded removal gate

The removal gate is satisfied only when:

1. No active or test-only Brain orchestrator remains reachable; required legacy refusals are inert.
2. Ordinary native operation and retained Brain memory/context/skills work in the tested scope without Brain task admission; native permissions and user cancellation are not overridden.
3. Tests and subprocesses use disposable state, and the possible earlier real-home contact has an honest disposition.
4. Retained applicable tests pass, skipped/retired/historical tests are enumerated, and no applicable HIGH has been waived by renaming it.
5. The active mandate, register, roadmap, tool surface, and claims agree on the new boundary.
6. Independent review covers the exact frozen candidate, with runtime proof and limitations stated accurately.

Report this as an orchestration-free candidate result, never as production activation or proof of the retired features. Report blockers by retained subject, not through the old orchestration campaign.

## 10. Continue toward v3

After the bounded candidate removal gate, proceed to attributable measurement and the request-neutral fast path in the isolated development environment. Before that gate closes, non-mutating analysis and isolated algorithm fixtures may proceed where they do not depend on unresolved defects; they do not qualify an unaccepted parent.

Use the accompanying orchestration-free roadmap. Keep delivery modular. Do not begin another coordinator, custody, supervisor, multi-agent runtime, or model-routing improvement campaign under a new name. Production activation and release publication remain separate decisions.

## Final report format

State the candidate identity; what was removed; what retained behavior was verified; the test-retirement mapping; the per-finding dispositions; real-home preservation evidence/uncertainty; exact independent-review scope; unresolved retained blockers; and the next bounded v3 packet. Distinguish author-tested, independently reviewed, candidate-qualified, and activated.

No claim in this document says that repository files, existing roadmap files, or production have already been changed.
