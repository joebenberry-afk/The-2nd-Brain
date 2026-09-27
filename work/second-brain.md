---
at: 2026-09-27T22:39:21Z
---

Goal: make V4 an agent's best friend (tokens, speed, reliability) via recursive swarm→fix rounds.
Done: V4 verified LIVE in OMP 18.3.5 (card 386 tok, tools mounted). Round-1 swarm (5 hunters, privacy, perf, Astra, Fable) → batch 5 workers running: Lifecycle (resume ≤150, subagent state guard, auto→state/), Card, Notes, Capture, SyncData.
Next: full gate (eslint/tsc/vitest), smoke card/recall/resume, commit, round-2 re-swarm on changed code, README.
Watch out: compaction re-inject measured 399 tok (budget 150); subagents could overwrite this plan via brain_state.
