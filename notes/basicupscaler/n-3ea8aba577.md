---
id: n-3ea8aba577
kind: gotcha
at: 2026-10-15T09:06:13Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-15T09:06:13Z
tested_sha: 5b83cc4d0168
---

M1 game-session steps (arena.m1_gate execute) record camera decode tiles into <runs>/<step>/camera at ~46-52 MB/s until finish_step deletes them: FT-1 60 s ≈ 3.1 GB, FT-3 632 s ≈ 30 GB, FT-4 765 s ≈ 36 GB. On C: (≈110 GiB free, 100 floor) a long session breaches the floor and the bench stops it (exit 6). Put session `--runs` on D:\BU-gen\m1-gate\<cohort>\runs (D: floor 60) and score with the same --runs dir; check `space_guard.py check --path D:/BU-gen --need 40` first.
