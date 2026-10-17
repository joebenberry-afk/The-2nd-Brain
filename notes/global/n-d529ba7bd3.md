---
id: n-d529ba7bd3
kind: note
at: 2026-10-16T00:51:33Z
source: agent
replaces: n-65f138ef65
---

Arzopa Z3FC portable monitor (2026-10-15): Windows HDR over USB-C DP gives a black screen on the RTX 5070 Ti laptop regardless of power (not a power brownout), refresh (60-180Hz), or pixel format (RGB/YCbCr444/422, 8/10bpc, full/limited). The monitor stays enumerated while black. Cause is undetermined: enumeration alone does not prove a scaler-firmware bug, and no public Z3FC firmware exists to test. Working setup: SDR 2560x1440 180Hz RGB full 8bpc, G-SYNC Compatible on, Windows VRR on. Gotcha: GDI \.\DISPLAYn numbering swapped mid-session; resolve display by EDID name before ChangeDisplaySettingsEx.
