# T0.3 Claude Code usage capture report

## Implementation

Implemented bounded Claude Code transcript usage capture and hook telemetry.

- Added `extract_usage_tail(path, max_bytes=262144)` to `src/second_brain/antigravity_transcript.py`.
  It reads only the bounded binary tail, discards a partial first line, tolerates malformed JSON, extracts assistant UUID plus the four Claude usage counters, and never returns transcript content. Added generic `extract_latest_task` alias while preserving `extract_latest_user_task`.
- Updated `_cmd_claude_code_hook` in `src/second_brain/cli.py`:
  - `Stop` extracts assistant usage and appends `assistant_usage` records through the existing best-effort telemetry writer.
  - Maps `cache_creation_input_tokens` to `cache_write_tokens` and `cache_read_input_tokens` to `cache_read_tokens`.
  - Uses canonical `state/sessions/<sha256(host-session-id)>/claude-usage-cursor.json` cursor state, deduping only by transcript record UUID.
  - Includes optional payload cache stats as `cache_state`; absent stats are recorded as `null`.
  - Adds fail-open, telemetry-only `UserPromptSubmit` prompt byte/hash and `PostToolUse` tool/output byte/hash handling; no prompt, tool input, or tool output content is persisted.
- Added `UserPromptSubmit` and `PostToolUse` command hook entries to `brainstem/adapters/claude-code/hooks.json`. Installer merge behavior was not changed.
- Registered the two new telemetry kinds in `src/second_brain/telemetry.py`.
- Added focused adapter coverage for two assistant rows, cache-write mapping, UUID Stop dedupe, canonical cursor, 256 KiB tail behavior, optional cache state, and hook configuration.

## TDD evidence

### RED

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -k claude_stop_hook_emits_assistant_usage_from_transcript -q
```

Output:

```text
F                                                                        [100%]
...
E       assert 0 == 2
E        +  where 0 = len([])
1 failed
```

The new adapter test failed because the Stop handler did not yet emit assistant usage rows.

### GREEN

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -q
```

Output:

```text
..............................                                           [100%]
30 passed
```

The focused adapter suite passes after implementation. A direct subprocess smoke reproduction also emitted `assistant_usage` with the expected UUID and counters, followed by existing session/Stop telemetry.

## Files

- `src/second_brain/antigravity_transcript.py`
- `src/second_brain/cli.py`
- `src/second_brain/telemetry.py`
- `brainstem/adapters/claude-code/hooks.json`
- `tests/test_claude_code_adapter.py`

## Evidence limitation / concerns

No real local Claude Code session was available or launched during this task. Therefore the DONE-WHEN condition requiring a real session to produce non-null rows and `governor report` to show Claude tokens is not empirically demonstrated here. Synthetic JSONL fixtures and the actual CLI subprocess path are covered; no live-session evidence is fabricated.

No full project validation was run, per task scope. The focused Claude adapter suite is the only suite used for GREEN evidence.

## Review-fix pass

Addressed the review findings without changing the requested scope:

- Restored `import os` in `cli.py`.
- Made `extract_latest_task` the implementation and retained
  `extract_latest_user_task` as its backward-compatible alias; PreCompact now
  uses the generic name. `extract_usage_tail(path, max_bytes=262144)` keeps
  the exact generic bounded extractor signature.
- Restored the pre-existing `context_paging`, `context_structure`, and
  `extension_error` telemetry vocabulary.
- Made the existing AutoInject telemetry writer return a success boolean and
  select the declared per-kind schema version. Claude usage cursors advance
  only after a successful `assistant_usage` write, and usage rows now emit v3.
- Guarded session-id, prompt, and tool/output encoding/hashing so escaped lone
  surrogates remain fail-open (`{}`, exit 0) and never crash the hook.
- Added focused privacy tests for UserPromptSubmit/PostToolUse and regression
  coverage for absent cache state, malformed surrogate payloads, schema version,
  and failed usage writes leaving the UUID eligible.

### Review-fix RED

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -k "prompt_and_tool_hooks or malformed_surrogate or usage_cursor_waits or claude_stop_hook_emits" -q
```

```text
F.FF                                                                     [100%]
3 failed, 1 passed
```

The failures were the expected pre-fix v2 usage rows, surrogate payload exit
1, and cursor advancement after a writer returning `False`.

### Review-fix GREEN

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py tests/test_telemetry.py -q
```

```text
................................................                         [100%]
48 passed
```

No full project validation, formatter, or linter was run.

### Review-fix evidence limitation

The real Claude Code host remains unavailable in this environment. The
required live-session/non-null `governor report` DONE-WHEN evidence is blocked,
not inferred; synthetic JSONL plus the actual CLI subprocess path are the only
available evidence.

### Final focused regression

Added explicit coverage for valid-session auxiliary hooks carrying escaped
lone-surrogate prompt/tool fields. The bounded fail-open path remains
content-free.

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py tests/test_telemetry.py -q
```

```text
.................................................                        [100%]
49 passed
```

## Real Claude Code evidence

The controller exercised the installed hook against a real local Claude Code
transcript. The transcript content was not copied or persisted by this task.

- Transcript path:
  `C:\Users\assas\.claude\projects\C--Users-assas-Documents-The-Second-Brain\459595be-f0d7-4fcc-800e-bd65ff23d411.jsonl`
- Fresh Brain home:
  `C:\Users\assas\AppData\Local\Temp\v2-claude-live-jsczhcuk`
- Evidence artifact:
  `outputs/reports/v2/v2-0/claude-code-live-evidence.json`
- Hook exit: `0`; hook stdout: `{}`; hook stderr: empty.
- Telemetry file:
  `C:\Users\assas\AppData\Local\Temp\v2-claude-live-jsczhcuk\telemetry\agent-performance\v2-real-claude-1788365218.jsonl`
- The evidence artifact records 65 non-null `assistant_usage` rows with
  `harness="claude-code"`.
- `governor report --json` exit: `0`; reported `model_turns=65`,
  `input_tokens=130`, `output_tokens=34592`, `cache_read_tokens=9737036`,
  and `cache_write_tokens=52095`.

This satisfies the real-session DONE-WHEN evidence. The exact raw transcript
and tool output remain unpersisted by the adapter; only the controller's
privacy-safe aggregate evidence artifact is staged.

### Round-3 focused verification

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py tests/test_telemetry.py -q
```

```text
.................................................                        [100%]
49 passed
```
