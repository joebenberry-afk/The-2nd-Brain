---
id: n-ebd23ddc28
kind: decision
at: 2026-10-21T08:57:40Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-21T08:57:40Z
tested_sha: 0e6757a1af37
---

Cost pass 6 (2026-10-21): brain-view DEFER now includes PowerShell (17.9k-char schema). In 30 days, PowerShell ran 562 calls in 39 of 451 sessions; Bash ran 11,394 calls in 145. Headless first request 24.0k -> 20.3k. Deferred PowerShell still loads with ToolSearch select:PowerShell and runs (probe returned 5.1.26100.9711); the model may also reach Windows PowerShell from Bash. It was deferred rather than trimmed so its PS 5.1 gotchas are intact whenever it loads.
