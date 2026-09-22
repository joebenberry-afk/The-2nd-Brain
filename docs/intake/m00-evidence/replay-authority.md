# M00.3 restart-replay qualification — corrected expectation

**Subject (frozen):** candidate worktree `.worktrees/m00.3-producer-guard`, branch
`brain/m00.3-producer-guard`, base commit `545133d` plus the artifacts listed below.
**Production activation: NOT PERFORMED.** The runtime worktree, the installed extension and the
canonical database were not touched; every Brain state used here is disposable.

## 1. What changed relative to the earlier (wrong) claim

The earlier checkpoint recorded that after a restart the journaled completion is "skipped, never
emitted". That was falsified by reading the rest of the recovery branch, and the owner then corrected
the *requirement* as well: the safety requirement is **zero unauthorized authoritative effects**, not
zero emission. A completion emitted without the attempt's credential and refused by the Brain
satisfies it, provided neither side converts the refusal into a false lifecycle fact.

This report qualifies that corrected requirement against the real path:

```
persisted admission + result journal → registered before_agent_start hook → recoverWorkerResults
  → reconstructed tracking state (no callback credential) → emitWorkerCompletion
  → runOmpWorkerResult (real bridge, real subprocess) → `-m second_brain autoinject omp-routing`
  → omp_adapter._prepare_worker_result → worker_protocol.record_worker_event → _require_terminal_authority
  → durable worker_tasks / worker_attempt_results
```

## 2. Route actually qualified

| Element | Identity |
| --- | --- |
| Extension under test | `brainstem/prime-extension/src/index.ts` factory, loaded as **source** by vitest (not the packaged `dist`, not the installed copy) |
| Hook | the extension's own registered `before_agent_start` handler (recovery call site `src/index.ts:3031`) |
| Bridge | the real `runOmpWorkerResult` (`src/worker-result-bridge.ts`) — the seam only captures its options |
| Interpreter | candidate venv `.worktrees/m00.3-producer-guard/.venv/Scripts/python.exe` (`sys.executable` echoed by the fixture) |
| Consumer | candidate source `src/second_brain/**` (`second_brain.__file__` echoed by the fixture, asserted to be inside the candidate worktree) |
| Durable state | disposable home under the OS temp dir, built by `tests/fixtures/omp_replay_state.py` |
| Journal | `ctx.sessionManager.getEntries()` (read) and `pi.appendEntry` (write) — the extension's real journal surfaces |

Not covered by this route: the real OMP host loading the installed/packaged extension (`dist`), i.e.
a host-level end-to-end launch. That remains a separate subject.

## 3. Cases and results

`brainstem/prime-extension/tests/worker-result-replay.test.ts` — **8 tests, all green** in the file's
own run and in the full extension suite.

| Case | Observation | Result |
| --- | --- | --- |
| Recovered mutating attempt | recovery reads the persisted admission + job binding, emits exactly one completion for the journaled `attempt_id`/`packet_sha256` with `callbackToken === undefined`; the real consumer refuses; the extension journals `worker-result-pending` and **not** `worker-result-accepted`; an `extension_error` record carries the same receipt failure; no `worker_completed` mirror and no dispatch-failure claim; the probe is unchanged (`WORKING`, ownership `held`, 0 attempt results). The refusal is corroborated by sending the *same bytes the bridge sent* straight to the consumer, which answers `UNAUTHORIZED_CALLBACK` | pass |
| **Already accepted mutating completion replayed** | the attempt first completes with its own credential (state `COMPLETED`, 1 attempt result, `result_sha256` and authority digest on disk); the unauthenticated replay then refuses, and the full row — state, ownership, lease, logical outcome, settled/cleanup flags, native binding, lifecycle sequence, attempt-result count **and** result hash, digest hash — is byte-identical before and after | pass |
| Journal label downgrade | journal claims `access_intent: read_only` while the Brain's row is mutating and holds the minted digest; journal is otherwise complete (job binding included) so the refusal cannot be a binding artifact; identical outcome to the case above | pass |
| Repeat replay | the same journal replayed through a second extension instance refuses again and accumulates nothing | pass |
| No persisted admission | result entry without an admission entry → zero emissions, zero worker journal entries | pass |
| Hook disconnected (vacuity control) | with the recovery hook unregistered, the reachability evidence (emission, `worker-result-pending`) is absent; the same journal through the registered hook produces it — so the absence assertions cannot pass because recovery never ran. This control asserts emissions, not a refusal, and therefore passes under the guard-removal mutation | pass |
| Credential present (binding control) | the *same emitted payload* plus the attempt's real credential is accepted (`ok: true`, state `COMPLETED`, 1 attempt result) — proving the replayed payload was binding-correct, so the refusals above were caused by the missing authority, not by a malformed request | pass |
| Read-only journal-only completion (**open finding**) | a genuinely read-only attempt (no digest, ownership `released`) accepts a completion carrying no credential at all; a duplicate replay of the same accepted completion adds no second effect | pass (records the finding) |

## 4. Findings

### 4.1 Reconstructing tracking state is not a new privileged admission (#3-R.2 reclassification)

Recovery populates `workerAdmissionsByTask`, `workerAdmissionsBySource` and `pendingWorkerTaskIds`
from `second-brain.worker-admission-pending`, and merges `nativeAttemptId`/`nativeJobId`/`agentId`/
`hostGeneration` from `second-brain.worker-job-pending`. It does **not**, on this path:

- call authoritative admission (no `worker_context` request is issued),
- issue or renew any credential (`callbackToken` stays `undefined`; the token is never journaled),
- acquire or renew ownership (no bind/lifecycle call is made; the probe shows ownership unchanged),
- start or restart execution.

It restores knowledge of an old attempt so the host can try to deliver its already-known result. That
is **journal-based tracking-state reconstruction**, not new admission, and it coexists with the
prohibition on automatic privileged re-admission. No new execution authority was observed.

### 4.2 A mutating replay needs its journaled native binding, or nothing is emitted

For a mutating attempt, `emitWorkerCompletion` refuses to emit when `admission.agentId === undefined`
(`BRAIN_WORKER_AGENT_ID_MISMATCH`). The reconstructed admission has no `agentId` from the admission
entry, and recovery restores the native binding from **either** of two later journal entries —
`second-brain.worker-job-pending` (dispatch observation) **or** `second-brain.worker-lifecycle-accepted`
(which merges `nativeAttemptId`/`nativeJobId`/`agentId`/`hostGeneration` when the entry carries
`executorSettled` and `cleanupComplete`). A journal containing the admission but **neither** of those
produces no emission at all for a mutating attempt — fail-closed in the host, but silently, recorded
only as a sensor error. It is a behavioural fact about the recovery path, not a defect, and it is why
the primary replay case asserts the emission rather than zero emissions; the executed fixtures use the
job-pending route, and the lifecycle-accepted route is source-read, not exercised by these cases.

### 4.3 Open finding carried under #4 (source authenticity) — evidence level raised

A journal can also carry `access_intent: read_only`. Because admission mints read-only attempts no
authority, `_require_terminal_authority` has nothing to compare, so a read-only attempt's terminal
evidence is a *named, weaker class* decided by journal fields alone: the last case above drives the
real hook, the real bridge and the real consumer to `COMPLETED` + 1 attempt result **with no
credential of any kind**. Evidence level is now **integrated reproduction** (extension hook + real
Python consumer + durable-state readback), not source analysis.

Scope, stated precisely: no writer lease is released (there was none), so this is an evidence-integrity
defect, not a writer-authority bypass. The forbidden downgrade *does* hold: a journal label cannot
decide whether an authoritatively mutating attempt needs authentication, because the Brain's guard
reads the stored digest and writer-ownership state from its own row, not the label. That is the
narrow #3 verdict condition the owner set, and it is now proven by construction (case 2 + mutation 1).
The forged read-only completion remains **OPEN as an M00 blocker under #4**.

### 4.4 Test-design pitfall worth recording

The attempt's `host_session_id` must equal the OMP session under which the completion is delivered,
and the extension's Brain home must be the fixture's Brain home. The first draft failed on both: the
fixture admitted with `session-<task_id>` and the extension resolved its own home to the temp root, so
the consumer refused with `BINDING_MISMATCH` for a reason unrelated to authority. The current test
binds them explicitly (`--host-session omp-session`, `SECOND_BRAIN_HOME` = fixture home) and the
credential-present control is what proves the binding is now correct.

## 5. Mutation sensitivity against the integrated bytes

`run-mutations.py` removes one load-bearing element, runs the replay file, restores the exact original
bytes (verified by sha256) and now retains the failing assertions. Evidence: `mutation-evidence.json`.

| Mutation | Mutated sha256 | Replay file result | Failing assertions | Restored |
| --- | --- | --- | --- | --- |
| `_require_terminal_authority` no longer refuses a digest mismatch (`worker_protocol.py`) | `d502e680…559ddd` | **5 failed / 3 passed** | `expected true to be false` — the five cases that assert a refusal (including both mutating replay cases and the label-downgrade case) fail; the three absence/reachability controls and the read-only finding case pass, the latter because it never needed authority | exact bytes restored |
| journal admission reconstruction no longer populates the tracking maps (`index.ts`) | `6a6d51c1…8661bf` | **7 failed / 1 passed** | `expected [] to have a length of 1 but got +0` — no emission occurs at all; only "no persisted admission emits nothing" survives, because it asserts absence | exact bytes restored |

Baseline hashes for the restored files, recomputed on the current tree after the mutation runs
(`sha256sum`): `src/second_brain/worker_protocol.py` = `17997bcc…f3e4fac2`,
`brainstem/prime-extension/src/index.ts` = `f2c95300…12749e6e` — both equal to the recorded baselines.

Scope of the mutation claim: it establishes sensitivity of *these* cases to *these* two elements. It is
not a claim that the guard is the only protection on the path, nor that unrelated mutations would be
caught.

## 6. Executed evidence

| Artifact | Command | Result |
| --- | --- | --- |
| `vitest-full-transcript.txt` | `npx vitest run --config vitest.candidate.config.ts` (candidate-local cache config) | **771 passed / 771**, 35 files — 763 pre-existing + 8 new |
| `pytest-writer-admission.txt` | `.venv\Scripts\python.exe -m pytest tests/test_writer_admission.py -v` | **37 passed** |
| `pytest-completion-authority-cases.txt` | same file, `-k` the five completion-authority cases | **5 passed** |
| `mutation-evidence.json` | `run-mutations.py` | see §5 |
| `tsc --noEmit` / `npx eslint tests/worker-result-replay.test.ts src/worker-result-bridge.ts` | candidate toolchain | clean (exit 0) |
| identity for every case | asserted inside `setup()`: the fixture's `sys.executable` equals the candidate venv interpreter derived from the test's own location, and `second_brain.__file__` equals `<candidate>/src/second_brain/__init__.py`; both are printed per case and preserved in the transcript | `[replay] interpreter=…\.worktrees\m00.3-producer-guard\.venv\Scripts\python.exe second_brain=…\.worktrees\m00.3-producer-guard\src\second_brain\__init__.py` |

Added by this work:

- `brainstem/prime-extension/tests/worker-result-replay.test.ts` (new; 8 cases).
- `brainstem/prime-extension/src/worker-result-bridge.ts` — the wire-payload construction extracted into
  an exported `ompWorkerResultPayload(options)` so the test can send the bridge's own bytes to the
  consumer directly; no behaviour change (the bridge calls the same function).
- `tests/fixtures/omp_replay_state.py` (new; disposable Brain state + probe CLI).
- `tests/test_writer_admission.py` — the no-token refusal case now also asserts the attempt still
  holds writer ownership after the refusal (refusal must not release the lease).

## 7. Independent audit of this report (read-only, `evidence-auditor` agent)

An independent read-only audit of these artifacts returned PASS for the hook path, the real
bridge/consumer route, the durable-state observations (including direct `writer_ownership` observation
rather than inheritance from the Python test), the label-downgrade protection, the source-factory
scope, the vacuity control, the recorded mutation results and the open-finding disposition.

It also returned six items that were not yet demonstrated, and all six were repaired rather than
argued with:

| Audit item | Repair |
| --- | --- |
| Report said only a `worker-job-pending` entry supplies the binding | §4.2 now names the lifecycle-accepted route too and marks which route the fixtures exercise |
| Report said "every mutating replay case" fails the guard-removal mutation | §5 now states the exact counts and distinctions (the reachability control asserts emissions, not a refusal) |
| "No additional effects" exceeded the probe's coverage | new case: an **already accepted** mutating completion replayed unauthenticated, with the probe extended to the result hash, digest hash, lease, logical outcome, settled/cleanup flags, native binding and lifecycle sequence — compared in full before/after |
| Failure classification had blind spots | the refusal is now corroborated by sending the bridge's own payload bytes to the consumer directly (`UNAUTHORIZED_CALLBACK`), transport unavailability is excluded, the `extension_error` is correlated with the observed outcome, and a false `worker_completed` mirror is asserted absent |
| Interpreter/source identity assertion was weak | `setup()` now asserts the fixture's interpreter equals the candidate interpreter derived from the test's own location and that `second_brain.__file__` is exactly the candidate source file; both are printed per case so the transcript preserves them |
| Baseline hashes could not be recomputed by the auditor (no execution tool) | recomputed here with `sha256sum` on the current tree; both match the recorded baselines (see §5). The mutation runner now also retains the failing assertions instead of only their names |

The audit's residual notes are accepted and not glossed: the retained transcript still shows the
temp-tree cleanup fallback and one fail-open telemetry warning (both recorded in §8), and the identity
established is the *fixture's* interpreter/source, which is the same interpreter and source the bridge
subprocess uses (the bridge resolves `SECOND_BRAIN_PYTHON` first, which the test pins to that path).

## 8. Supplementary adjudication (Jev, `jev-latest` via `mcp__jev_gate` / `mcp__jev_verify`)

`jev_gate` over the patch, claims and evidence: **no contradicted claim**; 8 verified, 1 unsupported,
5 needing review, action `escalate` (composite 0.78, `safe_to_apply` 0.35 — the escalation is driven by
the review scores' low confidence, not by a contradiction).

Two items were investigated rather than accepted:

| Jev item | Resolution |
| --- | --- |
| "The replay test drives the registered `before_agent_start` hook" → unsupported (0.28) | Re-verified with the actual source excerpts (factory registration `src/index.ts:2987`, the recovery call site, the test's `pi.on` registration and the single invocation helper): **verified, support 0.96, confidence 0.94, auto** |
| "The downgrade refusal is not a binding artifact" → unsupported in the first batch | The first batch's evidence simply contained nothing about that claim. Re-verified with the downgrade case source, the credential-present control, the fixture's bind code and the guard-removal mutation result: **verified, support 0.91, confidence 0.86, auto** |

Jev findings direct investigation; they neither authorize mutation nor substitute for the outstanding
independent review. Both resolutions are against source and executed output, not against confidence.

## 9. Limitations and remaining work

- **Independent *review of the change* is not yet obtained.** A read-only independent *audit* of these
  artifacts was run and its findings are repaired (§7), but that is an evidence audit, not an
  acceptance review of producer + consumer + custody + replay. Spawning a mutating reviewer is refused
  in this session by the loaded extension itself (`BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`:
  this host advertises no settlement capability, so mutating worker dispatch is blocked). The review
  gate is therefore still open, and Jev adjudication plus the audit are the available substitutes —
  neither grants acceptance.
- The mutating replay uses the job-pending journal route (§4.2); the lifecycle-accepted route that also
  restores the binding is source-read, not exercised here.
- The extension side of the replay is exercised as source through the factory; the packaged `dist`
  entrypoint and a real OMP host launch remain unqualified for this subject.
- Probe scope: the deep probe compares the worker row and its attempt-result hash, not every table;
  it does not assert lease *timing* or unrelated telemetry contents.
- The retained transcript is not warning-free: the temp-tree cleanup falls back with a warning when a
  spawned bridge still holds the tree as its cwd (Windows lock), and one fail-open telemetry warning
  (`telemetry write failed: ENOENT`) appears in the read-only case. Neither affects the asserted
  behaviour, and neither is presented as a successful cleanup.
- Resource note: free RAM was 2,523 MiB before this work and disk free 131 GiB; two short test
  processes were run concurrently once (vitest + pytest) instead of strictly one instrumented tree at
  a time. Both passed; the deviation is recorded rather than hidden.
