# OMP / Second Brain M00 — trusted lineage research and implementation handoff

**Research date:** 22 September 2026  
**Status:** SOURCE-RESEARCH COMPLETE FOR THE EXAMINED SURFACES; IMPLEMENTATION AND RUNTIME QUALIFICATION NOT PERFORMED  
**Scope:** Automatic, model-independent coordinator recognition; protected admission and lifecycle issuance; portable Second Brain contracts. This is not a general security certification of OMP.

## 1. Decision

Retain automatic coordinator recognition, but implement it as an authenticated relationship between an explicitly admitted root execution context and a Second Brain episode. Do not derive authority from a model, provider, display name, `role=driver`, the string `Main`, an absent parent field, a transcript path, or whichever caller arrives first.

Use OMP's actual root bootstrap and session/spawn boundaries to supply provenance. The ordinary extension context, registry, and event bus are not an authenticated admission mechanism. A small host integration is a plausible implementation route, but it must be paired with evidence that agent-controlled execution cannot mint, steal, replay, or bypass its authority.

Keep request authority separate from evidence-issuer authority:

- The root coordinator may request work and permitted control operations within its episode.
- A worker may submit its own result through its permitted interface.
- Only the protected host-side producer may certify the host facts it actually observed, such as execution acceptance or cleanup completion.

A root model must not receive the issuer credential merely because it is the coordinator. This directly addresses the user-reported admission-to-completion-credential route; this research did not reproduce that private Brain route.

## 2. Evidence identity and limits

The upstream `v18.2.9` tag resolved to:

`8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75`

A later upstream `main` snapshot inspected during research was:

`b84f082e5b40494a253f6c1fecc5cf8bf17011d2`

The GitHub comparison placed that snapshot 13 commits ahead. The extension-context file had the same Git blob identity in both snapshots. Do not interpret either public snapshot as proof of the user's installed bytes, existing local patches, or ordinary launcher resolution. [S01–S03]

Research used official source, documentation, issue reports, and relevant Microsoft security documentation. It did not execute Bun/OMP, run Windows adversarial probes, access the live Brain database, modify the user's repository, or perform an independent runtime review. Search-discovered test files are starting points, not tests claimed to pass.

## 3. Findings and their implementation consequences

### F01 — Runtime identity exists internally, but the public extension context is insufficient

The inspected `ExtensionContext` exposes session and model access, mode, lifecycle methods, and tool-wrapper facilities, but not an authenticated root/child subject or protected issuer capability. The matching upstream issue requests main-versus-subagent observability; that request does not by itself specify authorization. [S03, S15]

**Consequence:** An extension-only implementation must not claim to have solved protected lineage by reading session metadata. New introspection fields would help diagnostics, but authentication additionally requires trustworthy creation and channel binding.

### F02 — OMP's root classification is not a security principal

The SDK derives main/sub classification from caller-supplied depth/prefix options. Its source also discusses additional top-level helper sessions within one process. Public options include parent/agent identifiers and registry input. [S04]

**Consequence:** Even a correctly read internal `main` classification does not establish that the session is the authorized root of a particular Brain episode. A worker-created SDK session, helper session, or separately launched OMP process must not acquire episode ownership merely by looking top-level.

### F03 — Several similarly named identities have different meanings

| OMP value | Appropriate use | Inappropriate use |
|---|---|---|
| `parentAgentId` | Host-side agent-tree correlation | Standalone proof of an authenticated caller |
| `parentTaskPrefix` | Artifact/output naming; child receives its own identifier here | Treating it as the spawning parent's identity |
| Session-header `parentSession` | Transcript fork/branch/new-session metadata | Canonical authorization foreign key |
| Transcript-entry `parentId` | Position within the conversation-entry tree | Parent agent identity |
| Model/provider/cache identifiers | Routing, accounting, caching | Coordinator permission |
| `AgentRef` identity / expected-ref checks | Live registry ownership and stale-reference checks | Durable cryptographic identity across process restart |

The session documentation explicitly distinguishes opaque header lineage from typed identity. Registry mutations and SDK identifiers are normal host bookkeeping, not a substitute for a protected Brain binding. [S04–S06]

### F04 — The common child-launch boundary is useful

Task and eval requests converge on `runStructuredSubagent`. It resolves policy, allocates artifacts/child identity, assembles executor options, and calls the execution path. Parent identity comes from the parent `ToolSession`, with a legacy fallback to `MAIN_AGENT_ID`. [S07]

**Consequence:** Implement the candidate's common admission gate at this semantic boundary and the subsequent session-construction boundary, not only around the visible `task` tool. For Brain authority, missing authenticated parent evidence must remain missing; do not translate the legacy fallback into a root grant.

Other consumers and continuation paths must still be inventoried. A common fresh-spawn boundary is not proof that every resume, wake, or direct SDK path goes through it.

### F05 — The event bus cannot enforce durable admission

`EventBus.emit` returns without awaiting async subscribers. Subscriber failures are caught and logged. The same frame mechanism serves session and root-scoped observability buses. [S08]

**Consequence:** Do not implement admission as an event subscriber that writes to Brain while execution proceeds. The gate must be a directly awaited control operation whose refusal prevents the protected transition. Emit telemetry only after the relevant decision is committed, while clearly distinguishing telemetry from authority.

Cryptographically signing an event would not, by itself, make this asynchronous ordering safe. Likewise, a synchronous API would not, by itself, authenticate its caller. Both provenance and ordering are required.

### F06 — Extension loading already has useful compatibility mechanisms

Normal project extension discovery is permissive. However, OMP also supplies the repeatable `--trusted-extension` route: native module paths are checked, normal extension discovery is disabled for that route, and selected extension-load errors are fatal. The root bootstrap can load extensions before `createAgentSession`. [S03, S09]

**Consequence:** Reuse the existing explicit-loading mechanism in an approved candidate launch profile instead of inventing another extension loader. Do not claim that an allowlisted path makes writable bytes, imported dependencies, custom tools, MCP processes, or configuration safe. Verify the complete executable-input boundary and preserve production configuration.

The SDK already distinguishes reusable prepared factories from loaded parent-bound extension instances. Rebind factories for children; do not reuse a parent closure that carries parent authority. [S04]

The existing `ctx.invokeTool` facility is same-tool delegation to a native built-in for a wrapper, not a general arbitrary-tool invocation API. It may help compatibility wrappers, but wrapping only `task` is insufficient coverage. [S03]

### F07 — Tool execution is broader than JSON tool arguments

OMP's executor describes agent sessions as in-process despite the historical `runSubprocess` name. Its eval documentation exposes host-capable JavaScript APIs, direct file helpers, retained kernels, and child-callable functions executed in a caller's kernel. [S10, S11]

**Consequence:** Define the threat model around actual permissions, not labels such as worker, read-only, isolated, or VM. A worktree is not an authorization boundary. A separate process is not automatically one either.

A particularly important test is a child invoking a function that physically runs in the parent kernel. The Brain bridge must preserve the logical invoking child and its scope. It must not substitute the kernel owner's root authority. When that provenance cannot be established, do not expose coordinator-sensitive operations through the callback.

### F08 — Fresh launch is only part of the lifecycle

The executor supports kept-alive agents and warm revival. There is also a distinct cold-revival path in `task/persisted-revive.ts`, installed by the root bootstrap. It reconstructs sessions from persisted conversation/runtime metadata and reinitializes extension wiring. [S09, S10, S12]

**Consequence:** Warm revival, cold revival, follow-up turns, and wake turns need explicit revalidation. A transcript or restored registry row may help reconstruct context; it must not mint issuer credentials or reset episode budget liability.

Preserve logical subject identity when continuation is proven, but distinguish new execution attempts/incarnations. Revoke or fence stale execution authority before granting its replacement. Do not claim safe recovery merely because the same session file opens.

### F09 — Result acceptance is not full cleanup

The executor has output finalization, status notifications, cancellation/late cleanup, and keep-alive behavior. Registry run milestones reset when another run begins. These are separate facts with separate lifetimes. [S06, S10]

**Consequence:** A valid coordinator or an accepted result must not automatically release a writer lease. Preserve the existing distinctions between requested cancellation, accepted logical outcome, settled executor, completed cleanup, and permitted release. Do not rewrite accepted outcomes to match later cleanup labels.

## 4. Minimal portable contract

The following is a proposed contract, not a claim that OMP already provides these APIs. Reuse existing Brain identifiers, tables, and transaction helpers whenever their semantics fit.

```text
Root admission
  admission_id             trusted launch/admission intent
  episode_id               canonical Brain episode
  root_subject_id          Brain logical actor, not model name
  issuer_identity          trusted producer identity
  execution_epoch          current incarnation/fencing value

Child binding
  episode_id
  subject_id
  parent_subject_id
  root_subject_id
  attempt_id
  execution_epoch
  admitted_scope

Lifecycle observation
  episode_id
  subject_id
  attempt_id
  execution_epoch
  event_id / sequence
  observed_fact
  evidence_reference
  authenticated producer/channel binding
```

Native session IDs, agent registry IDs, paths, models, providers, and host versions belong in diagnostic mappings as needed. They must not independently grant permissions.

A durable lineage document need not be secret. Reading it must not let a worker impersonate the root. Authentication must bind a request to the actual actor/channel; public IDs in a JSON envelope are not that binding.

Do not automatically add a new signing infrastructure. A protected in-process capability and an authenticated out-of-process channel have different implementation needs. Choose the smallest mechanism that genuinely enforces the declared boundary. If portable signed records are used, bind their issuer, purpose/audience, episode, subject, attempt, incarnation, and replay handling. A valid signature is not permission to perform every operation.

### Root rule

Bind a new episode only through an authorized root-admission operation. The permitted root becomes coordinator automatically, independently of the model occupying the session.

Do not use 'first valid-looking root wins'. Associate the transaction with the authorized admission intent. Duplicate delivery of the same intent is idempotent; a conflicting root claim must be rejected. A uniqueness constraint alone prevents two winners but does not decide whether the winner was authorized.

### Worker rule

Workers receive lineage and scoped operation access, not root-coordinator or issuer authority. Nested spawning must obey the existing bounded delegation policy. Do not add unrestricted subtree coordinators in M00.

### Model-change rule

Changing model/provider/effort inside the same admitted logical session does not alter authority. If the host creates a new runtime as part of the change, its continuation/rebind must be proven rather than assumed.

### Recovery rule

Only a protected recovery operation can attach a new runtime to an existing subject. Old attempts remain distinguishable. Missing, conflicting, stale, or caller-edited evidence keeps privileged operations closed. Preserve existing episode-scoped accounting and unresolved liabilities.

## 5. Protection boundary: what M00 must prove

The stated requirement is stronger than 'ordinary well-behaved models use the right role'. It includes agent-controlled parent and worker execution being unable to acquire issuer authority.

Before selecting the enforcement mechanism, map whether each actor can reach:

- issuer credentials and credential-issuing operations;
- host process memory/handles and local IPC;
- authoritative Brain database files, journals, configuration, and runtime code;
- extension modules, transitive imports, custom tools, and executable plugin inputs;
- alternate execution routes such as shell, eval, native tools, and bridged callbacks.

An ACL permitting the same principal as an unrestricted agent process does not prove that the agent is excluded. Microsoft documents access-token/DACL checks for named pipes and process rights; process memory and handle access are separate permissions to consider. [S17, S18]

AppContainer is one OS-backed containment candidate on Windows, not a verified drop-in OMP solution. Its applicability to Bun, Python, LSP/MCP, debugging, and the user's workflow requires a bounded qualification spike. A separately authorized principal plus deliberately scoped IPC is another design direction, but still needs file/process/channel proof. [S19]

Do not silently introduce new accounts, change system permissions, disable security controls, expose a network listener, or broaden tool permissions. Reuse existing approved isolation where it suffices. Any additional protection profile must go through the existing authorization boundary.

A private TypeScript field, nonexported function, random port, hidden filename, named-pipe name, `role=driver`, or a credential in agent-readable environment/arguments is not adequate evidence by itself.

If actual containment remains unproven, report the split honestly: functional routing may pass while the host-only issuer gate remains blocked. Do not downgrade the stronger requirement into a cooperative-agent assumption to close M00.

## 6. Concrete M00 work packages

These are proposed packet labels. Reconcile them with the existing M00 register rather than overwriting occupied identifiers.

### M00-CORD-A — Inventory actual execution and authority paths

Record the exact Windows command resolution for ordinary `omp`, distribution/source entrypoint, loaded package/extension hashes, runtime versions, active local patches, Brain interpreter/import path, and disposable-state path. Do not copy credential databases or refresh tokens to make this inventory.

Map every operation that creates credentials, binds roots/children, authorizes worker creation, consumes reservations, accepts lifecycle facts, cancels, releases, or recovers. Search the private Brain candidate as well as the host adapter; this public-source study is not a substitute for that local inventory.

**Exit:** a caller/operation/credential/authority table with no unexamined privileged entrypoint in the declared scope.

### M00-CORD-B — Define invariants and normalized state transitions

Implement pure Brain-side admission, lineage, scoped authorization, replay rejection, and incarnation fencing against controlled test issuers. Separate public metadata from authenticated request context. Keep model/provider/name fields out of the authorization predicate.

Define new-session, fork, transcript import, resume, same-runtime model change, runtime recreation, and multi-root behavior explicitly. A transcript fork need not mean a delegated worker, and an imported transcript cannot import permissions.

**Exit:** deterministic core tests and documented invariants. This proves the core contract, not real host authenticity.

### M00-CORD-C — Add the smallest awaited host integration

Use the actual root bootstrap and child session boundaries:

1. Trusted bootstrap authorizes a root launch and establishes its Brain context before any Brain-privileged work. Constrain executable inputs before loading them.
2. A model tool call arrives through an actor-bound request interface. Actor identity is supplied by the trusted binding, not copied from tool arguments.
3. The shared child path resolves native policy, prepares an attempt, and submits an authenticated child binding with the real parent relationship.
4. Wait for Brain's durable decision before releasing the child gate for privileged execution. Account explicitly for subprocesses/resources created during preparation.
5. Retain lifecycle issuer credentials exclusively in the protected producer. Return only permitted results/receipts to the model.
6. Emit ordinary telemetry after the relevant committed transition; do not let subscriber success decide admission implicitly.

Cover normal creation, initialization failure, cancellation racing startup, warm revival, cold revival, follow-ups, and wake turns. Do not use `onFirstChatDispatch` latency observation as the admission gate.

**Exit:** a model-free host integration test proves that refused or unavailable admission prevents the protected action, not merely that a refusal was logged.

### M00-CORD-D — Reuse and qualify the protected launch profile

In an isolated candidate, exercise existing explicit extension loading and session-local factory rebinding. Verify the installed source actually supports the selected capabilities. Audit custom-tool/plugin/import paths separately; an extension allowlist is not an all-code allowlist.

Prove credential, database, runtime-code, IPC, and process protection against the actual permitted agent executors. Do not claim success based only on a diagram or a mocked issuer.

**Exit:** a retained containment/provenance result with exact allowed attacker capabilities. Otherwise the host-only issuer gate remains blocked.

### M00-CORD-E — Replace role predicates without weakening lifecycle rules

Only after the trusted binding path exists, change coordinator-only operations to consume it. Remove authorization weight from caller role/name/model flags while retaining diagnostic compatibility where useful.

The old direct-CLI admission route must not return issuer/completion credentials. Reject or deliberately remove its authority-granting behavior. Re-run both issuance and consumption probes; rejecting a forged completion token alone is insufficient.

Use distinct diagnostics for missing host capability, invalid caller binding, stale execution, cross-episode scope, and actual unauthorized coordinator requests. Keep existing public error compatibility where required without obscuring the reason in retained diagnostics.

**Exit:** ordinary root coordination succeeds and the reported worker self-promotion/credential issuance pattern fails under the declared threat model.

### M00-CORD-F — Regression, portability, and independent review

Run the test matrix below. Reuse the existing Brain reservation, settlement, recovery, and preservation suites. Keep fixtures disposable and one owner per mutating scope. Record exact candidate bytes and the test route actually executed.

Independent review must genuinely occur through an authorized path. A refused delegation is not an independent review; do not fix that by granting a caller-declared driver role or using another executor to bypass a denial.

**Exit:** cumulative review accepts the exact candidate and explicitly states what is still unqualified. Production activation remains a separate decision and procedure.

## 7. Acceptance matrix

| Area | Required scenarios | Required observation |
|---|---|---|
| Root admission | Authorized root; duplicate admission; competing unauthorized root | One correct durable owner; no first-caller elevation |
| Model independence | Different model names/providers; unknown future model metadata; model switch | Same authority decisions for identical authenticated lineage |
| Worker separation | Same model as root; worker claims driver/coordinator; copied root ID | No root authority or issuer credential |
| Alternate root construction | Worker launches another OMP/SDK session; helper is classified main | No automatic authority over the original episode |
| Spawn coverage | Task, eval agent, workpool first turn, nested child | Actor-bound admission enforced at every admitted route |
| Continuation coverage | Follow-up, wake, warm revive, cold revive, restart | Correct subject; distinct attempt/incarnation; stale authority rejected |
| Shared-kernel attribution | Child calls parent-defined tool; concurrent child calls | Logical invoking child is retained; no parent-privilege substitution |
| Extension binding | Fresh child and resumed child; repeated factories | Child cannot execute Brain requests through parent-bound authority |
| Admission ordering | Slow/unavailable/rejecting Brain; failure before/after persistence | No privileged execution before accepted durable binding |
| Issuer custody | CLI issuance, environment/argument/log disclosure, direct IPC access | Agent cannot obtain or invoke privileged issuer capability |
| Protected storage/code | Direct database/config/module modification attempts within allowed tool scope | Authoritative state and trusted code remain protected |
| Replay and scope | Duplicate event; conflicting duplicate; cross-episode; prior epoch | Idempotence for exact repeat; reject conflict or stale/foreign scope |
| Reservation regression | Proven-unused cancellation; duplicate refund; late dispatch; cancellation failure | Capacity restored at most once and only with accepted evidence |
| Settlement regression | Accepted outcome then cancel; late cleanup; keep-alive activity | Outcome consistency; no release before actual required settlement |
| Failure/recovery | Missing/corrupt binding; crash at each transition; unavailable host capability | Fail closed with retained liability and useful diagnosis |
| Upgrade compatibility | Same semantic capability contract across real candidate snapshots | Core policy unchanged; incompatible producer refuses safely |
| Harness portability | Reference adapters and later a real second harness | Mock equivalence labeled contract-only; real host qualification separate |
| Deployment identity | Test launcher versus ordinary user launcher | Results bound to actual executed bytes, not a version label alone |

Use deterministic fake-model metadata for the broad permutation matrix. Add a small real-model control only through authorized normal provider access. Avoid an expensive provider-by-provider campaign to test a predicate that must not depend on providers in the first place.

Do not treat event-delivery tests, unit tests, static typechecks, or `git diff --check` as proof of host authenticity, OS isolation, or actual Windows restart behavior.

## 8. Version independence and v3

The architectural invariant is:

> Second Brain core decisions depend on its authenticated normalized contracts, not a particular harness release, model catalog, native class name, event string, or session-file layout.

This does not mean never using versions. Protocol versions, capability declarations, pinned source snapshots, and tested adapter compatibility ranges are valuable. A native host may require a small release-specific translator or patch; confine that to the adapter/compatibility package, document it, and prefer an upstream supported interface when one exists.

Capability discovery must establish semantics, not only that a method exists. A host claiming `lineage` while exposing forgeable JSON must not satisfy a protected-lineage requirement.

Recommended split:

```text
Second Brain core
  normalized admission and authority
  durable subject/attempt binding
  budgets, lifecycle, recovery
  replay/fencing and policy decisions

Host adapters
  native startup/spawn/continuation translation
  actor-bound request routing
  host lifecycle observation
  compatibility/probe results

Platform protection
  approved process/file/credential/IPC isolation
  executable-input trust and deployment integrity
```

Keep a small reference adapter for deterministic contract tests. Do not call a mock OpenCode adapter dual-host qualification. The existing roadmap reserves actual portable integration and a real second host for M12; M00 should establish the portable foundation without rebuilding that whole milestone.

Do not create another Brain database, second reservation ledger, or new orchestration system solely to implement identity. Use the existing authority and lifecycle structures wherever adequate. A broker design, if required, must be reconciled with the existing planned runtime/lifecycle broker rather than duplicated.

## 9. Agent continuation mandate

Proceed with source inventory, pure core contracts, and an isolated host prototype within existing permissions. Preserve the active installation and all historical acceptance records. Keep exact evidence for candidate identity, import/load paths, disposable stores, and scope of each result.

Do not wait for the upstream observability issues to become an authorization system. Reuse their concepts where useful, but implement/prove the missing control boundary explicitly. Prefer a small upstreamable host interface and replaceable adapter over monkey-patching arbitrary internals.

Do not bypass existing approvals, a refused coordinator operation, or resource caps to obtain an independent reviewer. Continue work that is genuinely authorized; label the remaining review/security gates truthfully.

The intended final closure claim is not 'any parent-looking model is coordinator'. It is:

> Any model occupying the authenticated, durably admitted root execution context can coordinate its episode. Descendants and agent-created lookalikes cannot acquire that authority, and neither root nor worker model-controlled execution can mint host lifecycle evidence.

## 10. Primary-source index

Ranges below are original repository source line ranges inspected, not wrapper/citation line numbers. Unless otherwise stated, all code links are pinned to the v18.2.9 commit. Search results naming related callers/tests were checked at the separately identified main snapshot and are not runtime evidence.

**S01 — Tag identity**  
`https://api.github.com/repos/can1357/oh-my-pi/git/ref/tags/v18.2.9`

**S02 — Comparison snapshot**  
`https://github.com/can1357/oh-my-pi/commit/b84f082e5b40494a253f6c1fecc5cf8bf17011d2`  
`https://github.com/can1357/oh-my-pi/compare/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75...b84f082e5b40494a253f6c1fecc5cf8bf17011d2`

**S03 — Extension context and same-tool wrapper API** — lines 380–600; comparison lines 424–532.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/extensibility/extensions/types.ts`  
`https://github.com/can1357/oh-my-pi/blob/b84f082e5b40494a253f6c1fecc5cf8bf17011d2/packages/coding-agent/src/extensibility/extensions/types.ts`

**S04 — SDK options, identity derivation, extension binding** — lines 430–640, 1580–1820, 2100–2300.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/sdk.ts`

**S05 — Session metadata semantics** — lines 1–185.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/docs/session.md`

**S06 — Agent registry / expected-ref / lifecycle** — lines 1–235.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/registry/agent-registry.ts`

**S07 — Shared structured subagent entry** — lines 1–230 and 400–650.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/task/structured-subagent.ts`

**S08 — Event bus** — entire small module.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/utils/event-bus.ts`

**S09 — Root bootstrap / explicit extension loading / cold-revive installation** — lines 1500–1710 and 2040–2270.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/main.ts`

**S10 — Executor / child session construction / warm revival / lifecycle** — lines 1–240, 2480–2720, 3270–3520, 3590–3985; partial monitor excerpt also inspected.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/task/executor.ts`

**S11 — Eval, shared kernels and kernel-defined tools** — inspected documentation excerpt starting at line 1, including runtime behavior and side effects.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/docs/tools/eval.md`

**S12 — Cold revival** — lines 1–210.  
`https://github.com/can1357/oh-my-pi/blob/8cd6f8c619e89e935b6c6c5c91f6a4d20f6d7a75/packages/coding-agent/src/task/persisted-revive.ts`

**S13 — Search-confirmed call sites / test starting points at comparison snapshot**  
`packages/coding-agent/src/eval/agent-bridge.ts`  
`packages/coding-agent/src/task/index.ts`  
`packages/coding-agent/src/task/workpool.ts`  
`packages/coding-agent/src/cleanse/agent.ts`  
`packages/coding-agent/test/task/structured-subagent.test.ts`  
`packages/coding-agent/test/task/workpool.test.ts`  
`packages/coding-agent/test/task/persisted-revive.test.ts`

**S14 — Search-confirmed trusted-extension flag and tests at comparison snapshot**  
`packages/coding-agent/src/cli/flag-tables.ts`  
`packages/coding-agent/test/cli-extension-path.test.ts`  
`packages/coding-agent/test/acp-mcp-isolation.test.ts`

**S15 — Main/subagent identity observability request** — issue opened 18 July 2026; open when inspected. Not proof of an implemented protected API.  
`https://github.com/can1357/oh-my-pi/issues/5985`

**S16 — Persistent spawn telemetry request** — issue opened 11 August 2026; open when inspected. A proposed telemetry contract, not an authentication guarantee.  
`https://github.com/can1357/oh-my-pi/issues/8259`

**S17 — Microsoft named-pipe access control**  
`https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights`

**S18 — Microsoft process access control**  
`https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights`

**S19 — Microsoft AppContainer isolation**  
`https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation`

## 11. Project-document provenance

The research also consulted retrieved Library copies of `00_MASTER_ROADMAP.md` (proposed roadmap dated 9 September 2026), an earlier M00 admission/credential review (`Pasted markdown.md`), and the historical `AUDIT-REPORT.md`. These establish project intent and prior findings, not present-day repository state or newly passing tests. In particular, do not reopen or declare closed historical audit items without reading the current candidate evidence.

**Production activation in this research: NOT PERFORMED.**
