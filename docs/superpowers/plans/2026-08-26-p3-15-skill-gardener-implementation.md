# P3.15 Skill Gardener Implementation Plan

> **For agentic workers:** Execute this plan inline with the approved design specification. Steps use checkbox syntax for tracking.

**Goal:** Add an evidence-composing, differentiated, gated, archive-first Skill Gardener lifecycle without replacing existing ROI, promotion, or registry primitives.

**Architecture:** Extend `src/second_brain/gardener.py` with read-only observation/classification, bounded recommendations, explicit authorization records, and archive-first retirement/restore. Reuse `skillforge.audit_lifecycle()`, `skillforge.lifecycle_content_hash()`, P3.10 Radar, P3.12 promotion records, P3.13 counterfactual JSON, P3.14 `SkillROILedger`, and existing lifecycle directories. Content changes delegate to existing development/evaluation workflows; demotion delegates to `promotion.demote()`; only archive retirement mutates through Gardener.

**Tech Stack:** Python 3.11+ project venv, pathlib/shutil, JSON, SQLite-backed existing SkillROILedger, pytest, ruff, pyright, current OMP telemetry.

## Global Constraints

- Observation never mutates skill state.
- Negative ROI is a review signal, never automatic retirement.
- Unknown usage/economics remain unavailable; never convert missing values to zero.
- All frozen conditions retain distinct `condition_code` values.
- Gardener is not a second editor, registry, economics engine, or promotion engine.
- Active production skills cannot be removed automatically.
- Retirement order is copy archive -> verify bytes/hash -> persist retirement record -> mutate source.
- Any pre-source-mutation failure leaves the source unchanged.
- Restore refuses to overwrite an existing artifact.
- Preserve P3.1–P3.14, Lean `candidate / HOLD_SHADOW`, and leave P3.16 untouched.

---


## Shared test fixtures

The test module defines these concrete helpers once and reuses them in later
tasks; they are test-only and never become production APIs:

```python
def _make_skill(home: Path, name: str, level: str) -> Path:
    directory = home / paths.SKILL_LEVEL_DIRS[level] / name
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- verified content"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output",
            "References",
        )
    )
    path = directory / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\nstatus: {level}\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    return directory
```

`_fixture_observation(home, condition_code)` returns a real observation
fixture produced by the test setup for the named condition and includes
`issue_id`, `issue_type`, `skill_name`, `skill_version`,
`lifecycle_state`, `reason_codes`, and `evidence_refs`. It is backed by the
same temporary Brain home and current skill files, not mocks.

`_fixture_negative_roi_observation(home)` returns the observation's
`negative_roi` issue for a skill whose P3.14 measured-only ledger row has a
negative `net_tokens_saved`; the test asserts recommendation is review-only.

`_fixture_retire_recommendation(home, name)` returns a real
`archive_retire` recommendation for the temporary skill's current hash with
concrete owner, issue, evidence, approval, non-regression, rollback, and
archive references. The missing-evidence test removes the specific required
field it is testing.

`_authorized_retirement(home, name)` creates a real temporary skill, obtains
its current content hash, and returns the authorization shape produced by
`authorize_maintenance()` after supplying explicit actor, approval,
non-regression, rollback, and archive evidence references. Tests that target
missing authorization evidence construct the same dictionary with the
specific field omitted rather than relying on an undefined placeholder.
**Files:**
- Modify: `src/second_brain/gardener.py:SkillGardener`
- Test: `tests/test_p3_15_skill_gardener.py`

**Interfaces:**
- Produces `SkillGardener.observe_portfolio() -> dict` with `skills`, `issues`, `recommendations`, and `economics`.
- Each issue contains `issue_id`, `issue_type`, `condition_code`, `skill_name`, `skill_version`, `lifecycle_state`, `reason_codes`, `evidence_refs`, `measurement_state`, and optional `replacement_ref`.
- High-level issue types: `stale`, `unused`, `duplicate`, `broken`, `superseded`, `negative_roi`.

- [ ] **Step 1: Write failing inventory/observation tests**

```python
def test_observe_portfolio_returns_all_lifecycle_skills_and_economics(brain_home):
    _make_skill(brain_home, "candidate-one", "candidate")
    _make_skill(brain_home, "shadow-one", "shadow")
    _make_skill(brain_home, "active-one", "active")
    result = SkillGardener(brain_home).observe_portfolio()
    assert {item["skill_name"] for item in result["skills"]} == {
        "candidate-one", "shadow-one", "active-one"
    }
    assert result["economics"]["model_calls"] == 0
    assert result["economics"]["tool_calls"] == 0
    assert result["economics"]["records_inspected"] >= 0
    assert result["recommendations"]
```

- [ ] **Step 2: Run the focused test and verify the expected missing-method failure**

Run:

```text
.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py::test_observe_portfolio_returns_all_lifecycle_skills_and_economics -q
```

Expected: FAIL because `observe_portfolio` is not implemented.

- [ ] **Step 3: Implement inventory and bounded observation**

Use `paths.SKILL_LEVEL_DIRS` and scan only existing lifecycle directories. For each `SKILL.md`, collect the current content hash with `skillforge.lifecycle_content_hash()`, lifecycle status, binding/evaluation presence, P3.14 summary, and `skillforge.audit_lifecycle()` issues. Read only metadata, hashes, counts, and bounded evidence references. Measure elapsed local processing with `time.perf_counter()`; set model/tool calls to zero.

- [ ] **Step 4: Run the focused test and the existing Gardener arithmetic test**

Run:

```text
.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py::test_observe_portfolio_returns_all_lifecycle_skills_and_economics tests/test_p3_gaps_live_integration.py::TestP3GapsLiveIntegration::test_skill_roi_ledger_and_gardener_audit -q
```

Expected: PASS.

---

### Task 2: Implement differentiated condition classification

**Files:**
- Modify: `src/second_brain/gardener.py:SkillGardener`
- Test: `tests/test_p3_15_skill_gardener.py`

**Interfaces:**
- Produces issue records with exact condition codes: `evidence_stale`, `dead_skill`, `capability_overlap`, `false_trigger`, `measured_zero_use`, `measured_negative`, `exact_duplicate`, `scope_too_broad`, `scope_too_narrow`, `model_specific_quirk`.
- Unknown values produce no false issue; usage absence produces `usage_unavailable` evidence, not `unused`.

- [ ] **Step 1: Write failing tests for every frozen condition code**

```python
@pytest.mark.parametrize(
    ("condition_code", "issue_type"),
    [
        ("evidence_stale", "stale"),
        ("dead_skill", "broken"),
        ("capability_overlap", "duplicate"),
        ("false_trigger", "broken"),
        ("measured_zero_use", "unused"),
        ("measured_negative", "negative_roi"),
        ("exact_duplicate", "duplicate"),
        ("scope_too_broad", "broken"),
        ("scope_too_narrow", "broken"),
        ("model_specific_quirk", "broken"),
    ],
)
def test_issue_condition_codes_are_distinct(brain_home, condition_code, issue_type):
    issue = _fixture_observation(brain_home, condition_code)
    assert issue["condition_code"] == condition_code
    assert issue["issue_type"] == issue_type
```

```python
def test_missing_usage_is_not_unused(brain_home):
    _make_skill(brain_home, "unknown-use", "shadow")
    result = SkillGardener(brain_home).observe_portfolio()
    assert not any(i["condition_code"] == "measured_zero_use" for i in result["issues"])
    assert any("usage_unavailable" in i["reason_codes"] for i in result["issues"])
```

- [ ] **Step 2: Run focused tests and verify they fail for the missing classifier**

Run:

```text
.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q
```

Expected: FAIL because issue classification is not implemented.

- [ ] **Step 3: Implement conservative classification**

Rules:

- Compare all bound evidence hashes and current content hash for `evidence_stale`.
- Emit `measured_zero_use` only from actual telemetry/ledger evidence proving zero use; emit `usage_unavailable` otherwise.
- Emit `measured_negative` only from P3.14 `MeasurementState.MEASURED` with negative `net_tokens_saved`.
- Emit `dead_skill`, `false_trigger`, `scope_too_broad`, `scope_too_narrow`, and `model_specific_quirk` only from explicit bounded evidence fields or concrete current lifecycle/verification evidence.
- Emit `exact_duplicate` only when normalized capability/content hashes are identical for distinct skills.
- Emit `capability_overlap` only when an explicit capability evidence record proves material overlap; similar names alone never qualify.
- Emit `superseded` only when an explicit replacement identity/version and capability evidence are present.

- [ ] **Step 4: Run focused classifier tests**

Expected: PASS for all condition-code and unknown-value tests.

---

### Task 3: Add recommendations and explicit authorization gate

**Files:**
- Modify: `src/second_brain/gardener.py:SkillGardener`
- Test: `tests/test_p3_15_skill_gardener.py`

**Interfaces:**
- `recommend_maintenance(observation: dict) -> dict` returns bounded recommendations with `evidence_detected`, `action_recommended`, `action_authorized=False`, `action_executed=False`.
- `authorize_maintenance(recommendation: dict, *, actor: str, approval_ref: str, non_regression_ref: str, rollback_ref: str, replacement: dict | None = None) -> dict` returns a persisted authorization record or raises `BrainError`.

- [ ] **Step 1: Write failing tests for recommendation semantics**

```python
def test_negative_roi_recommends_review_without_retirement(brain_home):
    observation = _real_or_fixture_negative_roi_observation(brain_home)
    recommendation = SkillGardener(brain_home).recommend_maintenance(observation)
    assert recommendation["action_recommended"] in {"repair", "no_action"}
    assert recommendation["action_authorized"] is False
    assert recommendation["action_executed"] is False
```

```python
def test_authorization_requires_owner_approval_non_regression_and_rollback(brain_home):
    recommendation = _fixture_retire_recommendation(brain_home, "retirable")
    with pytest.raises(BrainError, match="owner|approval|non-regression|rollback"):
        SkillGardener(brain_home).authorize_maintenance(
            recommendation,
            actor="",
            approval_ref="",
            non_regression_ref="",
            rollback_ref="",
        )
```

- [ ] **Step 2: Run tests and verify expected failures**

- [ ] **Step 3: Implement recommendation mapping and fail-closed authorization**

Use the approved action-authority table exactly: `keep`/`no_action` record only; `repair`/`narrow` emit existing development/evaluation tasks; `merge`/`supersede` require a verified survivor; `demote` delegates to `promotion.demote()`; `hide` delegates to the existing visibility/routing primitive; `archive_retire` is the only Gardener-owned mutation. Authorization rechecks current skill hash, issue evidence refs, owner/actor, approval, non-regression, and rollback references. Negative ROI alone can never authorize `archive_retire`.

- [ ] **Step 4: Run focused recommendation/authorization tests**

Expected: PASS.

---

### Task 4: Implement archive-first retirement and restore

**Files:**
- Modify: `src/second_brain/gardener.py:SkillGardener`
- Test: `tests/test_p3_15_skill_gardener.py`

**Interfaces:**
- `execute_maintenance(authorization: dict) -> dict` performs only an authorized `archive_retire`; all other actions return a delegated-task record without editing content.
- `restore_retirement(retirement_record_id: str) -> dict` restores the archived artifact to the prior lifecycle location without overwriting an existing artifact.

- [ ] **Step 1: Write failing archive/restore tests**

```python
def test_retirement_copy_verify_record_then_source_mutation_and_restore(brain_home):
    source = _make_skill(brain_home, "retirable", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "retirable")
    gardener = SkillGardener(brain_home)
    result = gardener.execute_maintenance(authorization)
    archive = Path(result["archive_location"])
    assert archive.read_bytes() == original
    assert not source.exists()
    restored = gardener.restore_retirement(result["retirement_record_id"])
    assert Path(restored["restored_path"]).read_bytes() == original
```

```python
def test_retirement_archive_failure_leaves_source_unchanged(brain_home, monkeypatch):
    source = _make_skill(brain_home, "protected", "shadow")
    original = (source / "SKILL.md").read_bytes()
    authorization = _authorized_retirement(brain_home, "protected")
    monkeypatch.setattr("shutil.copytree", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")))
    with pytest.raises(BrainError, match="archive|copy"):
        SkillGardener(brain_home).execute_maintenance(authorization)
    assert (source / "SKILL.md").read_bytes() == original
```

```python
def test_restore_refuses_to_overwrite_existing_artifact(brain_home):
    result = SkillGardener(brain_home).execute_maintenance(_authorized_retirement(brain_home, "collision"))
    _make_skill(brain_home, "collision", "shadow")
    with pytest.raises(BrainError, match="already exists"):
        SkillGardener(brain_home).restore_retirement(result["retirement_record_id"])
```

- [ ] **Step 2: Run tests and verify expected missing-method failures**

- [ ] **Step 3: Implement strict archive order**

Use an archive staging directory. Copy the complete skill directory, verify every file and the `SKILL.md` hash, atomically persist a retirement JSON record containing identity/version/owner/reason/evidence/replacement/previous state/archive ref/restore ref/timestamp, then mutate the source. On any earlier failure, remove only incomplete staging and leave the source untouched. Block automatic active retirement; require an explicit production-safety approval field for active artifacts.

- [ ] **Step 4: Run archive/restore and existing lifecycle tests**

Expected: PASS.

---

### Task 5: Verify focused P3.15 behavior and dogfood

**Files:**
- Test: `tests/test_p3_15_skill_gardener.py`
- Create: `state/p3_15_dogfood/summary.md`
- Create: `state/p3_15_dogfood/evidence.json`

- [ ] **Step 1: Add real-evidence dogfood checks**

Use the real `read-reuse` P3.14 measured-negative record as a review-only observation; verify no lifecycle mutation. Use `sqlite-migration-verifier` or another current active skill with no actionable issue to prove `keep`/`no_action`. Use an isolated copy of a real current skill only for archive/restore if all evidence gates pass; never alter the production artifact or Lean.

- [ ] **Step 2: Run focused tests**

```text
.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py tests/test_p3_gaps_live_integration.py -q
```

- [ ] **Step 3: Persist measured Gardener overhead**

Record model calls, tool calls, tokens, records inspected, local processing time, and maintenance work performed. Do not claim hypothetical savings.

- [ ] **Step 4: Run full relevant verification**

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m pyright src
```

Run the Prime extension suite once after Python verification.

---

### Task 6: Independent validation and qualification artifacts

**Files:**
- Modify: `outputs/reports/rc2/P3_15_SKILL_GARDENER_QUALIFICATION.json`
- Modify: `state/sessions/e294cd86ecbc6c0b8d97ab9c43903d01e00976b898c4564a18539e5b1ae9762a/active-state.json`

- [ ] **Step 1: Run a fresh independent OMP-primary validator**

Validator must reconstruct observation → condition classification → source evidence → recommendation → authorization → action/no_action → lifecycle/archive/restore result, and verify P3.1–P3.14, Lean, and P3.16 boundaries.

- [ ] **Step 2: Persist validator transcript and final evidence references**

- [ ] **Step 3: Update report and capsule only after validator result**

Set `P3.15_PROVEN` only if every approved condition is independently evidenced; otherwise preserve the smallest genuine `P3.15_PARTIAL` seam.
