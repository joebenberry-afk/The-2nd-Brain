---
id: mem-ad46a6ce2cd1
title: Swap-boundary artifact resolved: no missed increment; current_blast_id scoping revised to per-side+slot
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T19:26:25.256346+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Resolved the unaudited swap-boundary finding with hard evidence rather than assumption: pulled Kefla ki/blast_stock_current across all 187 telemetry snapshots in the full ~46s window (seq 65750-65937) leading up to and through a disputed blast_callback_diagnostic (raw=42, id=1, accepted under old blast_used logic as use #5). Both ki (constant 20000.0) and blast_stock_current (constant 5) stayed perfectly flat with zero variance across the entire window -- a real Blast Skill 1 costs about 30000 Ki and 1 blast-stock point, neither moved. This is direct evidence the raw=42 callback was NOT a real Blast press; it is the same class of false-positive artifact the old blast_used raw-callback logic has been over-accepting throughout this whole investigation, and current_blast_id correctly did not increment for it. This reconciles with the user's confirmation of using exactly 1 real Blast with Kefla: that press is the earlier fresh-match trial (already scored current_blast_id 0 to 1). Conclusion: no missed increment, cardinality still holds, this is NOT a T1 cardinality failure. Separately, Vegito's very first callback on swap-in showed id=1 (not 0), which is fully consistent with the above once the artifact is excluded -- exactly 1 real Blast commitment occurred on this side/slot before the swap, and Vegito inherited that running value rather than resetting. Combined evidence-supported hypothesis, revised from the earlier informal per-actor assumption: current_blast_id is scoped per SIDE+TEAM_SLOT (per team position -- N total real Blast commitments on this side/slot so far in the match), not per specific character actor, and does not reset on a mid-match character swap (only on a match boundary, already separately proven). This remains consistent with the CPU opponent hit (side 2) staying independently at 0, since that is a different side/slot entirely. Per-side+slot scoping is CANDIDATE, not yet formally tested with a dedicated controlled trial (e.g. deliberately swapping mid-cluster, or swapping back and forth to confirm the running total truly persists and combines across swaps). No production semantic acceptance change made.
