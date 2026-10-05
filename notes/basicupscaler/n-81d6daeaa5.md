---
id: n-81d6daeaa5
kind: note
at: 2026-10-02T12:41:08Z
source: agent
---

Godot 4.7.2: positional (Omni/Spot) shadow-atlas slots persist across draws; with soft shadow filtering a few px near lights depend on draw history (cross-process D2 fails). Fix: set each SubViewport.positional_shadow_atlas_size to 0 then back before each capture; verified identical across 4 orders x 4 tiers (godot-worlds pilot 2026-10-02).
