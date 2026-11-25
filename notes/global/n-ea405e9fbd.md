---
id: n-ea405e9fbd
kind: gotcha
at: 2026-11-04T17:08:10Z
source: agent
---

DSH Host plugin calling ctx.llm directly: with Anthropic max reasoning effort and a small maxTokens, the stream ends with no text block (all budget spent on reasoning) — looks like "empty result". Use medium effort or a larger maxTokens. Linked local plugin code reloads via plugin_manager set_plugin include:<id> false→true (no app restart needed).
