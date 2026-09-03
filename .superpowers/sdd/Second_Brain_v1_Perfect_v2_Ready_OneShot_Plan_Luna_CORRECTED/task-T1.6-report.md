# T1.6 Low-friction memory I/O report

## RED/GREEN

- RED: `tests/test_cli.py -k "remember_one_line or recall_prints_freshness"` failed because `brainctl remember` was not a registered command.
- GREEN: focused remember/recall tests pass after adding the parser, handlers, evidence capture, project ladder, IDF/gate/freshness path, and bounded renderer.
- Recall passes the question explicitly to the retrieval pipeline, so even a capsule under the hashed recall session id cannot replace the query.

## CLI smoke

- `brainctl remember "Use bounded memory I/O" --evidence notes.txt:1-2` exits 0 and prints only the generated `mem-*` id.
- Nested-cwd evidence regression confirms blob capture uses the git-root-relative path with git executed from the repository root.
- The remember test verifies captured `path` and line range directly from the canonical SQLite source row.
- `brainctl recall "bounded memory I/O"` exits 0 and renders `[VERIFIED_CURRENT] ... (mem-...)`.
- Unknown queries render `NO_INJECTION <reason>` without exposing query text or source contents.
- Existing `memory add` CLI tests remain green.

## Rule/injection evidence

- Claude rule retains the Stop-hook candidate marker implementation path while replacing the old marker instructions with the exact two command lines.
- The exact command lines occur once each in the Claude rule, Codex adapter README session guidance, and Antigravity rule prefix. The adapter test asserts one occurrence per source.
- Claude SessionStart remains `{}` (no retrieval/context mutation before T2.4); repeated session lifecycle telemetry remains idempotent.
- `tests/test_claude_code_adapter.py` passes all 37 tests, including SessionStart behavior and static command-count assertions.

## Real Claude exercise

`claude.exe` is installed and `claude --help` was available. A noninteractive smoke attempt with `claude -p "Reply exactly OK" --no-session-persistence --tools "" --max-budget-usd 0.01` was refused by Claude with `Error: Exceeded USD budget (0.01)` before a session could run. No successful live-session claim is made.

## Verification

- `.venv/Scripts/python.exe -m pytest tests/test_cli.py -k "remember_ or recall_" -q`: 6 passed.
- `.venv/Scripts/python.exe -m pytest tests/test_cli.py -k "remember_ or recall_ or fresh_verifier_record_parses_real_verdict" -q`: 7 passed.
- `.venv/Scripts/python.exe -m pytest tests/test_freshness.py -k "nested_cwd" -q`: 1 passed.
- `.venv/Scripts/python.exe -m pytest tests/test_cli.py -k "memory_add_" -q`: 3 passed.
- `py_compile` passed for changed Python modules/tests; `git diff --check` passed.

## Concerns

- Runtime adapter context injection is intentionally not enabled yet; existing Claude/Codex/Antigravity shadow/no-op behavior remains unchanged until T2.4 formalizes injection slots.
- No formatter, linter, project-wide build, or full test suite was run.
