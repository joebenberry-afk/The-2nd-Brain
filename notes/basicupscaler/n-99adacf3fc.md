---
id: n-99adacf3fc
kind: gotcha
at: 2026-10-23T10:13:20Z
source: agent
tags:
  - git
  - worktree
---

git worktree remove deletes the worktree's ignored files too (runs/, data/ copies). Before removing, list the worktree and check for junctions/reparse points that could lead outside it; then remove, and git worktree prune.
