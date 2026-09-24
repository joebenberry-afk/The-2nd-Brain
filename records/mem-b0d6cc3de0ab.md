---
id: mem-b0d6cc3de0ab
title: Prime print-mode runs route through a daemon that pins its own startup env
type: fact
scope: project
project: second-brain
status: candidate
grade: TESTED
recorded_at: 2026-08-14T07:03:40.370164+00:00
origin: MODEL_INFERENCE
evidence:
  - environment-20260814-281f85e7
  - run-integration.sh enabled/disabled checks
---

A shared prime-agent daemon does not see client env changes like SECOND_BRAIN_HOME. Integration runs need a dedicated --daemon-socket per run; production users must set SECOND_BRAIN_HOME before starting prime-agent.
