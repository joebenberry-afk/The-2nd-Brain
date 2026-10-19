---
id: n-c5b8be79de
kind: note
at: 2026-10-18T21:52:08Z
source: agent
---

K9 phase finding (measured, scratchpad phase.py on K9 content_etw): generated-picture slip rate vs ms since Cyberpunk's last PCL marker 2 (render-submit start) before the planned refresh: 0-4 ms window holds nearly all slip (pan_slow 10/36/64/41/1%, flick 5/50/79/71/5%), >=5 ms ~0%. Game's post-submit GPU burst causes our generated slip; phase-aware generated submit (draw early only when refresh lands 0-4 ms after predicted game submit) is the K10 candidate.
