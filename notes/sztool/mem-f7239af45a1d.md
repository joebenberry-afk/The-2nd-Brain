---
id: mem-f7239af45a1d
kind: fact
at: 2026-08-28T18:23:02.966703+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Reset-condition breakthrough: another CountUpUseBlast entry resets 0x721, not action/time

While preparing BLAST-WHILE-LATCHED, found that between a +0x721=1 latched baseline and a refreshed baseline taken after Ki charging finished, +0x721 and the full persistent cluster (1610-1614, 1787/1791/1795, etc.) had reverted exactly to true idle values. Telemetry showed two accepted blast_used events in that exact interval, both matching the previously-established charge-artifact 2-stage pattern (raw slot X then 88, current_blast_id unchanged across the pair), not a real 3-stage press triad, consistent with charging through the 3-bar threshold rather than a deliberate press. This was inferred from two discrete before/after snapshots plus telemetry timing, not continuous polling of the exact interval, so it is evidence-based but not directly observed at sub-second resolution. Working hypothesis: entry into CountUpUseBlast, whether a real press or a charge-artifact, resets the working-state fields including 0x721 near the start of the call; only a genuine full press subsequently re-sets the persistent latch pattern before returning. This means the reset trigger is simply another CountUpUseBlast invocation of any kind, not elapsed time or a non-Blast player action -- consistent with, and not contradicted by, the prior movement/guard/melee disconfirmations since none of those are CountUpUseBlast entries. Corrected confidence statement: 0x721 is a SUPPORTED Blast-correlated latch/state transition with unknown reset semantics, now evidenced to plausibly reset on subsequent CountUpUseBlast entries rather than time or unrelated player actions. Not yet PROVEN. T1 remains unpromoted; no SZ-CPU-Lab change.
