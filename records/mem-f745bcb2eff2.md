---
id: mem-f745bcb2eff2
title: Adaptive fan-out replaces the hard 2-worker cap
type: fact
scope: project
project: second-brain
status: superseded
grade: VERIFIED
recorded_at: 2026-08-16T00:36:05.052477+00:00
supersession_kind: invalidates
supersession_reason: Brain orchestration removed (orchestrator-removal gate, 2026-09-23); approved in the V3 currentness sweep
superseded_at: 2026-09-23T00:00:00+00:00
origin: MODEL_INFERENCE
evidence:
  - Second_Brain_P0-P2_Maximum_Prime_Agent_Harness_Amendment.md
---

The P0-P2 Maximum Prime-Agent Harness Amendment section 12.2 replaces the original hard 'default 1 / max 2 workers' ceiling with adaptive fan-out: default conservative width, config/env-driven maximum, hard resource ceiling, and telemetry. Ordinary tasks may still use two; wide independent audits may use more; constrained local models may use one or zero.
