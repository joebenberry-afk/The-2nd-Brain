# Phase 2 — Real Workload Baseline Tasks

Compact baseline (plan §98 "run real workload baseline"). The full 12-task
suite (outputs/plans/baseline-benchmark.md) runs before the first
behavior-changing phase. Each task here runs in a fresh prime-agent session
(print mode, tools enabled, model deepseek/deepseek-v4-flash) with the
measurement extension loaded via -e; telemetry is analyzed with
`brainctl telemetry report`.

Task 1 (file ops + test):
  Create C:\Users\assas\AppData\Local\Temp\sb-baseline-1\adder.py
  containing a Python function add(a, b) that returns a+b, plus a short
  `python -c` verification that add(2,3)==5. Report the result.

Task 2 (search + read):
  Without writing anything, find which file under
  C:\Users\assas\Documents\The-Second-Brain\config contains the word
  "governor" and report the matching line.

Task 3 (git inspection):
  Run git log --oneline (max 10) in C:\Users\assas\Documents\The-Second-Brain
  and report the commit subjects you see.

Recording (into milestone-02 report): per task — session stem, wall time,
tool calls by tool, bash calls, failed commands, max context %, tokens.
