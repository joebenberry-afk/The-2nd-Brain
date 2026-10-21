---
id: n-4bb1fd8e64
kind: decision
at: 2026-10-21T09:38:33Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-21T09:38:33Z
tested_sha: 00d4ab1adb66
---

brain-view adds a session system-prompt section (prompt.compose, id brain-view:powershell) telling the model to load deferred PowerShell with ToolSearch select:PowerShell first. Why: the desktop app leaves deferred PowerShell out of the deferred-tool list while the environment line still says 'Shell: PowerShell (primary)'. With the hint, a headless probe went straight to ToolSearch and then PowerShell, with no Bash detour (2026-10-21).
