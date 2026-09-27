---
id: mem-b582fe51e0ad
kind: fact
at: 2026-08-28T19:31:09.340117+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

current_blast_id scoping PROMOTED to SUPPORTED: per SIDE+TEAM_SLOT, persists across swaps

Dedicated controlled trial confirmed the per-slot-persistence hypothesis with resource-verified evidence: baseline sequence 68518, last observed side1/slot0 current_blast_id was 1 (Vegito active, same match, same team_slot as the earlier Kefla activity). After one deliberate Vegito Blast, audited through sequence 69010 with zero queue drops, zero sequence gaps, no match-boundary crossing: current_blast_id sequence was 1,1,2,2 -- exactly one 1-to-2 transition. Resource verification (same standard used to disqualify the earlier raw=42 artifact, not just raw callback presence): Vegito ki climbed from 20000 to 35653 during a charging phase then dropped sharply to 6226 at the accepted commit -- delta approximately -29427 Ki (about 3 bars), matching Blast Skill 1's known cost, timed exactly at the accepted blast_use_count transition 7 to 8. blast_stock_current stayed constant at 5 throughout -- new observation that Blast Skill 1 does not consume blast-stock (separate from whatever Ultimate or other techniques may cost). Actor/side/form: side=1, team_slot=0, character_key=vegito, form_key=0100_00, reflected_combo_slot_name=BlastSkill1. This exactly matches the primary hypothesis pattern: existing side/slot counter 1, Vegito real Blast, 1 to 2 to 2. PROMOTION: current_blast_id scoping is promoted from CANDIDATE to SUPPORTED as SIDE + TEAM_SLOT-scoped -- a running per-team-position counter of real Blast commitments that persists across mid-match character swaps, not per-character-actor. This directly explains the earlier Vegito swap-in id=1 observation, which is no longer an open question: it correctly inherited the running side/slot total rather than resetting. No production semantic acceptance change made.
