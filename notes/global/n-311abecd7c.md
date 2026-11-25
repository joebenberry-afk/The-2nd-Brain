---
id: n-311abecd7c
kind: gotcha
at: 2026-11-16T23:25:40Z
source: agent
---

Sub-agents have a soft request budget (~200 requests); past it a wake turn is cancelled ("Soft request budget exceeded (301 requests; budget 200)") and uncommitted work is all that remains.
Large slices on the default sub-agent model compacted at ~135K context and looped re-reading headers for 40 min with zero writes (Capture06B, Replay06C). Fix: split slices to ≤2-5 files, brief as a file with "notes file first, write code within 25 requests, commit after every file", check `git status`/rev-list of the worktree after ~10 min instead of trusting request counts. Per-call `model` is refused when the agent type has task.agentModelOverrides (feature-implementer, task): omit model.
