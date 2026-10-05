---
id: n-5ec31fc4ff
kind: gotcha
at: 2026-10-04T22:25:52Z
source: agent
errors:
  - find timed out after
tested: "true"
tested_by: owner
tested_at: 2026-10-05T03:56:44Z
tested_sha: 6ebc7f55efda
host: omp
---

OMP find over a large tree times out after 20 s: give it a narrow path

Point find at the subsystem folder, never the repo root or C:/Users/...; for a known string or file name use grep or glob instead. BasicUpscaler and Documents roots hold data folders that make find time out (20 timeouts in 14 days).
