---
id: mem-f745bcb2eff2
title: Adaptive fan-out replaces the hard 2-worker cap
scope: project
project: second-brain
status: current
grade: VERIFIED
version: 1
created_at: 2026-08-16T00:36:05.052477+00:00
---

The P0-P2 Maximum Prime-Agent Harness Amendment section 12.2 replaces the original hard 'default 1 / max 2 workers' ceiling with adaptive fan-out: default conservative width, config/env-driven maximum, hard resource ceiling, and telemetry. Ordinary tasks may still use two; wide independent audits may use more; constrained local models may use one or zero.
