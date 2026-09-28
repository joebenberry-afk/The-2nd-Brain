---
id: n-cba1928fb4
kind: gotcha
at: 2026-09-28T03:55:06Z
source: agent
errors:
  - yield used the last assistant turn as the result, but that turn contains no text
tested: "true"
---

Subagents: finish with visible text (or yield {"data": …}); a last turn with only thinking is rejected and retried, costing a turn.
