---
id: n-aab93ad928
kind: note
at: 2026-10-01T19:04:28Z
source: agent
---

Measured GPU cost model (RTX 5070 Ti Laptop, project guard, 720p->1080p, EASU+RCAS chain 0.1364 ms): time follows fxc instruction slots at ~0.036 ms per 100 slots; no extra fetches needed. Rewriting EASU tap distance as one quadratic form (same formula) = 252 vs 301 slots, chain -8.9%. Use 19_verification/gpu_bench (interleaved rounds, timestamp queries) to price any shader term.
