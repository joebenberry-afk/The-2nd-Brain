---
id: n-401bbbb0f7
kind: gotcha
at: 2026-10-17T06:11:09Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-17T06:11:09Z
tested_sha: e561fbf53c26
---

Claude Code behind ANTHROPIC_BASE_URL turns tool search off: set ENABLE_TOOL_SEARCH=true
CC 2.1.296 disables deferred tool search for a non-first-party base URL, so every request carries all tool schemas. claude -p probe, input tokens per request: direct 23,416; via brain proxy 38,221; proxy + ENABLE_TOOL_SEARCH=true 23,118. brain proxy passes tool_reference blocks through untouched (textOf skips non-text parts). probebench sets it for every e6 arm and the render arm.
