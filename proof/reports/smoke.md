# C0/C1 smoke and observability overhead

Date: 2026-08-14. Candidate base: `06bf24642aad61a4bf527fc97ddb8d5d08a07f1d`.

The paired run used the same Prime selector (`deepseek/deepseek-v4-flash`),
thinking level (`minimal`), offline mode, repo snapshot, task text, verifier,
and 20260814 randomization seed. Each condition got a fresh workspace, Brain
home, session directory, and Prime process. The 30 tasks were short response
tasks used only to measure instrumentation behavior; they are not product
effectiveness evidence.

| Metric | C0 OFF | C1 observability |
|---|---:|---:|
| Paired tasks | 30 | 30 |
| Successful | 30 | 30 |
| Success rate | 100% | 100% |
| Paired success delta, ACTIVE-OFF | 0.0 pp | 95% bootstrap [0.0, 0.0] pp |
| Median wall seconds | 12.5760 | 12.7958 |
| p95 wall seconds | 13.3306 | 13.6967 |
| Median latency overhead | — | 1.75% |
| p95 latency overhead | — | 2.75% |
| Input/output token measurements | unavailable | unavailable |
| Telemetry shutdown-loss check | passed | passed |

The latency result is within the plan’s provisional `<=3%` median and `<=8%`
p95 targets. Token overhead remains unmeasured, so this does not close the
full instrumentation gate. The 10-task smoke file also passed 10/10 in each
condition; its raw JSONL hash is
`E749CA465D0EF4641D574940B784E5AFC1177F2BF10E3887B14199C795FF3CAA`.

Raw 30-task JSONL (ignored derived output):
`proof/results/raw/overhead-paired.jsonl`

Hash captured at run completion:
`4F0A3E09266BBD7308D92AB1AD79D26B3424ACD01ED79FF3B0F29BB804F0B8B1`.
