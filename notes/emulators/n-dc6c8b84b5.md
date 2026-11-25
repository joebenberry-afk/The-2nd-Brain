---
id: n-dc6c8b84b5
kind: decision
at: 2026-11-25T21:03:00Z
source: agent
evidence:
  - src/fe-lab/remote/remote_build.py
checked: holds
checked_at: 2026-11-25T21:08:09Z
checked_why: remote_build.py docstring says compiles/runs unit tests only, no game data/keys/firmware, launches no game; ship/build/test/fetch-log commands present, host lap2 ALMIGHTY; owner parts not re-verified
checked_sha: 4f7fd3fcbe6e
replaces: n-3ceb1bf26e
---

Owner said on 2026-11-17 (not re-verified): use the 2nd laptop fully, and cap emulator launches at 10 per game per lane order; release-gate repeats beyond the cap need owner's OK. Split plan: this laptop (TheChosenOne) = timing measurements; lap2/ALMIGHTY = builds and unit tests via src/fe-lab/remote/remote_build.py (ship/build/test/fetch-log, seen 2026-11-25). That script's docstring says lap2 only compiles and runs unit tests: it copies no game data, keys or firmware and launches no game, so lap2 game runs are NOT implemented there. Standing rules from the old note, not re-verified: no speed figure from lap2 is published or used for a speed verdict; the owner's games/keys/firmware only move over the direct cable, never elsewhere or downloaded.
