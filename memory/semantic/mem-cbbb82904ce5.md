---
id: mem-cbbb82904ce5
title: T1 generalization protocol correction: Blast Skill 2 is not one archetype
scope: domain
project: 
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-28T18:52:06.045549+00:00
---

User correction during T1 generalization: Blast Skill 2 is not a single gameplay archetype across the roster -- some Blast Skill 2 techniques are projectile/beam attacks, others are rush/melee techniques where the fighter dashes at the opponent and, on contact, enters a cinematic attack sequence. Do not generalize Blast Skill 2 cardinality from one move alone. For T1, separate technique commitment/cardinality from all downstream behavior; the only question is whether one deliberate Blast Skill 2 activation causes exactly one current_blast_id increment. Must validate at least one projectile/non-cinematic Blast Skill 2 and one rush/melee/cinematic Blast Skill 2; for the rush archetype, eventually test both activation-then-miss and activation-then-connect-then-cinematic, both of which should still produce exactly one activation edge if current_blast_id represents Blast commitment generically. Rush movement, contact callbacks, cinematic transitions, multi-hit damage, and animation events must NOT affect the technique-use (commitment) count -- those are T2+ attack-instance/hit/damage lifecycle events, out of scope for T1. If both archetypes increment exactly once per commitment, that is materially stronger evidence the counter is generic to Blast activation rather than tied to one specific attack implementation. First Kefla Blast Skill 2 attempt (baseline seq 59087) was flagged, not resolved: cardinality itself was clean (exactly one 19-to-20 transition) but reflected_combo_slot_name reported BlastSkill1 for all Kefla callbacks despite Skill 2 being pressed (unresolved slot-name mismatch), and an opponent character (hit, side 2) fired its own BlastSkill1 twice in the same window without affecting Kefla's own counter (useful incidental evidence current_blast_id is scoped per-actor, not global). No production semantic acceptance change made.
