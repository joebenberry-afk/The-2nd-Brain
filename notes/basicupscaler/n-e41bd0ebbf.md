---
id: n-e41bd0ebbf
kind: note
at: 2026-10-02T01:52:51Z
source: agent
---

Gotchas from the 1 Oct BUNet profile: (1) torch thread count is a dynamo global-state guard: torch.set_num_threads after the first compile recompiles every compiled fn; set it before compiling. (2) cProfile on Python 3.14 records other threads too (the ThermalGuard sampler showed up), so its per-function split is unreliable in the trainer. (3) torch.cuda.set_sync_debug_mode('warn') found no sync in the fast step. (4) Throwaway torch.compile experiments should use their own TORCHINDUCTOR/TRITON cache dirs: my follow-ups added 106 entries (~0.95 GB on exFAT D:) to D:/bu, which train.py says never to delete.
