# T1.3 Corpus admission policy and feedback

## RED evidence

Added focused tests before implementation and ran:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py -k "observed_candidate or delivery_records_retrieval or mention_records_activation" -q
```

Result: 3 failures, as expected:

- OBSERVED candidate was rejected by `_valid_candidates`.
- delivery produced no `memory_retrievals` row.
- `BrainLifecycle.finalize_session` did not accept tool-call/final-message inputs.

Review follow-up RED tests also reproduced:

- nested Claude `assistant.message.content[].tool_use.input` was not extracted;
- Antigravity Stop transcript tool-use args were not forwarded;
- Antigravity `MODEL`/`PLANNER_RESPONSE` top-level `tool_calls` were not extracted;
- known-project retrieval prefilter dropped domain memories with unknown project;
- unresolved Antigravity Stop returned before activation finalization;
- reconsolidation feedback APIs had no atomic idempotent mode;
- Hermes session-end discarded available payload args/final output.

## GREEN evidence

Focused policy, feedback, and estimator tests:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py -q -k "observed_candidate or delivery_records_retrieval or mention_records_activation or admission_rejects or fit_budget"
```

Result: `11 passed`.

Atomic reconsolidation, nested Claude extraction, and Hermes session-end tests:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_reconsolidation.py tests/test_autoinject.py tests/test_claude_code_adapter.py tests/test_hermes_adapter.py -q -k "feedback_idempotency or delivery_records_retrieval or mention_records_activation or nested_assistant_tool_use or session_end_records_activation"
```

Result: `5 passed`.

Updated writeback contract tests (OBSERVED candidates are now admitted LOW):

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject_writeback.py -q
```

Result: `5 passed`.

Combined focused AutoInject regression set before review follow-up:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py tests/test_autoinject_writeback.py -q -k "not migration_0008"
```

Result: `37 passed`.

Hook safety smoke before review follow-up:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -q
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_antigravity_adapter.py -q -k "stop or inject or shadow"
```

Results: `34 passed`; `5 passed`.

Review follow-up transcript-schema test:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -q -k "nested_assistant_tool_use or antigravity_model_record"
```

Result: `2 passed`.

Focused integration regressions after review fixes:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py tests/test_autoinject_writeback.py tests/test_reconsolidation.py tests/test_claude_code_adapter.py tests/test_hermes_adapter.py tests/test_antigravity_adapter.py -q -k "not migration_0008 and (domain_unknown_project or feedback_idempotency or delivery_records_retrieval or mention_records_activation or nested_assistant_tool_use or antigravity_model_record or session_end_records_activation or activation_before_unresolved)"
```

Result: `8 passed`.

Semantic SQL/linear scope regression and final focused gate:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_semantic.py tests/test_autoinject.py tests/test_autoinject_writeback.py tests/test_reconsolidation.py tests/test_claude_code_adapter.py tests/test_hermes_adapter.py tests/test_antigravity_adapter.py -q -k "not migration_0008 and (project_search_retains_unknown_domain or domain_unknown_project or feedback_idempotency or delivery_records_retrieval or mention_records_activation or nested_assistant_tool_use or antigravity_model_record or session_end_records_activation or activation_before_unresolved)"
```

Result: `9 passed`; focused source modules also passed `py_compile`.

## Real CLI smoke

The existing real subprocess test exercises `python -m second_brain autoinject shadow --json` with a seeded candidate and validates candidate count > 0, INJECT output, deterministic packet output, delivery ID, and same-lineage dedupe:

```text
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_autoinject.py -q -k "cli_shadow_json_deterministic_and_dedupe"
```

Result: `1 passed`.

## Changes

- `src/second_brain/autoinject.py`
  - Admission is fail-closed on missing/unknown metadata.
  - Only `current`, `candidate`, and `labile` statuses are admitted.
  - Only `VERIFIED`, `TESTED`, and `OBSERVED` grades are admitted; VERIFIED/TESTED render HIGH, OBSERVED renders LOW.
  - Domain/global/project scope boundaries are enforced; global is always eligible and domain supports matching/unknown project scope. Semantic SQL and linear filters retain unknown-project domain rows; known-project retrieval supplements the project-prefiltered result before the admission gate.
  - Delivery feedback invokes existing `reconsolidation.record_retrieval` once per memory/session after a successful delivery ledger write.
  - Finalization accepts tool-call args/final message, finds only delivered memory IDs, and invokes `record_activation(..., "correct")` on deterministic substring matches.
  - Budget fitting continues to use the home-aware `contracts.estimate_tokens` estimator against configured target/hard-cap values; no 40,000-token ceiling exists.
- `src/second_brain/semantic.py`
  - SQL and linear project filters retain domain rows with unknown project identity while still excluding mismatched project-scoped rows.
- `src/second_brain/reconsolidation.py`
  - Added opt-in `idempotent=True` feedback modes that use `BEGIN IMMEDIATE` and session-bound lookup before insert/update, preserving append-only defaults for existing callers while preventing concurrent duplicate hook feedback.
- `src/second_brain/cli.py`
  - Claude/Antigravity transcript tool-call arguments are read from a bounded tail in memory only, including nested assistant tool-use and MODEL/PLANNER_RESPONSE `tool_calls` shapes; no raw/private content is persisted to telemetry.
- `src/second_brain/hermes_adapter.py`
  - Hermes session_end forwards direct args/final output or bounded transcript tool-use args into finalization.
- Tests
  - Added RED/GREEN admission, confidence, retrieval feedback, activation idempotency, metadata boundary, estimator-target, nested Claude/Antigravity transcript, Hermes session-end, unresolved Stop, domain-prefilter, and atomic reconsolidation coverage.

## Concerns

- Two pre-existing migration assertions expect schema version 10 / pending migrations through 10, while this worktree has migration 11; those tests were excluded from focused runs and no migration files were changed.
- The new Antigravity black-box transcript test cannot load this worktree source because its subprocess helper intentionally strips `PYTHONPATH`; the installed environment still has the pre-review package and reports zero activation. The source parser and forwarding path are covered directly, and the test should pass once the committed source is installed/integrated. Existing relevant Antigravity Stop/injection tests pass.
- No telemetry record stores tool-call arguments, final-message text, or other raw/private content.
