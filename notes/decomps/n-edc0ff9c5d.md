---
id: n-edc0ff9c5d
kind: gotcha
at: 2026-11-07T19:29:15Z
source: agent
errors:
  - "FAIL  raise a caught Digimon / FAIL  database registered flags: hp 98, px 0, clock 1862 on a fresh run"
tested: "true"
tested_by: agent
tested_at: 2026-11-07T19:29:15Z
tested_sha: 7b036eba6607
replaces: n-8f6285ec64
---

Always Remove-Item $sg,"$sg.port" in DWC gates (never only the image) and treat a dwc-rs run whose output lacks 'play: ran' as a crash, not a logic failure. A rare pre-exit crash leaves no fresh port_save.bin, so the next gate loads a STALE port_save.bin.port sidecar and reports impossible values (hp 98, clock 1862, px 0).
