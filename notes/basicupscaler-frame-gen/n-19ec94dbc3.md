---
id: n-19ec94dbc3
kind: note
at: 2026-10-18T15:28:14Z
source: agent
---

K8 receipts moved to main runs/frame_generation (cohortK8, cohortK8-tools, live-queue29 + STATUS.md superseded note); C:/BU-wt/m1-k8 removed 2026-10-18 15:30Z. K8 candidate exe kept hash-bound only as D:/BU-gen/m1-gate/20261018T112343Z_m1-cohortK8/runs/*/bufg_m1_ed06ce01.exe.zst. Candidate recipe (K8 tools manifest): detached worktree, cargo build --release -p bu-cli -p bu-record -p bu-replay -p bu-t06-camera with CARGO_TARGET_DIR=<main>/target under gpu lock, copy exes to worktree target, bu-cli -> bufg_m1_<sha8>.exe; inputs.json based on previous cohort tools inputs.json.
