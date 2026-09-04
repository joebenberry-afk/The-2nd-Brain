# T7.1 Task Report — Earned Memory / Friction Gate

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 455–485.

## Files

- `src/second_brain/semantic.py`
- `src/second_brain/migrations/0019_earned_memory.sql`
- `tests/test_earned_memory.py` (new)
- `scripts/run_earned_memory_replay.py` (new)
- `outputs/reports/v2/earned-memory/replay-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.1-report.md` (new)

## Implemented contract

1. **Exact Trigger Vocabulary**:
   Defined `CandidateTrigger` StrEnum in `semantic.py` with the exact seven required triggers:
   `CORRECTION`, `REGRESSION`, `REPETITION`, `SUBTLETY`, `SEVERITY`, `INDEPENDENT_EVIDENCE`, `CROSS_SESSION_REUSE`.
   Sorted and validated via `CANDIDATE_TRIGGERS`.

2. **Deterministic Trigger & Provenance Extraction**:
   Implemented `_extract_candidate_evidence(events: list[object]) -> tuple[tuple[str, ...], tuple[str, ...]]`:
   - Normalizes ledger events and hash-bound telemetry records.
   - Extracts triggers only from verifiable evidence (e.g. `regression_verified=True`, `result_corrected` with artifact SHA, `occurrence_count >= 2` with bound evidence, severity with critical impact and bound SHA, independent verification PASS, repeated verified failures across sessions).
   - Free-form model confidence or speculation never generates triggers.
   - Collects exact, bounded source event references (`source_event_refs`).

3. **Admission Decision Recording**:
   Every evaluation records an admission decision via `decisions.record(..., kind="admission", stage="SHADOW", ...)`:
   - When friction triggers are absent: outcome is `"no_candidate"`, no candidate is created.
   - When friction triggers are present: outcome is `"candidate_shadowed"`, candidate row created.

4. **Separate Candidate Storage (`v2_candidates`)**:
   Migration `0019_earned_memory.sql` creates the T7.0-retained table `v2_candidates` with:
   `candidate_id`, `title`, `body`, `scope`, `project_id`, `lifecycle_state` (`candidate`), `trigger_set_json`, `source_event_refs_json`, `origin_class`, `origin_root_sha`, `authority_ceiling`, `confidence`, `rollout_stage` (`SHADOW`), `decision_ref`, `created_at`, `updated_at`.
   Candidates are stored separately from active memories, ensuring zero leakage into active retrieval or injection.

5. **Strict Origin Authority Ceiling**:
   Enforces T1.7 origin authority ceiling via `_validate_origin`:
   - `MODEL_INFERENCE` ceiling is strictly `advisory` (confidence `low`).
   - `USER_AUTHORED`, `LOCAL_REPO`, `TRUSTED_TEST` ceiling is `project_rule` (confidence `medium`).
   - Neither model inference nor trusted tests can silently escalate to active `policy`.

6. **Idempotent Merge & Replay**:
   Submitting identical or overlapping candidates for the same identity merges trigger sets and source event refs idempotently up to bounded limits, updating `decision_ref` without creating duplicate candidate rows.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_earned_memory.py -q
8 passed

.venv/Scripts/python.exe -m pytest tests/test_semantic.py tests/test_decisions.py -q
24 passed

.venv/Scripts/python.exe -m pytest tests/test_doctor.py -q
9 passed
```

Named tests verified:
- `test_no_friction_signal_creates_no_candidate`: PASS (no triggers -> no candidate created, decision recorded)
- `test_repeated_verified_failure_creates_candidate`: PASS (verified failure across sessions creates candidate with REPETITION trigger)
- `test_model_inference_candidate_stays_advisory`: PASS (origin MODEL_INFERENCE retains advisory authority ceiling)
- `test_candidate_records_source_event_refs`: PASS (exact telemetry/ledger refs persisted in candidate record)

## Cheapest real experiment

Script `scripts/run_earned_memory_replay.py` replayed a bounded set of 8 real sessions (including RC4 Prime pilot bundle, v1-p4 stale state tool reads, v1-p4 compaction, verified regressions, verified corrections, repeated failures, subtle findings, and unverified model speculation):

- **Gate OFF (Unconditional Capture)**:
  - Candidates created: 8
  - False positives: 4/8 (50.0% false-positive rate)
- **Gate ON (Earned Memory Friction Gate)**:
  - Candidates created: 4
  - False positives: 0/4 (0.0% false-positive rate)
  - False positive reduction: 100.0%
  - Provenance compliance: 1.0 (100% of candidates have trigger set, source event refs, decision ref, advisory ceiling, SHADOW stage)
  - Active memory leakage: 0 (zero candidates written to active semantic memory)

Artifact saved: `outputs/reports/v2/earned-memory/replay-experiment.json`.

## Migration and rollback

Migration `0019_earned_memory.sql` uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
Fresh migration, reopen, and repeat migration verified idempotent (`db.migrate()` returns `[]` on second run).
Rollback is safe: older readers ignore `v2_candidates`. Dropping the table is optional on revert and destroys only candidate proposals, not active memory or canonical ledger data.

## Commit

Commit message: `brain(memory): earned memory friction gate`.
