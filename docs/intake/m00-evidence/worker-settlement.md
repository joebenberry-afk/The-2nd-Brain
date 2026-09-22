# M00.3 #5 settlement and truthful worker recording — first executed case

**Subject:** candidate worktree `.worktrees/m00.3-producer-guard`.
**Production activation: NOT PERFORMED.** Disposable home + disposable git worktree under the OS temp
dir; production leases untouched.

## 1. The mandate's headline case, executed

> *"Run ten sequential local mutating workers against the same disposable worktree/database. Each must
> bind, execute, settle, clean up, release, and permit its successor without manual unlock, changing
> worktrees, restart between normal runs, or waiting for expiry."*

Executed with `tests/fixtures/omp_replay_state.py sequence --count 10`; evidence
`ten-worker-sequence.json`. All ten iterations, in order, on one home and one registered worktree:

| # | completion | lifecycle | state | writer_ownership | attempt results |
| --- | --- | --- | --- | --- | --- |
| 1–10 | `completed` | `accepted` | `COMPLETED` | `released` | 1 each |

Each iteration is the real route, not a direct call: `worker_context` admission → `worker_bind` with
the attempt's credential → `worker_result` completion with that credential → `worker_lifecycle`
(`executor_settled=True`, `cleanup_complete=True`) → ownership `released`. The next iteration's
**admission** is what proves release took effect, because a mutating admission is refused while
another attempt holds the worktree (`WORKTREE_WRITER_BUSY`); the loop never touches a lease, never
waits for expiry, never unlocks by hand, never changes worktree and never restarts a process.

## 2. What this does and does not establish

Establishes: the release path used by a normal completion
(`worker_protocol.ingest_worker_lifecycle`: `executor_settled and cleanup_complete` → `released`)
leaves the worktree free for the successor, ten times in a row, with exactly one attempt result per
attempt and the credential enforced on every mutation.

Does **not** yet establish (§7 of the mandate): the single guarded finalization path, and the
separate cases — immediate completion, outcome-before-cleanup, active descendants after a top-level
result, cancellation before and after acceptance, delayed callbacks, duplicate receipts, process/job-ID
reuse, late dispatch after revocation, restart, newer-owner protection, and prevention of further
writes under the old attempt. Those are the remaining #5 acceptance conditions, listed here rather
than implied by the green run above.

Two structural notes from reading the code (not yet changed):

- `settle_task` (`worker_protocol.py:1973`) already requires approval, postcondition evidence, a
  matching approved review and a durably bound result, and accepts only `COMPLETED`. It is a
  *different* transition from the lifecycle release exercised above: the run above settles by
  lifecycle receipt, which is why the mandate's "one guarded finalization path" is still open.
- `reap` (`:2041`) quarantines expired writer authority and keeps legacy read-only reaping; it never
  releases a writer. Nothing in the executed sequence depended on it, which is the intended shape.

## 3. Ownership and receipt edges, executed

`tests/fixtures/omp_replay_state.py edges`; evidence `ownership-edges.json`. One attempt completes,
then reports settlement without cleanup; the sequence then exercises what a settlement path must not
get wrong:

| Observation | Result | What it establishes |
| --- | --- | --- |
| completion with the attempt's credential | `completed` | the normal acceptance path |
| lifecycle receipt `executor_settled=True, cleanup_complete=False` | accepted, ownership **`quarantined`** | an unsettled executor does not release the writer |
| successor admission while quarantined | **`WORKTREE_WRITER_BUSY`** | quarantine still excludes the next writer |
| lifecycle receipt with `cleanup_complete=True` (sequence 1) | accepted, ownership **`released`** | release needs *both* authenticated facts, not expiry |
| successor admission after release | prepared (`edge-b`) | the release is what permits the successor |
| the same receipt replayed | accepted, no state change (identical lease stamp) | delivery/retry duplicate is inert |
| an earlier sequence replayed with different content | **`RECEIPT_CONFLICT`** | a sequence cannot be restated |
| the released attempt's completion replayed **without** its credential | **`UNAUTHORIZED_CALLBACK`** | release does not make the attempt writable without authority |
| the same completion replayed **with** its credential | accepted, no second effect | terminal evidence is immutable; the retry is idempotent |
| first attempt after all replays | `COMPLETED`, `released`, 1 attempt result | nothing above added an effect |
| successor after all replays | `WORKING`, `held`, 0 results | the successor was unaffected |
| cancellation **before** acceptance (`edge-b`, no accepted outcome) | accepted → `CANCELED`, `released`, 0 attempt results | cancellation settles and releases without inventing a completion |
| completion for the cancelled attempt, **with its credential** | **`INVALID_TRANSITION`** | a cancelled attempt cannot be turned back into a completion; the state is unchanged |
| cancellation **after** acceptance (`edge-a`, already `COMPLETED`) | **`OUTCOME_CONFLICT`** | an accepted outcome is immutable; a later cancellation is refused as a rewrite rather than recorded by overwriting |
| accepted attempt after the late cancellation | `COMPLETED`, `released`, 1 attempt result | accepted outcome preserved |

Still not exercised (and therefore still open in #5): active descendants after a top-level result,
delayed callbacks beyond the receipt replay above, process/job-ID reuse, late dispatch after
revocation, restart during settlement, newer-owner protection with two live attempts, and the
consolidation of `settle_task` with the lifecycle release into one guarded finalization path.

## 4. Finalization vs release: two records, and what makes them consistent

The mandate asks for "one guarded finalization path" and for durable finalization and ownership
release to be consistent. Observed on the executed bytes after a fully evidenced normal completion
and cleanup (`ownership-edges.json` deep probe):

```
state=COMPLETED  writer_ownership=released  logical_outcome=completed
executor_settled=1  cleanup_complete=1  lifecycle_sequence=1  settled_at=NULL
```

`settled_at` has exactly **one writer** in the codebase, `worker_protocol.settle_task`
(`:2021-2023`), and that path demands `approved is True`, postcondition evidence, a matching
approved-review record and a durably bound result. Every other site only reads it or nulls it at
(re)registration. The two records therefore mean different things:

| Record | Authorises | Guard |
| --- | --- | --- |
| `writer_ownership='released'` | another writer taking the worktree | authenticated terminal outcome + `executor_settled` + `cleanup_complete`, attempt-scoped credential, exact native binding (all exercised above) |
| `settled_at` | approval-dependent claims ("reviewed and settled") | approval flag, postcondition evidence, matching approved review, durably bound result |

Making the release stamp `settled_at` would manufacture the approval `settle_task` exists to require,
which the mandate forbids. The consistency rule that holds on these bytes is: **release never writes
`settled_at`, `settled_at` never releases, neither reads the other's evidence**, and each is
idempotent on its own (duplicate receipt inert; `settle_task` returns `duplicate=True` when the stamp
already matches). This resolves the "one guarded finalization path" item by naming the two paths and
their guards rather than by merging them into one write that would have to weaken one of the guards.

## 5. Reproduce

```
<candidate python> tests/fixtures/omp_replay_state.py sequence --base <fresh temp dir> --task-id ten --count 10
```

Expected: one JSON envelope with `ok: true` and ten iterations, each `state: COMPLETED`,
`writer_ownership: released`, `attempt_results: 1`, no `completion_failure`.
