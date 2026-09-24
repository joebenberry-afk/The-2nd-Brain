---
id: mem-e0ee543da163
title: OMP 18.1.15 documented orchestration: task agents support role/model selection, 
scope: project
project: second-brain
status: current
grade: VERIFIED
version: 1
created_at: 2026-09-11T21:08:23.357470+00:00
---

OMP 18.1.15 documented orchestration: task agents support role/model selection, typed output/yield, fan-out and optional worktree isolation/apply/merge; Agent Hub supports steering, parked-agent revival, supervised jobs/processes and cancellation. Job completion does not establish independent acceptance of the task result. Isolation is optional and was disabled in the observed profile on 2026-09-11; shared-file edits are not guaranteed safe merges. Changing the parent model does not automatically remap every worker role. Read-only tool access is not an OS sandbox.
