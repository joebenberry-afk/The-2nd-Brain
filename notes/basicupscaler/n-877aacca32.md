---
id: n-877aacca32
kind: note
at: 2026-10-02T07:29:32Z
source: agent
---

Canonical BUNet game gate (runctl.stop_reason / others_vram_gib) counts a child Godot process's VRAM as 'other programs' (adapter total minus own torch use): a loaded Godot world (1.6-4.3 GiB) trips GAME_VRAM_GIB 2.0. godot_worlds.stop_reason subtracts live session pids via PDH 'GPU Process Memory' Dedicated Usage, which matched the adapter delta to 0.01 GiB (2 Oct, Task 10). godot_pairs likely has the same issue.
