---
id: mem-174b3f5abbba
title: Driver may execute trivial deterministic work
type: fact
scope: project
project: second-brain
status: superseded
grade: VERIFIED
recorded_at: 2026-08-16T00:36:05.094850+00:00
supersession_kind: invalidates
supersession_reason: Brain orchestration removed (orchestrator-removal gate, 2026-09-23); approved in the V3 currentness sweep
superseded_at: 2026-09-23T00:00:00+00:00
origin: MODEL_INFERENCE
evidence:
  - Second_Brain_P0-P2_Maximum_Prime_Agent_Harness_Amendment.md
---

Amendment section 31 acceptance item 3 overrides the original 'driver must not perform routine execution': the driver MAY execute trivial deterministic work (e.g. a one-line status read), but must not personally execute substantial work when delegation is advantageous. The Sol hard-orchestrator contract and delegation policy prompt need this allowance.
