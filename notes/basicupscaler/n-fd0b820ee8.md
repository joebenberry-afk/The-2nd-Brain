---
id: n-fd0b820ee8
kind: gotcha
at: 2026-11-13T17:57:35Z
source: agent
errors:
  - "Cloud Code Assist API error (429): Individual quota reached"
---

Gemini (google-antigravity/gemini-4-hydrogen-high) has an individual quota; after ~15 parallel agent-hours on 13 Nov it returned 429 QUOTA_EXHAUSTED with a ~40 min reset. Agents die with no output; re-dispatch after quotaResetTimeStamp. Second-vendor checks of GPT work then stall: keep Gemini concurrency ≤2.
