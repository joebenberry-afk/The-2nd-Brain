# Worker Plane Concurrency Guard

Phase R7. Confirms Prime exposes no spawn hook (R1), confirms the plan's
own "SQLite bookkeeping check alone is insufficient" concern was correct —
`WorkerPlaneManager` had zero real callers anywhere — and makes it a real,
invokable enforcement surface instead of dead code.

## 1. Prime exposes no spawn hook (re-confirmed, unchanged from R1)

`PrimeEvent` (`prime.d.ts:167-181`) — the complete union of the 11
subscribed lifecycle events — has no spawn/subagent/child event. Re-checked
this pass; nothing has changed. Per the plan's own instruction ("If Prime
exposes no hook to intercept spawn, document actual enforcement location
used"), enforcement cannot live at a Prime extension hook and must live
in Brain-owned code that something actually calls before spawning a
worker.

## 2. The "SQLite bookkeeping alone is insufficient" problem was real — and worse than expected

`WorkerPlaneManager.spawn_worker()`/`complete_worker()`/
`active_worker_count()` (`src/second_brain/repository_intelligence.py`)
already implement the concurrency ceiling correctly — confirmed by the
pre-existing test
`tests/test_repository_intelligence_live.py::test_worker_concurrency_ceiling_enforcement`,
which already exercises exactly the plan's required scenario (2 allowed,
3rd blocked) at the Python API level.

But `grep -rn "WorkerPlaneManager\|spawn_worker" src brainstem` (excluding
`repository_intelligence.py` itself and its own test) returned **zero**
matches. No CLI subcommand, no Prime wiring, no other adapter — nothing in
the entire codebase ever called it. The class was reachable only by
importing it directly in Python.

## 3. What this pass adds: `second_brain worker-plane spawn|complete|status`

New CLI subcommand group (`src/second_brain/cli.py`: `cmd_worker_plane`),
same pattern as R5's `action-cache search` and R3's `vmem` bridge — a
Brain-owned layer any caller can invoke instead of spawning a worker
directly, backed by the existing, unmodified `WorkerPlaneManager`:

- `worker-plane spawn <session_id> <subtask> [--max-workers N] [--json]` —
  spawns if under the ceiling; on overflow, exits 2 with
  `{"spawned": false, "error": "..."}` (JSON mode) rather than a stack
  trace, so a caller can branch on the block.
- `worker-plane complete <session_id> <worker_id> --status ... --summary
  ...` — records completion, freeing a ceiling slot.
- `worker-plane status <session_id> [--max-workers N]` — active count vs.
  ceiling.

## 4. Verified against the plan's exact required scenario

Manually reproduced end to end (`--max-workers 2`), then encoded as a
permanent test:

```
spawn task1 -> spawned=true                    (1/2)
spawn task2 -> spawned=true                    (2/2)
spawn task3 -> spawned=false, exit 2           ("ceiling reached (2/2)")
status      -> active_workers=2
complete task1's worker
status      -> active_workers=1
spawn task4 -> spawned=true                    (new spawn allowed again)
```

One real bug found by running this, not by reading the code: `cmd_worker_
plane` unconditionally read `args.max_workers` at the top, but the
`complete` subparser never defines that flag (`AttributeError`). Fixed
with `getattr(args, "max_workers", None)`.

## 5. Verification

```
.venv\Scripts\python -m ruff check src/second_brain/cli.py tests/test_cli.py
  → All checks passed
.venv\Scripts\python -m pyright src/second_brain/cli.py tests/test_cli.py
  → 0 errors, 0 warnings, 0 informations
.venv\Scripts\python -m pytest tests/test_cli.py -v
  → 13 passed
```

New test: `test_worker_plane_ceiling_block_complete_respawn` — the full
scenario above, via real subprocess CLI calls (`run_cli`), not direct
Python API calls.

## 6. What remains open

This is Brain-owned and harness-agnostic — it works today for any caller
willing to invoke it. It does **not** mean Prime's own subagent/RLM spawn
path actually calls it: per R1, the Sol minimal-orchestrator contract
(`SOL_ORCHESTRATOR_CONTRACT` in `index.ts`) states the concurrency policy
("default 1 active worker; at most 2 when genuinely independent; NEVER
3+") only in **prompt text**, and RLM delegation runs through the
`ipython` tool call, which `tool_call`'s `{block, reason}`-only result
shape (confirmed R1/R5) could in principle gate — but nothing in this
codebase can currently tell a legitimate `ipython` call apart from one
that is specifically spawning a worker, so building that heuristic here
would be guessing at a signal that doesn't exist yet. A live pilot
observing what a real RLM-delegating `ipython` tool_call's `event.input`
actually looks like is required before that gate could be built honestly.
