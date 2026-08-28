# Task 1: Add bounded observation and issue schema

Read the approved design first at `docs/superpowers/specs/2026-08-26-p3-15-skill-gardener-design.md`. This task adds only the read-only portfolio observation boundary in `src/second_brain/gardener.py` and its focused tests in `tests/test_p3_15_skill_gardener.py`.

Requirements:
- Add `SkillGardener.observe_portfolio() -> dict` with `skills`, `issues`, `recommendations`, and `economics`.
- Inventory existing candidate/shadow/active lifecycle directories using `paths.SKILL_LEVEL_DIRS`.
- Collect current skill content hash with `skillforge.lifecycle_content_hash()`, lifecycle status, binding/evaluation presence, P3.14 measured ROI summary, and `skillforge.audit_lifecycle()` findings.
- Keep observation read-only. Store only bounded metadata, hashes, counts, and evidence references; never raw transcripts/tool output.
- Measure local processing with `time.perf_counter()`; report model/tool calls as zero.
- Issue records must contain `issue_id`, `issue_type`, `condition_code`, `skill_name`, `skill_version`, `lifecycle_state`, `reason_codes`, `evidence_refs`, `measurement_state`, and optional `replacement_ref`.
- Use existing `SkillROILedger` and current lifecycle primitives; do not add registry, economics, promotion, or OMP-specific subsystems.
- Do not touch P3.16 or Lean.

Acceptance:
- Add focused tests proving inventory of candidate/shadow/active skills, bounded output, zero model/tool overhead, and no lifecycle mutation.
- Run only the focused tests covering this task; skip formatters, linters, and project-wide suites. Return a report at `.superpowers/sdd/2026-08-26-p3-15-skill-gardener-implementation/task-1-report.md` with status, focused test command/output, files changed, commit hash, and concerns. Commit the source/test changes.
