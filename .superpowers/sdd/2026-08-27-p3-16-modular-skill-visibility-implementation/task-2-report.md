# Task 2 Report: `omp_adapter.py` skill-visibility operation

## Status
Complete. All acceptance criteria met; committed.

## Files changed
- `src/second_brain/omp_adapter.py`
  - Added `skills` to the module-level `from . import ...` line (alphabetical order preserved).
  - Added `_prepare_skill_visibility(home, payload)`: validates `task` (returns `NO_TASK` if empty), calls `skills.build_plan(home, task, session_id=..., project_id=...)`, then `skills.hydrate_plan(home, plan)`, and returns `{"visibility_plan": skills.plan_to_evidence(plan), "hydrated_instructions": hydrated_bodies, "error": None}`.
  - Added a `skill_visibility` branch in `handle_request`, placed immediately after the existing `worker_context` branch's exception handling and before the model-routing fallthrough. It calls `_prepare_skill_visibility` via `skills.build_plan`/`skills.hydrate_plan` (module-attribute access, matching the `from . import skills` style so `monkeypatch.setattr("second_brain.skills.build_plan", ...)` takes effect) and fails open to `{"visibility_plan": None, "hydrated_instructions": {}, "error": "VISIBILITY_UNAVAILABLE"}` on any exception.
  - Both new blocks exactly match the brief's specified code, with the one exception-handler return dict reformatted across multiple lines to satisfy the 100-char ruff line-length limit (no logic change).
- `tests/test_omp_adapter.py`
  - Appended the three tests from the brief verbatim: `test_omp_adapter_skill_visibility_returns_bounded_plan`, `test_omp_adapter_skill_visibility_fails_open_on_error`, `test_omp_adapter_skill_visibility_requires_task`.
  - **One deviation from the brief's literal test text** (see Concerns below): changed the assertion `assert "task" not in str(response["visibility_plan"])` to `assert "demo-skill trigger phrase" not in str(response["visibility_plan"])` in `test_omp_adapter_skill_visibility_returns_bounded_plan`.

## Tests
- Step 2 (pre-implementation): `pytest tests/test_omp_adapter.py -k skill_visibility -q` → 3 failed with `KeyError: 'visibility_plan'`, confirming the tests exercised not-yet-existing behavior.
- Step 4 (post-implementation): `pytest tests/test_omp_adapter.py -q` → **10 passed** (7 pre-existing + 3 new), no regressions.
- Step 5 static checks: `ruff check`, `ruff format --check`, `pyright` on both files → all pass (0 errors/warnings).

## Commit
`f0abb30` — `feat(omp-adapter): add skill_visibility operation` (2 files changed, 458 insertions; both files were previously untracked in git, so this is their first commit).

## Concerns

1. **Brief's literal test assertion was unsatisfiable against Task 1's committed design; I fixed the test rather than working around it.** `skills.build_plan` (already committed, out of scope for me to change) intentionally includes a `task_hash` field in the plan — `sha256(task)`, explicitly documented in the Task 1 brief as "task text itself never stored." The brief's Step 1 test text asserts `"task" not in str(response["visibility_plan"])`, but that's a substring check, and the key name `task_hash` itself contains the substring `"task"` — so the check fails purely because of the field's *name*, regardless of privacy correctness. The evident intent (per Task 1's own docs) is "the raw task text must not leak into the plan," which the implementation already satisfies via hashing. I changed the assertion to check for the literal raw task string (`"demo-skill trigger phrase"`) instead of the substring `"task"`, which tests the real intended property and passes. I did not touch `skills.py` per the constraint. Flagging this for whoever reviews Task 2 in case the original literal assertion was intentional for a reason I'm not seeing.
2. **Pre-existing ruff-format debt in both files, unrelated to my additions**, was blocking Step 5's `ruff format --check` (module-docstring blank-line spacing, a list-literal wrap style in `_candidates`, a multi-line `assert ... in (...)` wrap, and a couple of blank-line-count issues in `test_omp_adapter.py`, plus a long-line test wrap around the `for title in (...)` tuple in the new visibility test). These predate my edits (confirmed via `git stash`, though since both files are git-untracked the stash didn't actually revert them — I could not get a clean pre-my-edit ruff-format baseline via git). Since the brief requires `ruff format --check` to pass before commit and these were whitespace-only, I ran `ruff format` (not just `--check`) on both files to bring them into compliance. This reformatted a few pre-existing lines outside the sections I authored (e.g. `_candidates`'s return-list wrap, an existing `assert ... in (...)` wrap in an unrelated worker_context test, and blank-line normalization between existing test functions). No logic changed — verified by rerunning the full `pytest tests/test_omp_adapter.py -q` (still 10/10 green) after formatting.
3. Both `src/second_brain/omp_adapter.py` and `tests/test_omp_adapter.py` were git-untracked before this task (not part of any prior commit despite already containing 7 passing tests and working `worker_context`/model-routing code) — this commit is their first appearance in git history. This is expected/pre-existing repo state, not something introduced by Task 2.
4. Did not touch `skills.py`, `router.py`, `gardener.py`, or any P3.15 code, and did not begin P3.17, per the brief's constraints.
