---
id: n-f977fcef7b
kind: note
at: 2026-10-02T01:52:50Z
source: agent
---

BUNet step profile FINAL (1 Oct, 3 guarded runs, runs/bunet_v1/1b/speed/fast_profile.md): 16x8 step is GPU-bound (7.5-8.1 ms as trained, 7.1-7.6 no sampler); sampler prefetch = no gain (plans 7.93, thread 7.92 vs 7.94; +1.0 ms host spin is free). Loss graphs 6.5-7.0 ms GPU = net 4.2 (bwd 3.17) + tail 2.06 + EASU 0.87. Best remaining: run EASU+tail only on the loss-core window: -1.45 ms (~18%), measured as separate pieces, not built (IDEAS SPD-30). Trainer spins all 16 OpenMP threads (data.synthetic float64 ops wake the pool): 15.7 cores busy, CPU pkg at cap; set_num_threads(1) -> 0.7 cores, -23 W, 16x8 step +6.8% here, batches bit-identical (SPD-31, owner's call). Launch 45-75 s -> stack members at short N (SPD-29).
