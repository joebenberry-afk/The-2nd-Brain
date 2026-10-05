---
id: n-ea9aad28f2
kind: note
at: 2026-10-02T01:26:02Z
source: agent
---

Gotcha (1 Oct): D: is exFAT with 1 MB clusters, so small-file caches balloon: D:/bu/tc Triton cache = 160 MB of files but 7.1 GB on disk; D:/venvs/bunet-speed/cache = 13 GB of stale 30 Sep experiment caches. Other sessions run python -m arena.godot_pairs in bursts and hold runs/bunet_v1/gpu.lock (byte-range lock at offset 1<<20; check without torch via msvcrt.locking LK_NBLCK).
