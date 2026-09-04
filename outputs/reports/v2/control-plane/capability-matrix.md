# Universal Harness Capability Matrix (T7.7)

Repository-true capability matrix across supported and available harnesses.
Missing capabilities degrade to conservative lower tiers (T0/T1) without faking support.

## Capability Summary

| Harness | Tier | Supported | Unsupported | Unknown | Primary Behavior |
|---|---|---|---|---|---|
| `prime` | **T2** | 9 | 1 | 0 | Fully governable harness: model rewriting, tool filtering, s... |
| `claude-code` | **T2** | 7 | 3 | 0 | Fully governable harness: model rewriting, tool filtering, s... |
| `codex` | **T1** | 4 | 6 | 0 | Operationally observable harness: tool, usage, cache, or com... |
| `antigravity` | **T2** | 5 | 5 | 0 | Fully governable harness: model rewriting, tool filtering, s... |
| `hermes` | **T2** | 6 | 4 | 0 | Fully governable harness: model rewriting, tool filtering, s... |

## Detailed Matrix

| Capability | Prime | Claude Code | Codex | Antigravity | Hermes |
|---|---|---|---|---|---|
| `subagents` | YES | YES | NO | YES | YES |
| `compaction_events` | YES | YES | NO | NO | NO |
| `usage_telemetry` | YES | YES | YES | YES | YES |
| `budget_enforcement` | YES | NO | NO | NO | NO |
| `model_rewrite` | NO | NO | NO | NO | NO |
| `cache_telemetry` | YES | YES | NO | NO | YES |
| `prompt_injection` | YES | YES | YES | YES | YES |
| `session_events` | YES | YES | YES | YES | YES |
| `tool_filter` | YES | NO | NO | NO | NO |
| `tool_events` | YES | YES | YES | YES | YES |
