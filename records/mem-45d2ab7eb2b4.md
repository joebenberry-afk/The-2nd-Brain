---
id: mem-45d2ab7eb2b4
title: T1 generalization COMPLETE: Step 6 full restart validation PASSES
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T20:01:47.779088+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Restart validation trial (user: charged to 3 ki bars and used a blast skill): baseline sequence 365 in the new post-restart telemetry file, Kefla side1/slot0, blast_stock_current 0/5 at baseline confirming the fresh-match-start-at-zero behavior. Audit through sequence 551, zero queue drops, zero sequence gaps. Previous process PID 30616, new process PID 12716. Previous session runtime_instance_id suffix ...1787927840-3556000-1708636030, new session suffix ...1787946491-3331000-1405626044. BuildID unchanged at 24497537. First observed current_blast_id was 0. Complete ID sequence: 0,0,0,0,0,1,1,1 -- ID delta +1, exactly 1 increment edge (0 to 1 at sequence 468). 8 total CountUpUseBlast callbacks; old-logic blast_used accepted count was 6, including 2 pre-press false-positive artifacts at id=0 with zero Ki cost -- the same over-counting pattern observed throughout this entire investigation, now reproduced immediately after a fresh process restart too. Actor/side/team_slot: kefla, side 1, team_slot 0. Character/form: kefla, 0920_00. Reflected slot: BlastSkill1. Resource confirmation: Ki dropped from 42907 to 12907 (delta approximately -30000, matching Blast Skill 1's known cost) at sequence 462, immediately preceding the 0-to-1 commit at sequence 468; blast_stock_current stayed constant at 1 through the real press, unaffected, consistent with prior findings that Blast Skill 1 does not touch blast-stock. STEP 6 PASSES: the semantic relationship holds across a full process restart -- one genuine Blast commitment produces exactly one current_blast_id increment. Raw callback userdata values, live UObject addresses, actor pointers, and memory addresses were correctly NOT assumed to survive the restart and were re-resolved fresh; the telemetry file itself was independently confirmed to reset/truncate per process launch. This completes the full T1 generalization campaign: Blast Skill 1 (1/5/10 PROVEN), Blast Skill 2 archetypes (connect+miss PASS), Ultimate (1x+5x PASS), side swap/second character PASS, transformation/form-change PASS, and now full game restart PASS. No production semantic acceptance change has been made at any point. Per the user's stated sequence, the next and final step before considering production T1 changes is a dedicated CPU/opponent counter-resolution investigation (the hit character's current_blast_id staying at 0 during its own real Blast activity remains unresolved).
