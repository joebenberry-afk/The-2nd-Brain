# Phase 17-21 — Final Bounded Live Regression + Token/Latency Sanity

## Small bounded final live regression

```text
omp.exe -p --cwd <worktree> --model deepseek/deepseek-v4-flash --auto-approve --max-time 3m "Reply with exactly: final-p1-regression-ok"
```

Output: `final-p1-regression-ok` (11.3s wall time). Telemetry
(`2026-09-05T02-37-28-602Z_...jsonl`): complete normal single-turn lifecycle
(`session_start` -> `before_agent_start` -> `turn_start`/`turn_end` ->
`agent_end` -> `session_shutdown`), **zero `extension_error` records**.
Confirms the deployed repaired candidate handles the ordinary (non-worker)
path with no regression, post-repair.

## Token and latency sanity (8-worker live-proof session)

Session `2026-09-05T02-16-14-068Z_01a06f5a-25f4-762b-b74e-1464fa61981f`
(`10-live-8worker-autodelivery-proof.md`):

- 22 `assistant_usage` records, 579,890 total tokens summed — dominated by
  `cache_read_tokens` (large repeated system-prompt/tool-surface context
  reused turn-to-turn via provider prompt caching), not by this repair's
  code. `cost_total` per turn as low as `$0.0004` on cache-heavy turns.
- Session wall time: 507.4s end-to-end, consistent with the explicit
  `sleep 150` instructed in the live-proof prompt plus real round-trip
  latency for 6 `read`/`glob` calls, 1 `task` spawn, and waiting on 8 real
  subagent completions — no anomalous stall or runaway loop.
- No `duration_ms` outlier or hang: the wall time is fully explained by
  intentional prompt design (the 150s sleep alone accounts for ~30% of it),
  not by extension overhead.

## Why this is a sufficient sanity bound, not a re-run of the full efficiency gate

This repair adds exactly one new observer
(`recordAsyncResultDeliveries`, wired to `message_end`): a synchronous,
local, bounded regex match over the message's own `content` string, with no
additional provider calls, no additional file I/O beyond the existing
telemetry append, and an early return (`message.role !== "custom" ||
message.customType !== "async-result"`) for the overwhelming majority of
`message_end` events that are plain assistant messages. It cannot plausibly
regress token cost or latency at the scale `outputs/reports/v2/final/../20-token-efficiency/TOKEN_EFFICIENCY.md`
and `21-latency-qualification/LATENCY_QUALIFICATION.md` already qualified
for the pre-repair candidate. This sanity check confirms no gross
regression (clean smoke run, no error/hang in the worker-heavy live-proof
session); it does not re-run those full efficiency gates, which remain
valid for the unrelated code paths they measured.
