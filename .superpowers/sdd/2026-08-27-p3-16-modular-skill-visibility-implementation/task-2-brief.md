# Task 2: `omp_adapter.py` skill-visibility operation

Task 1 is complete and committed (`src/second_brain/skills.py` exists with `build_plan`, `hydrate_plan`, `plan_to_evidence`, `resolve_visibility_mode`, `eligible_skills`, `descriptors` — read that file directly for exact signatures rather than assuming). Do not modify `skills.py`, `router.py`, `gardener.py`, or any P3.15 code. Do not begin P3.17. Skip formatters/linters/project-wide suites beyond the commands below.

**Files:**
- Modify: `src/second_brain/omp_adapter.py`
- Modify: `tests/test_omp_adapter.py`

**Interfaces:**
- Consumes (from Task 1, already implemented — read `src/second_brain/skills.py` directly): `skills.build_plan(home, task, *, session_id, project_id, max_active=None, mode=None) -> dict`, `skills.hydrate_plan(home, plan) -> tuple[dict, dict[str, str]]`, `skills.plan_to_evidence(plan) -> dict`.
- Produces: `omp_adapter.handle_request(home, {"operation": "skill_visibility", "task": str, "host_session_id": str, "project_id": str, ...})` returns `{"visibility_plan": <plan_to_evidence(plan) dict> | None, "hydrated_instructions": {skill_id: str} | {}, "error": str | None}`.

## Step 1: Write the failing tests

Append to `tests/test_omp_adapter.py`:

```python
def test_omp_adapter_skill_visibility_returns_bounded_plan(tmp_path):
    from second_brain import paths

    directory = tmp_path / paths.SKILL_LEVEL_DIRS["shadow"] / "demo-skill"
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- content"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output", "References",
        )
    )
    (directory / "SKILL.md").write_text(
        f"---\nname: demo-skill\nstatus: shadow\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    response = omp_adapter.handle_request(
        tmp_path,
        {
            "operation": "skill_visibility",
            "task": "demo-skill trigger phrase",
            "host_session_id": "omp-session-1",
            "project_id": "proj",
        },
    )
    assert response["visibility_plan"] is not None
    assert response["visibility_plan"]["mode"] == "shadow"
    assert "task" not in str(response["visibility_plan"])
    assert isinstance(response["hydrated_instructions"], dict)


def test_omp_adapter_skill_visibility_fails_open_on_error(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr("second_brain.skills.build_plan", _boom)
    response = omp_adapter.handle_request(
        tmp_path,
        {"operation": "skill_visibility", "task": "x", "host_session_id": "s", "project_id": "p"},
    )
    assert response["visibility_plan"] is None
    assert response["error"] == "VISIBILITY_UNAVAILABLE"


def test_omp_adapter_skill_visibility_requires_task(tmp_path):
    response = omp_adapter.handle_request(
        tmp_path,
        {"operation": "skill_visibility", "host_session_id": "s", "project_id": "p"},
    )
    assert response["visibility_plan"] is None
    assert response["error"] == "NO_TASK"
```

Note: `monkeypatch.setattr("second_brain.skills.build_plan", _boom)` only takes effect if `omp_adapter.py`'s new code calls `skills.build_plan(...)` via a module-level `from . import skills` import (module-attribute access at call time) — matching Task 1's own import-style requirement. Do not `from .skills import build_plan`.

## Step 2: Run tests to verify they fail

Run: `.venv/Scripts/python.exe -m pytest tests/test_omp_adapter.py -k skill_visibility -q`
Expected: FAIL (no `skill_visibility` branch yet).

## Step 3: Implement the branch

In `src/second_brain/omp_adapter.py`, add `skills` to the existing `from . import contracts, ledger, model_routing, worker_protocol, working_set` import line (result: `from . import contracts, ledger, model_routing, skills, worker_protocol, working_set` — keep alphabetical order matching the existing style). Add a new private function:

```python
def _prepare_skill_visibility(home: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    task = _text(payload.get("task"), _MAX_TASK_CHARS)
    if not task:
        return {"visibility_plan": None, "hydrated_instructions": {}, "error": "NO_TASK"}
    session_id = _text(payload.get("host_session_id") or payload.get("session_id"))
    project_id = _text(payload.get("project_id"))
    plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
    plan, hydrated_bodies = skills.hydrate_plan(home, plan)
    return {
        "visibility_plan": skills.plan_to_evidence(plan),
        "hydrated_instructions": hydrated_bodies,
        "error": None,
    }
```

In `handle_request`, add this branch immediately after the existing `if payload.get("operation") == "worker_context":` branch's `except` handling (before the `task = _text(...)` fallthrough that assumes model routing):

```python
    if payload.get("operation") == "skill_visibility":
        try:
            return _prepare_skill_visibility(Path(home), payload)
        except Exception:
            return {"visibility_plan": None, "hydrated_instructions": {}, "error": "VISIBILITY_UNAVAILABLE"}
```

## Step 4: Run tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_omp_adapter.py -q`
Expected: PASS, all tests green (including the pre-existing ones — no regression).

## Step 5: Static checks and commit

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/omp_adapter.py tests/test_omp_adapter.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/omp_adapter.py tests/test_omp_adapter.py && .venv/Scripts/python.exe -m pyright src/second_brain/omp_adapter.py tests/test_omp_adapter.py`

```bash
git add -- src/second_brain/omp_adapter.py tests/test_omp_adapter.py
git commit -m "feat(omp-adapter): add skill_visibility operation"
```

## Report

Write your full report to `.superpowers/sdd/2026-08-27-p3-16-modular-skill-visibility-implementation/task-2-report.md` with status/files/tests/commit/concerns. Return the same short summary as your final message.
