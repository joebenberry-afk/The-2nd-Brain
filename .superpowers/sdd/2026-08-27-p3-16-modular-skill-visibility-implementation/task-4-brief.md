# Task 4: `hermes_adapter.py` visibility integration

Tasks 1-3 are complete and committed: `src/second_brain/skills.py`, the `omp_adapter.py` `skill_visibility` operation, and the OMP Prime-extension bridge all exist. Do not modify `skills.py`, `router.py`, `gardener.py`, or `omp_adapter.py`. Do not begin P3.17. Skip formatters/linters/project-wide suites beyond the commands below.

**Important test-convention correction:** `tests/test_hermes_adapter.py` does NOT call `hermes_adapter._handle_pre_llm` directly. It runs full subprocess integration tests through the real CLI bridge via a helper `_run_hook(home, payload) -> subprocess.CompletedProcess[str]` (spawns `python -m second_brain --home <home> autoinject hermes-hook` with the JSON payload on stdin, returns parsed JSON from stdout). Read `tests/test_hermes_adapter.py` lines 1-280 directly first — especially `_start_payload`, `_router_skill`, `_ledger_rows`, `_run_hook`, and the existing test `test_pre_llm_routes_existing_skill_and_preserves_bounded_injection` — and write your new tests in that exact same subprocess-integration style. Do not invent a different, more unit-test-like calling convention.

**Files:**
- Modify: `src/second_brain/hermes_adapter.py`
- Modify: `tests/test_hermes_adapter.py`

**Interfaces:**
- Consumes (from Task 1, already implemented — read `src/second_brain/skills.py` directly for exact signatures): `skills.build_plan(home, task, *, session_id, project_id, max_active=None, mode=None) -> dict`, `skills.hydrate_plan(home, plan) -> tuple[dict, dict[str, str]]`, `skills.plan_to_evidence(plan) -> dict`.
- Produces: `_handle_pre_llm`'s existing response dict (and the `hermes-hook` CLI's JSON stdout, which is that same dict) gains `"visibility_plan": <bounded dict> | None` alongside the existing `"selected_routes"` field; when `visibility_plan.get("mode") == "enforced"` and hydration produced at least one body, the existing `packet` field is extended with the hydrated specialist text.

## Step 1: Read the current `_handle_pre_llm` implementation

Read `src/second_brain/hermes_adapter.py` in full around `_route_task` and `_handle_pre_llm` (search for both names) before editing. Confirm the exact current local variable name that holds the packet ultimately returned as `"packet"` in the response dict (it was `visible_packet` as of the last read during design, but re-confirm against the live file — earlier tasks did not touch this function, but confirm before writing your edit). Also confirm the two exact locations where `"selected_routes": selected_routes,` currently appears (the `event_payload` dict built for telemetry, and the function's final returned response dict) — you will add a `"visibility_plan"` entry immediately alongside each.

## Step 2: Write the failing tests

Add to `tests/test_hermes_adapter.py`, following the exact style of `test_pre_llm_routes_existing_skill_and_preserves_bounded_injection` (reuse `_current_memory`, `_start_payload`, `_run_hook`, `_ledger_rows`; do not redefine these helpers):

```python
def _visibility_skill(home: Path, name: str = "demo-visibility-skill") -> None:
    skill_dir = home / "skills" / "shadow" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {name} content"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output", "References",
        )
    )
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: shadow\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )


def test_pre_llm_shadow_mode_never_injects_hydrated_skill(brain_home: Path) -> None:
    _current_memory(brain_home)
    _visibility_skill(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-shadow", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "demo-visibility-skill content trigger",
        "turn_id": "visibility-shadow-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is not None
    assert out["visibility_plan"]["mode"] == "shadow"
    assert "demo-visibility-skill content" not in out["packet"]


def test_pre_llm_enforced_mode_injects_hydrated_skill(brain_home: Path) -> None:
    _current_memory(brain_home)
    _visibility_skill(brain_home, name="enforced-visibility-skill")
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "enforced"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-enforced", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "enforced-visibility-skill content trigger",
        "turn_id": "visibility-enforced-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is not None
    assert out["visibility_plan"]["mode"] == "enforced"
    assert "enforced-visibility-skill content" in out["packet"]


def test_pre_llm_visibility_failure_does_not_break_existing_autoinject_path(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-failure", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "How does Hermes retrieve bounded project context?",
        "turn_id": "visibility-failure-turn-1",
    }
    # Break skills.build_plan repo-wide via a malformed config/skills.toml so
    # resolve_visibility_mode's own TOML parse fails (a real, reachable
    # failure mode, exercised through the actual subprocess rather than a
    # monkeypatch that a fresh subprocess would not see).
    (brain_home / "config" / "skills.toml").write_text("not valid toml [[[", encoding="utf-8")

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    assert "Hermes integration rule" in out["packet"]
```

Note: `monkeypatch` is imported and used elsewhere in this file (see `test_pre_llm_authority_failure_fails_open_without_false_success`) but the third test above deliberately avoids it in favor of a real malformed-config failure, since `_run_hook` spawns a fresh subprocess that would not see an in-process monkeypatch. If you find `resolve_visibility_mode`'s malformed-TOML handling does NOT actually raise (Task 1 built it to fail safe to `"shadow"`, not raise), adjust this third test to break the failure path in ANY reachable, real way (e.g., make the skills directory unreadable, or omit `config/skills.toml` entirely while some other real fault is injected) — read `src/second_brain/skills.py` directly to find a genuinely reachable failure and adjust the test accordingly; do not delete the test's intent (visibility failure must not break the existing AutoInject packet path).

## Step 3: Run tests to verify they fail

Run: `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -k visibility -q`
Expected: FAIL (no visibility fields yet).

## Step 4: Implement

Add `skills` to the existing `from . import (...)` import block in `hermes_adapter.py` (alphabetical order, matching the existing style: `artifacts, autoinject, contracts, firewall, ledger, model_routing, router, skills, vmem, worker_protocol` — adjust to match whatever the actual current import list is).

Add a private helper mirroring `_route_task`'s exact fail-open shape:

```python
def _visibility_task(
    home: Path, task: str, session_id: str, project_id: str
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Run the visibility plan without owning routing state. Advisory/shadow
    by default; only 'enforced' mode may extend the returned packet."""
    try:
        plan = skills.build_plan(home, task, session_id=session_id, project_id=project_id)
        plan, hydrated_bodies = skills.hydrate_plan(home, plan)
        return skills.plan_to_evidence(plan), hydrated_bodies
    except Exception:
        return None, {}
```

In `_handle_pre_llm`, immediately after the existing `selected_routes, routing_error = _route_task(home, task) if task else ([], False)` line, add:

```python
    visibility_plan, hydrated_bodies = (
        _visibility_task(home, task, binding.host_session_id, binding.project_id)
        if task
        else (None, {})
    )
```

Locate the exact point later in the function where the packet variable (confirmed in Step 1) is computed from `autoinject.render_packet(decision)` and `mode in {"advisory", "active"}`. Immediately after that computation, add (using the actual confirmed variable name in place of `visible_packet` if it differs):

```python
    if visibility_plan is not None and visibility_plan.get("mode") == "enforced" and hydrated_bodies:
        specialist_text = "\n\n".join(hydrated_bodies[skill_id] for skill_id in sorted(hydrated_bodies))
        if visible_packet:
            visible_packet = f"{visible_packet}\n\n{specialist_text}"
        else:
            visible_packet = specialist_text
```

Add `"visibility_plan": visibility_plan,` to both the `event_payload` dict (bounded — `plan_to_evidence` already stripped anything unsafe) and the function's final returned response dict, alongside each existing `"selected_routes": selected_routes,` entry (both places it currently appears, confirmed in Step 1).

## Step 5: Run tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -q`
Expected: PASS, all tests green, no regression in pre-existing tests (this file is large and slow — a full run may take a few minutes since every test spawns a real subprocess; that is expected and matches this file's existing cost profile).

## Step 6: Static checks and commit

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py && .venv/Scripts/python.exe -m pyright src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py`

```bash
git add -- src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py
git commit -m "feat(hermes-adapter): fold visibility plan into pre-llm response"
```

## Report

Write your full report to `.superpowers/sdd/2026-08-27-p3-16-modular-skill-visibility-implementation/task-4-report.md` with status/files/tests/commit/concerns. Return the same short summary as your final message. If the confirmed variable name, import list, or packet-computation location differs materially from what this brief assumes, adapt to the REAL current code and note the difference in your report's concerns — do not block on it, this brief's job is to describe intent precisely, not to be byte-exact against a file you must re-read.
