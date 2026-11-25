---
id: n-cfc3a5fa3c
kind: note
at: 2026-10-19T08:19:22Z
source: agent
evidence:
  - target/release/bu.exe
evidence_sha:
  - target/release/bu.exe=82a7cdf5aa9b
---

M1 candidate exe is bu.exe (crates/bu-cli, ~4 MB), not BasicUpscaler.exe (bu-app GUI, ~25 MB). Copy target/release/bu.exe to bufg_m1_<sha8>.exe before m1_gate plan. m1_gate plan --out takes a NEW cohort directory (mkdir exist_ok=False) and writes freeze.json + queue.json in it.
