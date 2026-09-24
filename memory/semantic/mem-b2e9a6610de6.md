---
id: mem-b2e9a6610de6
title: CountUpUseBlast caller disambiguation hypothesis
scope: domain
project: 
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-28T09:06:48.461396+00:00
---

T1 run 1 established identity and transport correctness but not semantic cardinality: one reported Kefla Blaster Ball activation yielded 13 raw callbacks and 7 accepted blast_used events, with 6 duplicate-window rejects; no identity rejects, queue drops, gaps, stale bundle, or mixed action hook. Treat CountUpUseBlast as a multi-path callback boundary until per-callback caller/callsite evidence identifies a cluster with one callback per real activation. Probe cheaply for timestamp, sequence, thread/object/actor pointers, side/team slot, character/form, reflected slot, raw args, caller/return address or module-relative RVA, candidate callsite, and existing numeric state. Cross-reference runtime clusters with static BuildID 24497537 callers. Do not widen deduplication or emit technique_used.
