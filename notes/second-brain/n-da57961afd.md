---
id: n-da57961afd
kind: gotcha
at: 2026-10-21T09:52:28Z
source: agent
errors:
  - timed out after 5000 ms
tested: "true"
tested_by: agent
tested_at: 2026-10-21T09:52:28Z
tested_sha: d6e8a666313e
---

claude plugin test: a test tool.call hook that awaits a gate blocks every tool call the test makes, setup calls included, so the test dies at 'timed out after 5000 ms'. Gate only the call under test (match e.command).
