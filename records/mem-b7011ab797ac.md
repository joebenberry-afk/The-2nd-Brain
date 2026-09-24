---
id: mem-b7011ab797ac
title: OMP compaction cancellation on 2026-09-13 came from a stale global brainctl 0.1.
type: fact
scope: project
project: second-brain
status: candidate
grade: OBSERVED
recorded_at: 2026-09-13T17:00:16.788423+00:00
origin: USER_AUTHORED
authority: project_rule
evidence:
  - outputs/reports/omp-compaction-repair-20260913.json@dad73784b3f2 (repo C:\Users\assas\Documents\The-Second-Brain)
---

OMP compaction cancellation on 2026-09-13 came from a stale global brainctl 0.1.0 writing schema-1 STOP events into the v2 ledger. Global CLI now shares qualified-v2 runtime; guarded recovery preserved 530 events and 526 existing hashes. Manual and automatic snapcompact passed with Brain enabled.
