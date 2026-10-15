---
id: n-6b8ced9a64
kind: gotcha
at: 2026-10-08T09:56:21Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-08T09:56:21Z
tested_sha: a60a6f84d5be
---

BUFG zipper fix (pixel_candidates=2 etc., fg-occl stash) punches holes in HUD/dialog text on real Relink frames (relink_4 144-162 -1.3 dB, relink_6 menus). Cause: extra per-pixel trajectories find flat matches over static text on panels with moving backgrounds. Fix measured: pixel_guard=16 (only the 4 nearest blocks' chosen vectors compete where one explains the pixel within 4x occ_tau) keeps ~65% of the zipper gain and real content +0.01/+0.02 dB vs no refinement. Fast paired suites: D:/BU-gen/fg_off/fgsuite.py (pairs) and fgseq.py (LiveFg sequences), driver D:/BU-gen/fg_off/batch_driver (sequence mode).
