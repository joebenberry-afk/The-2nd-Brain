---
id: n-ff64ce6dd2
kind: gotcha
at: 2026-10-23T10:13:16Z
source: agent
tags:
  - windows
  - rename
errors:
  - "PermissionError: [WinError 5] Access is denied"
---

Windows refuses to rename a folder while any process has its cwd or an open handle inside it (shells, Codex, Explorer). Close or move them first; P1 Task 14 rehearsed the rename with a held handle and a rollback.
