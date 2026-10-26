---
id: n-9fac1c432d
kind: note
at: 2026-10-24T01:48:27Z
source: agent
evidence:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/outcome.md
evidence_sha:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/outcome.md=574ba7b1a282
---

Owned-source live probes (testsource + BU live): Windows may refuse the testsource the foreground (24 Oct 01:19Z: Settings app/ApplicationFrameHost in front, ForegroundLockTimeout already expired, testsource only ShowWindow(SW_SHOW)); BU live then pauses all arm (live.rs:802, 'Paused: capture ~4.0 fps, present 0.0 fps', 0-byte fg.jsonl, exit 0). Probe must bring source front (AttachThreadInput + SetForegroundWindow, no key; never with Roblox in front) and abort before BU launch if not. Receipts 20261024T002031Z_bufc-x2-rerun (void, outcome.md) and 20261024T014353Z_bufc-x2-rerun2.
