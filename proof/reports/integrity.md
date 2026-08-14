# Phase 1 integrity gate

Candidate repair commit: `06bf24642aad61a4bf527fc97ddb8d5d08a07f1d`.
Campaign runner commit: `1bccbe6`.

- Python Ruff check: passed.
- Python Ruff format check: passed.
- Pyright: `0 errors, 0 warnings, 0 informations`.
- Python suite: `431 passed`.
- Proof deterministic checks: `9 passed` (including the 10,000-file hash-scale check).
- Prime extension lint: passed.
- Prime extension typecheck: passed.
- Prime extension tests: `66 passed`.
- Real Prime extension integration: passed; enabled telemetry had valid v2
  JSONL and required lifecycle kinds, disabled mode wrote no new telemetry.
- SQLite `PRAGMA integrity_check`: `ok`.
- SQLite `PRAGMA foreign_key_check`: empty.
- `brainctl skills audit --home .`: `ok=True`.

Prime Agent’s full monorepo test command was also run, but is not a candidate
gate for this Brain repair: its existing suite reported provider/environment
failures including missing Ollama `gpt-oss:20b`, Windows temp/socket EACCES,
and process/daemon timing failures. No Prime source was changed. The scoped
extension checks and real extension integration are the relevant controls here.
