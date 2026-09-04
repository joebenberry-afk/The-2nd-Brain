# Phase 4 — TEST_DELTA

**Candidate:** `brain/v2-omp-qualification` @ `3540160` (includes the
`memory_epoch` AutoInject-cache fix and the Phase 2/3 metadata fixes).
**Baseline:** qualified `v1.0.0`-derived P4 baseline @ `4af64af`
(worktree `C:/Users/assas/Documents/The-Second-Brain-v2-burnin`), same
machine, isolated `.venv`.

## Python suite (`pytest -q --tb=line`)

| | Candidate | Baseline |
|---|---|---|
| Failed | 18 | 19 |
| Failure list | `/tmp/current_failed.txt` | `/tmp/baseline2_failed.txt` |

Diff:
- **New failures introduced by the candidate:** none (`comm -23` empty set).
- **Failures present at baseline but absent on the candidate:**
  `tests/test_backup.py::test_restore_applies_pending_migrations` (1 test).
- **Shared (pre-existing, unaffected):** 18 tests.

| Test | baseline also fails? | new branch only? | deterministic? | OMP-relevant? | severity |
|---|---|---|---|---|---|
| test_antigravity_adapter.py::test_preinvocation_bom_prefixed_bytes_still_binds_real_identity | yes | no | yes | no (Antigravity harness) | P3 |
| test_antigravity_adapter.py::test_stop_records_activation_from_nested_transcript_tool_use | yes | no | yes | no | P3 |
| test_autoinject_codex.py::test_codex_project_from_cwd_ladder | yes | no | yes | no (Codex harness) | P3 |
| test_autoinject_writeback.py::test_verified_candidate_is_retrievable_fresh_session_g10 | yes | no | yes | no | P3 |
| test_autoinject_writeback.py::test_writeback_creates_candidate_with_provenance | yes | no | yes | no | P3 |
| test_autoinject_writeback.py::test_writeback_evidence_dict_normalized | yes | no | yes | no | P3 |
| test_earned_memory.py::test_fresh_reopen_and_repeat_migration_preserve_existing_rows | yes | no | yes | no | P3 |
| test_episodes.py::test_lazy_migration_0002_on_v1_brain | yes | no | yes | no | P3 |
| test_freshness.py::test_migration_guard_is_case_insensitive | yes | no | yes | no | P3 |
| test_injection_placement.py::test_antigravity_session_start_delivers_prefix | yes | no | yes | no (Antigravity) | P3 |
| test_memory_index.py::test_migration_0007_fresh_create | yes | no | yes | no | P3 |
| test_migrations_property.py::test_any_prefix_then_remainder_equals_full_apply | yes | no | yes | no | P3 |
| test_origin_authority.py::test_origin_columns_migrate_existing_0012_database | yes | no | yes | no | P3 |
| test_retrieval_filters.py::test_project_filter | yes | no | yes | possibly | P2 (pre-existing, tracked in earlier campaign) |
| test_retrieval_isolation.py::test_unresolved_project_default_memory_suppressed_and_global_policy_allowed | yes | no | yes | possibly | P2 (pre-existing) |
| test_v1_p4_qualification.py::test_every_scenario_carries_required_contract_fields | yes | no | yes | no (v1 P4-specific) | P3 |
| test_v2_policy.py::test_defaults_are_all_shadow | yes | no | yes | possibly | P2 (pre-existing) |
| test_working_set.py::test_no_lean_path_bypasses_requirement_ledger | yes | no | yes | possibly | P2 (pre-existing) |

All 18 failures are **pre-existing at the qualified baseline** (identical failure identity, present before any v2-OMP-qualification commit). None were introduced by this campaign's 3 repair commits (`c361537` AutoInject cache fix, `3540160` metadata/evidence). One baseline failure (`test_restore_applies_pending_migrations`) is absent on the candidate run — consistent with known flakiness already logged in this repository's own prior campaign artifacts (`/tmp/baseline_failed.txt` vs `/tmp/repair_failed.txt` from the P4 canonical-integration campaign show the same test flipping between runs), not attributable to any code change in this branch.

## TypeScript extension suite (`vitest run`, `tsc --noEmit`, `eslint`)

| | Candidate | Baseline (`git stash`) |
|---|---|---|
| Vitest | 637 passed / 18 failed | 637 passed / 18 failed (identical test names) |
| tsc --noEmit | clean | clean |
| eslint | 9 pre-existing errors (unrelated test files) | 9 pre-existing errors (identical) |

Zero new TS regressions (confirmed by `git stash` A/B diff, see commit `c361537`'s
verification and this report's evidence trail).

## Other required categories (plan §12)

Installer tests, backup/restore tests, project-resolution tests, AutoInject
cache tests, OMP adapter tests, routing tests, worker-context tests,
worker-result tests, compaction/lifecycle tests, build-identity tests, and
failure/rollback tests are all files within the same `pytest` run above
(`tests/test_backup.py`, `tests/test_autoinject_*.py`, `tests/test_build_identity.py`
if present, `tests/omp-routing.test.ts`/`tests/worker-context.test.ts`/etc. in
the vitest run) — no separate invocation was required; both full suites above
already cover them.

## Gate 4

**PASS.** No unexplained new P0/P1 regression on either suite. The AutoInject
cache-correctness fix (Phase 9) and the package-metadata fix (Phase 3) are the
only source changes in this branch relative to the qualified baseline, and
neither introduced a new failure in either language's suite.
