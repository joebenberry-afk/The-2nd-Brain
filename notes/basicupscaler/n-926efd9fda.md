---
id: n-926efd9fda
kind: note
at: 2026-09-29T14:00:14Z
source: agent
---

Sparking ZERO pairs work: owner-approved UE4SS mod Mods/CapturePause (F8 SetGamePaused) + tools/sz_pairs.py. Game only takes standard sizes and pillarboxes 16:10 in 16:9 → capture 1280x720→1920x1080, crop to 1152x720→1728x1080. Game draws its own pointer and keeps the clamped spot when the window grows: park mouse at client (10,300) in the cropped bar; tools/pointer.py drops leftovers. Left paused over a level change = stuck white screen. 72 pairs / 12 stages.
