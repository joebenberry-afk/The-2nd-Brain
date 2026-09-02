# T0.2 Report: Telemetry kinds + Hermes usage

## Status

Complete. Implemented Hermes `model_invocation_completed` usage aggregation, preserved null/missing counters, closed the emitted `hermes_tool_result` kind gap, and committed the scoped changes.

## Files changed

- `src/second_brain/telemetry.py`
  - Added the literal `hermes_tool_result` kind to `KNOWN_KINDS`.
  - `session_usage()` now reads both root-level `assistant_usage` counters and nested Hermes `model_invocation_completed.usage` counters.
  - Missing and explicit `null` counters remain `None`; reported zero remains `0`.
  - Added `source_kind` to the returned usage dictionary; mixed source kinds report `None` rather than claiming a single source.
- `src/second_brain/governor.py`
  - Added `SessionTokens.source_kind`.
  - `parse_telemetry_session()` now accepts nested Hermes `model_invocation_completed.usage` counters with the same token field mapping as `assistant_usage`.
  - Null/non-numeric counters are ignored rather than fabricated or added.
- `tests/test_telemetry.py`
  - Added `test_known_kinds_cover_live_records`.
  - Added `test_session_usage_reads_hermes_model_invocation_completed` with the required literal fixture and null cache-write assertion.

## TDD evidence

### RED

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_telemetry.py -k "known_kinds_cover_live_records or session_usage_reads_hermes_model_invocation_completed" -q
```

Output:

```text
.F                                                                       [100%]
FAILED tests/test_telemetry.py::test_session_usage_reads_hermes_model_invocation_completed
assert usage["input"] == 10
E       assert 0 == 10
```

The new test failed because `session_usage()` only handled root-level `assistant_usage` records.

### GREEN

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_telemetry.py -q
```

Output:

```text
...............                                                          [100%]
15 passed
```

Governor regression command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -q
```

Output:

```text
.................................                                        [100%]
33 passed
```

Hermes governor smoke command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -c "import json,tempfile; from pathlib import Path; from second_brain import governor; d=Path(tempfile.mkdtemp()); p=d/'s.jsonl'; p.write_text(json.dumps({'kind':'model_invocation_completed','usage':{'input_tokens':10,'output_tokens':5,'cache_read_tokens':3,'cache_write_tokens':None}})+'\\n', encoding='utf-8'); t=governor.parse_telemetry_session(p); print(t.input_tokens,t.output_tokens,t.cache_read_tokens,t.cache_write_tokens,t.model_turns,t.source_kind)"
```

Output:

```text
10 5 3 0 1 model_invocation_completed
```

Direct worktree validation command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m second_brain --home . telemetry validate
```

Output:

```text
0 files, 0 records, 0 issues
```

The worktree has no checked-out `telemetry/agent-performance/*.jsonl` records. The live repository records were also validated without rewriting them:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m second_brain --home "C:/Users/assas/Documents/The-Second-Brain" telemetry validate
```

Output:

```text
1042 files, 221409 records, 3 issues
  01a003e2-c6e4-71a8-8a36-53d88ffc786a.jsonl:34: unparseable JSON line
  01a008bb-ae53-7120-a995-cdc0ade001f6.jsonl:4258: unparseable JSON line
  01a008c2-7713-719d-a014-369c12638428.jsonl:1256: unparseable JSON line
```

The three issues are pre-existing unparseable raw lines; none is an unknown-kind issue. A focused count over the same validation result reported `unknown kinds 0` and `all issues 3`.

## Commit

`a4dc1f5` — `brain(core): aggregate hermes usage, close telemetry kinds`

## Concerns

Focused telemetry and governor tests pass. Live repository validation reports zero unknown kinds without rewriting raw telemetry, but retains three pre-existing parse-error issues. The known-kind test is intentionally empty in this worktree and will inspect any live JSONL records when present. `hermes_tool_result` was identified from the live Hermes adapter emitter and added literally; no unrelated telemetry records were rewritten.

## Review-fix report

Addressed the review findings in one scoped fix:

- Removed `hermes_tool_result` from `KNOWN_KINDS`; it is an artifact-store
  label, while the telemetry event is `hermes_post_tool_call`.
- Hardened `test_known_kinds_cover_live_records` to consume
  `telemetry.iter_records()`, skip malformed/non-object/missing-kind records
  exactly as validation does, and require at least one checked fixture record.
  The fixture also exercises malformed and missing-kind tolerance.
- Added a fail-closed `BrainError` in `credit.arm_from_telemetry` when required
  counters are absent, instead of forwarding `None` into counterfactual
  validation.
- Made `SessionTokens` core token counters nullable when the source explicitly
  reports `null`, while retaining the existing zero default for fields that a
  session never exposes. Numeric values continue to sum exactly; role
  attribution retains its existing zero-compatible derived totals.
- Added focused governor and credit regression tests.

### Fix TDD RED

Governor null-preservation command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -k model_invocation_completed_preserves_null_cache_write -q
```

Output before the fix:

```text
F                                                                        [100%]
AssertionError: assert 0 is None
```

Credit fail-closed command before the fix:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_credit.py -k missing_required_usage -q
```

Output before the fix:

```text
F                                                                        [100%]
Failed: DID NOT RAISE BrainError
```

The hardened known-kind test was green against the initial implementation
because the repository worktree has no checked-out live JSONL; its fixture
path now proves the required tolerance and non-vacuity behavior.

### Fix GREEN

Focused telemetry/governor/credit command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_telemetry.py tests/test_governor.py tests/test_credit.py -q -rA
```

Output:

```text
........................................................................ [ 93%]
.....                                                                    [100%]
77 passed
```

Live unknown-kind check after the fix:

```text
PYTHONPATH=src .venv/Scripts/python.exe -c "from pathlib import Path; from second_brain import telemetry; r=telemetry.validate(Path(r'C:/Users/assas/Documents/The-Second-Brain')); print('files',r['files'],'records',r['records'],'unknown kinds',sum('unknown kind' in issue for issue in r['issues']),'all issues',len(r['issues']))"
```

Output:

```text
files 1042 records 221409 unknown kinds 0 all issues 3
```

The three retained issues are pre-existing unparseable raw lines; no raw
telemetry was rewritten.

### Fix commit

`brain(core): aggregate hermes usage, close telemetry kinds` (amended task
commit after review fixes).

## Review-fix round 2 report

Addressed the role-attribution null regression:

- `parse_telemetry_session()` preserves explicit nulls in nullable core token
  fields while retaining integer zero defaults for fields never exposed.
- Derived `driver_tokens`/`worker_tokens` keep their historical integer surface
  and contribute zero only when the source total is unknown.
- `attribute_roles()` skips unknown nullable input/output/total counters
  without converting the source fields themselves to fabricated values.
- Added `test_role_attribution_handles_explicit_null_counters`.

### Round 2 TDD RED

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -k role_attribution_handles_explicit_null_counters -q
```

```text
F                                                                        [100%]
TypeError: unsupported operand type(s) for +=: 'int' and 'NoneType'
```

### Round 2 GREEN

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -k role_attribution_handles_explicit_null_counters -q
```

```text
.                                                                        [100%]
```

Focused final command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_telemetry.py tests/test_governor.py tests/test_credit.py -q -rA
```

```text
........................................................................ [ 92%]
......                                                                   [100%]
```

All listed tests passed (78 total). Live validation remained `unknown kinds 0`
with three pre-existing unparseable lines. No full suite, formatter, linter,
or raw telemetry rewrite was performed.

### Round 2 commit

`fix(core): preserve Hermes telemetry nulls` (second fix commit).
