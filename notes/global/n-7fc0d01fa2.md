---
id: n-7fc0d01fa2
kind: gotcha
at: 2026-11-04T17:30:53Z
source: agent
---

DSH: per-subagent tool restriction — agent.ctx.tools.restrict() throws on names that are not inherited tools ("known global tools: …" in the message), and agent.ctx.tools.get(name) WITHOUT a scope can't see preset tools (read/grep live on the preset plane) — filtering by it silently strips them. Retry restrict with the names parsed from the error; add tools.guard for the child's own-layer tools (restrict never filters those). Tool args are deep-frozen: copy before normalizing. Blocking subagents: ctx.subagents.startActivation({provider:"spawn", childId, label, request:{prompt,parent,maxDepth,agentOptions}, signal, delivery:"caller"}) → await receipt.result; dispose() to stop (signal alone doesn't stop a published child). Implemented in default-workspace/dsh-agents.
