---
date: 2026-09-21
type: plan
authority: proposed
status: draft
scope: verification-execution
supersedes: none-additive
superseded-by: none
promoted:
---

# Design — constrained verification execution for BrainHostProtocol v1

> **Status: proposed, in `docs/intake/`.** Written by a `system-architect` pass at the
> owner's request (recorded as a requirement in
> `../requirements/2026-09-21-requirement-verification-execution.md`). It is a *proposal*,
> not authority: it grants nothing, and it authorises no implementation. It stays in
> `intake/` until the owner promotes it under the four gates in `../intake/README.md`.
>
> Nothing here was implemented and no runtime experiment was executed for it. Section 9 is
> handoff material for future work and section 10 lists what this design does **not**
> establish.

# 1. Current gap and established facts

Citations below use the exact path roots supplied in `citation_roots`; for example, `H/src/exec/exec.ts:9-53` names the installed package source, not an upstream repository.

**The present verifier lane cannot independently execute the subject.** Its declaration grants `read, grep, glob, ast_grep`, with no shell or evaluator (`V:1-5`). Its instructions require source preservation and distinguish inspected evidence from personally executed checks (`V:31-48`). The assignment additionally establishes that eval-defined tools are not exposed to workers in the current lane. Consequently, an agent verdict can establish source-level findings, audit existing artifacts, identify inconsistent evidence, or report runtime behavior as UNDEMONSTRATED. It cannot truthfully mean “this verifier independently ran this candidate.” Reading an implementer's transcript is artifact auditing, not an independent run.

**Important precision:** this is not a claim that OMP 18.2.8 lacks every mechanism for exposing eval-defined tools. Installed code has an explicit exposure mechanism and enablement check (`H/src/task/eval-tools.ts:77-114`), and task dispatch supplies requested eval custom tools (`H/src/task/index.ts:1482-1489`). Those are not exposed in the assigned lane and must not be enabled as a workaround: arbitrary parent-defined executable tools do not establish the desired authority boundary.

The installed package identifies itself as 18.2.8 and ships both source and the CLI artifact (`H/package.json:1-3,27-45`). Existing bridge observations are binding, cancellation and inventory, not verification execution (`B:49-84,309-374`). Its advertisement keeps effective grants, settlement, cleanup, complete census and authenticated source false (`B:251-269`). Existing safety features require their capabilities and qualified advertisement provenance (`P:46-86,325-442`).

The rehearsal is useful evidence of parser, negotiation and bridge-narrowing behavior, **not a real verifier execution demonstration**. Its `stockContext()` is synthetic (`E:42-57`); the report explicitly preserves that limitation even in its final reviewer conditions (`R:269-272,379-394`). Do not promote the report's “live-load” heading into evidence of a live host event boundary.

**Qualification-hash correction:** current `advertisement_sha256` hashes canonical parsed JSON, not literal file bytes (`P:193-219`; `R:222-230`). Preserve that actual contract. Retain a separate raw artifact digest in evidence when exact reviewed serialization matters; do not silently redefine the existing field.

# 2. Recommended minimal design and ownership

Append precisely these booleans to the existing seven-capability vocabulary:

- `verification_execution`
- `verification_environment_identity`
- `verification_result_attestation`

Keep every existing capability name and meaning. These are independent facts; availability of a process launcher does not imply confinement, environment identity, or authentic provenance. Missing capability remains false, as in the present manifest parser (`P:270-317`).

Use four ownership boundaries:

1. **Independent authorizer / qualification owner:** admits a sealed candidate and an invocation policy; owns qualification records and final acceptance. This is not the verifier or candidate process.
2. **Host verification runner:** resolves the candidate, validates the caller and policy, launches the command, controls its resources, captures output and produces the factual result. It owns only verification execution state and a separate evidence store—not Brain writer leases or settlement state.
3. **Bridge:** maps the host's execution facts to the protocol and advertises only capabilities supported by qualification evidence. It does not interpret test exit status as approval and does not grant authority. This preserves the existing bridge's stated ownership boundary (`B:1-15`).
4. **Verifier and Brain consumer:** the verifier selects a permitted check and interprets evidence; Brain validates provenance and bindings before using it. A separate acceptance owner decides whether the requirements are met. Neither a result record nor the verifier's verdict releases a writer or approves deployment.

The verifier-facing operation should be a single proposed `verification_request` tool. **This name is a design proposal, not an existing OMP API.** It accepts structured executable/argv data only for previously admitted invocation policies. It is not a command-string proxy, evaluator, package installer, task launcher or generic RPC client.

Use an existing independently enforced execution environment if one is available. This proposal specifies its required properties; it does not propose building a general sandbox. If no available backend can enforce them, advertise `verification_execution: false` and refuse execution. A disposable directory alone is insufficient.

# 3. Capability meanings, proof and degradation

## `verification_execution`

**Question:** Can this verifier ask the host to execute a policy-approved, bounded invocation against this exact disposable candidate, without obtaining ambient execution or mutation authority?

**Evidence required for true:** a live caller-bound request path; exact candidate and executable resolution; enforceable input immutability and output-write policy; production and canonical-state isolation; bounded execution, output and concurrency; observed success, nonzero exit, timeout/cancellation and denial cases; and evidence that descendant processes cannot continue using the verification environment after completion. Record the qualified implementation and enforcement-policy digests. A function named `exec` is not sufficient evidence.

**Cost of false:** runtime requests refuse; source review and existing-artifact auditing remain possible. The proposed `independent_runtime_verification` feature must refuse, not fall back to parent-run shell commands, eval tools or a writer worker.

**Cost of a false-positive advertisement:** arbitrary candidate code acquires the user's filesystem, credentials or production access; an apparently read-only verifier becomes an execution deputy.

## `verification_environment_identity`

**Question:** Can the verifier establish which host instance/build, bridge, runtime executable, effective execution profile and workspace actually performed this request?

**Evidence required for true:** a runner-observed launch record containing the host instance and generation; a digest identifying its admitted loaded build; bridge digest; runtime path/version/digest; executable path/digest; candidate input manifest/digest and resolved workspace; effective environment and enforcement-policy digests. Freeze or otherwise bind the measured inputs through launch to prevent measure-then-replace races. Include uncommitted candidate content, test inputs and relevant dependencies/configuration; a Git commit or package version alone is insufficient. Expose the referenced manifests for audit, not just opaque hashes. Distinguish the controlling host build from the candidate being tested.

**Cost of false:** commands must not qualify as verification of a specified subject. `independent_runtime_verification` refuses. A separately authorized diagnostic might generate logs, but those logs cannot close a requirement about an exact candidate.

**Cost of a false-positive advertisement:** a passing run against an old checkout, different runtime, changed dependency set or production workspace is attributed to the submitted candidate.

## `verification_result_attestation`

**Question:** Can the verifier obtain a host-produced result that binds the request, measured execution identity, termination and output artifacts, with an explicit, honestly supported provenance strength?

**Evidence required for true:** the runner—not the agent or tested program—constructs a complete result envelope, binds it to the admitted request and attempt/generation, captures termination from the process controller, hashes captured output, and declares a validated provenance mode. Exercise mismatched request, replay, modified output and substituted-result cases. A transcript saying “PASS” is not such a record.

This capability's boolean means that this evidence-envelope facility exists. It does **not** by itself mean impersonation resistance. The per-result provenance enum and the existing `authenticated_observation_source` capability make that distinction explicit.

**Cost of false:** no result can be admitted as host verification evidence. `independent_runtime_verification` refuses, even if some process ran. Existing artifacts remain auditable as unverified claims.

**Cost of a false-positive advertisement:** agent-authored or substituted output is laundered into host evidence. Treating its weak mode as authentication would also bypass the existing safety model.

## Feature negotiation

Add one proposed safety-qualified feature, `independent_runtime_verification`, requiring:

```
execution_binding
 effective_tool_grant
 verification_execution
 verification_environment_identity
 verification_result_attestation
 authenticated_observation_source
```

It also requires qualified advertisement provenance using the existing mechanism. The `effective_tool_grant` requirement prevents a supposedly read-only verifier from retaining a different mutation-capable route. The grant must classify the new bounded tool's actual semantics; a name alone is not proof.

Do not add these requirements to memory, retrieval, context injection, telemetry or source/artifact review. Do not relax `read_only_delegation_verified`, `mutating_delegation` or `settlement_recovery` (`P:46-105,370-442`). Runtime evidence can inform an independent review but never substitutes for settlement or cleanup.

On stock 18.2.8 the new safety feature remains refused. New capabilities start false until separately demonstrated; lack of authenticated source and effective grant alone is already sufficient to refuse the qualified feature. An extension-only experiment is explicitly authorized research, not an enabled production dispatch lane. The existing restricted declared lane must not become an automatic bypass (`R:78-81`).

# 4. Strict request and observation contract

Everything in this section is **proposed protocol**, not an installed OMP method.

## Parsing and primitive rules

- UTF-8 JSON objects; duplicate keys rejected at every nesting level using the existing strict-load discipline (`P:164-190`). For these new request/result types, reject unknown fields and unknown discriminants as well.
- No coercion, truthiness, trimming into validity or dropping malformed array entries. Reject non-finite numbers, unpaired surrogates, NULs in text/path arguments and oversized documents.
- `protocol_version` is the exact integer `1`, never `true`. Numeric fields are exact integers, never booleans, numeric strings or fractional numbers. Wire integers stay within JavaScript's exact-integer range.
- `Id`: nonempty string, at most 512 characters. `Token`: the contract's lowercase identifier syntax. `Sha256`: exactly 64 lowercase hexadecimal characters.
- `Path`: nonempty platform path string, at most 4096 characters, checked by the host against its admitted registry. No user-controlled URI dereferencing. Display paths are not authority.
- Requests are at most 256 KiB. `argv` is an array of at most 128 strings, at most 4096 characters each and 32 KiB UTF-8 total. Empty argument strings are legitimate and must be preserved. There is no shell interpolation or joining of arguments.
- Proposed initial policy bounds: timeout 1–120000 ms; at most 1 MiB captured per output stream; one active request per verifier binding. The independent authorizer can admit a smaller bound, never an agent-supplied larger one.

## Request: `HostVerificationRequest`

All fields below are required; braces denote exact objects:

```
{
  protocol_version: 1,
  kind: "HostVerificationRequest",
  attempt_id: Id,
  host_generation: nonnegative exact integer,
  request_id: 32 lowercase hex characters,
  nonce: Sha256,
  requester_agent_id: Id,
  requester_native_execution_id: Id,
  policy_id: Id,
  policy_sha256: Sha256,
  expected_environment_sha256: Sha256,
  workspace: {
    candidate_id: Id,
    input_manifest_sha256: Sha256,
    cwd_relative: string
  },
  executable: {
    path: Path,
    sha256: Sha256
  },
  argv: string[],
  timeout_ms: exact integer in 1..120000,
  expected_access: "read_only" | "writes_permitted"
}
```

`cwd_relative` is `.` or a normalized candidate-relative directory. Absolute paths, drive-relative paths, parent traversal, alternate roots and unresolved links are refused. The runner resolves it beneath a registered candidate, verifies the resulting object identity, and holds that identity through launch. The verifier cannot register candidates, select arbitrary environment variables or choose a different home directory.

The policy registry binds candidate, caller/attempt/generation, admitted environment digest, exact executable digest, allowed argv forms, timeout/output bounds and writable output locations. No security decision comes from the asserted requester fields: they must equal identity supplied by the host's caller binding. Registering or changing a policy is not a verifier operation. Scripts, response files and plugin/test inputs referenced by argv must be admitted input artifacts; an interpreter with `-c`, a shell with `-Command`, or an unbounded plugin-discovery path cannot bypass the invocation policy.

`expected_access` is a requirement, not a promise made by the caller:

- `read_only`: command-visible inputs/filesystems are non-writable; stdout/stderr pipes remain usable. The host may persist the captured evidence outside the command's accessible namespace.
- `writes_permitted`: only policy-listed disposable output/scratch locations are writable. The sealed subject, tests and acceptance inputs remain immutable. This does not mean a writable source checkout, canonical Brain writes or a writer lease.

A command needing cache/build writes uses `writes_permitted` and admitted output locations. A host unable to enforce the requested mode refuses rather than silently widening it. Use isolated copies, not writable links/hardlinks into canonical trees; a Git worktree is not treated as a security boundary.

## Response observation: `HostVerificationResult`

The observation retains the existing base fields (`P:445-485`):

```
{
  protocol_version: 1,
  kind: "HostVerificationResult",
  attempt_id: Id,
  host_generation: nonnegative exact integer,
  method: nonempty string <=512 characters,
  observation: nonempty string <=512 characters,
  request_id: 32 lowercase hex characters,
  nonce: Sha256,
  requester_agent_id: Id,
  requester_native_execution_id: Id,
  request_sha256: Sha256,
  request: HostVerificationRequest,
  outcome: Refused | SpawnFailed | Finished,
  attestation: HostRecord | AuthenticatedRecord
}
```

`request_sha256` hashes the canonical complete request; the echoed request must match it. All duplicated binding fields must agree. Only an authoritative caller-supplied expected attempt/generation/request/nonce is usable for admission; extracting expected values from the received record would be a tautology. Existing optional expected attempt/generation checks demonstrate the distinction between structural validity and binding (`P:448-475`). Make those expectations mandatory at the verification-result consumer.

Use these exact tagged outcomes:

```
Refused = {
  state: "refused",
  reason_code: RefusalCode
}

SpawnFailed = {
  state: "spawn_failed",
  native_execution_id: Id,
  execution: ExecutionIdentity,
  error_code: "not_found" | "permission_denied" | "launch_error"
}

Finished = {
  state: "finished",
  native_execution_id: Id,
  execution: ExecutionIdentity,
  started_at_unix_ms: nonnegative exact integer,
  ended_at_unix_ms: nonnegative exact integer,
  duration_ms: nonnegative exact integer,
  termination:
    {kind: "exit", code: exact integer} |
    {kind: "signal", signal: nonempty string <=64 characters} |
    {kind: "timeout"} |
    {kind: "cancelled"} |
    {kind: "output_limit"} |
    {kind: "host_error", code: nonempty string <=64 characters},
  process_tree_state: "reaped" | "unknown",
  confinement_state: "enforced" | "violated" | "unknown",
  subject_integrity:
    {state: "unchanged", after_manifest_sha256: Sha256} |
    {state: "changed", after_manifest_sha256: Sha256} |
    {state: "unknown"},
  stdout: OutputArtifact,
  stderr: OutputArtifact
}
```

`RefusalCode` is a closed enum:

```
UNQUALIFIED_HOST | CAPABILITY_UNAVAILABLE | BINDING_MISMATCH |
WORKSPACE_MISMATCH | ENVIRONMENT_MISMATCH | EXECUTABLE_NOT_ALLOWED |
ARGV_NOT_ALLOWED | ACCESS_NOT_ENFORCEABLE | PROTECTED_TARGET |
AUTHORITY_VIOLATION | REQUEST_CONFLICT | CAPACITY_EXCEEDED
```

Malformed or unsupported wire payloads produce protocol parse errors before execution, not a coerced well-formed observation. A refusal has no execution ID or fabricated zero exit status. `spawn_failed` identifies the admitted launch attempt, not a process that successfully ran.

`ExecutionIdentity` is an exact object:

```
{
  host: {
    vendor: Token, name: Token, version: nonempty string <=64,
    instance_id: Id, build_manifest_sha256: Sha256
  },
  bridge_sha256: Sha256,
  runtime: {
    name: Token, version: nonempty string <=64,
    path: Path, sha256: Sha256
  },
  platform: {
    os: Token, architecture: Token, kernel: nonempty string <=128
  },
  workspace: {
    candidate_id: Id, input_manifest_sha256: Sha256,
    resolved_root: Path, resolved_cwd: Path,
    isolation_instance_id: Id
  },
  executable: {path: Path, sha256: Sha256},
  argv: string[],
  timeout_ms: exact integer in 1..120000,
  effective_access: "read_only" | "writes_permitted",
  writable_roots: Path[],
  environment_profile_sha256: Sha256,
  enforcement_policy_sha256: Sha256,
  effective_tool_surface_sha256: Sha256
}
```

These are observed/admitted values, not blind copies of assertions in the request. `read_only` requires an empty `writable_roots`; `writes_permitted` roots must equal the independently admitted policy. The observed candidate, environment, executable, argv, timeout and access must match the request and policy, or the run is inadmissible. Host identity and candidate identity remain separate even when the candidate is another OMP installation.

```
OutputArtifact = {
  artifact_id: Id,
  sha256: Sha256,
  stored_bytes: nonnegative exact integer,
  capture: "complete" | "limit_reached" | "incomplete"
}
```

Artifacts contain captured bytes, not agent summaries. The digest covers exactly `stored_bytes`; it does not pretend a stored prefix represents a complete stream. Reaching an output cap terminates the run with `output_limit`. Incomplete capture, unknown process-tree state, violated/unknown confinement, or changed/unknown subject integrity prevents a successful verification claim even if an exit code is zero. A completed nonzero test is valid runtime evidence of failure, not a failed attestation.

```
HostRecord = {
  mode: "host_record",
  issuer_id: Id,
  record_sha256: Sha256
}

AuthenticatedRecord = {
  mode: "authenticated",
  issuer_id: Id,
  record_sha256: Sha256,
  algorithm: "ed25519",
  key_id: Id,
  signature_base64: canonical base64 of exactly 64 signature bytes
}
```

The chosen signature format is a proposed future wire contract, not an OMP facility. Compute `record_sha256` over the complete response excluding `attestation`, using a fully specified canonical JSON encoding matching the existing sorted-key, compact, ASCII-escaped JSON hashing convention (`P:193-219`). Sign the domain-separated bytes `BrainHostProtocol/v1/HostVerificationResult\0` followed by the ASCII record digest. Pin issuer/key authorization outside the worker's writable context. A sender's `mode: authenticated` or a locally verified signature using an attacker-supplied key is not evidence of authentication.

## Ordering, duplicates and failure

- Validate qualification, capabilities, caller identity, policy and frozen input identity before launch. Mismatch means no spawn.
- Bind one request ID to one canonical request digest within the authoritative attempt/generation. An identical retry shares the existing execution/result; a conflicting digest refuses. Never re-run merely because delivery was lost.
- Host restart changes the authoritative generation. Old requests/results refuse; lost execution state is UNDEMONSTRATED, not assumed clean. No automatic recovery that can create a second run.
- Timeout/cancellation stops the entire contained execution, drains/captures bounded output and records the actual ending. Cancellation is not success. If reaping cannot be established, record `unknown`, quarantine that verification environment and refuse reuse.
- `process_tree_state: reaped` concerns only this verification execution. It is never converted into `HostWorkerSettlement`, `HostWorkerCleanup`, a writer release, or proof that an unrelated worktree is idle.

# 5. Authority invariants and required refusals

| Invariant | What would violate it | Mandatory refusal / enforcement |
|---|---|---|
| No writer lease | Submitting or completing a check creates, transfers, releases or refreshes Brain writer ownership | Verification dispatch cannot call writer-admission/release paths; reject lease/ownership fields and operations. Compare writer state before/after in the demonstration. |
| No canonical/DB mutation | A command writes repository canonical data, derived Brain DB/state, production extension/install, or a shared Git directory | Those resources and credentials are absent or independently denied. Refuse targets resolving outside the admitted disposable environment, including junction/symlink/hardlink escapes. Project namespaces are defined in `.worktrees/qualified-v2/AGENTS.md:18-27`. |
| Source-preserving verification | The verifier repairs source/tests/acceptance fixtures and verifies the repaired result as the original subject | Sealed input identity remains immutable. Only admitted output locations are writable. Any integrity change invalidates the run. |
| No self-approval | Exit zero or verifier PASS records acceptance, qualification, promotion, deployment or a waived requirement | Result schema has facts, not approval fields. Approval APIs/credentials are unavailable. Only a separate authorized owner accepts evidence. |
| No lifecycle authority | A request/result mints a settlement, cleanup completion, generation, lifecycle token or release permission | Caller cannot select authoritative identities. Reject lifecycle-control fields/commands. Never translate the new observation into old lifecycle observations. |
| No production reach | Candidate code accesses production network endpoints, host sockets/pipes, real home credentials, live DB, deployment tools or writable production paths | Default-denied network and IPC; no credentials or host handles inherited; policy-approved fixtures only. If the backend cannot enforce this, refuse execution. |
| No general shell authority | The new tool accepts arbitrary command strings, interpreter snippets, unrestricted executable paths, user-selected env or nested worker launch | Structured argv plus admitted invocation policy; only the host runner launches. No shell/eval/task tool added to the verifier. Candidate test code remains potentially hostile, so allowlisting does not replace confinement. |
| No result laundering | Agent stdout, bus payloads or editable session logs can create trusted execution evidence | Runner captures OS results; provenance mode is explicit. An unauthenticated record never satisfies the qualified feature. |

These are properties of the runner and its independently enforced environment, not promises embedded in a prompt. Unsandboxed extensions remain outside what an extension-only prototype can defend against.

# 6. What attestation means on this host

On OMP 18.2.8, an extension-only `verification_result_attestation` can at most provide a **host-generated record that hostile in-process code could forge**.

That record is operationally better than an agent's own statement: a separate callback can capture actual process output, bind a nonce/request and preserve exact artifacts. It is not stronger origin evidence against an attacker who controls another extension in the same process. Hashing detects inconsistent content, not a hostile emitter that recomputes the hashes. Signing with a key available to that same process merely moves the forgery target.

Installed evidence supports this limit:

- The public extension API exposes a shared EventBus (`H/src/extensibility/extensions/types.ts:1499-1500`).
- Binding extensions shares the resolved bus and runtime (`H/src/extensibility/extensions/loader.ts:480-501`).
- `EventBus.emit(channel, data)` directly delivers arbitrary payloads; the frame helper merely emits onto buses (`H/src/utils/event-bus.ts:3-48`).
- The extension load guard prevents startup hard exits and stdin hijacking; it is not a filesystem/process security boundary (`H/src/extensibility/utils.ts:89-117,117-172`).
- The reviewed bridge therefore keeps authenticated source false (`B:266-269`; `R:285-291,387-394`).

For stronger provenance, the result producer, its execution registry, verification key and acceptance consumer need a boundary unavailable to candidate code and hostile OMP extensions: for example, an independently controlled broker under a distinct OS principal or equivalent existing isolated execution service. The broker must authenticate **authorized scope and actual launch**, not sign arbitrary JSON supplied by an extension. Brain must validate its proof outside the adversary's writable execution context, using independently provisioned issuer trust, current request bindings and anti-replay state. The candidate must not inherit signing credentials or access to the control channel.

An upstream observer or a private JavaScript class alone cannot supply this. Keep `authenticated_observation_source: false` until that separate boundary is demonstrated. Do not redefine it to mean “a host callback was probably the emitter.”

# 7. OMP 18.2.8 feasibility and smallest seam

| Installed surface | Can carry | Cannot honestly establish |
|---|---|---|
| `ExtensionAPI.registerTool`, schema and `ToolDefinition.execute(toolCallId, params, signal, onUpdate, ctx)` | A narrow structured request and structured tool result; cancellation signal; explicit tool exposure | A trusted caller/source boundary or execution confinement. Tool `approval: exec` is an approval category, not a sandbox. `H/src/extensibility/extensions/types.ts:595-640,1265-1266`; registration storage `H/src/extensibility/extensions/loader.ts:205-213`. |
| `ExtensionAPI.exec(command, args, options)` | Existing extension-side process launch with cwd, timeout and AbortSignal | Candidate confinement, clean environment selection, production/network exclusion, complete environment identity or attestation. Public options contain only signal/timeout/cwd; result contains stdout/stderr/code/killed. `H/src/extensibility/extensions/types.ts:1410-1411`; `H/src/extensibility/extensions/loader.ts:300-302`; `H/src/exec/exec.ts:9-53`. |
| `execCommand` result mapping | Ordinary process output for a trusted demonstration | A sufficiently precise termination union: absent `exitCode` becomes `0`, and `killed` records an aborted flag. Do not translate this mechanically into successful verification or distinguish timeout from cancellation without additional evidence. `H/src/exec/exec.ts:38-53`. |
| `ExtensionAPI.events` / EventBus | Request/result correlation notifications in a prototype | Authentic origin, exclusive producer identity, or settlement authority. `H/src/extensibility/extensions/types.ts:1499-1500`; `H/src/utils/event-bus.ts:3-48`. |
| `ExtensionContext.cwd`, `sessionManager`, `getAsyncJobSnapshot()` | Calling-session context and job correlation | Immutable candidate/build identity, a complete execution census, another child's effective grant or process confinement. Context declarations: `H/src/extensibility/extensions/types.ts:429-448`; existing bridge interpretation: `B:79-84,251-269,348-374`. |
| `getActiveTools/getAllTools/setActiveTools` | Calling-session tool registry metadata and activation | An authenticated post-resolution child permission grant. Public API: `H/src/extensibility/extensions/types.ts:1413-1420`; child wiring uses that child's session: `H/src/task/executor.ts:4007-4010`. |
| Child explicit tools and custom-tool plumbing | A future narrow verification tool can be deliberately exposed to the verifier without adding bash/eval | Proof of final permissions from the agent declaration alone. Tool list handling: `H/src/task/executor.ts:3357-3387`; custom/MCP tools: `H/src/task/executor.ts:3659-3663,3740-3752,3803-3808`. Qualification must inspect the final surface, not just the YAML list. |

**Smallest upstream seam:** a host-owned, attempt/caller-bound **verification runner port** with structured submit/result semantics, a read-only effective-grant observation for the requesting worker, and execution/environment/termination facts produced below the extension's tool callback. Expose that port through the documented extension boundary rather than importing OMP internals into the Brain bridge. These are proposed changes; the inspected public extension and exec interfaces contain no `HostVerificationResult` or verification runner API.

The port must delegate confinement and, for strong mode, authenticated result production to an already suitable independently controlled backend. Adding a method to `ExtensionContext` without that backend does not make the guarantee true. An external broker adapter could potentially avoid a host patch for some transport plumbing, but it must still obtain independently trustworthy caller admission and final grant evidence; neither should be claimed from an unsigned extension frame.

**Extension-only prototype:** register an explicitly granted verification tool; validate the proposed schema and invocation policy; run a fixed harmless fixture via existing `exec`; capture its output into `mode: host_record`; exercise parsing, bindings, known exits, output handling and policy refusals in a disposable host/profile. This can demonstrate transport and auditability under a trusted-extension assumption. It cannot demonstrate hostile-code confinement, production exclusion, impersonation resistance or the qualified feature. Do not advertise the complete `verification_execution` contract true solely from such a prototype.

# 8. Demonstration required before a runtime-verification claim

This is a future experiment specification, not work performed in this assignment.

## Preparation

An independent fixture/qualification owner, not the verifier:

1. Creates a sealed disposable candidate containing the exact subject and acceptance inputs; records manifests for the host launch artifact, bridge, dependencies, runtime, configuration and subject. Source files alone do not identify the running installed CLI artifact (`H/package.json:27-45`).
2. Registers one caller-bound invocation policy and a controlled execution environment with no production credentials or reachable production resources.
3. Starts the actual candidate host and loads the candidate bridge/tool. Creates or reuses the read-only verifier with exactly its inspection tools plus the proposed request tool; records the **resolved** tool surface. Do not substitute `E:43-57`'s context stub.
4. Places protected sentinel resources outside the allowed execution namespace, using disposable stand-ins for canonical files, DB, production path and local IPC/network services. Attempts to name actual protected paths must be refused before accessing them; the experiment must not write to real production as a test.

## Exact execution exercises

Use a proposed immutable stdlib-only `verification-probe.py` fixture, separately reviewed and digest-pinned. The authorized request's executable is the admitted Python executable; argv is exactly `['-I', '-B', '<sealed-fixture>/verification-probe.py', '--case', '<case>']`; timeout is 1000 ms for the timeout case and 10000 ms for the others. This fixture does not exist yet and is explicitly a proposed experiment asset, not a claimed repository script.

Cases:

- `ok`: writes distinguishable bytes to both output streams and exits 0. Require exact argv/environment/candidate binding and independently recomputed artifact hashes.
- `nonzero`: exits 7. Require `termination.kind=exit, code=7`; no success conversion.
- `timeout-descendant`: starts a child that would create an output marker after the parent timeout. Require timeout result and externally observed absence of a surviving descendant/late marker before environment reuse; unknown reaping prevents a verified claim.
- `output-limit`: exceeds the admitted output cap. Require `output_limit`, a correctly hashed captured prefix and `capture=limit_reached`, not a complete-output claim.
- `write-input`: attempts to change sealed candidate source. Require enforced denial and unchanged input manifest.
- `write-output`: denied under `read_only`; allowed only in the admitted disposable output root under `writes_permitted`. Protected inputs remain unchanged in both modes.
- `escape`: tries parent traversal, a prepared link/junction escape, a canonical/DB sentinel, the production stand-in, host IPC and a denied network endpoint. Each unauthorized action must be denied by the enforcement boundary, not merely omitted by a cooperative fixture.

Also execute a **real subject check** through the same request path: the sealed `scripts/host-bridge-conformance.py` against (a) a valid admitted advertisement/observation fixture, and (b) an advertisement with a duplicate capability key. Its actual CLI accepts `--advertisement` and `--observations`, preserves input bytes and reports strict-load failures (`.worktrees/qualified-v2/scripts/host-bridge-conformance.py:27-36,64-117,124-135`). Require exit 0 for the valid case and exit 2/`DUPLICATE_JSON_KEY` for the duplicate case, independently captured by this new execution. That establishes runtime behavior of the conformance subject, **not real-host settlement or cleanup**. For any broader claimed behavior, select and run an acceptance check that exercises that actual path.

## Authority and forgery exercises

- Submit requests containing writer-lease, settle, release, approve, promote or caller-selected lifecycle authority. Require parse/policy refusal and unchanged externally observed writer/approval state.
- Attempt the same actions indirectly from the candidate process. Require absence/denial of the relevant filesystem, credentials and control endpoints.
- Attempt shell/interpreter substitution, extra argv, alternate cwd, wrong executable hash, wrong input digest and larger timeout. Require refusal before spawn.
- Replay a result with a wrong attempt, generation, request ID, nonce, request digest, environment or output artifact. Require rejection before requirement admission.
- Repeat an identical request: one execution only. Reuse its ID with different bytes: refusal.
- On the extension-only prototype, emit a byte-identical forged frame from another extension using the real EventBus. The expected finding is **no authenticated origin can be established**; Brain must refuse the qualified feature rather than pretend the frame was rejected cryptographically.
- On a future strong backend, attempt forged result submission and arbitrary-record signing through that boundary. Require authentication/scope rejection. Only then may `authenticated_observation_source` be reconsidered.

## Evidence and claim rules

Accepted evidence is the frozen input/build manifests; admitted policy and environment records; resolved verifier grant; raw request and response bytes; canonical and raw artifact hashes; output bytes; runner-origin termination; external denial/reaping observations; unchanged protected-state evidence; and requirement-by-requirement PASS/FAIL/UNDEMONSTRATED findings from an independent acceptance owner.

Do not use the bare label **independently runtime-verified** until the live verifier request path, exact identity, required execution safety, appropriately authenticated provenance and the relevant subject assertions are all demonstrated. A nonzero or negative result can be independently observed runtime evidence without making the subject PASS.

For the weak prototype, the correct wording is: **“Verifier-requested runtime observation, recorded by a trusted-in-process extension; not impersonation-resistant or security-qualified.”** A source/artifact-only review must continue to say exactly that.

# 9. Ordered implementation handoff — future work only

| Task / owner | Scope and dependencies | Acceptance |
|---|---|---|
| 1. Protocol implementer | After separate implementation authorization: extend `P`, `.worktrees/qualified-v2/tests/test_host_protocol.py` and conformance input handling. Add three capability names, the one safety feature, strict request/result parsing and mandatory consumer binding; preserve all existing requirements. | Each missing new requirement refuses only its dependent feature; wrong provenance remains refused; strict types/duplicates/unknown variants/binding mismatches fail before execution; weak attestation never unlocks qualified verification. Existing tests already cover negotiation and strict parsing (`tests/test_host_protocol.py:64-219,243-308,408-444,466-483,545-585`, relative to `.worktrees/qualified-v2/`). |
| 2. Host/backend owner | In parallel with task 1 only after the wire contract is frozen: supply the proposed runner seam and choose an existing enforceable backend. Installed extension/exec surfaces above are integration locations, not sufficient implementations. Provide caller/grant evidence and exact launch/result identity. | Live bounded execution and all confinement/provenance negative cases demonstrated; absent prerequisite keeps capability false. No general sandbox construction or unsafe extension-only fallback. |
| 3. Bridge/integration owner | Depends on 1+2. Extend `B`'s narrow host surface, advertisement and observation mapping; expose only the request tool to the verifier. Keep host-specific field knowledge in the bridge. Update the rehearsal entry without confusing synthetic checks with live proof. Coordinate any later production consumer wiring in `.worktrees/qualified-v2/brainstem/prime-extension/src/index.ts` with its owner; do not reclassify bounded execution as writer ownership. | All actual observed values reach the strict contract; stock defaults refuse; unavailable fields never fabricate identity/termination; no calls into settlement, cleanup, writer or approval paths. |
| 4. Independent validation owner | Depends on integrated 1–3. Own the live experiment and authority/forgery probes, not implementation repairs. | Evidence packet demonstrates each applicable invariant; incomplete or weak evidence remains UNDEMONSTRATED. Parent owns final integration and performs project-wide validation once. |

Tasks 1 and 3 share protocol types/advertisement semantics and should not edit those interfaces concurrently. Bridge integration should be serial with any changes to the existing admission code. Host/backend work can proceed independently against the frozen proposed wire contract. No worker should independently run project-wide checks while siblings are changing shared surfaces.

# 10. Compatibility, rollout and explicit non-establishments

Older v1 consumers reject unknown capabilities (`P:270-299`), so adding capability keys is **not transparently backward compatible**, despite keeping `protocol_version: 1`. Deploy support in the Brain consumer before a bridge emits the new keys. An old bridge remains safe with a new consumer because absent capabilities default false (`P:313-315`). Do not teach old consumers to ignore unknown capabilities.

Any changed bridge or advertisement requires new qualification evidence: the existing mechanism compares the canonical advertisement hash and bridge digest (`P:325-367,390-410`). On rollback, restore a mutually compatible bridge/consumer/qualification combination or remove the new emission and remain refused. No database backfill, writer-lease migration, production activation or automatic promotion is part of this design.

**Not established by this assignment or the existing rehearsal:**

- Any implementation of the three new capabilities or new observation/tool.
- Live execution by the read-only verifier.
- An authenticated result channel or protected signing authority on stock OMP 18.2.8.
- Enforced child filesystem/network/IPC confinement, effective-grant authentication or complete process reaping for verification.
- Production exclusion merely from a disposable cwd, a tool label, a hash or a restricted agent declaration.
- Worker settlement, cleanup completion, census completeness, writer release or self-approval authority.
- Equivalence between inspected package source and the exact running build, absent the proposed launch manifest.
- Full project/runtime acceptance from conformance fixtures or from a passing exit code.

The material implementation prerequisite is an independently enforceable execution backend and, for the qualified claim, a genuine authenticated producer/consumer boundary. Stock extension plumbing alone cannot satisfy it. That is an explicit engineering dependency, not a reason to weaken the protocol or grant the verifier shell access.
