---
id: mem-7667f0b43eec
title: T1 generalization Step 2 complete: Kefla Ultimate Blast passes cardinality
scope: domain
project: 
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-28T18:58:51.602440+00:00
---

Deliberate Kefla Ultimate Blast cardinality trial: required entering Sparking Mode first (full 5 Ki bars, then charging further past full). One earlier Sparking Mode entry attempt was aborted/exited before pressing the Ultimate and correctly produced zero spurious current_blast_id activity. Real trial: baseline sequence 61485, starting current_blast_id 21, sparking=True confirmed at baseline. Audit through sequence 61755, zero queue drops, zero sequence gaps, no match-boundary crossing, clean single-actor window. current_blast_id sequence was 21,21,21,22,22 -- exactly one 21-to-22 transition. PASSES the hard cardinality gate (ID delta +1, exactly 1 edge, zero unexplained/missing increments, zero drops, zero gaps). reflected_combo_slot_name reported BlastSkill1 again on all 5 callbacks -- third technique type (Skill1, Skill2, Ultimate) now observed with this same mislabel, strengthening the conclusion the field is stale/hardcoded rather than skill-specific and is not reliable for skill-type attribution; this does not affect cardinality. Sparking Mode entry itself (a prerequisite gameplay state change, not a Blast) produced zero spurious counter activity. No production semantic acceptance change made. Next per user's generalization order: side swap.
