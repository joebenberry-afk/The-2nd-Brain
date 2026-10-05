---
id: n-c7a154e7bb
kind: note
at: 2026-10-01T09:34:37Z
source: agent
---

BUF guard (buf.py Neighbour): a 1b trainer relaunched after a pause keeps steps.jsonl's step continuous (cap_16x8_p1 row 701: 350500 -> 351000 after a pause at 350998), and thermal_pauses restarts at 0 per process. So launch boundaries cannot come from rows; buf reads the lock note every CHECK_S even while waiting, and gpu.lock's mtime (written at launch) vs steps.jsonl's mtime tells whether a launch has a row yet.
