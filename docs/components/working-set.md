# Working Set (Active State Capsule, Requirement & Read Ledgers)

## Purpose
Per-session operational state so a fresh agent resumes exactly where the previous one stopped (plan §17-18, §73, §100; Phase 4).

## Problem it solves
Long sessions get compacted/replaced; without durable state, objectives, requirements, and evidence are lost.

## Responsibilities
- `session_dir`: validates `^[A-Za-z0-9._-]{1,64}$` (rejects `.`/`..`) → `state/sessions/<id>/`.
- Capsule (`active-state.json`): `init_capsule` (fails if exists), `update_capsule` (partial merge, enum/type-validated, `updated_at` auto, atomic tmp+replace), `show_capsule`. Fields: objective, task_mode (9), risk (4), 8 list-of-str fields, verification dict, next_action, brain_refs, artifact_refs.
- Requirements (`requirements.json`): `add_requirement` (auto REQ-001.. gap-free, duplicate text rejected, importances 4), `add_evidence`, `set_requirement_status` (5 statuses), `check_requirements` (material = importance in {critical,high} and status not in {verified,not_applicable} → blocks completion), `show_requirements`.
- Read ledger (`read-ledger.json`): `record_read` (path as given, sha256 or null, range, purpose, turn, artifact, ts), `show_reads` (append-only).

## Non-responsibilities
No pruning/consolidation (advisory/shadow start); stores state, not file contents or memories.

## Inputs
`home`, validated session_id, fields/statuses/read records.

## Outputs
Three schema-validated JSON files per session; material-requirement check dicts.

## State ownership
`state/sessions/<session-id>/` (created on demand).

## Invariants
JSON always schema-valid or write refused; corrupt files → BrainError naming path; atomic writes; unique req ids; evidence append-only; material unverified blocks completion.

## Interactions
`brainctl capsule/requirements/read-ledger`; JIT compiler reads all three files; Phase 7 intent verifier consumes ledger.

## Failure behavior
Unknown fields/enums, duplicates, unknown req ids, invalid session ids, double init, corrupt JSON → BrainError.

## Verification
`tests/test_working_set.py` (35) incl. 3 Hypothesis properties: random updates round-trip; random requirement sequences keep ids unique + evidence append-only; session-id accept-or-raise only.

## Known limitations
Checkpoint-only updates (no per-token); no cross-session sharing; unbounded lists.

## Future extension
Phase 7 ledger enforcement/risk controller; session_before_compact hooks; tool/routing ledgers (context.toml).

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #5 (material = critical/high unverified), #2.

## Relevant tests
`tests/test_working_set.py`, `tests/test_cli.py`.
