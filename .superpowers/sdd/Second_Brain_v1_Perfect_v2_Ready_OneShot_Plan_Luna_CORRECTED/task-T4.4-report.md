# T4.4 — Move harness parsing into adapters; codex cwd ladder

## Summary
Extracted the three hook adapter bodies (`_cmd_codex_shadow`, `_cmd_antigravity_hook`, `_cmd_claude_code_hook`) from `src/second_brain/cli.py` into dedicated modules under `src/second_brain/adapters/`:
- `src/second_brain/adapters/codex.py`
- `src/second_brain/adapters/antigravity.py`
- `src/second_brain/adapters/claude_code.py`

Each adapter exports a uniform public entry point: `def run(home: Path) -> int`.
`cli.py`'s `cmd_autoinject` routes thin delegation to `from .adapters import <module>; return <module>.run(home)` with backward-compatible private aliases (`_cmd_codex_shadow = _codex_adapter.run`, etc.) to preserve existing white-box unit test suites without drift.

## Helper Relocation Decisions
1. **`_autoinject_output`** promoted to public `autoinject.shadow_output(decision, packet, delivery_id) -> dict` in `src/second_brain/autoinject.py`. Both `cli.py`'s remaining `cmd_autoinject` (for the generic `brainctl autoinject shadow` subcommand) and `adapters/codex.py` import and call this function, preserving single-source truth and enforcing clean dependency direction (no adapter reaches backward into `cli.py`).
2. **`_git_capture` and `_extract_candidate_marker`** moved into `src/second_brain/adapters/claude_code.py` as module-private helpers; verified via grep to have zero other consumers across the codebase.
3. **`_claude_tool_call_args`** logic moved to `antigravity_transcript.extract_tool_call_args` in `src/second_brain/antigravity_transcript.py`, as it was shared by both Claude Code and Antigravity hook paths for JSONL transcript extraction.
4. **`_log_telem`** remains a closure inside `adapters/antigravity.py::run`.

## Codex Project Resolution (CWD Ladder)
In `adapters/codex.py`, project resolution in both the Stop/SessionEnd branch and the main execution path now calls `autoinject._resolve_project_id(home, payload_dict.get("cwd"), payload_dict.get("project"))`.
- Precedence: explicit payload `project` field wins (rung 1); otherwise resolves against registered project roots containing `cwd` (rung 2); falls through to `SECOND_BRAIN_PROJECT` env var (rung 3) or `"default"` (rung 4).
- Added focused test `test_codex_project_from_cwd_ladder` in `tests/test_autoinject_codex.py` proving that a payload omitting `project` with `cwd` matching a registered project correctly resolves that project, and that an explicit `project` field still takes precedence.

## Verification
- Focused test suite:
  - `tests/test_autoinject_codex.py` (including `test_codex_project_from_cwd_ladder`)
  - `tests/test_claude_code_adapter.py`
  - `tests/test_antigravity_adapter.py`
  - Total: 69 passed in 53.34s, 0 failures.
- No `uv.lock` generated.

## Qualification Limitations
No live Claude Code, Codex, or Antigravity host was spawned during this campaign turn; behavior is verified through comprehensive stdin/stdout JSON contract tests reproducing official hook payloads byte-for-byte.
