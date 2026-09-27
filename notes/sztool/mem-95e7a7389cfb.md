---
id: mem-95e7a7389cfb
kind: fact
at: 2026-08-28T18:09:37.503840+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Reset-condition forensics: Trial2-to-Trial3 telemetry reconstruction exhausted, hypotheses ranked

Reconstructed the 377s interval between Trial 2's Blast press and Trial 3's confirmed clean baseline from existing telemetry (1520 rows, zero sequence gaps). Player summary fields (hp, ki, blast_stock_current, sparking, form_key) newly extracted this session: P1 ki dropped exactly 30000 (3 bars) at the same row as Trial 2's first accepted blast_used, confirming BlastSkill1 Ki cost; ki then climbed 2217 to 20000 over about 10.8 seconds (consistent with a brief post-Blast charge hold) then plateaued unchanged for the remaining approximately 302 seconds; hp (both sides), blast_stock_current (5/5 both sides), sparking (false both sides), form_key, and match_active were completely static for the entire window. No other event types occurred. Telemetry has no action/movement/guard-level instrumentation (action hook disabled throughout), so Step 1 evidence is exhausted without identifying the reset trigger. Hypothesis ranking: DISCONFIRMED by direct evidence are Ki charging alone, damage exchange, Blast-stock consumption, Sparking toggle, form change, and match-state transition. Remaining untested candidates ranked by plausibility: movement/positional change, guard/block input, melee/basic action input, being hit or opponent action, and a state-gated (not pure elapsed-time) cooldown. Corrected confidence language per explicit instruction: +0x721 is a supported member of a reproducible Blast-correlated state transition, whose reset semantics remain unknown -- not described as a supported Blast-activation flag. T1 remains unpromoted; no SZ-CPU-Lab change made.
