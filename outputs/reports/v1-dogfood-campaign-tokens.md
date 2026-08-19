# v1.0 campaign dogfooding measurement (real, live)

Source: Brain telemetry written by the Prime extension during THIS campaign, path
`C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/<session>.jsonl`.
Measured by the DRIVER from `assistant_usage` records; no estimates.
Snapshot taken 2026-08-18 during Phase 0.

| session | telemetry records | assistant_usage events | input | output | cache read | cache write | total |
|---|---|---|---|---|---|---|---|
| driver | 503 | 62 | 124 | 37,465 | 3,509,614 | 161,303 | 3,708,506 |
| p0-baseline | 458 | 56 | 713 | 39,744 | 2,223,236 | 191,988 | 2,455,681 |
| p0-primitives | 840 | 105 | 1,346 | 104,853 | 9,303,154 | 668,330 | 10,077,683 |

- Campaign total observed: 16,241,870 tokens across 3 sessions (1 driver + 2 workers).
- DRIVER share: 22.8% of total tokens; worker share 77.2%.
- Driver model: claude-opus-5; workers: claude-haiku-4-5 (cheap-worker rule satisfied by volume; cost-weighting still favours keeping driver turns few).
- Cache behaviour is the dominant term: cache_read 15,036,004 vs cache_write 1,021,621
  (~14.7x reuse), which is direct evidence that the
  cache-preserving context architecture (P1.3) is functioning on live sessions rather than only in tests.

## Why this matters for the plan
- Plan §23 (dogfooding) requires the Brain to be ON and observed during its own development. It was: every turn of this campaign
  (driver and both workers) produced session_start/turn_start/context/provider_request_meta/provider_response_meta/assistant_usage/turn_end records.
- Plan §2.4 requires host-reported input/output/cache-read/cache-write/total. Those four fields ARE captured today.
- What §2.4 still lacks (confirmed in v1-token-baseline.md): context peak, worker-turn spans, repeated file reads,
  duplicate recall/injection detection, compaction cost, task-success rollup, and a Brain-OFF control arm.
  Without a Brain-OFF arm these numbers are a baseline, NOT a token-efficiency proof.
