# T1.2 Retrieval abstention gate — RED/GREEN report

## Scope
Implemented the T1.2 retrieval score metadata, score-gap abstention gate, persistent epoch-bound negative cache, lane floors, and SHADOW rollout behavior.

## RED evidence
Added and ran the required focused regressions before the implementation:

- `test_gate_uses_computed_score_not_fallback_constant`: failed with `INJECT` when `_rank_rows` was monkeypatched to return `_score=0.2`; this demonstrated the old hybrid fallback constant (`0.85`) bypassed computed scores.
- `test_negative_cache_invalidated_by_epoch_bump`: failed because a fresh retriever had no persisted negative cache and there was no memory epoch invalidation boundary.

The system Python did not provide pytest; the repository `.venv` was used for all subsequent focused runs.

## GREEN implementation

### Files and schema

- `src/second_brain/semantic.py`
  - `_rank_rows` now attaches every returned row's computed `_score` and preserves `_bm25` as explicit metadata (`None` when unavailable).
  - Added `RetrievalGate` and gate parsing in `load_retrieval_config`.
  - Calibrated `abs_floor`/`gap_min` values are accepted only when source, reason, version, and effective metadata are present and values are bounded.
- `src/second_brain/hybrid_retrieval.py`
  - Gate condition is `top1 >= max(abs_floor, lane_floor)` and, for multiple rows, `top1 - top2 >= gap_min`.
  - Missing score remains `None` and never passes the active gate; no score is coerced to a fallback constant or zero.
  - Exact-reference matches retain confidence/score `1.0`.
  - Added persistent `state/cache/negative.sqlite` table `negative_cache` with primary key exactly comprising `query_hash`, `project_id`, `lane`, `retrieval_config_version`, and `memory_epoch` (plus `created_at`).
  - Cache is persistent across retriever/process instances and old epochs are naturally ignored after mutation.
  - Infrastructure retrieval failures remain `BRAIN_UNAVAILABLE` and never populate the negative cache.
- `src/second_brain/db.py`
  - Added idempotent guarded `brain_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` initialization with `memory_epoch='0'`.
  - Added transactional epoch read/bump helpers. `migrate` initializes the control table without introducing a migration-number conflict.
- `src/second_brain/semantic.py` mutation transactions bump `memory_epoch` before commit for `add_memory`, `curate` (including archive status), `supersede`, and `reindex_all`.
- `src/second_brain/autoinject.py`
  - Active/canary low-confidence retrieval returns `NO_INJECTION(LOW_CONFIDENCE)` and records `decisions(kind='retrieval', propensity=1.0)` using privacy-safe hashes/metadata only.
- `config/retrieval.toml`
  - Added `[gate]` defaults: `abs_floor=0.55`, `gap_min=0.08`, rollout `SHADOW`.
  - Added lane floors: `policy=0.80`; `active_state`, `semantic`, `repo`, `decision`, `skill` all `0.55`, with calibration provenance metadata.
- `src/second_brain/cli.py` clears the persistent cache for the selected Brain home.
- Focused tests cover computed-score gate, epoch invalidation/persistence, missing score, policy lane floor, and existing vector/error behavior.

### Rollout semantics

The default `SHADOW` rollout preserves existing injection behavior: low-confidence observations continue through the existing injection path while score/gate metadata and retrieval telemetry are available. `ACTIVE`/`CANARY` enforce abstention. Exact references remain a confidence-1.0 short circuit. `BRAIN_UNAVAILABLE` remains the infrastructure-error reason and is not converted into a genuine negative result.

### Focused verification

- Required gate/cache/vector focused run: `4 passed`.
- Expanded focused semantic/autoinject/hybrid run: `42 passed`, with one pre-existing baseline discrepancy listed below.
- Additional missing-score and policy-lane boundary tests passed.
- Changed modules compiled with `python -m py_compile`.

Baseline discrepancy (not caused by T1.2): `tests/test_autoinject.py::test_migration_0008_fresh_and_v7_upgrade` expects schema version `10`, while the corrected T1.1 baseline already includes migration `0011_decisions` and reports version `11`. No migration was added by T1.2; the requested 0012 migration slot remains available to the sibling T1.4 work.

## Review follow-up

- Initialized the retriever's last-home state so a pre-retrieval cache clear is a safe no-op, preserving the previous API behavior.
- Wrapped persistent cache open/schema/read/write failures as `BRAIN_UNAVAILABLE`; infrastructure failures never populate the negative cache.
- Changed the cascade CLI threshold default to `None`, so configured lane floors are honored unless the user supplies an explicit override.
- Follow-up focused safety/gate run: `4 passed`.
