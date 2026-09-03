# T1.7 Report — Origin classes and authority ceilings

## Recovery of the uncommitted work

The prior implementer hit a usage limit before committing, leaving the worktree
dirty against base `baf8009`. On inspection the prior diff already implemented
most of the required behavior correctly:

- Migration 0012 additive/guarded columns (`origin_class`, `origin_root_sha`,
  `authority_ceiling`) on `memories`, plus the fresh/reopen replay path in
  `db.py`.
- `semantic._validate_origin` (enum + sha256 + ceiling-from-class binding),
  `semantic.corroboration_count` (distinct non-null `origin_root_sha`),
  `semantic.add_memory`/`curate` write-time binding and lower-only ceiling
  transitions.
- `cli.py` wiring for `remember` (USER_AUTHORED), `memory add` (LOCAL_REPO
  when `--evidence` captured a root, else MODEL_INFERENCE), and `memory
  curate --authority-ceiling`.
- `autoinject.py` policy-lane admission gate in `_valid_candidates` and
  `contradicts` rendering plumbing in `contracts.PacketItem`/`BrainPacket`.
- `tests/test_origin_authority.py` with the three named RED/GREEN tests
  already present and correctly asserting the intended behavior.

However, two **regressions** had been accidentally introduced into
pre-existing, unrelated code while making those edits (visible only once the
test environment was pointed at this worktree instead of a stale global
editable install — see Concerns):

1. `autoinject._valid_candidates` was missing its `return out` statement,
   so it always returned `None`. This broke *all* AutoInject retrieval
   (semantic lane included), not just the new policy lane.
2. `contracts.BrainPacket.render()` dropped the `UPDATE <id> vN supersedes
   <id> vM` line emission while adding `contradicts` rendering, even though
   `parse()` and several existing tests (`test_new_version_renders_
   supersedes_delta`, `test_superseded_never_current_and_delta_emitted`,
   `test_materially_updated_memory_delivered_with_supersede_pointer`) still
   depended on it.

Both were restored (see Files touched). The worktree was **not** reset or
discarded; both fixes are additive corrections layered on top of the
existing dirty diff.

A third gap (not a regression, a missing scope item from the brief's exact
mapping table) was found and closed: `ledger.SessionLifecycle.extract_durable`
(the `extract_durable`-style writeback path) created memories without binding
`origin_class`, so it silently fell back to the schema default
`MODEL_INFERENCE` instead of the specified `TOOL_OBSERVATION`. Fixed by
passing `origin_class="TOOL_OBSERVATION"` at its `semantic.add_memory` call
site.

A fourth gap was found while writing the contradiction-rendering test: the
policy-lane admission gate correctly excluded lower-authority (advisory)
memories from being promoted as packet ITEMs, but `_build_items` still
flagged the *surviving* higher-authority item as `CONTRADICTED` whenever its
`contradiction_with` referenced the excluded lower-authority id (attached
before policy filtering by `semantic._contradiction_map`). That flipped the
withholding gate (`NoInjectionReason.CONTRADICTORY_UNRESOLVED`) and silently
suppressed authoritative facts instead of rendering the required `contradicts:
<id>` line, contradicting the brief ("lower-authority contradictions render
`contradicts: <id>` and are never promoted"). Fixed in `_build_items`: for
`lane == "policy"`, only contradiction ids that are *also* present among the
currently-admitted rows flip status to CONTRADICTED / trigger withholding;
contradictions against excluded lower-authority rows are rendered via
`contradicts` only. The semantic lane's pre-existing (unconditional)
contradiction-withholding behavior is unchanged, preserving
`test_contradiction_withheld_per_policy`.

## RED/GREEN

Environment note: the global editable install of `second-brain` (a
process-wide `.pth`) pointed at a *different* worktree
(`v1-p4-canonical-integration`), and `hypothesis` (used by
`tests/test_semantic.py`) was not installed at all. Both were pre-existing
environment issues unrelated to this task; resolved locally for this session
by prepending `PYTHONPATH=src` (this worktree) ahead of the stale editable
install for every test invocation, and installing `hypothesis` into the
shared interpreter (a genuine missing `dev` dependency, additive, does not
change any worktree's code).

RED (before the two regression fixes, full target battery):
```
PYTHONPATH=src py -3.13 -m pytest tests/test_origin_authority.py tests/test_contracts.py \
  tests/test_autoinject.py tests/test_semantic.py tests/test_cli.py tests/test_retrieval_isolation.py
```
→ ~50 failures: 6 in `test_origin_authority.py` (API not yet wired — false
RED from environment only, since the API *was* wired; the real RED signal
is item 2 below), 1 in `test_contracts.py`
(`test_new_version_renders_supersedes_delta`, the regression), and ~40 in
`test_autoinject.py`/`test_cli.py`/`test_retrieval_isolation.py` all
downstream of `_valid_candidates` returning `None` (the regression).

GREEN (after both regression fixes + the extract_durable/contradiction-scope
fixes + the completed test suite):
```
PYTHONPATH=src py -3.13 -m pytest tests/test_origin_authority.py -q
→ ...........                                                          [100%]
11 passed

PYTHONPATH=src py -3.13 -m pytest tests/test_origin_authority.py tests/test_contracts.py \
  tests/test_autoinject.py tests/test_semantic.py tests/test_cli.py \
  tests/test_retrieval_isolation.py tests/test_ledger.py tests/test_hermes_adapter.py -q
→ 2 failed (both pre-existing, see Concerns), remainder passed
```

Pre-existing-failure confirmation (bisected via `git stash` back to base
`baf8009`, run in isolation, then `git stash pop` to restore all work):
```
PYTHONPATH=src py -3.13 -m pytest tests/test_autoinject.py::test_migration_0008_fresh_and_v7_upgrade -q
→ FAILED (assert 12 == 10) — reproduces identically at base baf8009

PYTHONPATH=src py -3.13 -m pytest tests/test_retrieval_isolation.py::test_unresolved_project_default_memory_suppressed_and_global_policy_allowed -q
→ FAILED (assert INJECT == NO_INJECTION) — reproduces identically at base baf8009

PYTHONPATH=src py -3.13 -m pytest tests/test_decisions.py::test_fresh_migration_is_idempotent_and_preserves_decision -q
→ FAILED (missing 12 in expected list(range(1,12))) — reproduces identically at base baf8009
```
All three hardcode assumptions (schema v10, or a specific WRONG_PROJECT
fallthrough) that predate T1.5/T1.6's migrations 0011/0012; none reference
origin/authority code and none regressed by this change.

## Files touched

- `src/second_brain/migrations/0012_evidence_freshness.sql` — additive
  guarded `ALTER TABLE memories ADD COLUMN origin_class|origin_root_sha|
  authority_ceiling` (prior work, verified correct; migration number
  unchanged).
- `src/second_brain/db.py` — guarded-ALTER replay for pre-extension v12
  databases (prior work, verified correct, unmodified by this pass).
- `src/second_brain/semantic.py` — `ORIGIN_CLASSES`, `AUTHORITY_CEILINGS`,
  `_validate_origin`, `corroboration_count`, write-time binding in
  `add_memory`, lower-only ceiling transition in `curate` (prior work,
  verified correct, unmodified by this pass).
- `src/second_brain/cli.py` — `remember`/`memory add`/`memory curate`
  origin wiring (prior work, verified correct, unmodified by this pass).
- `src/second_brain/contracts.py` — **fixed**: restored the `UPDATE ...
  supersedes ...` line emission in `BrainPacket.render()` that had been
  accidentally deleted; `contradicts` field/rendering (prior work) retained.
- `src/second_brain/autoinject.py` — **fixed**: restored the missing
  `return out` in `_valid_candidates`; **fixed**: scoped policy-lane
  contradiction status to admitted peers only in `_build_items` so
  lower-authority contradictions render without withholding; lane plumbing
  through `RetrievalIntent`, `prepare_injection`, `_build_items`,
  `_render_packet_text`, `_fit_budget`, `_ids_only`, `BrainLifecycle.
  prepare_injection` (prior work, verified correct).
- `src/second_brain/ledger.py` — **added**: `origin_class="TOOL_OBSERVATION"`
  on the `extract_durable` writeback call site (closing the brief's exact
  mapping table; was previously unbound, falling back to the schema
  default).
- `tests/test_cli.py` — extended `test_remember_one_line_creates_memory_
  with_evidence` with `origin_class`/`authority_ceiling`/`origin_root_sha`
  assertions (remember/evidence coverage).
- `tests/test_origin_authority.py` — retained the three named tests; added
  `test_invalid_origin_class_and_ceiling_rejected`,
  `test_curate_can_only_lower_authority_ceiling`,
  `test_origin_columns_migrate_fresh_database`,
  `test_origin_columns_migrate_existing_0012_database` (fixed missing
  `memory_sources` table in its fixture; a real pre-existing-v12 database
  always has it since migration 0003 created it),
  `test_origin_columns_migration_is_idempotent`,
  `test_writeback_candidate_binds_model_inference`,
  `test_extract_durable_binds_tool_observation`,
  `test_policy_lane_renders_lower_authority_contradiction_without_
  withholding` — 11 tests total, all green.

## Schema / migration evidence

`PRAGMA table_info(memories)` after migration on a fresh database and after
replay on a simulated pre-extension v12 database both contain
`origin_class`, `origin_root_sha`, `authority_ceiling`
(`test_origin_columns_migrate_fresh_database`,
`test_origin_columns_migrate_existing_0012_database`). The latter also
asserts a pre-existing row survives non-destructively with the schema
defaults (`MODEL_INFERENCE` / `NULL` / `advisory`) rather than being
rewritten or dropped. `test_origin_columns_migration_is_idempotent` asserts
`db.migrate()` run twice returns `[]` on the second call (nothing re-applied,
no error) while the columns remain present.

## Concerns

- Two environment issues were pre-existing and outside this task's scope but
  were necessary to work around to run any tests at all: (1) the shared
  Python interpreter's editable `second-brain` install pointed at a sibling
  worktree (`v1-p4-canonical-integration`) rather than this one — worked
  around locally via `PYTHONPATH=src`, no shared state changed; (2)
  `hypothesis` (declared in `pyproject.toml`'s `dev` extra) was missing from
  the interpreter, installed it (additive, not a config/version change).
- Three pre-existing test failures remain in the repo, all confirmed (via
  `git stash` to base `baf8009`) to predate this task and to be unrelated to
  origin/authority: `test_autoinject.py::test_migration_0008_fresh_and_v7_
  upgrade`, `test_retrieval_isolation.py::test_unresolved_project_default_
  memory_suppressed_and_global_policy_allowed`,
  `test_decisions.py::test_fresh_migration_is_idempotent_and_preserves_
  decision`. Left untouched per scope (fixing them is not part of T1.7 and
  would expand the change beyond origin authority).
- The policy-lane contradiction-status fix (`_build_items` admitted-peer
  scoping) is a small, targeted addition to satisfy the brief's explicit
  "lower-authority contradictions render `contradicts: <id>` and are never
  promoted" requirement; it does not alter the pre-existing semantic-lane
  contradiction-withholding behavior, verified by the still-passing
  `test_contradiction_withheld_per_policy`.

### Post-review fix

Code review caught a real off-by-one bug in `contracts.BrainPacket.parse()`:
`lines[idx][12:]` sliced the `"contradicts: "` line one character short of
its 13-character prefix, so the first parsed id carried a leading space
(e.g. `" mem-abc"` instead of `"mem-abc"`), breaking round-trip fidelity for
any packet with a `contradicts` field. Fixed by using the same
`partition(": ")` idiom already used for every other field in that method.
Added `test_contradicts_renders_and_parses_without_leading_space` (2+ ids,
asserts no leading space and byte-identical `render()` round trip) to
`tests/test_contracts.py`, and extended the `_item()` test helper with a
`contradicts` parameter. Re-ran `tests/test_contracts.py`,
`tests/test_origin_authority.py`, `tests/test_autoinject.py` — all pass
except the one pre-existing `test_migration_0008_fresh_and_v7_upgrade`
failure noted above.
