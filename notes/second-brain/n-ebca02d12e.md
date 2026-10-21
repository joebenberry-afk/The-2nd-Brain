---
id: n-ebca02d12e
kind: gotcha
at: 2026-10-21T09:02:56Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-21T09:02:56Z
tested_sha: a3a1559c6dee
---

Desktop app with PowerShell deferred (2026-10-21): PowerShell is in neither the front tool list nor the announced deferred-tool list, yet ToolSearch select:PowerShell still loads it and it runs (probe printed 5.1.26100.9711). The model only learns it exists from the env line 'Shell: PowerShell (primary)'.
