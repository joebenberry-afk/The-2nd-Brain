# T4.2 — OMP result validation + one session-id scheme — Report

## Summary

Implemented all four brief requirements on top of the completed T4.1 lifecycle
contract (commit 91b4430), in the existing v2-one-shot worktree.

1. **Unified session-id scheme.** Deleted the `"is-" + sha256(...).hexdigest()[:12]`
   identity construction at all 6 host-adapter call sites in `src/second_brain/cli.py`
   (codex-hooks Stop/SessionEnd branch, codex-hooks main branch, antigravity hook,
   claude-code hook, brainctl `writeback`, prime-cli `shadow`). Every site now
   builds `internal_session_id` via `ledger.internal_session_id(host_session_id)` —
   the full SHA-256 hex digest, the same scheme `ledger.py` already used internally.
   `host=` values at all 6 sites are unchanged (`"codex-hooks"`, `"antigravity"`,
   `"claude-code"`, `"brainctl"`, `"prime-cli"`).
   - Removed the now-unnecessary `dataclasses.replace(session, internal_session_id=internal)`
     workaround in the claude-code `PreCompact` block (the two schemes were the
     same value once cli.py's own construction was fixed, so `store.create_session(session)`
     is used directly) and its stale explanatory comment.
   - Fixed a latent `UnboundLocalError` this surfaced: `_cmd_claude_code_hook` had
     a redundant local `from . import ledger` inside its `PreCompact` branch that,
     combined with the new top-level `ledger` import, shadowed `ledger` for the
     *entire* function (Python's whole-function local-name rule) and broke the
     earlier `ledger.internal_session_id(session_id)` call. Removed the redundant
     local import.
   - Restored a fail-open guard that was implicit in the deleted `session_hash`
     line: `ledger.internal_session_id(session_id)` (a `.encode("utf-8")` call)
     can raise `UnicodeEncodeError` on malformed surrogate `session_id` input;
     it is now computed inside the hook's existing top `try/except` so malformed
     input still fails open (`"{}"`, exit 0) instead of crashing the hook.

2. **`ledger.py` host-required behavior.** `LedgerStore.__init__` gained an
   optional keyword-only `host: str | None = None`. `_write_manifest` no longer
   hardcodes `"host": "prime"`: if `self._host` is set it is used; otherwise, if
   the ledger directory already has a manifest (re-open/append on an
   already-initialized ledger), its recorded host is preserved; only when the
   ledger is genuinely brand-new **and** no host is supplied does it raise
   `BrainError("ledger session <host_session_id> requires an explicit host for
   first-time initialization")`. `_ensure_session_row` mirrors this: with an
   explicit host it inserts the row with that host; without one it no-ops if a
   session row already exists (the common case, since a prior explicit
   `create_session` call already wrote the row), and raises the same
   deterministic `BrainError` only if no row exists and no host was given.
   Every `LedgerStore(...)` construction across `src/second_brain` and `tests`
   that reaches `.open(create=True)` was migrated to pass `host=` (or to rely on
   the manifest-preserving re-open path, verified case by case) — grepped
   exhaustively; see "Call-site migration" below.

3. **OMP T4.1 lifecycle wiring.** `omp_adapter._prepare_worker_context` now
   calls `worker_protocol.register_task(...)` and (unless the registration is a
   duplicate already in a terminal state) `worker_protocol.record_worker_event(...,
   "worker_started", ...)` after `prepare_context_handoff` succeeds, mirroring
   `hermes_adapter.request_worker_task`'s pattern exactly, including the
   duplicate-terminal short-circuit response shape.

4. **Result validation.** Added `worker_protocol.dispatch_snapshot(home, task_id)`
   (read-only `dispatch_payload` recovery), `omp_adapter.to_result_packet(payload)`
   (thin `WorkerResultPacket.from_dict` seam), and a new `"worker_result"`
   operation in `omp_adapter.handle_request` dispatching to
   `_prepare_worker_result`, which: rejects missing/blank `task_id`/`packet_sha256`
   before touching the lifecycle DB (`MALFORMED_RESULT`); on a
   `contracts.WorkerPacketError` from `to_result_packet`, synthesizes a failed
   `WorkerResultPacket` (role from `dispatch_snapshot`'s `requested_role` when
   available, else `"worker"`) and records a `"failed"` lifecycle event, never
   raising even if that event recording itself errors; on a valid packet,
   cross-checks `worker_identity.role_profile` against the dispatch snapshot's
   `requested_role` (mismatch → `UNAUTHORIZED_WORKER` through the same
   malformed-failure path; no snapshot → proceeds, correlation unprovable) and
   then calls `record_worker_event` with the full canonical result payload,
   returning its terminal status/failure_code/hashes; a `WorkerPacketError`
   from that final call is caught and returned as a failure response, never
   raised to the CLI boundary.

## Review round 1 fixes (adversarial review, commit amended in place)

`ReviewT42`'s round-1 adversarial review of the initial commit found two
genuine, patch-introduced bugs; both are fixed in this (amended) commit.

**Finding 1 (P0) — every real OMP worker result was rejected as
`MALFORMED_RESULT`.** `worker-result-bridge.ts` always sent flat
`worker_agent`/`worker_model`/`worker_role` fields (never a nested
`worker_identity`), but `_prepare_worker_result` called
`to_result_packet(payload)` directly on the raw wire payload, and
`WorkerResultPacket.from_dict` requires a nested `worker_identity` — so every
real bridge call raised `KeyError` internally, converted to
`WorkerPacketError("MALFORMED_RESULT")`, which then drove the T4.1 lifecycle
row to the terminal `FAILED` state (immutable — no retry could ever land
`COMPLETED`). The original `test_omp_result_validated_as_packet` did not catch
this because it hand-built a nested `worker_identity` dict, a shape production
never sends.

Fixed by adding `omp_adapter._worker_result_identity(home, task_id,
session_id, payload)`, which assembles the `worker_identity` dict server-side
from the bridge's flat fields — mirroring how `_prepare_worker_context`
assembles `driver_identity` from `worker-context-bridge.ts`'s flat fields:
`agent_id` from `worker_agent`, `model` from `worker_model`,
`internal_session_id` from `ledger.internal_session_id(session_id)`,
`host_agent_id="omp"`, `provider="omp"`. `role_profile` comes from
`worker_role` when it is a valid `WORKER_ROLES` member; the real bridge never
actually populates `worker_role` (`index.ts`'s `recordWorkerChildResults`
never sets `workerRole` on its `runOmpWorkerResult` call), so in production
this always falls back to the task's registered `requested_role` via
`worker_protocol.dispatch_snapshot` (the same pattern
`_synthesize_failed_result` already used). `_prepare_worker_result` now calls
`to_result_packet({**payload, "worker_identity": _worker_result_identity(...)})`
before validation, so the assembled identity is what gets checked against
`WORKER_ROLES` and the role-mismatch guard.

`tests/test_omp_adapter.py::_worker_result_payload` was rewritten to build the
exact flat wire shape (`worker_agent`/`worker_model`/`worker_role`, no nested
`worker_identity`) instead of a hand-crafted nested dict. A new dedicated test,
`test_omp_worker_result_bridge_flat_shape_round_trips_and_preserves_host`,
constructs the payload literally matching `runOmpWorkerResult`'s wire shape
(including `worker_role: ""`, the actual production value) and proves it
round-trips to `COMPLETED` — the exact contract Finding 1 said was
unreachable. `test_omp_result_validated_as_packet`'s malformed-input case was
changed from "omit `worker_identity`" (no longer a distinguishing input, since
identity is always server-assembled now) to an invalid `status` value, which
is still genuinely rejected by `WorkerResultPacket.validate()`.
`test_omp_worker_result_rejects_role_mismatch` now sends a flat
`worker_role="dev"` (mismatched against the task's registered `"worker"`
role) instead of a nested identity dict.

**Finding 2 (P1) — the terminal worker-result event silently clobbered the
ledger manifest's `host="omp"`.** `_prepare_worker_context`'s
`record_worker_event(..., "worker_started", ...)` call, and every
`record_worker_event` call inside `_fail_worker_result`/`_prepare_worker_result`,
omitted `host=`, falling back to `worker_protocol._DEFAULT_HOST =
"worker-protocol"`. `worker_started` never triggers `_emit_worker_event`
(`WORKING` isn't terminal), so this was latent there, but the terminal
`completed`/`failed`/`cancelled` event from `_prepare_worker_result` does
trigger it — `LedgerStore.open(create=True)` unconditionally re-runs
`_write_manifest` on every open, and since `self._host` was
`"worker-protocol"` (not `None`), the "preserve existing host when host is
`None`" branch was skipped, silently rewriting the manifest's already-correct
`host: "omp"` to `host: "worker-protocol"` on every completion/failure.

Fixed by threading `host="omp"` through all three call sites (matching
`hermes_adapter.py`'s exhaustive `host=binding.session.host` threading):
`_prepare_worker_context`'s `record_worker_event("worker_started", ...)`,
`_fail_worker_result`'s `record_worker_event("failed", ...)`, and
`_prepare_worker_result`'s terminal `record_worker_event(result.status, ...)`.

`test_omp_worker_result_bridge_flat_shape_round_trips_and_preserves_host`
(same new test as above) also directly reproduces Finding 2's repro: it reads
the ledger manifest via `ledger._load_manifest(ledger.session_dir(...))`
immediately after `worker_context` preparation (asserts `host == "omp"`) and
again after the terminal `worker_result` call (asserts `host` is still
`"omp"`, not `"worker-protocol"`).

## Prime extension (brainstem/prime-extension)

Added `src/worker-result-bridge.ts`, modeled directly on
`worker-context-bridge.ts` (same `execFile` spawn of
`python -m second_brain autoinject omp-routing`, same `PYTHONHOME`/`PYTHONPATH`
deletion + `SECOND_BRAIN_HOME` env, same bounded-string helpers, same JSON
stdin/stdout contract, same fail-open shape). It exports `runOmpWorkerResult`
sending a flat `{operation: "worker_result", ...}` payload; all
`AgentIdentity`/`internal_session_id` assembly happens Python-side inside
`omp_adapter._prepare_worker_result`, not in TypeScript, keeping identity
rules in one place.

`index.ts`: added an injectable `ompWorkerResultRunner` option (default
`runOmpWorkerResult`), made `recordWorkerChildResults` `async`, wrapped the new
bridge call in `try/catch` (local telemetry/mirror calls are unchanged and
still fire regardless of the bridge outcome), and updated its one call site
inside the `tool_result` handler to `await recordWorkerChildResults(event, ctx, session)`.
`summary` is derived cheaply from the first `event.content` block's `.text`
field when present (no new expensive extraction), bounded to 2048 chars.

`npm run typecheck` (the project's own configured script) passes for every
line touched by this change; the one remaining `tsc --noEmit` error
(`src/index.ts` — a pre-existing `"role" | "active" | ... ` literal-type
mismatch) is present identically on the pre-T4.2 commit (verified via
`git stash`) and is out of scope for T4.2.

## Call-site migration (LedgerStore host=)

Grepped every `LedgerStore(` construction in `src/second_brain` and `tests`
and classified each:

- **Read-only `.dbfile` access / `.open()` without `create=True`** (re-open of
  an already-initialized ledger): unaffected, no `host=` needed. Left as-is.
- **`.open(create=True)` with a real host known at the call site**: passed
  `host=` explicitly — `cli.py`'s verify/env/stop utility commands
  (`host="prime"`, matching their existing explicit `BrainSessionIdentity.host`),
  `cli.py`'s `ledger init` CLI (`host=args.host`), `cli.py`'s claude-code
  `PreCompact` block (`host="claude-code"`), `hermes_adapter.py`'s
  `_append_event`/`_register_binding` and its `prepare_context_handoff`/
  `record_worker_event` calls (`host=binding.session.host`),
  `simplification.py`'s `_record_ledger_event` (`host="prime"`, a host-agnostic
  CLI utility command matching cli.py's own convention).
- **`worker_protocol.py`** (explicitly harness-neutral by its own module
  docstring): `prepare_context_handoff`/`_store_context_snapshot` and
  `record_worker_event`/`_emit_worker_event` gained an optional `host: str |
  None = None` parameter threaded through to `ledger.LedgerStore(...)`.
  `omp_adapter._prepare_worker_context` passes `host="omp"` explicitly (the
  real, known host). Callers that are genuinely host-agnostic at this generic
  layer (the T4.1 lease reaper's redelivery/expiry paths, and direct
  protocol-level tests) fall back to a bounded module constant
  `_DEFAULT_HOST = "worker-protocol"` — a deliberate, explicit, documented
  literal, never a silent guess, and never `"prime"`.
- **Test files** (`test_ledger.py`, `test_governor.py`, `test_origin_authority.py`,
  `test_worker_lifecycle.py`, `test_worker_protocol.py`): every
  `.open(create=True)` construction updated to pass `host=` (`"test"`,
  `"hermes"`, or `"prime"`, matching what each test is exercising) so no test
  silently relied on the deleted `'prime'` fallback. `test_worker_protocol.py`'s
  3 direct `prepare_context_handoff` calls pass `host="test"`.
  `test_hermes_adapter.py`, `test_orchestration.py`, `test_claude_code_adapter.py`,
  `test_omp_adapter.py` needed no `host=` additions (only read-only `.dbfile`
  accesses, or flows already covered by an upstream `host=`-carrying
  construction / the manifest-preserving re-open path).

## Historical-ID migration note

Old-scheme rows are untouched: `ledger.py`'s `UPGRADERS`/replay path never
rewrites, and this change touches only *construction* call sites (what
`internal_session_id` value a *new* `BrainSessionIdentity` gets), never
existing ledger rows or manifests. Any session directory already created
under the old `"is-"+sha256[:12]` scheme keeps its existing
`state/sessions/<old-id>/` path and its existing `sessions.internal_session_id`
value; it is simply never looked up again by that old id from a fresh hook
invocation (the hook now always derives the full-hash id). No migration
script was written or requested by the brief for these AutoInject-identity
rows (they are a separate, host-adapter-local identity from the P2 ledger's
own canonical `internal_session_id()`, which was never wrong).

## Unavailable real-host qualification

No live Prime/OMP host process was available to exercise the TypeScript
`worker-result-bridge.ts` end-to-end against a running `omp` extension host.
Verified instead at the unit level: `npm run typecheck` for structural/type
correctness of the whole call chain (`index.ts` → `worker-result-bridge.ts`),
and exhaustive Python-side tests for the `omp_adapter`/`worker_protocol`
surface the bridge calls into (`_prepare_worker_result`, `dispatch_snapshot`,
role-mismatch rejection, malformed-payload handling) via
`omp_adapter.handle_request(home, {"operation": "worker_result", ...})`,
which is the exact wire contract the bridge's `execFile` spawn produces on
stdin.

## Tests added

- `tests/test_ledger.py::test_single_session_id_scheme` — in-process, spies on
  `contracts.BrainSessionIdentity` construction (monkeypatched at the module
  attribute so every host adapter's live reference sees it) while driving all
  6 cli.py hook/CLI call sites (`_cmd_codex_shadow` twice — Stop/SessionEnd and
  main branches — `_cmd_antigravity_hook`, `_cmd_claude_code_hook`,
  `_cmd_writeback`, `cmd_autoinject` shadow branch) and asserts every captured
  identity's `internal_session_id == ledger.internal_session_id(host_session_id)`,
  is not `"is-"`-prefixed, and is a full 64-hex-char digest.
- `tests/test_ledger.py::test_ledger_store_requires_explicit_host_on_first_init`
  — proves `LedgerStore(...).open(create=True)` on a genuinely brand-new
  directory with no host raises the deterministic `BrainError` (never writes
  `host='prime'`), that an explicit `host=` succeeds and is recorded in the
  manifest, and that re-opening the now-initialized ledger without a host
  preserves the already-recorded host instead of raising.
- `tests/test_omp_adapter.py::test_omp_result_validated_as_packet` — malformed
  result payload (invalid `status` value) against a task registered via
  `worker_context` first → `{"status": "failed", "failure_code": ...}` and the
  T4.1 lifecycle DB (`worker_tasks.state`) actually transitions to `FAILED`;
  valid result payload, using the actual flat bridge wire shape (no nested
  `worker_identity`) → lifecycle transitions to `COMPLETED` and
  `record_worker_event`'s response (`status`, `failure_code`, `task_id`,
  `packet_sha256`, `result_sha256`) is returned.
- `tests/test_omp_adapter.py::test_omp_worker_result_bridge_flat_shape_round_trips_and_preserves_host`
  (added in review round 1) — builds the payload literally matching
  `worker-result-bridge.ts`'s `runOmpWorkerResult` wire shape (flat
  `worker_agent`/`worker_model`/`worker_role: ""`, no nested `worker_identity`)
  and proves it round-trips to `COMPLETED`; also reads the ledger manifest via
  `ledger._load_manifest` right after `worker_context` preparation and again
  after the terminal `worker_result` call, asserting `host` stays `"omp"`
  both times.
- `tests/test_omp_adapter.py::test_omp_worker_result_rejects_role_mismatch` —
  a result whose flat `worker_role` doesn't match the task's registered
  `requested_role` is rejected with `UNAUTHORIZED_WORKER` and the lifecycle
  transitions to `FAILED`.
- `tests/test_omp_adapter.py::test_omp_dispatch_snapshot_round_trips_requested_role`
  — `dispatch_snapshot` returns `None` before registration and the correct
  `requested_role`/`task_id` after a `worker_context` operation registers the
  task.

Existing adapter tests remain green (verified full re-run below).

## Verification

`PYTHONHOME` cleared, `PYTHONPATH=src`, `.venv\Scripts\python.exe` for all
Python runs. Only focused test files were run (no full suite, no
formatter/linter).

```
pytest tests/test_ledger.py tests/test_governor.py tests/test_origin_authority.py \
  tests/test_worker_lifecycle.py tests/test_worker_protocol.py tests/test_omp_adapter.py \
  tests/test_hermes_adapter.py tests/test_orchestration.py tests/test_claude_code_adapter.py -q
```

Round 1 re-run (post review-fix, same command): `tests/test_omp_adapter.py`
all 14 tests pass (10 pre-existing + 3 rewritten + 1 new). Full command above
re-run: 1 pre-existing baseline failure only (the `test_origin_authority.py`
migration-fixture gap above; `test_hermes_adapter.py`'s previously-flaky
`test_pre_llm_routes_existing_skill_and_preserves_bounded_injection` passed
this run). Neither failure touches `omp_adapter.py`, `worker_protocol.py`, or
`ledger.py`.

- `test_origin_authority.py::test_origin_columns_migrate_existing_0012_database`
  — `sqlite3.OperationalError: no such table: main.model_skill_outcomes`

Every other test in these files passes, including all newly added/rewritten
tests. `tests/test_worker_protocol.py`, `tests/test_ledger.py`, and
`tests/test_hermes_adapter.py` were also re-run standalone and are fully
green.

`npm run typecheck` (brainstem/prime-extension): one pre-existing error only
(verified identical on the pre-T4.2 commit via `git stash`); zero errors on
any line touched by this task.

No `uv.lock` was generated by any tooling during this work; none to remove.

## Files changed

- `src/second_brain/cli.py`
- `src/second_brain/ledger.py`
- `src/second_brain/hermes_adapter.py`
- `src/second_brain/omp_adapter.py`
- `src/second_brain/simplification.py`
- `src/second_brain/worker_protocol.py`
- `tests/test_ledger.py`
- `tests/test_governor.py`
- `tests/test_origin_authority.py`
- `tests/test_worker_lifecycle.py`
- `tests/test_worker_protocol.py`
- `tests/test_omp_adapter.py`
- `brainstem/prime-extension/src/index.ts`
- `brainstem/prime-extension/src/worker-result-bridge.ts` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T4.2-report.md` (new, this file)

## Commit

`brain(adapter): validate omp results, unify session ids`
