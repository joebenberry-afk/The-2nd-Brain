---
id: n-ba1a2bd24c
kind: note
at: 2026-10-01T03:09:37Z
source: agent
---

Cache files checked by mtime must be written atomically (write a temp file, then os.replace): an interrupted in-place save leaves a truncated file newer than its source, and the mtime check keeps it forever. Found as BasicUpscaler L25 (arena/datasets.py prepare).
