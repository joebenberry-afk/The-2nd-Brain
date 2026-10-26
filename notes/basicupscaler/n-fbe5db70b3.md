---
id: n-fbe5db70b3
kind: note
at: 2026-10-23T17:53:52Z
source: agent
evidence:
  - modules/frame-capture/research/2026-10-22_bufc-capture/claims.csv
evidence_sha:
  - modules/frame-capture/research/2026-10-22_bufc-capture/claims.csv=0f10d4c0e86e
---

Git Bash sed -i on this PC strips CR from CRLF files (turned BUFC claims.csv to LF, 23 Oct). Edit CRLF registers with Python byte edits (read rb, replace, write wb) and check CRLF count after.
