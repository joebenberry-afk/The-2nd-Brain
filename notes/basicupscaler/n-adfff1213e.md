---
id: n-adfff1213e
kind: procedure
at: 2026-10-23T10:13:17Z
source: agent
tags:
  - sqlite
  - codex
---

Read a live SQLite DB (e.g. Codex's) without locking or creating -wal/-shm: sqlite3.connect('file:<path>?mode=ro&immutable=1', uri=True). Never write codex-dev.db; its thread history is a record.
