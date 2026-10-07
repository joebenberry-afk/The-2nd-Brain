---
id: n-6ff0b10ca9
kind: decision
at: 2026-10-06T10:44:57Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-BasicUpscaler\memory\quiet-cpu-during-training.md
---

While a BUNet training queue is running on the GPU, keep the CPU quiet: no pytest suites, mutation runs or other multi-threaded Python. Light file edits and reading only; run tests after the queue ends (or in a gap, with few threads).

**Why:** on 2 Oct 2026 I ran unit and mutation tests on the CPU beside phase 1c's training to save time. Job 1's steps ran 25% slower (9.3 against 7.8 ms), and job 2's launch was refused by the thermal guard (sensor setup over 1 s under CPU load, IDEAS PRC-19), which costs the supervisor's 10-minute cool-down per failure and the whole queue after three. The owner asked twice why I had not just used the GPU or waited for it to be free.

**How to apply:** plan the CPU-heavy part (tests, reviews that run tests, fits) before the queue starts or after it ends. If code must be written during a queue, write it and defer its test run. Never put work on the GPU beside a training job: one GPU job at a time behind `runs/bunet_v1/gpu.lock` ([[concurrent-sessions-shared-ledgers]]). Related: [[fast-reliable-efficient]].
