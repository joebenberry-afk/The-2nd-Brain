---
id: mem-b7011ab797ac
title: OMP compaction cancellation on 2026-09-13 came from a stale global brainctl 0.1.
scope: project
project: second-brain
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-09-13T17:00:16.788423+00:00
---

OMP compaction cancellation on 2026-09-13 came from a stale global brainctl 0.1.0 writing schema-1 STOP events into the v2 ledger. Global CLI now shares qualified-v2 runtime; guarded recovery preserved 530 events and 526 existing hashes. Manual and automatic snapcompact passed with Brain enabled.
