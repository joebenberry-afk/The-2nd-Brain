---
id: n-bf3f191f0a
kind: note
at: 2026-11-25T21:09:28Z
source: agent
evidence:
  - modules/frame-pacer/README.md
  - FramePacing.md
  - arena/FRAME_HOOK.md
evidence_sha:
  - modules/frame-pacer/README.md=da81d094004b
  - FramePacing.md=54fad5a22373
  - arena/FRAME_HOOK.md=7f2bda99fe66
checked: holds
checked_at: 2026-11-25T21:10:19Z
checked_why: b9350e64 25 Oct DECISIONS 58, module files, no Pacer folder in Documents, FP-17 link, frame_hook files, nine bufp_* only on salvage ref (not ancestor), m2-bufp ae071e4d 10 Oct
checked_sha: 8bd8ef06b722
replaces: n-f1f1936cf0
---

BUFP module made 25 Oct 2026 (commit b9350e64, DECISIONS 58): modules/frame-pacer/ holds README.md, ROADMAP.md and research/2026-10-02_bufp-research-package/
Seen 25 Nov 2026 in BasicUpscaler/BasicUpscaler: no 'BasicUpscaler Frame-Pacer' zip or folder under Documents; FramePacing.md still links ../BasicUpscaler_Frame_Pacer_Research_Package/ (FP-17). The frame hook is on main: arena/frame_hook*.{cpp,h,py} and arena/FRAME_HOOK.md (protocol 7). The nine arena/bufp_*.py/.ps1/.cpp BUFP tools are not on main; they are on refs/archive/bu/salvage/bu-main-2026-10-22, which is not an ancestor of main. refs/archive/bu/heads/salvage/m2-bufp exists (ae071e4d, 10 Oct 2026, uncommitted state of worktree m2-bufp); the earlier note said the M2 cap lives only there, not re-checked.
