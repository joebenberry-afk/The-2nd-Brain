---
id: n-b8ad95b79a
kind: note
at: 2026-11-12T20:58:42Z
source: agent
evidence:
  - Lab 2/Q4/src/main.c
evidence_sha:
  - Lab 2/Q4/src/main.c=75b7eb52071b
---

ECNG3006 labs: board = Arduino MKR Zero (PlatformIO atmelsam, briscoetech/FreeRTOS_SAMD21 V10.2.0), NOT ESP8266. pio not on PATH: use ~/.platformio/penv/Scripts/pio.exe. Library has weak vApplicationIdleHook calling loop(); define a strong one in main.c to override. Lab 2 Q4 owner chose IDLE hook mechanism only (not trace macros).
