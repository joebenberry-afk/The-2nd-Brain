---
id: n-5584ffe6dd
kind: decision
at: 2026-10-11T08:52:17Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-11T08:52:17Z
tested_sha: 3a4191ba5d62
replaced_by: n-b2db657b03
retired: 2026-10-15T08:02:50Z
---

Tora now runs inside the Second Brain's judged recall (built 11 Oct; IDEAS TI-03). Tora's per-session MCP server serves POST /score on localhost with a bearer token, published in %LOCALAPPDATA%\tora\sessions\<pid>.json. The Brain's brain/src/tora.ts sends Jev up to 2 notes it missed that score ≥ Tora's cut 0.7605, and logs a skip floor of 0.70 in shadow mode. Turn the skip on with BRAIN_TORA_SKIP=on only after `brain stats` says "skip floor: ready" (lost 0 and ≥150 kept). BRAIN_TORA=off disables Tora. Every failure falls back to exact current behaviour. Both OMP sessions need a restart to load it.
