---
id: n-fdb49987ef
kind: decision
at: 2026-11-25T21:01:01Z
source: agent
evidence:
  - BasicUpscaler/AGENTS.md
checked: holds
checked_at: 2026-11-25T21:08:18Z
checked_why: Frame-Gen is 725-byte file; repo has 33 fg-* and 9 salvage/fg-* branches, snapshot/main-checkout-2026-10-10 contains tools/space_guard.py, C:/BU-wt worktrees, C:/BU-gen/m1-gate cohorts with MOVED.json, D:/BU-gen absent
checked_sha: 44cde734ae1b
replaces: n-e41ef69592
---

Frame generation lives in the BasicUpscaler repo at C:\Users\assas\Documents\BasicUpscaler\BasicUpscaler (branch main), since the 23 Oct 2026 architecture overhaul P1; the old sibling folder 'BasicUpscaler Frame-Gen' is now a 725-byte stub file. Seen 25 Nov 2026: that repo has fg-* branches (33), salvage/fg-* (9), snapshot/main-checkout-2026-10-10 (contains tools/space_guard.py), receipts in runs/frame_generation, architecture/, worktrees under C:/BU-wt. FG data: D:\BU-gen no longer exists; large cohort data is now at C:/BU-gen/m1-gate/<cohort> (MOVED.json records the D:->C: move). Owner directives of 10 Oct 2026 (not re-verified): no building until the architecture is approved; ideal-first design; failures count as diagnoses.
