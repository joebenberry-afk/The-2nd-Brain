---
id: n-9c18dabb30
kind: fact
at: 2026-10-06T10:45:02Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-Dragon-Ball-Sparking-Zero-Ultimate-AI\memory\aiplus-performance-constraint.md
---

Stated 2026-08-07: the AIplus mod must have effectively **zero** CPU overhead — "non-existent if possible" — and must not burden FPS. The user will call on this repeatedly ("when I call on you it's to see if we can make our mod utilize the right resources") as an ongoing audit role, not a one-time task. As of that date no mod logic exists yet, so this is a design constraint on what gets built, not an optimization backlog.

**Why:** the mod runs during live 5v5 matches on the user's machine; any per-frame cost is visible as dropped frames and defeats the point of an AI quality mod.

**How to apply:**
- Asset-only value edits (the current `FormChangeProbabilityMap` approach in [[leagueai-project-state]]'s successor design) cost **nothing** per frame — same UObject, same property reads, only load-time pak mount differs. Defend that path.
- The real cost surfaces, in order: UE4SS Lua hooks on hot functions > added behavior-tree nodes (evaluated per AI tick × up to 10 characters) > polling/logging loops. Push back before any of these land.
- Measure, don't assume: the archived harness `backups/aiplus-cleanup-20260807-0001/tools/perf/` (run_benchmark.py + analyze_presentmon.py + PresentMon) does controlled A/B captures. Its materiality thresholds: avg FPS −5%, 1% low −10%, or +5 frames over 50 ms in an equal 60 s run.
- Caution reading old data: the 2026-07-24 vanilla-vs-UE4SS captures both sat at a 60 FPS vsync cap (median 16.6 ms), so average FPS could not detect headroom loss. Any new benchmark should uncap or compare frametime percentiles.
