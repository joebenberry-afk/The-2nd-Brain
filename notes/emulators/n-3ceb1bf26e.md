---
id: n-3ceb1bf26e
kind: decision
at: 2026-11-17T18:54:37Z
source: agent
evidence:
  - src/fe-lab/remote/remote_build.py
evidence_sha:
  - src/fe-lab/remote/remote_build.py=c1dea1e812aa
checked: moved
checked_at: 2026-11-25T17:59:45Z
checked_why: The ship/build/test/fetch-bin driver exists, but its docstring says lap2 only compiles and runs unit tests, copies no game data, and launches no game. That contradicts the note's plan for lap2 correctness game runs. The owner's cap and speed-figure rules can't be checked from files. [C:/Users/assas/
checked_sha: 99e05eed72d8
---

Owner (Nov 17): "make full use of the 2nd laptop, do what gives the greatest gains" + cap of 10 emulator launches per game per lane order.
Split: this laptop (TheChosenOne, RTX 5070 Ti) = timing measurements only, should stop compiling; lap2/ALMIGHTY (i5-13420H 12 threads, RTX 2050 4 GB, 15.7 GB RAM) = all builds + unit tests (src/fe-lab/remote/remote_build.py: ship/build/test/fetch-bin) AND correctness game runs (boots, capture/replay, census, scene routes). Owner's own games/keys/firmware may be copied to lap2 over the direct cable only; never elsewhere, never downloaded. One heavy job at a time on each machine. No speed figure from lap2 is ever published or used for a speed verdict. Release-gate repeats beyond the 10-launch cap need the owner's OK.
