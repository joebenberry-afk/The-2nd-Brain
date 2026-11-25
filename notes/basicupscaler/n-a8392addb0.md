---
id: n-a8392addb0
kind: gotcha
at: 2026-11-13T07:37:18Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-13T07:37:18Z
tested_sha: df28f93e1fd7
---

BUFG plan dispatch: per-call `model` in `task` is off; agent type decides the vendor. Observed 13 Nov: integration-engineer = anthropic/claude-opus-5-5 (breaks the owner's Gemini/GPT/deepseek-only rule; do not use for plan work), feature-implementer = gemini-4-hydrogen-high, performance-engineer and reviewer = gpt-6.1-sol. Make each agent write its model id to a file first and check it.
Also 13 Nov: D: drive not connected (plans 005, 007, 011 blocked). `arena/fg_structure.py:58 MAIN = ROOT.parents[2]` raises IndexError in worktrees under `C:/BU-wt/<name>`; 12 test files fail collection there; use a path 3+ levels deep (e.g. C:/BU-wt/velocity/008/tests).
