---
id: mem-174b3f5abbba
title: Driver may execute trivial deterministic work
scope: project
project: second-brain
status: current
grade: VERIFIED
version: 1
created_at: 2026-08-16T00:36:05.094850+00:00
---

Amendment section 31 acceptance item 3 overrides the original 'driver must not perform routine execution': the driver MAY execute trivial deterministic work (e.g. a one-line status read), but must not personally execute substantial work when delegation is advantageous. The Sol hard-orchestrator contract and delegation policy prompt need this allowance.
