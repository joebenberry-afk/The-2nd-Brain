---
id: n-6ada18cf9e
kind: fact
at: 2026-10-14T11:49:12Z
source: agent
---

Disk cause found on 14 Oct: C:\pagefile.sys is system-managed and was 36 GiB. It grows under memory pressure from parallel cargo builds, games and GPU tests, and that matches the 15-30 GiB free-space swings that blamed an 'external writer'.
Other large C: users at that time:
- BUFG runs/: 72.5 GiB
- BasicUpscaler/runs: 56.5 GiB (tpr_sparse 28.5, godot_bench 11.3, fill 6.7)
- BasicUpscaler/data: 15 GiB (gameir 11.9)
- Steam games on C:: 47.8 GiB
- ~/.cache: 14.5 GiB
- Temp: 12.5 GiB
- NVIDIA DXCache: 9.8 GiB
- hiberfil.sys: 6.1 GiB
Git worktrees were not the cause: bu-diet 0.19 GiB and fg232-repro 0.03 GiB were removed after their receipts were merged into main runs/. Run fewer parallel builds to limit pagefile growth.
