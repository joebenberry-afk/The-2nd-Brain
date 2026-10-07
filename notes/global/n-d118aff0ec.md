---
id: n-d118aff0ec
kind: gotcha
at: 2026-10-06T02:40:38Z
source: agent
errors:
  - Command timed out after 30 seconds. The JS worker was force-killed
tested: "true"
tested_by: owner
tested_at: 2026-10-06T10:04:55Z
tested_sha: 274366b49734
---

OMP JS eval cells die at 30 s by default and lose every variable
A JS eval cell that awaits slow tools (web reads, edit, wait, task, find, long bash) is force-killed at 30 s and its VM state reset; pass an explicit eval `timeout` (e.g. 180) for such cells, or call the slow tool directly instead of through eval. 32 such kills in 14 days (25 in BasicUpscaler).
