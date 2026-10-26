---
id: n-ea2924bb8b
kind: note
at: 2026-10-22T20:38:54Z
source: agent
---

ECNG3006 labs: board Arduino MKR Zero (SAMD21), PlatformIO env mkrzero/atmelsam/arduino. pio not on PATH: use ~/.platformio/penv/Scripts/pio.exe. Arduino Serial is C++ only; for .c programs wrap it in a .cpp shim with extern "C" guards in the HEADER (extern "C" on .cpp defs alone gives 'conflicting declaration ... with C linkage'). Folder names with spaces build fine.
