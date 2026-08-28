# Task 1: `skills.py` harness-neutral visibility core

Read the approved design first at `docs/superpowers/specs/2026-08-27-p3-16-modular-skill-visibility-design.md`. Approved design is locked; do not mutate lifecycle/state, add a registry, or begin P3.17. Skip formatters, linters, or project-wide test suites; run only the focused commands named below.

**Files:**
- Create: `src/second_brain/skills.py`
- Create: `tests/test_skills.py`
- Modify: `config/skills.toml` (add `[visibility] mode = "shadow"` documented key, following the exact comment style already used for `[router] max_active`)

**Interfaces:**
- Consumes: `router.route(home, task, max_active=None) -> {"selected": list[str], "scores": dict[str, float], "shadow": True}` (existing, unchanged). `skillforge.read_metadata(path) -> dict[str, str]`. `skillforge.lifecycle_content_hash(path) -> str`. `paths.SKILL_LEVEL_DIRS: dict[str, str]` (keys `"active"`, `"candidate"`, `"shadow"`). `autoinject.token_estimate(text: str) -> int`.
- Produces (consumed by Task 2 and Task 4):
  - `skills.eligible_skills(home: Path) -> list[dict]` — each dict: `{"skill_id": str, "lifecycle_state": str, "content_hash": str | None, "path": Path}`.
  - `skills.descriptors(home: Path) -> dict[str, dict]` — keyed by `skill_id`, each value: `{"lifecycle_state": str, "content_hash": str | None, "descriptor_text": str, "descriptor_ref": str}`.
  - `skills.build_plan(home: Path, task: str, *, session_id: str, project_id: str, max_active: int | None = None, mode: str | None = None) -> dict` — the canonical `VisibilityPlan` dict (fields below).
  - `skills.hydrate_plan(home: Path, plan: dict) -> tuple[dict, dict[str, str]]` — returns `(updated_plan, hydrated_bodies)` where `updated_plan` has `hydrated_skill_ids`/`unavailable_skill_ids` finalized and `hydrated_bodies` maps `skill_id -> full SKILL.md text` (selected+eligible+hash-matched only).
  - `skills.plan_to_evidence(plan: dict) -> dict` — identity function that strips nothing extra (the plan dict itself is already bounded/JSON-safe by construction) but is the named, stable entry point adapters call before passing to telemetry — exists so Tasks 2/4 have one documented "safe to log" boundary.
  - `skills.resolve_visibility_mode(home: Path) -> str` — reads `config/skills.toml [visibility] mode`, same `tomllib`-read-with-fallback pattern as `router._router_max_active`, returns `"shadow"` on any missing/invalid/non-string/unrecognized value, `"enforced"` only for the exact string `"enforced"`.

## Canonical `VisibilityPlan` fields (per accepted instruction)

```
visibility_plan_id        sha256("{task}|{session_id}|{project_id}|{sorted(selected)}")[:16], prefixed "vplan-"
task_hash                 sha256(task) — task text itself never stored
session_id / project_id   as given
router_decision_hash      sha256(canonical_json({"selected": selected, "scores": scores}))
eligible_skill_ids        sorted names from eligible_skills(home)
descriptor_refs           {skill_id: descriptor_ref} for every eligible skill
selected_skill_ids        router's selected list, re-capped at max_active (0–3)
hydrated_skill_ids        subset of selected_skill_ids that passed revalidation + hydration
rejected_skill_ids        {skill_id: reason} — stale / retired / hidden / unknown / duplicate-collapsed
unavailable_skill_ids     {skill_id: reason} — selected + eligible but hydration read failed
mode                      "shadow" | "enforced"
descriptor_chars / descriptor_tokens     summed over ALL eligible descriptors
hydrated_chars / hydrated_tokens         summed over hydrated bodies only
avoided_full_chars / avoided_full_tokens summed over eligible-but-NOT-hydrated full bodies
created_at                 UTC ISO-8601
```

## Step 1: Write the failing tests

```python
# tests/test_skills.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import paths, skillforge, skills


def _make_skill(home: Path, name: str, level: str, purpose: str = "Handles X.") -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n{purpose if title == 'Purpose' else '- content'}"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output", "References",
        )
    )
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory


def test_eligible_skills_scans_active_candidate_shadow_only(brain_home):
    _make_skill(brain_home, "a", "active")
    _make_skill(brain_home, "c", "candidate")
    _make_skill(brain_home, "s", "shadow")
    result = {item["skill_id"]: item for item in skills.eligible_skills(brain_home)}
    assert set(result) == {"a", "c", "s"}
    assert result["a"]["lifecycle_state"] == "active"
    assert result["a"]["content_hash"] is not None


def test_descriptors_are_bounded_and_exclude_other_sections(brain_home):
    _make_skill(brain_home, "one", "active", purpose="Secret internal detail. " * 50)
    described = skills.descriptors(brain_home)["one"]
    assert len(described["descriptor_text"]) <= 400
    assert "Tools" not in described["descriptor_text"]
    assert len(described["descriptor_ref"]) == 16


def test_build_plan_selects_and_caps_at_three(brain_home, monkeypatch):
    for name in ("a", "b", "c", "d"):
        _make_skill(brain_home, name, "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "b", "c", "d"], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert len(plan["selected_skill_ids"]) == 3
    assert "d" in plan["rejected_skill_ids"]
    assert plan["rejected_skill_ids"]["d"] == "over_cap"


def test_build_plan_zero_selection_is_legitimate(brain_home, monkeypatch):
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": [], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert plan["selected_skill_ids"] == []


def test_build_plan_rejects_unknown_and_duplicate_selection(brain_home, monkeypatch):
    _make_skill(brain_home, "a", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["a", "a", "ghost"], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    assert plan["selected_skill_ids"] == ["a"]
    assert plan["rejected_skill_ids"]["ghost"] == "not_eligible"


def test_hydrate_plan_rejects_stale_content_hash(brain_home, monkeypatch):
    directory = _make_skill(brain_home, "stale", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["stale"], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    (directory / "SKILL.md").write_text(
        (directory / "SKILL.md").read_text(encoding="utf-8").replace("Handles X.", "Changed."),
        encoding="utf-8",
    )
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert "stale" not in updated["hydrated_skill_ids"]
    assert updated["unavailable_skill_ids"]["stale"] == "stale_content_hash"
    assert bodies == {}


def test_hydrate_plan_hydrates_selected_only(brain_home, monkeypatch):
    _make_skill(brain_home, "picked", "shadow")
    _make_skill(brain_home, "not-picked", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["picked"], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    updated, bodies = skills.hydrate_plan(brain_home, plan)
    assert updated["hydrated_skill_ids"] == ["picked"]
    assert set(bodies) == {"picked"}
    assert "not-picked" not in bodies


def test_plan_to_evidence_has_no_raw_bodies_or_task_text(brain_home, monkeypatch):
    _make_skill(brain_home, "picked", "shadow")
    monkeypatch.setattr(
        "second_brain.router.route",
        lambda home, task, max_active=None, skills=None: {
            "selected": ["picked"], "scores": {}, "shadow": True
        },
    )
    plan = skills.build_plan(brain_home, "super secret task text", session_id="s1", project_id="p1")
    evidence = skills.plan_to_evidence(plan)
    dumped = json.dumps(evidence)
    assert "super secret task text" not in dumped
    assert "Handles X." not in dumped


def test_resolve_visibility_mode_defaults_to_shadow(brain_home):
    assert skills.resolve_visibility_mode(brain_home) == "shadow"
    (brain_home / "config").mkdir(parents=True, exist_ok=True)
    (brain_home / "config" / "skills.toml").write_text(
        "[visibility]\nmode = \"enforced\"\n", encoding="utf-8"
    )
    assert skills.resolve_visibility_mode(brain_home) == "enforced"
    (brain_home / "config" / "skills.toml").write_text(
        "[visibility]\nmode = \"bogus\"\n", encoding="utf-8"
    )
    assert skills.resolve_visibility_mode(brain_home) == "shadow"


def test_router_failure_yields_zero_selection_not_all_skills(brain_home, monkeypatch):
    _make_skill(brain_home, "a", "shadow")

    def _boom(home, task, max_active=None, skills=None):
        raise RuntimeError("router down")

    monkeypatch.setattr("second_brain.router.route", _boom)
    with pytest.raises(RuntimeError):
        skills.build_plan(brain_home, "task", session_id="s1", project_id="p1")
    # Callers (Tasks 2/4) catch this and fail open to zero selection —
    # skills.py itself must never silently substitute "select everything".
```

Note: `brain_home` is an existing pytest fixture already used throughout `tests/test_router.py` and `tests/test_skill_lifecycle.py` — reuse it, do not redefine it.

## Step 2: Run tests to verify they fail

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'second_brain.skills'`

## Step 3: Implement `src/second_brain/skills.py`

Implement exactly the functions named in Interfaces above. Key design points (do not deviate — these close specific frozen-contract gaps):

**Import style requirement:** `skills.py` MUST `from . import router` and call `router.route(...)` (module-attribute access at call time) — never `from .router import route`. The test suite's `monkeypatch.setattr("second_brain.router.route", ...)` calls only take effect if `skills.py` looks up `route` through the `router` module object at call time; a direct-name import would bind the original function and silently make every monkeypatched test in this file pass against the real router instead of the fixture.

- `_MAX_SPECIALIST_SKILLS = 3` module constant (the frozen 0–3 invariant), enforced in `build_plan` independently of `router`'s own `max_active`.
- `_DESCRIPTOR_TEXT_MAX_CHARS = 240` for the `# Purpose` section slice, plus a small bounded prefix of `name`/`version` frontmatter (via `skillforge.read_metadata`) — total `descriptor_text` capped at 400 chars (test asserts `<= 400`). Write a small local helper (5–10 lines) that finds `"# Purpose"` in the file text and returns text up to the next `"# "` heading or EOF, stripped and truncated — do not import `router`'s private `_parse_sections`/`_SECTION_TITLES` (private-name coupling); this is a distinct, smaller concern (one section, bounded, for display) from routing's full multi-section scorer.
- `descriptor_ref` = `hashlib.sha256(descriptor_text.encode("utf-8")).hexdigest()[:16]`.
- `eligible_skills` iterates `paths.SKILL_LEVEL_DIRS` in a fixed order (`"active"`, `"candidate"`, `"shadow"` — same pool `router.py`'s `LEVEL_PRIORITY` scores) and lists subdirectories containing `SKILL.md`; uses `skillforge.lifecycle_content_hash(path)` wrapped in `try/except OSError: content_hash = None` (unreadable file is eligible-but-hash-less, never raises).
- `build_plan`:
  1. Call `router.route(home, task, max_active=max_active)` (let exceptions propagate — callers fail open, see test `test_router_failure_yields_zero_selection_not_all_skills`).
  2. Compute `eligible = {item["skill_id"]: item for item in eligible_skills(home)}` fresh in this same call.
  3. De-duplicate the router's `selected` list preserving order (`dict.fromkeys`).
  4. Partition into `selected_skill_ids` (first `_MAX_SPECIALIST_SKILLS` that are keys of `eligible`) and `rejected_skill_ids`: anything beyond the cap → `"over_cap"`; anything not a key of `eligible` → `"not_eligible"`.
  5. Build `descriptor_refs = {skill_id: descriptors(home)[skill_id]["descriptor_ref"] for skill_id in eligible}` (compute `descriptors(home)` once, reuse for both the response's `descriptor_refs` field and the economics char/token sums).
  6. Build the fields listed in the "Canonical `VisibilityPlan` fields" section above: `visibility_plan_id` (`"vplan-" + sha256(f"{task}|{session_id}|{project_id}|{','.join(selected_skill_ids)}").hexdigest()[:16]`), `task_hash` (`sha256(task.encode("utf-8")).hexdigest()`), `router_decision_hash` (`sha256(contracts.canonical_json({"selected": selected_skill_ids, "scores": router_result["scores"]}).encode("utf-8")).hexdigest()`), `eligible_skill_ids` (sorted `eligible` keys), `descriptor_refs`, `selected_skill_ids`, `rejected_skill_ids`, `unavailable_skill_ids: {}` (populated later by `hydrate_plan`), `hydrated_skill_ids: []` (populated later), `mode` (`mode` argument if given else `resolve_visibility_mode(home)`), the four `descriptor_chars`/`descriptor_tokens`/`avoided_full_chars`/`avoided_full_tokens` fields computed from `eligible`'s full-body char counts (read each eligible skill's file text once to compute both the hash and the char/token counts — do not read the file twice) minus the selected ones' contribution (computed properly once hydration happens — see below), `hydrated_chars: 0`/`hydrated_tokens: 0` (populated later), `created_at` (`datetime.now(UTC).isoformat()`).
  7. **Note on economics timing:** `descriptor_chars`/`descriptor_tokens` are final at `build_plan` time (sum over every eligible descriptor's `descriptor_text`, via `autoinject.token_estimate`). `hydrated_chars`/`hydrated_tokens`/`avoided_full_chars`/`avoided_full_tokens` are NOT final until after `hydrate_plan` runs (hydration can still reject a selected skill as stale/unavailable, moving its bytes from "hydrated" to "avoided"). `build_plan` sets `hydrated_chars`/`hydrated_tokens` to `0` and `avoided_full_chars`/`avoided_full_tokens` to the sum over ALL eligible skills' full-body char/token counts (the conservative "nothing hydrated yet" baseline); `hydrate_plan` subtracts the successfully hydrated skills' char/token counts from `avoided_full_*` and adds them to `hydrated_*` in the plan dict it returns.
  8. Also add a private `_selected_content_hashes: dict[str, str]` field to the plan dict, populated from `eligible[skill_id]["content_hash"]` for every id in `selected_skill_ids` at plan-build time — used by `hydrate_plan` below for staleness comparison. This field must be stripped by `plan_to_evidence`.
- `hydrate_plan(home, plan)`:
  1. Copy `plan` (do not mutate the caller's dict in place — return a new dict, matching the `tuple[dict, dict[str, str]]` return type).
  2. Recompute `eligible = {item["skill_id"]: item for item in eligible_skills(home)}` fresh (this fresh recomputation, compared against `plan["_selected_content_hashes"]`, is what closes the TOCTOU window from the negative-control requirement).
  3. For each `skill_id` in `plan["selected_skill_ids"]`: if `skill_id` is not a key of the fresh `eligible`, or the fresh `content_hash` differs from `plan["_selected_content_hashes"][skill_id]`, or the fresh hash is `None`: do not hydrate; add to `unavailable_skill_ids` with reason `"stale_content_hash"` (hash changed) or `"not_eligible"` (vanished/unreadable) — never raise.
  4. Otherwise read the full `SKILL.md` text (`try/except OSError: unavailable_skill_ids[skill_id] = "read_failed"`), add to `hydrated_bodies[skill_id]`, append to `hydrated_skill_ids`.
  5. Recompute `hydrated_chars`/`hydrated_tokens`/`avoided_full_chars`/`avoided_full_tokens` per the note above.
  6. Return `(updated_plan, hydrated_bodies)`.
- `plan_to_evidence(plan)`: return `{k: v for k, v in plan.items() if not k.startswith("_")}` — the single place that strips any private/internal field (like `_selected_content_hashes`) before anything reaches a caller that might log it. Document in the docstring that callers (Tasks 2/4) MUST call this before passing anything to telemetry/ledger.
- `resolve_visibility_mode(home)`: mirror `router._router_max_active`'s exact `tomllib`-read-with-fallback shape (own copy — do not import the private function): read `<home>/config/skills.toml`, `cfg.get("visibility", {}).get("mode", "shadow")`, return `"enforced"` only if the value is exactly the string `"enforced"`, else `"shadow"` (covers missing file, malformed TOML, missing key, and any non-`"enforced"` value — all fail-safe to shadow).

Add to `config/skills.toml`:

```toml
[visibility]
mode = "shadow"     # SHADOW/REPORT-ONLY default (plan §56/§113 "shadow route first").
                    # skills.py resolves this per build_plan() call (invalid/absent -> shadow,
                    # fail-safe). "enforced" is only ever set by the controlled current-OMP-primary
                    # evaluation harness for the P3.16 two-phase proof — flipping this file's
                    # shipped default is a separate promotion decision, not part of this task.
```

## Step 4: Run tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: PASS, all tests green.

## Step 5: Static checks and commit

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/skills.py tests/test_skills.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/skills.py tests/test_skills.py && .venv/Scripts/python.exe -m pyright src/second_brain/skills.py tests/test_skills.py`

```bash
git add -- src/second_brain/skills.py tests/test_skills.py config/skills.toml
git commit -m "feat(skills): add harness-neutral visibility plan core"
```

## Report

Write your report to `.superpowers/sdd/2026-08-27-p3-16-modular-skill-visibility-implementation/task-1-report.md` with status, files changed, commit hash(es), test command + result summary, and any concerns. Return the same short summary (status/commit/tests/concerns) as your final message.
