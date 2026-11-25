---
id: n-7ccebd595a
kind: note
at: 2026-10-18T20:31:10Z
source: agent
---

Crosshair square (owner-seen, 18 Oct): fg_standalone_repose.hlsl copies every pixel inside camera exclusion rects un-re-posed while the rest is homography re-posed. Cyberpunk profile rects: crosshair-spread [890,550,1030,650] and viewmodel [540,550,1490,1200]. K9 gate-open frames ~85%; max_displacement_px p50 13.5 (clip_pan_slow), 37.2 (diagonal) = seam jump at box edges. Fix belongs to M2 HUD masks: copy only HUD pixels (label/static mask), re-pose the background inside rects.
