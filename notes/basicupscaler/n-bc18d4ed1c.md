---
id: n-bc18d4ed1c
kind: note
at: 2026-10-24T01:59:06Z
source: agent
---

BUFC X13 (24 Oct, receipt runs/frame_generation/20261024T015529Z_bufc-x13): on the owner's laptop panel (1920x1200, 165 Hz nominal, RTX 5070 Ti Laptop) the scan-line probe in s01 showed the refresh following the source (scanout gaps p50 8.30 ms at 60 fps, 12.04 ms at 82.5 fps), not a 165 Hz clock: treat it as variable refresh; any fixed-vblank model (C071, a DWM qpcVBlank pacer) needs checking against it. No VRR flag is recorded in receipts.
