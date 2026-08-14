# Phase 2 — Observability: Acceptance Checklist (plan §98)

Gate requires all rows have direct evidence recorded in milestone-02.

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | Telemetry accurate (records match ground truth of a real session) | real prime-agent integration run: expected vs recorded kinds/tool calls | pending |
| 2 | Overhead low (event-write cost measured, no hot-path awaits) | micro-benchmark + integration wall time | pending |
| 3 | No behavior changes (handlers return void; disabled-run identical) | unit tests + disabled-run check + code review | pending |
| 4 | Collects: session, model, tools, files(tool-level), tokens, context, environment(cwd/model), commands(bash), tests(derivable), children(sessions) | schema coverage vs SCHEMA.md | pending |
| 5 | No context mutation / no auto cleanup / no auto routing | design review + tests | pending |
| 6 | Real workload baseline run + recorded | baseline tasks 1-3 output in milestone report | pending |
| 7 | Python aggregation (`brainctl telemetry report|validate`) | pytest tests/test_telemetry.py | done (7 tests) |
| 8 | Install/uninstall safe (backup + restore, idempotent) | Pester 5/5 | done |
| 9 | Validation loop green (ruff, pyright, pytest; tsc, eslint, vitest) | tool outputs in milestone report | pending |
| 10 | Milestone report + independent verification + commit | — | pending |

Known deferred items (documented in milestone-02): per-file read ledger (Phase 4),
full environment snapshot (Phase 8), RepoWise freshness (needs index; Phase 3),
parent/child session linkage, 12-task benchmark suite (plan §95, before Phase 7
behavior changes).
