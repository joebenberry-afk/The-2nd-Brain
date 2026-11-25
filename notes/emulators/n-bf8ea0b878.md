---
id: n-bf8ea0b878
kind: gotcha
at: 2026-11-15T17:25:36Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-15T17:25:36Z
tested_sha: 4350bc3bbd7a
checked: moved
checked_at: 2026-11-25T17:59:30Z
checked_why: The fallback chain [sonnet-5-5, haiku-5-5] for gemini-4-hydrogen is now persisted in config.yml and task.perCallModel is "on", so the claim that per-task model is rejected and the chain is the only lever is out of date. The owner-preference and kernel wait() exit-130 parts can't be checked from disk
checked_sha: 4350bc3bbd7a
replaces: n-5226e0af48
retired: 2026-11-25T21:00:04Z
---

Model substitutes when google/gemini-4-hydrogen is down: owner wants Sonnet 5.5 as substitute, Haiku 5.5 for simple tasks.
The task tool rejects a per-task `model` ("Per-call model is disabled for task calls (task.perCallModel: off)"), and eval agent() has no model parameter. The only working lever is cfg://retry/fallbackChains: "google/gemini-4-hydrogen": ["anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-5-5"] (a session write; persists only via cfg://retry/fallbackChains/save after the owner agrees). The chain is per model, so it cannot send simple tasks to Haiku: that needs task.perCallModel on, or a per-agent model override for sonic/scout.
A kernel-side wait() on agent handles dies with exit 130 when the user interjects and cancels those agents: for long fan-outs use the task tool and have agents write result files.
