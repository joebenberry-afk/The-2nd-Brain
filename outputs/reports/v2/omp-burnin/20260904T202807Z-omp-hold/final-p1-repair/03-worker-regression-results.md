# P1 #1 — Worker Regression Results

## Focused suite

```text
npx vitest run tests/wiring.test.ts -t "OMP async worker result correlation"
```

12/12 passed:

- Existing hub-path tests (unmodified, still pass): completed via hub,
  failed via hub, no double-report on repeated hub polls, running job
  produces no telemetry.
- New auto-delivery tests (all pass):
  - completed worker via `message_end` async-result auto-delivery
  - failed worker via `message_end` async-result auto-delivery
  - multiple `<task-result>` blocks in one async-result message → all
    correlated results emitted (3/3, correct statuses)
  - unrelated custom message ignored (no telemetry, result runner not called)
  - malformed async-result (no `<task-result>` blocks) fails open — no throw,
    message still returned, no fabricated result
  - unknown/untracked task-result id ignored safely
  - dedup: hub observes first, then the same job auto-delivers → 1 result
    total
  - dedup: async-result observes first, then the same job is later polled
    via hub → 1 result total

## Full extension suite comparison (regression gate)

| | Baseline (`0b2aaf9`, unmodified) | Repaired (this branch) |
|---|---:|---:|
| Test files failed | 4 | 4 (same 4 files) |
| Tests failed | 18 | 18 (identical count) |
| Tests passed | 642 | 650 (+8, all new) |
| Total tests | 660 | 668 |

Verified by `git stash` / `git stash pop` A-B comparison on the exact same
tree: stashing the repair and rerunning `npx vitest run` reproduces the
identical 18 failures (all in pre-existing "Part B/E: context paging wiring"
tests, unrelated to worker-result code), confirming **zero new failures**
introduced by this repair. The 18 pre-existing failures are an existing
repository backlog item, out of scope for this P1 repair, and unchanged by
it.

## TypeScript

```text
npm run typecheck
```

Clean, no errors, both before and after.
