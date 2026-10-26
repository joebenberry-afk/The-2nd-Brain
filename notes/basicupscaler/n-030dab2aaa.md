---
id: n-030dab2aaa
kind: note
at: 2026-10-24T01:48:28Z
source: agent
evidence:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/analyze.py
  - runs/frame_generation/20261024T014353Z_bufc-x2-rerun2/analyze.py
evidence_sha:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/analyze.py=bbe727182145
  - runs/frame_generation/20261024T014353Z_bufc-x2-rerun2/analyze.py=c02408dde51a
---

Frozen analyze.py gotcha: compute validity before reading records[0]; a zero-record arm crashed X2 rerun scoring (IndexError) instead of voiding it. Also validate the source held foreground from bu_launch to source_exit-0.5 s (poller field 5).
