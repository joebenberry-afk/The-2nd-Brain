---
id: n-3cc77d15ee
kind: note
at: 2026-10-01T03:09:37Z
source: agent
---

Coverage denominators in a measurement must start when the instrument started recording (first matched event): frames from before a collector started count as never seen, and startup time varies per run. BasicUpscaler L23 (arena/latency.py).
