---
id: n-2f1fb1f7e1
kind: fact
at: 2026-10-03T02:53:12Z
source: agent
tags:
  - frame-pacer
  - gemini
tested: "true"
---

2 Oct ~22:50: checked Gemini's claim that BU's pacer beats RTSS (FramePacing section 21 scorecard). Not validated: no measured head-to-head on the same path. Its pipeline simulation's 13.4 ms gain = hook handoff + display-aligned start, with 2.4% missed deadlines and 5x RTSS's cadence SD; swapping handoffs alone changes nothing (vsync quantisation); making the model causal (worst of last 60 frames instead of the frame's own cost) and matching RTSS's miss rate leaves about 8 ms (24%). timer_bench used timeBeginPeriod+TIME_CRITICAL+spin (not DECISIONS 16). Section 27's 4.4% cadence gain is within one standard error. Only hardware A/B vs real RTSS (Codex section 26): FP timer 4-6% core vs RTSS 29-38%, but RTSS 15x more even (11 us vs 170 us); latency not measured on a display. Logged as FramePacing section 28, FP-85..87, FPF-065. Improvements: three separate contests; compare at equal miss rate (margin curve); causal trace-fed simulation; normal-priority timer benchmarks; paired stats with standard errors; decisive test needs the hook on a real game.
