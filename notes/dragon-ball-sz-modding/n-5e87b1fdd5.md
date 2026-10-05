---
id: n-5e87b1fdd5
kind: gotcha
at: 2026-09-28T16:42:04Z
source: agent
tested: "true"
---

Update to the 2026-09-28 SZ gotcha 'direct winner never arrives'
In E002c v0.2 match 1 (16:41Z), finish mode delivered GetBattleDirectingWinner 18 s after play stopped, and it agreed with the KO (loser HP 0). The earlier four KOs gave no direct result within 120 s.
So the direct result is intermittent. Keep the KO fallback in ab_summary. The recorder's 120 s wait only affects when match_end is written; match_stop checkpoints make it harmless.
