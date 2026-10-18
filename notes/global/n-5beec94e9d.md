---
id: n-5beec94e9d
kind: decision
at: 2026-10-18T06:29:01Z
source: agent
---

Owner (2026-10-18): Claude Code agents may swarm with Haiku 5.5 subagents. User-level agent ~/.claude/agents/haiku-swarm.md (model claude-haiku-5-5; the `haiku` alias also resolves to claude-haiku-5-5 in Claude Code 2.1.302). Smoke: `claude -p "<prompt>" --allowedTools "Task,Agent,Read"` dispatched it (modelUsage showed claude-haiku-5-5). Note: put the prompt before --allowedTools, which is variadic and swallows it. Mention haiku-swarm in Orca worker specs.
