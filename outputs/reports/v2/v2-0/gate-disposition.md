# v2-0 gate disposition

Base and tag both resolved to `7735033a939cda08739193378116bb908a5fd983`.

The `pytest -q` result is split by the machine-generated classification
evidence; the command's four failures are not one broad `code_regression`.

| Gate/evidence slice | Exit | Disposition | Evidence |
|---|---:|---|---|
| source identity probe (worktree policy) | 0 | — | `gates/source-identity.stdout.txt`, `gates/source-identity.stderr.txt` |
| sanitized subprocess identity probe | 0 | — | `gates/subprocess-source-identity.stdout.txt`, `gates/subprocess-source-identity.stderr.txt` |
| ruff | 0 | — | `gates/ruff.stdout.txt` |
| pyright | 0 | — | `gates/pyright.stdout.txt` |
| pytest -q: subprocess/env-drift failures (3) | 1 | `env_drift` | `gates/pytest.stdout.txt`, `gates/failure-classification.json` |
| pytest -q: in-process promotion guard (1) | 1 | `code_regression` | `gates/pytest.stdout.txt`, `gates/failure-classification.json` |
| Prime lint | 1 | `unavailable_integration` | `gates/prime-lint.stderr.txt` (`eslint` unavailable) |
| Prime typecheck | 1 | `unavailable_integration` | `gates/prime-typecheck.stderr.txt` |
| Prime test | 1 | `unavailable_integration` | `gates/prime-test.stderr.txt` |
| doctor --json | 0 | — | `gates/doctor-json.stdout.txt` |
| telemetry validate | 1 | `env_drift` | `gates/telemetry-validate.stdout.txt`, `gates/failure-classification.json` |
| v1 P4 verifier rerun | 1 | `env_drift` | `gates/verify-v1-p4.stdout.txt`, `gates/verify-v1-p4.result.json` |

The three pytest subprocess failures are `test_preinvocation_bom_prefixed_bytes_still_binds_real_identity`
(BOM handling), `test_init_doctor_status_flow` (schema v9 versus worktree
v10), and `test_every_scenario_carries_required_contract_fields`
(fresh-session `JSONDecodeError`). Their helpers remove `PYTHONHOME` and
`PYTHONPATH`, allowing the stale parent checkout to be resolved; only
`test_guard_combos_match_reference` executes the promotion guard in-process.
The split and source excerpts are generated in
`gates/failure-classification.json`.

The source probe records `second_brain.__file__` under this worktree's
`src`, with `PYTHONHOME` unset and `PYTHONPATH` restricted to this
worktree's `src`. The rerun command wrote detailed verifier JSON to
`gates/verify-v1-p4.result.json` and left
`outputs/reports/v1-p4/independent-verifier.json` unchanged; its only failed
checks are artifact-hash integrity and git currency. The three malformed
telemetry lines are live mutable data with no source-writer evidence tying
them to this commit, so the generated qualification classifies them as
`env_drift`.

The Prime integration is unavailable because this checkout has no installed
Node dependencies. The v1 artifact/git-currency exception and environment
policy are recorded in the v2 discrepancy ledger.
