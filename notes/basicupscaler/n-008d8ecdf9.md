---
id: n-008d8ecdf9
kind: note
at: 2026-10-18T15:32:24Z
source: agent
checked: holds
checked_at: 2026-11-25T20:52:46Z
checked_why: commit 779021f exists (BasicUpscaler/BasicUpscaler git show), msg says gain x1.3 pitch opens 8.5% >5%, not for merge; Frame Gen.md FG-388 FAIL, FG-390 v2 lattice mixture
checked_sha: bb5120df7e71
---

FG-388 gate fix FAIL (frozen): Gaussian sigma inflated to ~1 count admits count jitter but also absorbs systematic gain/lag errors (gain x1.3 control opened 8.5%). Quantization is discrete: v2 = count-lattice mixture H0 + signed persistence term. Commit 779021f kept as record, not merged.
