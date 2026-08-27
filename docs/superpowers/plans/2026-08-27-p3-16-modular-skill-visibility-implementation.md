# P3.16 Modular Skill Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing router-selection → skill-visibility gate: a harness-neutral core (`skills.py`) that turns the existing proven `router.py` decision into a bounded, lifecycle-revalidated visibility plan, JIT-hydrates only the selected 0–3 specialist skills, and two thin adapter extensions (OMP, Hermes) that inject only the hydrated content in enforced mode while leaving shadow mode's exposure unchanged.

**Architecture:** See `docs/superpowers/specs/2026-08-27-p3-16-modular-skill-visibility-design.md` (approved). One new Python module (`skills.py`), one new branch in the existing `omp_adapter.handle_request`, one new TS bridge (`visibility-bridge.ts`) plus `index.ts` wiring, one new function in `hermes_adapter.py`.

**Tech Stack:** Python 3.11+ stdlib, existing pytest/ruff/pyright toolchain; TypeScript/Bun + Vitest for the Prime extension.

## Global Constraints

- Reuse `router.route()`, `router.natural_baseline()`, `router.eval_router()` **unchanged** — no routing/scoring redesign.
- Reuse `skillforge.read_metadata`, `skillforge.lifecycle_content_hash`, `paths.SKILL_LEVEL_DIRS`, `autoinject.token_estimate`, `autoinject._append_telemetry`, `contracts.canonical_json` — no duplicate primitives.
- `skills.py` is not a registry: it stores no independent skill state; every fact is re-derived from the same directories/files `router.py` already reads.
- Frozen invariant: selected specialist skills is always 0–3 (`_MAX_SPECIALIST_SKILLS = 3`), enforced independently of `router`'s own `max_active` config.
- No raw skill body text or full task text ever reaches `autoinject._append_telemetry` or any ledger writer — only bounded refs/hashes/counts (`plan_to_evidence`).
- Fail-closed for ineligible/stale/unknown skills; fail-open (zero specialist skills, never "load all") on router failure.
- Default `config/skills.toml [visibility] mode` stays `"shadow"`; nothing in this plan flips the shipped default to `"enforced"`.
- Preserve P3.1–P3.15 (including P3.15's evidence-provenance hardening) and Lean `candidate/HOLD_SHADOW`. Do not begin P3.17.
- Skip formatters/linters/project-wide suites mid-task; run focused tests per task. Full suite + Ruff + Pyright + npm test run once at the end by the controller, not per task.

---

### Task 1: `skills.py` harness-neutral visibility core

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

**Step 1: Write the failing tests**

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'second_brain.skills'`

- [ ] **Step 3: Implement `src/second_brain/skills.py`**

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
  6. Build the fields listed in the spec's "Canonical `VisibilityPlan` fields" section: `visibility_plan_id` (`"vplan-" + sha256(f"{task}|{session_id}|{project_id}|{','.join(selected_skill_ids)}")[:16]`), `task_hash` (`sha256(task).hexdigest()`), `router_decision_hash` (`sha256(contracts.canonical_json({"selected": selected_skill_ids, "scores": router_result["scores"]})).hexdigest()`), `eligible_skill_ids` (sorted `eligible` keys), `descriptor_refs`, `selected_skill_ids`, `rejected_skill_ids`, `unavailable_skill_ids: {}` (populated later by `hydrate_plan`), `hydrated_skill_ids: []` (populated later), `mode` (`mode` argument if given else `resolve_visibility_mode(home)`), the four `descriptor_chars`/`descriptor_tokens`/`avoided_full_chars`/`avoided_full_tokens` fields computed from `eligible`'s full-body char counts (read each eligible skill's file size once — `path.stat().st_size` is sufficient for chars; `autoinject.token_estimate` needs text, so read the text you already need for the hash) minus the selected ones' contribution (computed properly once hydration happens — see below), `hydrated_chars: 0`/`hydrated_tokens: 0` (populated later), `created_at` (`datetime.now(UTC).isoformat()`).
  7. **Note on economics timing:** `descriptor_chars`/`descriptor_tokens` are final at `build_plan` time (sum over every eligible descriptor). `hydrated_chars`/`hydrated_tokens`/`avoided_full_chars`/`avoided_full_tokens` are NOT final until after `hydrate_plan` runs (hydration can still reject a selected skill as stale/unavailable, moving its bytes from "hydrated" to "avoided"). `build_plan` sets `hydrated_chars`/`hydrated_tokens` to `0` and `avoided_full_chars`/`avoided_full_tokens` to the sum over ALL eligible skills' full-body char/token counts (the conservative "nothing hydrated yet" baseline); `hydrate_plan` subtracts the successfully hydrated skills' char/token counts from `avoided_full_*` and adds them to `hydrated_*` in the plan dict it returns.
- `hydrate_plan(home, plan)`:
  1. Copy `plan` (do not mutate the caller's dict in place — return a new dict, matching the `tuple[dict, dict[str, str]]` return type).
  2. For each `skill_id` in `plan["selected_skill_ids"]`: look up its current path via `eligible_skills(home)` (recomputed fresh — this fresh recomputation, compared against the hash recorded when `descriptors(home)` was built inside `build_plan`, is what "closes the TOCTOU window" — compare the fresh `content_hash` against `descriptors(home)[skill_id]["content_hash"]` captured via the plan's own `descriptor_refs`/eligible snapshot; since `descriptor_ref` is a hash of `descriptor_text` not `content_hash` directly, look up the ORIGINAL `content_hash` the plan recorded — add a private `_selected_content_hashes: dict[str, str]` field to the plan dict in `build_plan` for exactly this comparison, populated from `eligible[skill_id]["content_hash"]` at plan-build time; this field is internal-only and must be stripped by `plan_to_evidence` before anything reaches telemetry).
  3. If the skill is no longer in `eligible_skills(home)` at all, or its fresh `content_hash` differs from `_selected_content_hashes[skill_id]`, or the fresh hash is `None`: do not hydrate; add to `unavailable_skill_ids` with reason `"stale_content_hash"` (hash changed) or `"not_eligible"` (vanished) — never raise.
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: PASS, all tests green.

- [ ] **Step 5: Static checks and commit**

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/skills.py tests/test_skills.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/skills.py tests/test_skills.py && .venv/Scripts/python.exe -m pyright src/second_brain/skills.py tests/test_skills.py`

```bash
git add -- src/second_brain/skills.py tests/test_skills.py config/skills.toml
git commit -m "feat(skills): add harness-neutral visibility plan core"
```

---

### Task 2: `omp_adapter.py` skill-visibility operation

**Files:**
- Modify: `src/second_brain/omp_adapter.py`
- Modify: `tests/test_omp_adapter.py`

**Interfaces:**
- Consumes (from Task 1): `skills.build_plan`, `skills.hydrate_plan`, `skills.plan_to_evidence`, `skills.resolve_visibility_mode`.
- Produces (consumed by Task 3's TS bridge): `omp_adapter.handle_request(home, {"operation": "skill_visibility", "task": str, "host_session_id": str, "project_id": str, ...})` returns `{"visibility_plan": <plan_to_evidence(plan) dict> | None, "hydrated_instructions": {skill_id: str} | {}, "error": str | None}`.

**Step 1: Write the failing tests**

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_omp_adapter.py -k skill_visibility -q`
Expected: FAIL (no `skill_visibility` branch yet).

- [ ] **Step 3: Implement the branch**

In `src/second_brain/omp_adapter.py`, add `from . import skills` to the existing `from . import contracts, ledger, model_routing, worker_protocol, working_set` import line. Add a new private function:

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

In `handle_request`, add this branch immediately after the existing `worker_context` branch (before the `task = _text(...)` fallthrough that assumes model routing):

```python
    if payload.get("operation") == "skill_visibility":
        try:
            return _prepare_skill_visibility(Path(home), payload)
        except Exception:
            return {"visibility_plan": None, "hydrated_instructions": {}, "error": "VISIBILITY_UNAVAILABLE"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_omp_adapter.py -q`
Expected: PASS, all tests green (including the pre-existing ones — no regression).

- [ ] **Step 5: Static checks and commit**

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/omp_adapter.py tests/test_omp_adapter.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/omp_adapter.py tests/test_omp_adapter.py && .venv/Scripts/python.exe -m pyright src/second_brain/omp_adapter.py tests/test_omp_adapter.py`

```bash
git add -- src/second_brain/omp_adapter.py tests/test_omp_adapter.py
git commit -m "feat(omp-adapter): add skill_visibility operation"
```

---

### Task 3: `visibility-bridge.ts` + `index.ts` wiring

**Files:**
- Create: `brainstem/prime-extension/src/visibility-bridge.ts`
- Create: `brainstem/prime-extension/tests/visibility-bridge.test.ts`
- Modify: `brainstem/prime-extension/src/index.ts`
- Modify: `brainstem/prime-extension/tests/wiring.test.ts` (or add a focused new test file if `wiring.test.ts` is already large — check its current size with `read` before deciding; if it is under ~2000 lines, add cases there to match existing wiring-test conventions)

**Interfaces:**
- Consumes: same `execFile("python", ["-m", "second_brain", "autoinject", "omp-routing"], ...)` transport `routing-bridge.ts`/`worker-context-bridge.ts` already use; sends `{"operation": "skill_visibility", "task": ..., "host_session_id": ..., "project_id": ...}` on stdin; receives the JSON `omp_adapter.handle_request` produces in Task 2.
- Produces (consumed by `index.ts`): `runOmpVisibility(options: OmpVisibilityOptions) -> Promise<OmpVisibilityResult>` where `OmpVisibilityResult = { visibility_plan: Record<string, unknown> | null; hydrated_instructions: Record<string, string>; error: string | null }`.

**Step 1: Read `routing-bridge.ts` and `worker-context-bridge.ts` in full first** (both already in this repository) — `visibility-bridge.ts` must follow their exact structure: bounded input helpers (`bounded`, `validIdentity`-equivalent), a `parseOmpVisibilityOutput(stdout: string): OmpVisibilityResult` pure-parsing function (unit-testable without spawning a process), and `runOmpVisibility(options): Promise<OmpVisibilityResult>` that spawns the process with a hard timeout (`OMP_VISIBILITY_TIMEOUT_MS = 3000`, matching `OMP_ROUTING_TIMEOUT_MS`), bounds stdout (`OMP_VISIBILITY_MAX_STDOUT_CHARS = 256 * 1024`, matching the others), and **fails open** — any spawn error, timeout, non-JSON stdout, or malformed shape resolves to `{ visibility_plan: null, hydrated_instructions: {}, error: "<reason>" }`, never throws and never rejects the returned promise.

**Step 2: Write the failing tests**

```typescript
// brainstem/prime-extension/tests/visibility-bridge.test.ts
import { describe, expect, it } from "vitest";
import { parseOmpVisibilityOutput, runOmpVisibility } from "../src/visibility-bridge";

describe("parseOmpVisibilityOutput", () => {
  it("parses a well-formed shadow-mode plan", () => {
    const stdout = JSON.stringify({
      visibility_plan: { mode: "shadow", selected_skill_ids: ["a"], hydrated_skill_ids: [] },
      hydrated_instructions: {},
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.visibility_plan?.mode).toBe("shadow");
    expect(result.error).toBeNull();
  });

  it("fails open on malformed JSON", () => {
    const result = parseOmpVisibilityOutput("not json");
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });

  it("fails open when hydrated_instructions is not an object", () => {
    const stdout = JSON.stringify({ visibility_plan: null, hydrated_instructions: "nope", error: null });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.hydrated_instructions).toEqual({});
  });
});

describe("runOmpVisibility", () => {
  it("fails open when the python process errors", async () => {
    const result = await runOmpVisibility({
      home: "/nonexistent/path/that/does/not/exist",
      task: "test task",
      hostSessionId: "s1",
      projectId: "p1",
    });
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `brainstem/prime-extension/`): `npm test -- --run visibility-bridge`
Expected: FAIL (module does not exist).

- [ ] **Step 4: Implement `visibility-bridge.ts`**

Follow `worker-context-bridge.ts`'s exact shape (imports, `bounded()` helper, options interface with `home`, `task` (bounded to `OMP_VISIBILITY_MAX_TASK_CHARS = 2048`, matching `OMP_ROUTING_MAX_TASK_CHARS`), `hostSessionId`/`projectId` (bounded to 128 chars, matching `OMP_ROUTING_MAX_IDENTITY_CHARS`), spawn `python -m second_brain autoinject omp-routing` with `env.SECOND_BRAIN_HOME = options.home`, JSON payload `{ operation: "skill_visibility", task, host_session_id: hostSessionId, project_id: projectId }` written to stdin, `OMP_VISIBILITY_TIMEOUT_MS` timeout via the same pattern `runOmpRouting` uses (check its exact timeout/kill mechanism and mirror it verbatim), bounded stdout accumulation, `parseOmpVisibilityOutput` on success.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- --run visibility-bridge`
Expected: PASS.

- [ ] **Step 6: Wire into `index.ts`**

Read the existing `autoinjectCall`/routing-call site (search `index.ts` for where `routingRunner`/`runOmpRouting` — imported near the top alongside `ompRoutingRecord` — is actually invoked at the pre-model hook; it is called from a helper around line 590–600 keyed by `${session}:${currentTurnIndex}:${taskHash}` with a `routingCache` Map for dedup within a turn). Add an analogous `visibilityRunner = options.ompVisibilityRunner ?? runOmpVisibility` (add `ompVisibilityRunner?: (options: OmpVisibilityOptions) => Promise<OmpVisibilityResult>;` to the extension's options interface, mirroring `ompRoutingRunner`), call it at the same site with the same `task`/`session`/`project` identity already available there, and:

- If `result.visibility_plan?.mode !== "enforced"` (shadow, null, or missing): do nothing further — no injection, matching the spec's "existing behavior unchanged" for shadow mode. Still record `result.visibility_plan` into the existing telemetry mirror call the routing result already goes through (bounded, no bodies — the plan is already bounded by construction).
- If `result.visibility_plan?.mode === "enforced"` and `result.hydrated_instructions` has at least one entry: build one bounded text block (`Object.entries(result.hydrated_instructions).map(([id, text]) => text).join("\n\n")`, capped defensively at a fixed max chars e.g. `16384`, matching the order-of-magnitude of `OMP_WORKER_CONTEXT_MAX_TEXT_CHARS`/AutoInject packet bounds already used elsewhere in this file) and inject it via the same `custom_message` mechanism the AutoInject packet patch already uses at this hook (find that exact return shape in the surrounding code and mirror it — do not invent a new injection channel).

Do not modify `routingRunner`'s own call or `ompRoutingRecord`; add the visibility call and its telemetry/injection handling alongside, not inside, the existing routing logic.

- [ ] **Step 7: Add/extend the wiring test**

In `brainstem/prime-extension/tests/wiring.test.ts` (or a new focused file if that file is unwieldy — check its line count first), add cases asserting: (a) shadow-mode plan never appears in the injected `custom_message` list; (b) enforced-mode plan with one hydrated skill produces exactly one additional injected block containing that skill's text; (c) a bridge error (`ompVisibilityRunner` rejecting or resolving to `{ visibility_plan: null, ... }`) produces zero injected blocks and no thrown error out of the handler (fail-open, matching this file's existing `try/catch` convention for every handler).

- [ ] **Step 8: Run full TS suite and commit**

Run (from `brainstem/prime-extension/`): `npm test -- --run`
Expected: all tests pass, no regressions.

```bash
git add -- brainstem/prime-extension/src/visibility-bridge.ts brainstem/prime-extension/tests/visibility-bridge.test.ts brainstem/prime-extension/src/index.ts brainstem/prime-extension/tests/wiring.test.ts
git commit -m "feat(prime-extension): wire skill-visibility bridge at pre-model hook"
```

---

### Task 4: `hermes_adapter.py` visibility integration

**Files:**
- Modify: `src/second_brain/hermes_adapter.py`
- Modify: `tests/test_hermes_adapter.py`

**Interfaces:**
- Consumes (from Task 1): `skills.build_plan`, `skills.hydrate_plan`, `skills.plan_to_evidence`, `skills.resolve_visibility_mode`.
- Produces: `_handle_pre_llm`'s existing response dict gains `"visibility_plan": <bounded dict> | None` alongside the existing `"selected_routes"` field; when `mode == "enforced"` and hydration produced at least one body, `packet` (the existing field already returned and already fed to `render_packet`/the host) is extended with the hydrated specialist text using the SAME extension pattern `vmem_context` already uses to extend `packet` in this function (read the current `_handle_pre_llm` body first to find that exact pattern and mirror it — do not invent a second packet-extension mechanism).

**Step 1: Write the failing tests**

Read `tests/test_hermes_adapter.py` first to match its existing fixture/binding-construction conventions exactly (do not guess the `HermesBinding`/payload shape — copy an existing `_handle_pre_llm`-exercising test's setup). Add:

```python
def test_pre_llm_shadow_mode_never_injects_hydrated_skill(...):
    # Reuse the existing test file's binding/payload builder helpers.
    # Arrange one shadow-level skill whose trigger phrase matches `task`.
    # Assert: response["visibility_plan"]["mode"] == "shadow"
    # Assert: the skill's full body text does not appear anywhere in response["packet"].
    ...


def test_pre_llm_enforced_mode_injects_hydrated_skill(..., monkeypatch):
    # monkeypatch second_brain.skills.resolve_visibility_mode to return "enforced"
    # for this test's home.
    # Assert: response["visibility_plan"]["mode"] == "enforced"
    # Assert: the hydrated skill's full body text appears in response["packet"].
    # Assert: an unselected eligible skill's full body text does NOT appear in response["packet"].
    ...


def test_pre_llm_visibility_failure_does_not_break_existing_autoinject_path(..., monkeypatch):
    # monkeypatch second_brain.skills.build_plan to raise.
    # Assert: response["visibility_plan"] is None
    # Assert: response still contains the existing "packet"/"decision" fields unaffected
    # (matching _route_task's existing "routing failure must not suppress AutoInject" contract).
    ...
```

Fill in each test body using the exact `HermesBinding`/payload construction already present in this file's other `_handle_pre_llm` tests — do not introduce a new fixture pattern.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -k visibility -q`
Expected: FAIL (no visibility fields yet).

- [ ] **Step 3: Implement**

Add `skills` to the existing `from . import (...)` import block in `hermes_adapter.py`. Add a private helper mirroring `_route_task`'s exact fail-open shape:

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

Locate the exact point later in the function where `packet`/`visible_packet` is computed from `autoinject.render_packet(decision)` and `mode in {"advisory", "active"}`. Immediately after that computation, add:

```python
    if visibility_plan is not None and visibility_plan.get("mode") == "enforced" and hydrated_bodies:
        specialist_text = "\n\n".join(hydrated_bodies[skill_id] for skill_id in sorted(hydrated_bodies))
        if visible_packet:
            visible_packet = f"{visible_packet}\n\n{specialist_text}"
        else:
            visible_packet = specialist_text
```

(Use whatever the actual local variable name is after reading the current function — `visible_packet` is the name shown in the excerpt already read from this file; confirm before writing.)

Add `"visibility_plan": visibility_plan,` to both the `event_payload` dict (bounded — `plan_to_evidence` already stripped anything unsafe) and the function's final returned response dict, alongside the existing `"selected_routes": selected_routes,` entries (both places it currently appears).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -q`
Expected: PASS, all tests green, no regression in pre-existing tests.

- [ ] **Step 5: Static checks and commit**

Run: `.venv/Scripts/python.exe -m ruff check src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py && .venv/Scripts/python.exe -m ruff format --check src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py && .venv/Scripts/python.exe -m pyright src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py`

```bash
git add -- src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py
git commit -m "feat(hermes-adapter): fold visibility plan into pre-llm response"
```

---

## Post-plan: controller-run proof (not an SDD task)

After Task 4's final review is clean, the controller (not a subagent) runs, directly in the primary session:

1. Full `pytest`/Ruff/Pyright + `npm test` regression (whole repo).
2. Shadow-phase dogfood: fresh current-OMP-primary run(s) exercising `skills.build_plan` shadow-mode across representative tasks (no-specialist-needed, one-specialist, multi-specialist, confusing/near-trigger), using `router.eval_router`'s existing fixture plus one fresh live comparison, confirming acceptance (router f1 >= natural f1, no success regression) still holds.
3. Controlled enforced-mode probes (0/1/2/3/>3 selected) via `omp_adapter.handle_request`/the OMP extension's actual injected `custom_message`, verifying via `descriptor_ref`/`content_hash` markers (never full bodies) that selected content is present and unselected content is absent in the effective injected text.
4. Economics aggregation from `plan_to_evidence` fields across the probe session.
5. Fresh independent OMP-primary P3.16 acceptance validator (read-only), reconstructing the full evidence chain per the accepted instruction's "Canonical evidence" section.
6. Persist dogfood artifacts under `state/p3_16_dogfood/` and update the Active State Capsule, mirroring the P3.15 closure pattern.

Return `P3.16_PROVEN` only if every accepted-instruction condition is independently evidenced; otherwise `P3.16_PARTIAL / <smallest remaining seam>`.
