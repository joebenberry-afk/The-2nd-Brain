---
id: n-4cf4dc15db
kind: decision
at: 2026-11-17T08:31:39Z
source: agent
checked: holds
checked_at: 2026-11-25T17:59:25Z
checked_why: The folder exists at the stated size with the stated contents, and the bare repo lists 104 branches. D:/EglantineReturn does not exist yet, which does not contradict the statement. I did not count the 9 pinned rows exactly. [D:/EglantineTransfer (218 MB, README_TRANSFER.md with 11 table rows, eglant
checked_sha: 6aea9cf24725
---

Second-computer build lane: transfer folder D:\EglantineTransfer (made 04:40, 218 MB)
Bare shallow clone eglantine.git (all 104 branches), cpm-cache, deps, plans, fe-lab tools, README_TRANSFER.md with 9 pinned rows (acc/base ae300166 first). Outside model (Gemini) builds + unit-tests there, returns D:\EglantineReturn (report.md, logs, ext.bundle with ext/<branch> fix branches). Updates go out as update-N.bundle. Import: git fetch bundle, review, re-stamp identity if needed, cherry-pick. Kernel ledger["transfer"] holds pins.
