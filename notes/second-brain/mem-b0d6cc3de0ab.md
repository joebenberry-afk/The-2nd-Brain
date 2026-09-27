---
id: mem-b0d6cc3de0ab
kind: fact
at: 2026-08-14T07:03:40.370164+00:00
source: convert
evidence:
  - environment-20260814-281f85e7
  - run-integration.sh enabled/disabled checks
---

Prime print-mode runs route through a daemon that pins its own startup env

A shared prime-agent daemon does not see client env changes like SECOND_BRAIN_HOME. Integration runs need a dedicated --daemon-socket per run; production users must set SECOND_BRAIN_HOME before starting prime-agent.
