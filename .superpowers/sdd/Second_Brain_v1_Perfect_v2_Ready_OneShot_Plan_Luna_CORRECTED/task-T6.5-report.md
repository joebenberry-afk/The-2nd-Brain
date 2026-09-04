# T6.5 Task Report — Action cache dependency classes

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 399–406.

## Files

- `src/second_brain/action_cache.py`
- `src/second_brain/cli.py`
- `src/second_brain/telemetry.py`
- `tests/test_action_cache_deps.py` (new)
- `tests/test_action_cache.py`
- `tests/test_action_cache_safety_proof.py`
- `tests/test_cli.py`
- `tests/test_cleanup_t61.py`
- `tests/test_dogfood_token_economics.py`
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T6.5-report.md`

The existing test files outside `test_action_cache_deps.py` were changed only where their direct `ActionProof`, `store_action`, or `get_or_execute` usage had to declare the new dependency contract.

## Implemented contract

- Added persisted `DependencyClass` values `FILE_SET`, `WORKTREE`, `ENV`, `TIME`, and `PURE_CONSTANT`. `ActionProof.to_dict` writes the class and worktree/constant fields; `from_dict` accepts rows written before those fields existed.
- Enforced the action-type completeness table before storage. Direct incomplete stores fail closed. `get_or_execute` still performs the requested computation for incomplete or unverifiable proofs, but skips lookup/storage.
- `PURE_VERIFICATION` proofs include the package runtime version as the reserved ENV dependency `second_brain.runtime_version` in addition to a caller-declared dependency. `DISTILLATION` requires a source artifact SHA and current distiller version. `GENERIC_PURE` requires a non-empty caller-declared `PURE_CONSTANT` fingerprint.
- Added `worktree_fingerprint_for`: it discovers the Git repository root, validates a repository-relative non-escaping scope, and hashes canonical JSON containing `HEAD^{tree}`, `git write-tree`, the raw scoped binary diff hash, and sorted scoped untracked `(repository-relative path, bytes sha256)` pairs. Git/path/read failures return no fingerprint; invalid escaping scopes are rejected.
- WORKTREE validation recomputes the same scope. `get_or_execute` validates before computation and again afterward for every dependency class. The public `put(..., fingerprint_before=...)` boundary also recomputes the declared proof immediately before persistence and requires the current WORKTREE fingerprint to equal `fingerprint_before`; missing/mismatched fingerprints skip storage. Both mutation paths emit `cache_store_skipped_inputs_changed`.
- Added idempotent `action_cache_economics` table and class/key indexes. Every lookup path records validation time, files/bytes hashed, token savings, and available miss/avoided-compute timing. Existing top-level statistics fields are unchanged; `economics_by_dependency_class` adds grouped samples, averages, byte/file totals, token savings, and `RETIRE_CANDIDATE` only when a hit has a paired avoided-compute sample and average hit validation is more expensive.
- Restored CLI code-search replay with a scoped WORKTREE proof. Stable worktrees hit; staged, unstaged, and in-scope untracked changes alter or invalidate the proof. When Git fingerprinting is unavailable, the CLI computes directly and never stores.

## Focused verification

Project venv commands were run with `PYTHONHOME` and inherited `PYTHONPATH` removed, then `PYTHONPATH=src` set.

```text
.venv/Scripts/python.exe -m pytest tests/test_action_cache_deps.py tests/test_action_cache.py tests/test_action_cache_safety_proof.py -q
31 passed

.venv/Scripts/python.exe -m pytest tests/test_cli.py -q -k action_cache
2 passed

.venv/Scripts/python.exe -m pytest tests/test_cleanup_t61.py tests/test_dogfood_token_economics.py -q -k 'action_cache or multi_turn_dogfood_session'
3 passed
```

Post-review direct-`put` boundary proof:

```text
.venv/Scripts/python.exe -m pytest tests/test_action_cache_deps.py -q
11 passed

.venv/Scripts/python.exe -m pytest tests/test_action_cache.py tests/test_cleanup_t61.py -q -k 'ArtifactRefs or action_cache_lru'
5 passed
```

The acceptance coverage includes the six named adversarial tests, a non-vacuous direct-`put` mutation between output computation and persistence, and focused completeness, telemetry, economics, scope rejection, backward deserialization, schema reopen/idempotency, and existing public-`put` caller coverage. No full suite, Ruff, or Pyright run was performed.

## Migration and rollback

The action-cache SQLite database expands in place with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. Opening a fresh database, reopening it, or opening a database with existing `action_cache` rows is idempotent and does not delete or rewrite those rows. Legacy proof JSON remains deserializable; because it lacks an explicit dependency class, it is conservatively non-replayable and is invalidated only if queried.

Rollback is code-revert safe: older code ignores the additive economics table and indexes. They may remain in place without affecting old readers; dropping them is optional and would discard only derived economics observations, not cached entries or canonical data.

## Commit

Exact commit message: `brain(core): action cache dependency classes`.

The commit hash is not available inside the report-containing commit before that commit is created; it is reported by the committing command/output.
