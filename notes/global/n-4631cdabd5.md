---
id: n-4631cdabd5
kind: gotcha
at: 2026-10-10T19:18:02Z
source: agent
---

Gotcha: BasicUpscaler worktrees used directory junctions (data, runs, target) that point at the main checkout's 77 GiB runs/ and 15 GiB data/. Naive recursive deletion, or size walks that follow junctions, would delete or double-count them. Safe removal: os.rmdir each junction first (this removes only the link), check that the target still exists, then run git worktree remove --force. Also, some fg-* branches had force-added files under runs/, so moving receipts out makes those files show as tracked deletions. Verify with git hash-object --no-filters, because .gitattributes can change hashes.
