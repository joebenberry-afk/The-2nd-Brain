---
id: mem-c4c36ca00db0
title: Kefla Blast Skill 2 archetype identified: rush/melee, connect case passes cardinality
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T18:52:57.875706+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

User-confirmed: Kefla's Blast Skill 2 is a rush/melee technique (dash at opponent, cinematic attack sequence on contact) -- not a projectile. The earlier flagged attempt (baseline seq 59087, current_blast_id 19 to 20) was this rush archetype and it CONNECTED, triggering the cinematic. Result: exactly one activation edge for one commitment, satisfying the rush/melee/cinematic archetype's CONNECT case per the two-archetype validation requirement. The projectile/non-cinematic archetype requirement is already independently satisfied by Kefla Blast Skill 1 (Blaster Ball), which passed full PROVEN 1/5/10 cardinality in Trials A/B/C. Still needed: the rush/melee MISS case for Kefla Blast Skill 2 (activation with no contact, no cinematic) to confirm the counter reflects commitment rather than depending on the cinematic actually firing. Separately flagged as a data-quality issue, not a cardinality blocker: reflected_combo_slot_name reported BlastSkill1 for this genuine Skill 2 press, suggesting the field may not reliably discriminate skill slot number. No production semantic acceptance change made.
