---
id: mem-eb739dee3c9b
title: TEL-BLAST-SIGNATURE trial 1 contaminated by match transition
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T10:20:38.631333+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Trial 1, audited strictly after baseline sequence 9495 through captured sequence 10023 (528 rows), found 13 raw CountUpUseBlast callbacks, 6 accepted blast_used events, 3 duplicate-window rejections, 4 invalid-context rejections, zero missing-identity/invalid-slot rejections, zero callback errors, zero drops, zero sequence gaps. A match ended and a new one started inside this window: sequences 9839-9841 show pre-context callbacks at match_active=false elapsed_ms=0 on two different objects, then a fresh match begins at elapsed_ms=8533 on object address:2161491312656. Within the new match: accepted callbacks 41,43,45 (raw slot 19, Blast ID 0, events 19-21, counts 1-3), rejected duplicates 42,44,46 (raw slot 88, Blast ID 0, 335-1183 ms after each accepted callback), then accepted 47,48,49 (raw slot 144,142,88, Blast ID 0,1,1, events 22-24, counts 4-6), spanning 14067 ms total. This 6-event, ~14s pattern does not match the previously observed 3-callback/~3.4s three-stage signature and is not a clean single-isolated-Blast capture. Do not count this trial toward the 3-trial signature comparison; a match transition and possibly more than one Blast/charge action are the likely confound. Ask the user to redo trial 1 with a clean same-match isolation.
