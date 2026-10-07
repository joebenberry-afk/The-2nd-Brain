---
id: n-e36fd1e6ca
kind: decision
at: 2026-10-06T10:44:57Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-BasicUpscaler\memory\manage-disk-space.md
---

On 30 Sep 2026 the owner asked me to "make space something you're managing". C: had 70 GB free (D: 624 GB).

**Why:** my work piles up rebuildable caches and scratch files on C: (cargo `target/debug` 5.8 GB, review build dirs and captures in the session scratchpad 4 GB, `probe/host/target` 0.8 GB).
**How to apply:** check `Get-PSDrive` free space at the start of heavy work and after big runs. Clean what I created and can rebuild (`cargo clean --profile dev`, scratchpad dirs, probe target), never `data/` or the owner's files. Before any recursive delete, check for junctions/reparse points (worktrees link `data/`, `runs/`, `target/` into the main checkout), and remove those with `cmd /c rmdir` first. Put large new datasets or caches on D: when a location is free to choose. Keep `target/release` (bu.exe is in daily use). Related: [[fast-reliable-efficient]].

D: is exFAT with 1 MB clusters (checked 1 Oct 2026, `Win32_Volume.BlockSize`), so every small file takes a whole megabyte there. Caches of many small files balloon: the Triton cache `D:/bu/tc` holds 160 MB of files in 7.9 GB, and `D:/venvs/bunet-speed/cache` (30 Sep experiment caches) takes 13 GB. D: suits large files (frames, datasets); give throwaway `torch.compile` experiments their own cache folder so they can be removed, because `D:/bu` is the training cache that `train.py` says never to delete.
