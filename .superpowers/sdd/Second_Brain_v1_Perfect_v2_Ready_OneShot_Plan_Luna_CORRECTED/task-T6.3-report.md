# T6.3 Task Report — Artifact GC + ledger hash chain

Plan source: `Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md` lines 389-394.

## Migration number

The plan text's literal "0014_hash_chain.sql" is stale (0014 is `worker_leases.sql`,
T4.1). Fresh `glob` of `src/second_brain/migrations/*.sql` at the start of this task
showed 0017 (`decision_inputs.sql`) as the highest existing file — the real next-free
number is **0018**. Wrote `migrations/0018_artifact_gc.sql`, targeting the same shared
`db/brain.sqlite` every other `migrations/*.sql` file targets (not the per-session
`ledger.sqlite` — separate schema mechanism, see Part B):

```sql
CREATE TABLE IF NOT EXISTS artifact_refs (
    sha TEXT NOT NULL,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sha, owner)
);
CREATE INDEX IF NOT EXISTS idx_artifact_refs_sha ON artifact_refs(sha);
```

`created_at` is a debugging/audit trail of when a ref was *registered*; `gc()`'s
age check reads the blob's own `state/artifacts/meta/<sha>.json` `created_at`
field instead (the correct source of blob age), never this column.

## Part A — Artifact refcount + GC

### `src/second_brain/artifacts.py`

Added `from . import db` (first DB usage in this previously pure-filesystem module)
and four functions, all self-healing via the same `if db.pending_migrations(...):
db.migrate(...)` pattern already used by `worker_protocol._worker_db`:

- `add_ref(home, sha, owner)` — `INSERT OR IGNORE`, idempotent.
- `remove_ref(home, sha, owner)` — `DELETE ... WHERE sha=? AND owner=?`, idempotent.
- `remove_refs_by_owner_suffix(home, suffix)` — `DELETE ... WHERE owner LIKE ?` with
  the pattern built in Python (`f"%{suffix}"`) and bound as a parameter (never
  string-formatted into the SQL). Returns the deleted row count. This is the session
  purge primitive.
- `gc(home, min_age_days=30)` — iterates `state/artifacts/meta/*.json` directly
  (not `list_artifacts`, so one corrupt/unreadable meta file is skipped-and-noted
  rather than aborting the whole sweep, per the task's "never raise on an individual
  file's OS error" requirement). A blob is deleted only when its own meta
  `created_at` age exceeds `min_age_days` **and** `artifact_refs` has zero rows for
  its sha. Returns `{"deleted_count", "deleted_shas", "kept_referenced_count",
  "kept_too_recent_count"}` plus an `"errors"` key when any entry was skipped.

### Owner-string convention (exact, per call site)

Adopted `f"{subsystem}:{internal_session_id}"` for every session-scoped subsystem,
reusing `ledger.internal_session_id(host_session_id)` (T4.2's unified scheme) —
never a second session-id scheme:

| File:line (post-edit) | Subsystem | Owner string |
|---|---|---|
| `vmem.py:349` (`store_object`, after `store_text`) | `vmem` | `f"vmem:{self.internal_id}"` (already computed in `__init__`) |
| `hermes_adapter.py:2125` (`_handle_post_tool_call`, RTD raw preservation) | `rtd` | `f"rtd:{ledger.internal_session_id(binding.host_session_id)}"` |
| `handoff.py:270` (`create_handoff_envelope`) | `handoff` | `f"handoff:{ledger.internal_session_id(session_id)}"` (added `ledger` import; no cycle — `ledger.py` does not import `handoff.py`) |
| `action_cache.py:300` (`store_action`, after `action_key` is computed) | `action_cache` | `f"action_cache:{action_key}"` (NOT session-scoped — keyed by action_key, independent of any session) |

Fresh grep confirmed exactly these 7 real `store_text`/`store_file`/`store_bytes`
call sites exist (the stale line numbers in the task context were re-verified, not
trusted). The remaining three have no natural per-owner deletion lifecycle and are
registered with a stable, honest owner string per the task's explicit guidance —
**no artificial removal logic was invented** for them; natural GC after
`min_age_days` with zero refs is the correct eventual behavior once nothing
references them:

| File:line | Owner string | Reasoning |
|---|---|---|
| `firewall.py:524` (`reduce_observation`) | `f"firewall:{session}"` if `session` else `"firewall:none"` | `session` is an optional param with no owning lifecycle in this module |
| `repository_intelligence.py:373` (`complete_worker`) | `f"repository_intelligence:{self.session_id}"` | worker-result artifacts have no explicit removal path today |
| `cli.py:1663` (`cmd_artifact` manual `artifact store`) | `"cli-manual"` (fixed literal) | a manual CLI invocation has no session/task tracking it — nothing ever "owns" it beyond storage itself |

### `action_cache.py` ref-removal pairing

Every `DELETE FROM action_cache` site now pairs artifact ref removal, fetching
`output_ref`/`action_key` for the doomed rows before deleting:

- **LRU eviction** (`store_action`, max_entries overflow) — `SELECT action_key,
  output_ref ... ORDER BY last_accessed_at ASC LIMIT ?` before the existing
  `DELETE`, then `artifacts.remove_ref` per evicted row.
- **`invalidate_by_key`** — `SELECT output_ref` before `DELETE`, then one
  `remove_ref` call.
- **`invalidate_by_path`** — both the target-match and the `input_hashes`-scan
  branches now also collect `output_ref` (previously only `action_key`); a single
  `remove_ref` loop runs after all `DELETE`s commit.
- **`prune_expired`** — `SELECT action_key, output_ref ... WHERE expires_at ...`
  before the existing bulk `DELETE`, then `remove_ref` per expired row.
- **`clear`** — per the task's explicit allowance, this one does a single bulk
  `DELETE FROM artifact_refs WHERE owner LIKE 'action_cache:%'` against the main db
  (self-healing `pending_migrations`/`migrate` first) instead of per-row deletes,
  since every action_cache-owned ref is being cleared in the same operation anyway.

Without this pairing, refs would leak forever after their action_cache row is gone
and their blobs would never become GC-eligible — a leak in the **safe** direction
(never wrongly deletes a live blob), but explicitly required by the task for GC
correctness, so it is done everywhere except the one place (`clear`) the task
itself names as an acceptable bulk-delete exception.

One known, accepted gap (not asked for, not built): `store_action`'s `ON CONFLICT
DO UPDATE` upsert path (same `action_key`, new content) registers a new ref for the
new `output_ref` but does not remove the old ref for that same owner string — a
safe-direction leak (old blob keeps a stale ref, never wrongly deleted), out of the
task's explicit deletion-pairing list (which names five specific `DELETE` sites,
none of which is the upsert path).

### `ledger.py` session purge

`SessionLifecycle.purge()` now calls
`artifacts.remove_refs_by_owner_suffix(self._home, f":{self._internal}")`
immediately before `shutil.rmtree(target)` (not after) — so a `rmtree` failure
partway through never leaves orphaned refs pointing at a half-deleted session.
Added `from . import artifacts` to `ledger.py`'s imports; confirmed no import
cycle (`artifacts.py`'s own imports are `contextlib, hashlib, json, os, re,
tempfile, datetime, pathlib, typing, .db, .errors` — no `ledger` reference).

## Part B — Ledger hash chain (`ledger.sqlite`, per-session, separate mechanism)

`ledger.py`'s internal `LEDGER_SCHEMA_VERSION`/`_SCHEMA` DDL/`_check_version`
mechanism is entirely separate from the `migrations/*.sql` files that govern the
shared `db/brain.sqlite` (Part A). Confirmed this distinction was not confused
anywhere in this task's edits.

- `LEDGER_SCHEMA_VERSION` bumped **1 → 2**. Added `prev_hash TEXT` to the `events`
  table inside `_SCHEMA`. Added module constant `_GENESIS_HASH = "0" * 64`.
- **`append_events`**: seeds a running `prior_row_hash` once per batch from
  `SELECT prev_hash FROM events ORDER BY seq DESC LIMIT 1` (falls back to
  `_GENESIS_HASH` for a brand-new ledger), then per inserted row computes
  `prev_hash = sha256(running_prev_hash + canonical_json(payload)).hexdigest()`
  and advances the running variable — one query per batch, not per row.
- **`integrity()` rewrite**:
  - **Removed** the eager per-call loop that re-hashed every `object_refs` row
    (`SELECT sha256, size FROM object_refs` + read+hash every blob) — this was the
    O(all objects) cost the task explicitly asks to eliminate from the
    checkpoint-facing hot path.
  - **Real discrepancy found and resolved** (task explicitly asked to verify, not
    assume, that nothing depends on `object_digests_ok`/`object_bad`): a fresh
    repo-wide grep found the task's own investigation claim ("confirmed... there are
    NONE") was **wrong** — `LedgerStore.replay()` (a real, tested production path)
    reads `integrity()["object_digests_ok"]`/`["object_bad"]` to reject replay on a
    corrupted object, and `tests/test_ledger.py::test_replay_rejects_missing_object`
    depends on exactly that behavior. Since `replay()` itself never reads object
    *bytes* (it only assembles the events/segments/epochs/fingerprints projection),
    its full object-digest check was always logically independent of the
    incremental event-hash-chain concern this task targets. Resolution: extracted
    the removed loop verbatim into a new private `LedgerStore._verify_object_digests()`
    helper; `replay()` now calls it directly (same `"replay rejected: object digest
    failures {...}"` error, same test still passes) while `integrity()` (and
    therefore `checkpoint_ledger()`, its hot-path caller) no longer pays that cost.
    This satisfies both the plan's literal instruction ("no full re-hash of objects
    per checkpoint") and the pre-existing tested contract of `replay()`.
  - `object_digests_ok`/`object_bad` fields **omitted** from `integrity()`'s return
    (preferred option per the task, confirmed safe: no other production caller or
    test reads either field from `integrity()`'s dict — only `replay()` did, and it
    now calls `_verify_object_digests()` directly instead).
  - **Added** incremental hash-chain verification: reads
    `ledger_meta['last_verified_seq']` (default 0), seeds `running_prev_hash` from
    that row's own stored `prev_hash` (or `_GENESIS_HASH` if seq 0/absent), then for
    every event with `seq > last_verified_seq` (ascending) recomputes the expected
    `prev_hash` from the *previous row's own stored* `prev_hash` + this row's
    *stored* `payload_json` text and compares against this row's stored `prev_hash`.
    On success, persists `last_verified_seq = max verified seq` via `INSERT OR
    REPLACE INTO ledger_meta`. Returns `hash_chain_ok`, `hash_chain_verified_through_seq`,
    `hash_chain_break_seq` (the mismatching row's seq, else `None`); kept
    `seq_contiguous`/`orphan_parents`/`schema_version`/`event_count` unchanged in
    meaning; added `objects_verified_on_read_only: True` as an honest documentation
    marker (not a check result) in place of the removed fields.
- **`checkpoint_ledger()`**: `ok` now requires `integrity["hash_chain_ok"]` instead
  of the removed `object_digests_ok`.

### `LEDGER_SCHEMA_VERSION` bump consequence (explicit, not glossed over)

Any *existing* `ledger.sqlite` created under schema version 1 now raises
`BrainError("ledger schema version 1 unsupported...")` on open, per T6.1's
intentional strict-version-match design (no upgrader was reintroduced). This is the
accepted consequence, not a bug. **Not** touched: `contracts.py` defines its own,
*separate* `LEDGER_SCHEMA_VERSION = 1` constant and `read_ledger_header()`/
`LedgerHeader` — a distinct, independently-versioned host/adapter-interop contract
with **zero production callers connecting it to `ledger.py`'s internal DB schema**
(confirmed by grep: `read_ledger_header` is referenced only by
`contracts.py`/tests). Bumping only `ledger.py`'s constant, as the task explicitly
scopes, does not touch `contracts.LEDGER_SCHEMA_VERSION` and breaks no real path.

### Test-literal fallout from the bump (updated deliberately, explained here)

Only tests exercising the real `ledger.py` `LedgerStore`/`_check_version` path
(not `contracts.read_ledger_header`, which stayed at version 1 and needed no
changes) hardcoded the old version number or a mismatch value that became valid
post-bump:

- `tests/test_ledger.py:86,1057,1066` — `header["schema_version"] == "1"` →
  `== str(ledger_mod.LEDGER_SCHEMA_VERSION)` (dynamic, future-proof).
- `tests/test_ledger.py:194` and `tests/test_cleanup_t61.py:94` — both manually
  `UPDATE ledger_meta SET value = '2'` to simulate a *mismatched* version; `2` is
  now the *correct* version, so both were changed to `'99'` (still deterministically
  wrong) to keep testing "version mismatch raises `BrainError`".
- `tests/test_contracts.py` and the rest of `tests/test_cleanup_t61.py` (which test
  `contracts.LEDGER_SCHEMA_VERSION`/`read_ledger_header`, confirmed via fresh read to
  be the separate, unbumped constant) needed **no changes**.

## Part C — Heartbeat GC wiring

- `heartbeat.py`: added `from . import artifacts`. In `LocalHeartbeatEngine.pulse()`'s
  active-mode branch (the same `else:` under `if mode == "shadow": ... else: ...`
  that already runs `cache.prune_expired()`), added `artifacts.gc(self.home,
  min_age_days=30)` in its own `try/except`, appending `"artifacts_gc_probe"` to
  `issues` on any exception (never crashes the heartbeat), else setting
  `gc_count = result["deleted_count"]`.
- Added `artifacts_gc_count: int = 0` to the `HeartbeatStatus` dataclass (threaded
  through `to_dict()`), the `HeartbeatStatus(...)` construction in `pulse()`,
  `HeartbeatCoordinator._base_result()`, and the `result` dict built in
  `run_if_due()`. Stays `0` in shadow/off mode or on GC failure, matching the
  task's requirement.
- Two real callers build `heartbeat_pulse` telemetry records by explicit field list
  from the coordinator's result dict — both updated to include the new field:
  `cli.py::cmd_heartbeat` (the dict literal passed to `telemetry.append_record`) and
  `p4.py::_HEARTBEAT_RECORD_FIELDS` (the tuple `pulse()` uses to slice
  `heartbeat_result`).
- `telemetry.py`: added `"artifacts_gc_count"` to `_HEARTBEAT_FIELDS` (which both
  defines `_APPEND_FIELDS["heartbeat_pulse"]` via `set(_HEARTBEAT_FIELDS)` and marks
  the field **required** for any raw `heartbeat_pulse` record read by `validate()`),
  to the non-negative-integer validation loop, and a `safe.setdefault
  ("artifacts_gc_count", 0)` in `append_record` so every record written through the
  normal API always carries it.
- Because `_HEARTBEAT_FIELDS` now treats the field as required, three existing
  tests that construct raw `heartbeat_pulse` fixtures **outside** `append_record`
  (bypassing its `setdefault`) needed the field added explicitly to stay green:
  `tests/test_telemetry.py::test_current_omp_v3_records_validate`'s raw literal, and
  `tests/test_operational_telemetry.py::_heartbeat()` helper (shared by both of that
  file's raw-fixture tests). `tests/test_heartbeat_coordinator.py::test_off_does_not_probe_or_mutate`'s
  exact-dict-equality assertion on `run_if_due()`'s off-mode result also needed the
  new key added.

## Tests

Added, in the files the task named:

- `tests/test_artifacts.py` — `test_gc_keeps_referenced_blobs` (referenced+aged
  blob survives; then unref+re-gc deletes it; a fresh unreferenced blob survives via
  the age floor), plus supporting `test_add_ref_remove_ref_idempotent` and
  `test_remove_refs_by_owner_suffix`.
- `tests/test_ledger.py` — `test_hash_chain_detects_in_place_edit`,
  `test_integrity_incremental`, `test_hash_chain_verified_on_append`, and
  `test_purge_removes_artifact_refs_before_rmtree`.
- `tests/test_action_cache.py` — `TestActionCacheArtifactRefs`: LRU-eviction,
  `invalidate_by_key`, and `clear` each proven to remove the corresponding
  `artifact_refs` rows.
- `tests/test_vmem.py` / `tests/test_handoff.py` — one narrow test each proving the
  `vmem`/`handoff` store call sites actually register a ref with the documented
  owner-string convention (end-to-end wiring proof for two of the four store sites).
- `tests/test_heartbeat_coordinator.py` — `test_active_runs_artifact_gc`: seeds an
  aged unreferenced artifact, runs an active-mode heartbeat, asserts
  `artifacts_gc_count == 1` and the blob is gone.

### Incremental-verification proof strategy

`test_hash_chain_detects_in_place_edit` establishes a checkpoint at seq 2, appends
one more event (seq 3, *not* covered by that checkpoint), tampers seq 3's
`payload_json` in place (same raw-sqlite3 `UPDATE` style as
`test_replay_detects_payload_tamper_via_compare`), and asserts the next
`integrity()` call catches it at exactly `hash_chain_break_seq == 3`.

`test_integrity_incremental` is the negative proof: seeds 3 events, checkpoints
(`hash_chain_verified_through_seq == 3`, persisted to `ledger_meta`), appends 2 more
(seq 4-5), then tampers seq **2** — a row that *was* already covered by the first
checkpoint — and asserts the second `integrity()` call still reports
`hash_chain_ok is True` and `hash_chain_verified_through_seq == 5`. This proves
verification genuinely resumes from `last_verified_seq` forward only (an
already-checkpointed row's tamper is structurally unreachable from that point on —
the standard, documented trade-off of any checkpoint-based incremental verifier),
rather than silently re-scanning the whole chain every call.

## Tests run

Clean environment: `PYTHONHOME` unset, `PYTHONPATH=src`, `.venv\Scripts\python.exe`.

```
tests/test_artifacts.py .............................                    29 passed
tests/test_ledger.py    ...........................................      43 passed
tests/test_heartbeat_coordinator.py + tests/test_action_cache.py          25 passed
tests/test_vmem.py + tests/test_handoff.py                                85 passed
tests/test_cleanup_t61.py + tests/test_telemetry.py
  + tests/test_operational_telemetry.py + tests/test_contracts.py         71 passed
tests/test_firewall.py + tests/test_repository_intelligence_live.py
  + tests/test_hermes_adapter.py + tests/test_p4.py + tests/test_p4_persistence.py
                                                                           92 passed
tests/test_cli.py                                                        38 passed
tests/test_db.py                                                          8 passed
```

All green. Two unrelated pre-existing failures were checked and confirmed present
on baseline commit `8e06ac4` (via `git stash`), not caused by this task, not
modified:
- `tests/test_migrations_property.py::test_any_prefix_then_remainder_equals_full_apply`
  (an unrelated `brain_meta` table appearing in a synthetic `k=0` migration-prefix
  scenario).
- `tests/test_reconsolidation.py::test_lazy_migration_0005` (duplicate-column error
  re-applying migration 0017 in a hand-rolled partial-schema test, unrelated to
  0018/`artifact_refs`).

No `uv.lock` was generated during this task.

## Files changed

- `src/second_brain/migrations/0018_artifact_gc.sql` (new)
- `src/second_brain/artifacts.py`
- `src/second_brain/action_cache.py`
- `src/second_brain/vmem.py`
- `src/second_brain/handoff.py`
- `src/second_brain/hermes_adapter.py`
- `src/second_brain/firewall.py`
- `src/second_brain/repository_intelligence.py`
- `src/second_brain/cli.py`
- `src/second_brain/ledger.py`
- `src/second_brain/heartbeat.py`
- `src/second_brain/p4.py`
- `src/second_brain/telemetry.py`
- `tests/test_artifacts.py`
- `tests/test_ledger.py`
- `tests/test_action_cache.py`
- `tests/test_vmem.py`
- `tests/test_handoff.py`
- `tests/test_heartbeat_coordinator.py`
- `tests/test_cleanup_t61.py`
- `tests/test_telemetry.py`
- `tests/test_operational_telemetry.py`
