# Task 2: Implement differentiated condition classification

Read the approved design first at `docs/superpowers/specs/2026-08-26-p3-15-skill-gardener-design.md`. Task 1 already implemented `SkillGardener.observe_portfolio()` and bounded skill/binding observations in `src/second_brain/gardener.py`; extend that boundary only for condition classification and focused tests in `tests/test_p3_15_skill_gardener.py`.

Required high-level issue types remain exactly: `stale`, `unused`, `duplicate`, `broken`, `superseded`, `negative_roi`.
Required deterministic condition codes are:
- stale/evidence mismatch: `evidence_stale`
- dead skill: `dead_skill` -> issue_type `broken`
- overlap: `capability_overlap` -> issue_type `duplicate` only when material capability evidence exists; names alone never qualify
- false trigger: `false_trigger` -> `broken`
- never-used: `measured_zero_use` -> `unused`; missing usage must emit bounded `usage_unavailable` evidence and must not become unused
- negative ROI: `measured_negative` -> `negative_roi`, only from P3.14 measured ROI with negative net_tokens_saved
- exact duplicate: `exact_duplicate` -> `duplicate`, only identical normalized capability/content evidence for distinct IDs
- too broad: `scope_too_broad` -> `broken`
- too narrow: `scope_too_narrow` -> `broken`
- model quirks: `model_specific_quirk` -> `broken`
- superseded remains an explicit issue_type and requires concrete replacement identity/version/capability evidence.

Compose existing evidence only: P3.10 Radar, P3.11 binding/evaluation, P3.12 promotion records, P3.13 results, P3.14 measured ROI, telemetry, skillforge.audit_lifecycle. Do not recompute economics. Do not add a registry, evaluator, promotion engine, content editor, or P3.16/Lean changes. Observation remains read-only and bounded.

Add focused tests proving each condition code is independently represented/detected, unknown usage is not measured zero, estimated-only ROI is not negative_roi, exact duplicate differs from capability_overlap, and stale/broken/superseded evidence carries bounded evidence refs. Run only focused Task 2 tests; skip formatters, linters, and project-wide suites. Write report to `.superpowers/sdd/2026-08-26-p3-15-skill-gardener-implementation/task-2-report.md`, include status/tests/commit/concerns, and commit only relevant source/test files.
