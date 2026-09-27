---
id: n-af0bf0109c
kind: gotcha
at: 2026-09-27T21:50:40Z
source: agent
tags:
  - omp
tested: "true"
---

OMP: Anthropic-native compaction drops every message before the compaction block, so post-compaction context must be inserted after the last compactionSummary message, not at index 0
