---
id: n-95ddb24fa2
kind: note
at: 2026-10-24T03:29:44Z
source: agent
evidence:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/probe.py
  - runs/frame_generation/20261024T024613Z_bufc-x2-rerun3/probe.py
evidence_sha:
  - runs/frame_generation/20261024T002031Z_bufc-x2-rerun/probe.py=cec7aa0863d5
  - runs/frame_generation/20261024T024613Z_bufc-x2-rerun3/probe.py=f9dea4d5b802
---

BUFC X2 rerun 3 (24 Oct 03:06Z, receipt runs/frame_generation/20261024T024613Z_bufc-x2-rerun3): foreground on this PC. AttachThreadInput to the foreground thread fails with error 5 (access denied) when the UWP Settings frame (ApplicationFrameWindow, ApplicationFrameHost.exe) is in front, so an attached SetForegroundWindow never runs. Fallback that worked first try: SendInput Alt by scan code 0x38 (press+release) then SetForegroundWindow. Later child sources took the foreground by themselves (no try needed); why not determined. Probe pattern: probe.py in that receipt.
