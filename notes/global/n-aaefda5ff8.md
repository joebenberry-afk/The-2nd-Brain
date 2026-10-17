---
id: n-aaefda5ff8
kind: gotcha
at: 2026-10-17T09:20:03Z
source: agent
errors:
  - "`PUT` without `:` is clipboard-backed and takes no body rows"
tested: "true"
tested_by: agent
tested_at: 2026-10-17T09:20:03Z
tested_sha: 482a15d020ee
host: omp
---

OMP edit: a PUT row without a trailing colon is a clipboard paste and takes no body rows. Put the colon after the locator, then the +TEXT rows: `PUT 2.=2:` then `+new line`, or `PUT >40:` then `+TEXT`. Use the colonless form only with a CUT register (`PUT <N @name`).
