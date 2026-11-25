---
id: n-4d39d5eb8a
kind: note
at: 2026-10-19T16:25:25Z
source: agent
---

M1 gotcha: a new bu-record flag must also be added to arena.session_record (T1) argparse and forwarded; otherwise T1 exits 2 and the arm is acquisition-failed (K24 flick, 19 Oct; fix bae6fe9).
