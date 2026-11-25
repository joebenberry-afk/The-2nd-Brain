---
id: n-94b3fd55ab
kind: note
at: 2026-11-25T21:00:59Z
source: agent
evidence:
  - AGENTS.md
evidence_sha:
  - AGENTS.md=26bdd80ff0ad
checked: holds
checked_at: 2026-11-25T21:08:17Z
checked_why: "AGENTS.md:66-67 states 60 GiB floor and 3 Nov permit; space_guard status shows C: 48.5 GiB free BELOW FLOOR, D: 162.8 free; 22 Oct sizes are labelled unverified"
checked_sha: 20bf33d9aa53
replaces: n-83e512455a
---

22 Oct 2026 disk audit (BasicUpscaler collection), not re-verified: space is receipts/data, not builds. FG runs/frame_generation 72G (20G png, 19G json, 14G jsonl), BU runs 57G (tpr_sparse 29G, godot_bench 12G), BU data 16G; all cargo target dirs ~4.6G; both .git 0.26G; source ~10M. The free-space floor in that audit (C: 100G) is superseded: BasicUpscaler/AGENTS.md:66-67 says free space never goes below 60 GiB on C: or D: (owner permitted C: below 100 GiB on 3 Nov 2026); check with python tools/space_guard.py status|check. Seen 25 Nov 2026: C: 49G free (below that floor), D: 163G free.
