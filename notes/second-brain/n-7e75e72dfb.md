---
id: n-7e75e72dfb
kind: gotcha
at: 2026-10-21T08:21:40Z
source: agent
errors:
  - gitStatus still in context after prompt.context hook drops it
tested: "true"
tested_by: agent
tested_at: 2026-10-21T08:21:40Z
tested_sha: f77ea0a115ab
replaces: n-2fa032c706
---

To drop gitStatus set includeGitInstructions=false (or CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1); that also removes the commit/PR instructions. A prompt.context hook cannot: the engine sends its own gitStatus and currentDate (Claude Code 2.1.302).
