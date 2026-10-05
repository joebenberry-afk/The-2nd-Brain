---
id: n-9fe7f3ce40
kind: gotcha
at: 2026-10-05T00:02:21Z
source: agent
errors:
  - Service mode does not accept async or timeout
tested: "true"
tested_by: owner
tested_at: 2026-10-05T03:56:44Z
tested_sha: 9101ce206da0
---

OMP bash with a `name` is service mode: it rejects async/timeout ("Service mode does not accept async or timeout")
For a finite job (build, eval, test) drop `name` and use async (or a plain foreground call with timeout); `name` + `ready` is only for long-lived servers. Seen 29 times; the retry without name/async always worked.
