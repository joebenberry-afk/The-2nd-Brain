# C0/C1 smoke and observability overhead

Date: 2026-08-14. Candidate runner commit: `1bccbe6`.

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
| Median wall seconds | 12.6799 | 12.8077 |
| p95 wall seconds | 13.0335 | 13.2791 |
| Median latency overhead | — | 1.01% |
| p95 latency overhead | — | 1.88% |
| Input/output token measurements | unavailable | unavailable |
| Telemetry shutdown-loss check | n/a | 30/30 passed |

The latency result is within the plan’s provisional `<=3%` median and `<=8%`
p95 targets. C1 had zero failed tool calls and mean peak context usage of
1.0632%. Token overhead remains unmeasured, so this does not close the full
instrumentation gate. The earlier 10-task smoke file also passed 10/10 in each
condition; its raw JSONL hash is
`E749CA465D0EF4641D574940B784E5AFC1177F2BF10E3887B14199C795FF3CAA`.

Raw 30-task JSONL (ignored derived output):
`proof/results/raw/overhead-paired-v2.jsonl`

Hash captured at run completion:
`443F9EACD4F4A6B5D8E5A8BCA29891A095380C32028C1D5CE27053C5A71CE9A0`.
