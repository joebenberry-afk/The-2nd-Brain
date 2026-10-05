---
id: n-53a2dee97f
kind: gotcha
at: 2026-10-02T16:17:36Z
source: agent
tags:
  - rtss
errors:
  - "PermissionError: [Errno 13] Permission denied"
tested: "true"
---

RTSS profile folder (C:\Program Files (x86)\RivaTuner Statistics Server\Profiles) is admin-only: writing a .cfg as a normal user fails with PermissionError [Errno 13]. Workaround used by the probe: copy the test exe under the file name of a game that already has an RTSS profile (RTSS matches by exe name), e.g. SparkingZERO-Win64-Shipping.exe = 60 fps async. For other limiter modes the owner must add a profile for bu_rtss_probe.exe in the RTSS UI, then run: python runs/rtss_probe/rtss_probe.py own
