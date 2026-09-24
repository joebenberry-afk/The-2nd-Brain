---
id: mem-27fc58215bba
title: Synchronized PresentMon capture end screenshot was taken 57ms after profiler wai
type: fact
scope: project
project: unknown
status: candidate
grade: OBSERVED
recorded_at: 2026-09-15T18:52:05.713088+00:00
origin: USER_AUTHORED
authority: project_rule
evidence:
  - reports/capture-synchronized-20260915/completion.json@6d1ab7ffe014 (repo C:\Users\assas\Documents\Dragon Ball SZ Modding\DBSZ Telemetry\SZ-CPU-Lab)
---

Synchronized PresentMon capture end screenshot was taken 57ms after profiler wait returned, but both start/end frames were post-match after a refused foreground preflight and stale Fighting now signal reuse. Use reports/capture-synchronized-20260915/synchronized-window-v2.js only after fresh approval: one-shot signal file, read-only five-second focus wait, fresh window check, monotonic ten-second trigger-age rejection. Synthetic focus/duplicate/stale/permission guards pass; v2 has no live validation. No valid OFF baseline or observer ON.
