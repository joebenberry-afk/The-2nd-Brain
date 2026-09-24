---
id: mem-8c8b13bf82b4
title: Current Blast ID increment cleanly discriminates real Blast from artifact callbacks (SUPPORTED)
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T18:35:02.136615+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Input model corrected: the charge button is a technique-menu/modifier button; holding it opens the skill menu without necessarily charging Ki, Blast Skill 1 commits via Square while held; with 3+ Ki bars already available modifier+Square can commit with negligible Ki gain. Three states to track separately going forward: actual Ki charging, technique-menu/modifier-held state, and Blast Skill commitment via Square. Mined all 46 blast_callback_diagnostic events across the entire retained raw runtime file (multiple matches, elapsed_ms resets confirm match boundaries), time-clustered into 15 groups by greater than 3000ms gaps. Every cluster with exactly 3 callbacks (4 of 4) shows current_blast_id transitioning N to N+1 to N+1 with identical raw pattern 95,22,88 -- these are all the real isolated Blasts captured this session. Every 2-callback artifact cluster (10 of 11, plus one 12-callback burst) shows current_blast_id completely unchanged, with varying, unstable raw values (88,155,89,8,22). current_blast_id resets to 0 at each match start and increments by exactly 1 per real press within a match, consistent with a per-match activation counter. One 12-callback burst with zero ID increments had 8 of 12 callbacks accepted by the current semantic path, direct proof the existing raw-callback-based blast_used acceptance over-counts independent of duplicate-window tuning. Memory-side cross-reference: every ID-incrementing cluster coincided with the 0x721/persistent-cluster commit; every directly-observed artifact cluster left it unset or reset it if already latched. DECISION: current_blast_id increment promoted to SUPPORTED as the T1 activation-edge candidate, NOT PROVEN (no deliberate 1/5/10 cardinality trial run yet; variable name not trusted, only observed increment behavior). Not implemented into production semantic acceptance, duplicate window, or T1 promotion. 95/22/88 remain session-relative, not BuildID-stable. 0x721 remains a SUPPORTED member of the latched cluster, not a reusable activation flag on its own. The continuous float64 triple remains CANDIDATE.
