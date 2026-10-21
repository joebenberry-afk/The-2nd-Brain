---
id: n-a2cefd58cd
kind: decision
at: 2026-10-21T07:36:17Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-21T07:36:17Z
tested_sha: 099ed0fa7b9f
---

Claude Code cost pass 2 (2026-10-21): disabled intent@intent and typesafe@typesafe-ai plugins in ~/.claude/settings.json, and brain-view mod hides 0-use skills from the skill_listing attachment via prompt.attachment (HIDE regex: design suite, anthropic-skills docs/pdf/pptx/xlsx/docx etc, deepeval, abdiff, dependency-evaluator, duplicate deep-research/skill-creator/code-review). Listing 98 -> 55 entries, 30.0k -> 17.7k chars. Headless first request 37.7k -> 32.9k tokens (-13%). Hidden skills still run via /name. Why: 437 sessions/30 days invoked none of them. Desktop baseline was 51.1k with tool deferral only; re-measure in a fresh desktop session.
