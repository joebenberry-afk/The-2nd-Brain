# Final regression delta — tests pass; type gate HOLD

Candidate: `75b80d2aab33929923d4d9323bcaf639bc69591b`; runtime implementation `64694bb32f02cd6a736ec65a24660bd8acd6a3f6`. Baseline: isolated `f5089ac1b6e27f0b3329196cec7e74f402cd0636`, equivalent installed dependencies. The contaminated initial Python baseline artifacts are retained but excluded from comparison.

## Executed gates

| Gate | Starting snapshot | Final candidate | Evidence |
|---|---|---|---|
| Full Python | 1802 passed / 13 failed, 1815 total | **1823 passed / 0 failed / 0 skipped**, exit 0, 444.454 s | `artifacts/pytest-baseline-full.xml`; `artifacts/pytest-final-candidate.xml`; `artifacts/final-suite-inventory.json` |
| Full extension Vitest | 650 passed / 18 failed, 668 total | **684 passed / 0 failed**, exit 0 | `artifacts/vitest-starting-full.json`; `artifacts/vitest-final-source.json` |
| TypeScript | Final `tsc --noEmit` | **PASS**, exit 0 | `artifacts/tsc-final-source.txt` |
| Changed-file ESLint | Historical failures retained | **PASS**, exit 0 | `artifacts/eslint-final-source.txt` and execution sidecar list exact files |
| Python Pyright | 85 errors | **85 errors**, exit 1; no new signature/source-line diagnostics | `artifacts/pyright-final-candidate.json`; individual delta below |
| Python Ruff | 438 diagnostics | **434 diagnostics**, exit 1; no new signature/source-line diagnostics | `artifacts/ruff-final-candidate.json`; individual delta below |
| Inventory script Ruff | Newly requested evidence script | **PASS**, exit 0 | `artifacts/ruff-final-coverage-script.txt` |
| Installer Pester | 5 passed / 13 failed | **18 passed / 0 failed / 0 skipped** | `artifacts/installer-before.json`; `artifacts/installer-after.json` |

The final TypeScript source did not change during the subsequent Python-only manifest fix or verification-only corrections. Full suites were rerun after executable changes, not after documentation-only updates. All execution sidecars preserve exit status, signal and elapsed time; a killed/truncated earlier run is not represented as success.

## Every original Python failure

| Original test | Cause and disposition |
|---|---|
| `test_attach::test_detach_keeps_whitespace_only_agents_file` | Fixture used `Path.read_text(newline=...)`, unsupported by Python 3.11. Compare exact bytes instead; detach already preserved the file. PASS, not a product whitespace-loss fix. |
| `test_autoinject_codex::test_valid_stdin_deterministic_output` | Whole-key-set assertion rejected additive project metadata. Remove that implementation pin; retain injection, deduplication and deterministic-packet behavior. PASS. |
| `test_earned_memory::test_fresh_reopen_and_repeat_migration_preserve_existing_rows` | Hard-coded migration list was stale. Preserve prefix migration, existing-row and repeat-migration contracts. PASS. |
| `test_episodes::test_lazy_migration_0002_on_v1_brain` | Stale pending-version list. Existing episode/lazy-migration behavior retained. PASS. |
| `test_freshness::test_migration_guard_is_case_insensitive` | Fixture lacked the prerequisite memories table. Complete the schema fixture; retain case-insensitive migration guard. PASS. |
| `test_hermes_adapter::test_pre_llm_routes_existing_skill_and_preserves_bounded_injection` | Task requested migration verification but did not match the seeded Hermes context. Request both relevant context and skill routing; retain bounded injection, selected route and no-task-echo assertions. PASS. |
| `test_memory_index::test_migration_0007_fresh_create` | Asserted schema 10 against schema 21. Remove stale version pin while retaining fresh/index behavior. PASS. |
| `test_migrations_property::test_any_prefix_then_remainder_equals_full_apply` | Prefix expectation omitted the always-created `brain_meta` table. Preserve explicit prefix and final table invariants. PASS. |
| `test_origin_authority::test_origin_columns_migrate_existing_0012_database` | Incomplete 0012 fixture omitted `model_skill_outcomes`. Build the actual prefix schema before migration. PASS. |
| `test_retrieval_filters::test_project_filter` | Expected project-only results although shared domain memory is intentionally available. Explicitly include domain knowledge and exclude foreign project memory. PASS. |
| `test_retrieval_isolation::test_unresolved_project_default_memory_suppressed_and_global_policy_allowed` | Generic query matched unrelated seeded/global knowledge. Unique fixture terms isolate default-project suppression without changing retrieval predicates. PASS. |
| `test_v2_policy::test_defaults_are_all_shadow` | Removed: pins mutable shipped defaults rather than a behavioral contract. **This does not fix the legacy parser's rejection of canonical `models`/`providers` metadata.** See the open compatibility issue below. |
| `test_working_set::test_no_lean_path_bypasses_requirement_ledger` | Removed: asserted that source text never contains “requirement”, including valid type fields. Existing requirement-ledger behavior tests remain. |

Also removed the policy migration forwarding-only mock test. Build-identity schema checks and migration-prefix checks were retained with dynamic, meaningful assertions. The promotion property retains the accept/refuse guard invariant rather than undocumented ordering among simultaneous refusal reasons. These changes are not claimed as runtime fixes.

All 18 original extension failure identities and their final passing identities are in `artifacts/extension-failure-delta.json`: nine approximately five-second fixture timeouts lacked controlled auxiliary budget/routing/visibility runners; three configuration tests pinned entire object shape; six pager fixtures omitted the required breakpoint precondition. The final tests exercise the intended branch without introducing a live-host claim.

## Additional mandatory failure discovered and fixed

One converged full run exposed `test_cli_concurrent_init_and_append_burst`. Five independent eight-process bursts on each source passed, so a repeat-pass was not accepted as a waiver. A held Windows reader then reproduced `PermissionError [WinError 5]` during manifest replacement on **both** baseline and candidate (`artifacts/manifest-reader-before.json`).

The narrow fix retries only Windows sharing/access-denial codes 5/32, at most four attempts with 60 ms total requested delay. It never removes the destination. Persistent denial still raises and preserves the old manifest; temporary files are cleaned. The deterministic transient-reader regression failed before and passed after; all 47 ledger tests pass. A real runtime reader-release scenario fails on baseline and opens successfully on candidate (`artifacts/manifest-transient-baseline.json`, `artifacts/manifest-transient-candidate.json`). Final full Python also passes the burst.

## Individual diagnostic classification and open gate

`artifacts/individual-diagnostic-delta.json` enumerates every remaining Ruff/Pyright diagnostic with path, rule/message, location, source line and comparison classification. Pyright comparison is a multiset, not only a count. All 85 type errors and 434 lint findings match baseline signatures and source lines; four Ruff findings disappeared. No blanket formatting, ignored-error setting or diagnostic suppression was added.

**Pyright remains a mandatory failed gate. Equal baseline errors do not make type checking pass. Release remains HOLD.** The JSON is the exact bounded worklist for a separate type cleanup; unchanged source errors on CLI/ledger/governor/worker paths are not automatically waived.

**P2 legacy policy API compatibility remains open:** `v2_policy.load_policy` rejects canonical `models`/`providers` root metadata. Targeted source search found no production imports/calls; the nested-worktree LSP reference result was incomplete and was reported as a tool issue. Retiring that unused legacy API or aligning it with the current policy owner requires an explicit compatibility decision. Do not describe removing the default-pin test as repairing this API.

## Doctor, migration and telemetry

Sealed runtime doctor: **19 checks, 0 failures, 0 warnings**, exit 0; Python 3.11.15, schema 22, RC version. `artifacts/doctor-sealed-source.txt` identifies implementation commit `64694bb32f02`; the later candidate commit changes only tests.

Canonical DB migration was preceded by `backups/backup-20260905-042829-573966`; application/reapplication returned `[22]` then `[]`. Existing backup/reopen/idempotency tests pass. No historical data was hand-edited.

`artifacts/telemetry-sealed-epoch.json`: 7811 historical records, 708 historical heartbeat records missing `artifacts_gc_count`; latest such record predates this run. Since `2026-09-05T03:06:28.977Z`, 21 records validate with zero issues. Those records are not a qualified native candidate epoch. The final extension run used an isolated home; no raw history was deleted to improve counts. The bridge scratch home has zero telemetry records, so its empty validation is not credited as telemetry coverage.

**Gate 4/G: HOLD for type checking and the separately recorded P1/live gates, despite passing final test suites.**


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
