# T6.2 Task Report — Fix listed integration defects

Plan source: `Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md` lines 380-387.

## 1. `handoff.py:171` wrong capsule key

**Defect**: `create_handoff` read `capsule.get("current_objective")`. The canonical
capsule schema (`working_set.CAPSULE_FIELDS`) has no `current_objective` field — only
`objective` — so `final_objective` always fell through to the
`"Continue session task"` default, silently discarding the real capsule objective on
every handoff.

**Fix**: `src/second_brain/handoff.py:171` — `capsule.get("current_objective")` →
`capsule.get("objective")`. The four sibling reads on the same block
(`decisions_this_session`, `open_questions`, `files_touched`, `next_action`) were
already correct against `CAPSULE_FIELDS`/`CAPSULE_LIST_FIELDS`; left untouched.

**Test**: `tests/test_handoff.py::TestLegacyHandoffObjective::test_handoff_uses_capsule_objective`
— seeds a real capsule via `working_set.init_capsule`/`update_capsule` (existing
`_seed_capsule` helper, objective `"Close the P3.17 handoff seam"`), calls
`create_handoff`, asserts `artifact.objective` equals that string (not the fallback).

## 2. `capsule_runtime._bounded_items` dropped-item history

**Defect**: `_bounded_items` truncated the merged+deduped list to the last
`MAX_ITEMS=8` via `deduped[-MAX_ITEMS:]` with no record of what fell off the front.

**Fix**: `src/second_brain/capsule_runtime.py` — threaded `home`/`session_id`/`field`
through `_bounded_items` (its only caller, `update_capsule`'s list-field loop, already
had both in scope). When `len(deduped) > MAX_ITEMS`, the dropped prefix is appended,
one JSON object per line, to `state/sessions/<session_id>/capsule-history.jsonl` via
new helper `_record_dropped_items` (uses `working_set.session_dir`, matching this
file's existing `_metadata` convention). Each line: `ts`, `session_id`, `field`,
`dropped_item`. Best-effort: wrapped in `except OSError: pass` — a history-write
failure never blocks the capsule update it accompanies (observability, not a
correctness gate, matching this module's fail-open style for non-input-defect
failures).

**Test**: `tests/test_capsule_runtime.py::test_update_drops_oldest_item_to_capsule_history_beyond_max`
— pushes 8 items then a 9th; asserts (a) the capsule still bounds to exactly the last
8 (`decision-1`..`decision-8`), (b) `capsule-history.jsonl` gains exactly one line for
the dropped `decision-0` with the expected `field`/`session_id`/`ts`.

## 3. `cli.py` action-cache search unsafe `HEAD^{tree}`-only cache gate

**Defect**: `_action_cache_search` gated CODE_SEARCH caching solely on
`action_cache.git_tree_hash_for` (`git rev-parse HEAD^{tree}` — the **committed**
tree). An uncommitted (staged/unstaged/untracked) edit to a searched file was
invisible to that gate, so a stale cached result could be served as a "hit" even
though on-disk content had changed.

**Fix**: `src/second_brain/cli.py::_action_cache_search` — removed the
`git_tree_hash_for`/`store.get_or_execute` branch entirely (the T6.5-deferred real
fix is a full worktree fingerprint including dirty/staged/untracked state, out of
scope here). The function now unconditionally calls `_code_search_git_tracked`
directly (the same fallback path already used for non-git directories), so no stale
hit can ever be served. `hit` is now always `False`; `latency_ms` reflects real
elapsed compute time via `time.perf_counter()`. The `--json`/`hit`/`latency_ms`/
`content` output shape is unchanged. Dropped the now-unused `store` parameter and
updated its single call site in `cmd_action_cache`.

**Test**: replaced `tests/test_cli.py::test_action_cache_search_hits_on_second_call_and_misses_after_a_commit`
(which asserted the now-removed cache-hit behavior) with
`test_action_cache_search_never_caches_and_reflects_uncommitted_edits` — proves two
back-to-back calls are both misses, and an **uncommitted** edit (no `git commit`) is
reflected in the very next call's output — the exact regression this fix closes.
`test_action_cache_search_non_git_dir_never_caches` (unchanged, still passes).

## 4. `docs/components/artifacts-rtd.md` doc drift

**Defect**: doc stated RTD substitution was "SHADOW MODE ONLY" / "NOT implemented",
stale versus the implemented reality.

**Evidence grounding each edit**:
- `brainstem/telemetry/SCHEMA.md` "Phase P3-F addition (RTD substitution, plan §11)"
  section: substitution is active when `[rtd] enabled=true`; raw result preserved
  byte-exactly through the Artifact Store and verified recoverable *before* the
  model-visible content is replaced by a `[SECOND_BRAIN_RTD]` block; preservation
  failure returns original content unchanged; binary/non-text never distilled;
  `rtd_shadow` gains additive fields (`original_chars`, `visible_chars`,
  `saved_chars`, `artifact_ref`, `command_class`, `error_status`, `distilled`) when
  substitution runs.
- `config/context.toml [rtd]` comments: `enabled` is the "master switch: substitution
  happens only when true"; `threshold_chars` is "ENFORCED"; `max_distill_chars`,
  `whitelist_tools`, `whitelist_commands` are "now REAL for the RTD substitution
  surface" (`config.ts loadRtdConfig`, `rtd.ts runRtd`).

**Edits**:
- Responsibilities (TS `rtd.ts` bullet): removed "substitution NOT implemented.
  SHADOW MODE ONLY."; states substitution is ACTIVE when `[rtd] enabled=true` with
  the preserve→verify→substitute sequence and failure/binary handling from
  SCHEMA.md; shadow-only measurement when disabled/below-threshold; names all five
  `[rtd]` keys as real runtime inputs per context.toml.
- Non-responsibilities: removed "Never substitutes tool-result content
  (shadow-only)" (no longer true); replaced with the real remaining
  non-responsibilities (no raw content in `rtd_shadow`; no substitution when
  disabled/ineligible; never lossy-compresses source edit regions).
- Known limitations: removed "Substitution unimplemented (shadow-only)"; also
  corrected the now-false trailing claim that non-`threshold_chars` `[rtd]` keys are
  "documented defaults, NOT read at runtime" (context.toml says otherwise) to state
  they ARE read at runtime for the substitution decision.
- Future extension: removed "Active RTD substitution with expand recovery" (already
  implemented, no longer future). Kept "sensory gateway; retention policy" — verified
  via repo-wide grep that no `sensory` module/gateway and no artifact
  retention/expiry code exist anywhere in `src/second_brain` or `brainstem/`; both
  remain genuine future gaps.

Documentation-only change; no test required per the task instructions.

## 5. `action_cache.invalidate_by_path` full-table scan

**Defect**: ran `SELECT action_key, proof_json, target FROM action_cache` with no
`WHERE` clause, then resolved and compared every row's `target` (and every row's
`input_hashes`) in Python — O(n) per invalidation call.

**Repository-reality discrepancy** (recorded per plan rule 9): the plan's fix
instruction was "add `CREATE INDEX IF NOT EXISTS idx_action_cache_target ON
action_cache(target)`". Fresh inspection of `_ACTION_CACHE_SCHEMA` showed
`CREATE INDEX IF NOT EXISTS idx_action_target ON action_cache (target)` **already
exists** (present before this task). Adding a second, differently-named, functionally
identical index would be pure duplication with no query planner benefit. The real
defect was narrower than the plan assumed: the index existed but `invalidate_by_path`
never queried through it. Fixed the query instead of adding a redundant index.

**Matching-strategy determination**: grepped every production `store_action`/
`get_or_execute` call site. Before this task there was exactly one:
`cli.py::_action_cache_search`'s CODE_SEARCH call, which used a composite
`target=f"{target_dir}::{pattern}"` string. Defect #3 above removes that call site
entirely, so after this task's fixes there is **no remaining production caller**
that stores a composite `target`; every real `target` in this codebase (test
convention: `target=str(<absolute path>)` for `FILE_READ`/`DIR_SCAN`/`GENERIC_PURE`)
is a bare path string.

**Fix**: `src/second_brain/action_cache.py::invalidate_by_path` — the target-match
branch is now a single indexed `SELECT action_key FROM action_cache WHERE target IN
(?, ?)` against `{str(path), str(Path(path).resolve())}` (covers both the literal
string a caller passed and its resolved form; the existing `idx_action_target` index
services the `IN` lookup). The `input_hashes` JSON-embedded fallback stays a linear
scan (explicitly out of scope per the plan's narrow "index on target" ask); its
existing correctness is unchanged (same resolve()-equality comparison as before).

**Test**: `tests/test_action_cache.py::TestActionCacheStoreAndReplay::test_invalidate_by_path_uses_target_index`
— stores two entries with **no `input_hashes`** (so a match is only reachable
through the indexed target branch, not the fallback scan), invalidates one by path,
asserts exactly that one entry is removed, and asserts `idx_action_target` is present
via `PRAGMA index_list('action_cache')`. Pre-existing
`test_invalidate_by_path` (target+input_hashes combined case) still passes unchanged.

## 6. `autoinject` session_started scan + `is_already_delivered`

**Defect (session_started)**: `_has_session_started` read the entire per-session
telemetry JSONL file into memory (`path.read_text(...).splitlines()`) on every call,
even though it returns on first match — full read/decode cost regardless of match
position, on every call for the session's lifetime (file grows every turn).

**Fix**: `src/second_brain/autoinject.py` — added `ledger` to the module's `from .
import (...)` block (no circular import: `ledger.py` imports only `semantic`,
`contracts`, `errors`, `security.paths`). New `_session_started_marker_path(home,
host_session_id)` returns `ledger.session_dir(home, host_session_id) /
"session-started.marker"` (same per-session directory `ledger`/`working_set` already
use elsewhere; mirrors `adapters/claude_code.py::_claude_usage_cursor_path`'s
try/except-`Exception`-returns-`None` pattern). `_has_session_started` is now a
`Path.exists()` check. New `_mark_session_started` creates the marker
(`mkdir(parents=True, exist_ok=True)` + `touch()`), called from
`BrainLifecycleController.start_session` immediately after the `session_started`
telemetry append (same call site that previously gated only on
`_has_session_started`). Both fail-open on `OSError` exactly as before (return
`False` / silently no-op).

**Test**: `tests/test_autoinject.py::TestHasSessionStartedMarker` —
`test_marker_check_is_idempotent` (False before, `_mark_session_started`, True
after); `test_marker_check_fails_open_on_error` (monkeypatches
`_session_started_marker_path` to raise `OSError`, asserts `_has_session_started`
returns `False`, does not raise). Existing end-to-end idempotency coverage in
`tests/test_claude_code_adapter.py` (`test_startup_records_exactly_one_session_started`,
`test_repeated_startup_same_session_still_one`, `test_startup_stop_resume_same_brain_session`)
continues to pass unchanged — same one-record-per-session contract, now backed by
the marker instead of a JSONL scan.

**`is_already_delivered` discrepancy** (recorded per plan rule 9, task item 6's
second half): fresh grep of `src/second_brain` confirms `contracts.is_already_delivered`
has **zero production callers** — its only reference outside its own definition/
docstring-comment is `tests/test_contracts.py`. The production dedupe path already
goes through `autoinject._delivered_keys`, which runs
`SELECT memory_id, memory_version, canonical_hash FROM deliveries WHERE
root_session_id = ? AND branch_id = ?` — and `migrations/0008_deliveries.sql` already
defines `CREATE INDEX IF NOT EXISTS idx_deliveries_dedupe ON deliveries
(root_session_id, branch_id, memory_id, memory_version)`, which exactly covers that
query. There is no scan defect to fix and no dead code with a real caller to redirect
onto SQL. Per plan rule 9 ("if a step contradicts repository reality, stop, record
the discrepancy... continue with the narrower repository-true version"): **no code
change was made for this half of item 6** — inventing one would be unnecessary churn
against a component that is already correct.

## Tests run

Clean environment: `PYTHONHOME` unset, `PYTHONPATH=src`, `.venv\Scripts\python.exe`.

- `tests/test_handoff.py` — 34 passed (combined with capsule_runtime/action_cache
  below in the same invocation)
- `tests/test_capsule_runtime.py` — passed
- `tests/test_action_cache.py` — passed
- `tests/test_cli.py` (full file, touched) — 38 passed
- `tests/test_autoinject.py` (full file, touched) — 39 passed
- `tests/test_action_cache_safety_proof.py`, `tests/test_working_set.py`,
  `tests/test_contracts.py` — all passed except one **pre-existing, unrelated**
  failure confirmed present on baseline commit `8034de5` before any T6.2 change
  (verified via `git stash`): `test_working_set.py::test_no_lean_path_bypasses_requirement_ledger`
  (asserts `brainstem/prime-extension/src/lean-code.ts` never contains the substring
  `"requirement"`; it does, in an unrelated TS interface field name — no file this
  task touches). Not in scope for T6.2; not modified.

No `uv.lock` was generated during this task.

## Files changed

- `src/second_brain/handoff.py`
- `src/second_brain/capsule_runtime.py`
- `src/second_brain/cli.py`
- `src/second_brain/action_cache.py`
- `src/second_brain/autoinject.py`
- `docs/components/artifacts-rtd.md`
- `tests/test_handoff.py`
- `tests/test_capsule_runtime.py`
- `tests/test_cli.py`
- `tests/test_action_cache.py`
- `tests/test_autoinject.py`

## Amendment — ReviewT62 findings (2 P2, post-`0d0198e`)

### Finding 1 — `_mark_session_started` called unconditionally, decoupling idempotency from telemetry success

`BrainLifecycle.start_session` called `_mark_session_started` right after
`_append_telemetry`, discarding its `bool` return. Since the marker
(`state/sessions/<id>/session-started.marker`) and the telemetry record
(`state/telemetry/<id>.jsonl`) are different files in different directories,
a transient I/O failure writing the telemetry record (while the marker
write still succeeded) would permanently lose that `session_started` record
for the session's lifetime, with no self-heal — a regression versus the
pre-T6.2 behavior where the idempotency check read back the same file the
append wrote, so a failed append was retried on the next call.

**Fix**: `src/second_brain/autoinject.py::BrainLifecycle.start_session` —
capture `_append_telemetry`'s return into `recorded`; only call
`_mark_session_started` `if recorded`. A failed append now leaves no marker,
so the next `start_session` call for that `host_session_id` retries exactly
as before this task's change.

**Test**: `tests/test_autoinject.py::TestSessionStartedMarkerOnlyOnSuccessfulTelemetry`
— `test_marker_not_written_when_telemetry_append_fails` (monkeypatches
`_append_telemetry` to always return `False`, asserts the marker is never
written); `test_marker_written_and_retried_once_telemetry_succeeds`
(monkeypatches `_append_telemetry` to fail once then succeed, asserts the
first `start_session` call leaves no marker, the second call retries the
append — proven by the fake being invoked exactly twice — and only then
writes the marker). Both independently verified to fail against the
pre-amendment unconditional-write code (`AssertionError: assert True is
False` — the marker was present after a failed append).

### Finding 2 — `test_invalidate_by_path_uses_target_index` did not prove indexed-lookup usage

The original regression test for defect #5 only checked functional
correctness plus `idx_action_target`'s presence in `PRAGMA index_list` —
both true of the pre-fix O(n) full-table-scan implementation too, since the
index already pre-existed in the schema and the old code was already
functionally correct (just not indexed). The test therefore could not catch
a future regression back to a full-table scan.

**Fix**: `tests/test_action_cache.py::TestActionCacheStoreAndReplay::test_invalidate_by_path_uses_target_index`
rewritten to trace the *exact* SQL `invalidate_by_path` itself issues via
`sqlite3.Connection.set_trace_callback` (rather than running an independent
hand-written query, which — as ReviewT62 found in the first pass of this
fix — never actually observes what the method under test does), asserts a
`WHERE`-filtered `SELECT ... target ...` statement was captured, then runs
`EXPLAIN QUERY PLAN` on that captured statement and asserts
`USING INDEX idx_action_target` appears in the plan. Independently verified
to fail against `invalidate_by_path` reverted to the pre-fix full-table-scan
implementation (no `WHERE`-filtered target query is ever issued, so the
"query observed" assertion fails first) and to pass against the current
indexed implementation.

### Re-verification

Clean environment (`PYTHONHOME` unset, `PYTHONPATH=src`,
`.venv\Scripts\python.exe`): `tests/test_handoff.py tests/test_capsule_runtime.py
tests/test_action_cache.py tests/test_cli.py tests/test_autoinject.py` —
112 passed, 0 failed.
