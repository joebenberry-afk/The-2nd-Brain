---
id: n-c57f253ced
kind: gotcha
at: 2026-11-22T22:02:01Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-22T22:02:01Z
tested_sha: 695b3b716435
---

Switch 2 GPU memory: Nx2Map reused SMMU device ranges keyed by {cpu,size}; DeviceMemoryManager::Map pins physical pages at map time, so after gpu sub 102 free + 101 re-register at the same VA the GPU read stale pages (XC2 area change: VS programs rejected, world invisible). Fixed in 9018e12ca1 by page-compare + re-map in GPU order. Symptom: rejected program headers look like texture data/zeros while CPU read_memory shows valid code.
