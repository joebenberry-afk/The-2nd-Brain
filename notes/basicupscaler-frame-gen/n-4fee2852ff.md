---
id: n-4fee2852ff
kind: note
at: 2026-10-18T19:36:47Z
source: agent
---

[gotcha] M1 FT-2 step needs ~75 GiB free on D: at step start: main arm retains ~5.8 GiB (roi.bgra etc.) until finish_step, then identity_control arm's ensure_room(9 GiB) must leave >=60. Stopped/failed attempts leave uncompacted .attempt-N data dirs (~3 GiB) on D: that cascade-fail later arms; move them to C:/BU-gen/m1-gate/<cohort>/stopped/ (K9, 18 Oct 19:40Z)
