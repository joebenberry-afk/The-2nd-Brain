---
id: n-84cc8ddde8
kind: gotcha
at: 2026-10-17T07:37:10Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-17T07:37:10Z
tested_sha: cb31d0c12947
replaced_by: n-5436ee085c
retired: 2026-10-17T08:32:03Z
---

Claude Code brain hooks cost ~137 ms each in process spawn, which makes the brain arm 9-13% slower at equal tokens. — Windows, Node 26: `bash -c exit` 34 ms, node hook started directly 102 ms, via `bash -c` 137 ms (UserPromptSubmit); brain telemetry shows card work at 0 ms. E2 d10: filler turns 5.47 vs 4.28 s mean, same cacheRead/output. Six synchronous hooks fire per session (SessionStart, UserPromptSubmit, PostToolUse on Bash|PowerShell|Edit|Write|MultiEdit, PostToolUseFailure, PreCompact, SessionEnd). Owner options, not applied: make SessionEnd async; a lean hook entry that skips cli.ts imports.
