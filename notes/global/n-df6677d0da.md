---
id: n-df6677d0da
kind: gotcha
at: 2026-11-03T23:57:42Z
source: agent
evidence:
  - BasicUpscaler/runs/frame_generation/20261103T192211Z_bufc-x3r2/protocol.md
  - BasicUpscaler/runs/frame_generation/20261103T195156Z_bufc-x3r3/protocol.md
  - BasicUpscaler/runs/frame_generation/20261103T174634Z_bufc-v2-scoreboard/protocol.md
evidence_sha:
  - BasicUpscaler/runs/frame_generation/20261103T192211Z_bufc-x3r2/protocol.md=52ac02eb419e
  - BasicUpscaler/runs/frame_generation/20261103T195156Z_bufc-x3r3/protocol.md=98ea27053697
  - BasicUpscaler/runs/frame_generation/20261103T174634Z_bufc-v2-scoreboard/protocol.md=ae79fecec229
---

Python one-liner `open(p,'w').write(open(p).read().replace(...))` truncates the file to 0 bytes: open(p,'w') is evaluated before the argument. Read into a variable first, then write. This wiped 4 frozen protocol.md + freeze.txt files in BUFC receipts (3 Nov 2026); restored from agent transcripts, code proved unchanged by mtimes/hashes.
