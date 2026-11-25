---
id: n-dc6c8b84b5
kind: decision
at: 2026-11-25T21:03:00Z
source: agent
evidence:
  - src/fe-lab/remote/remote_build.py
replaces: n-3ceb1bf26e
---

Owner said on 2026-11-17 (not re-verified): use the 2nd laptop fully, and cap emulator launches at 10 per game per lane order; release-gate repeats beyond the cap need owner's OK. Split plan: this laptop (TheChosenOne) = timing measurements; lap2/ALMIGHTY = builds and unit tests via src/fe-lab/remote/remote_build.py (ship/build/test/fetch-log, seen 2026-11-25). That script's docstring says lap2 only compiles and runs unit tests: it copies no game data, keys or firmware and launches no game, so lap2 game runs are NOT implemented there. Standing rules from the old note, not re-verified: no speed figure from lap2 is published or used for a speed verdict; the owner's games/keys/firmware only move over the direct cable, never elsewhere or downloaded.
