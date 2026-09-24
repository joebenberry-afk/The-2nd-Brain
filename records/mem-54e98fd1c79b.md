---
id: mem-54e98fd1c79b
title: TEL-BLAST-SIGNATURE trial 1 redo: third confirmation of 3-stage triad
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T10:28:12.050623+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Clean same-match redo, audited strictly after baseline sequence 10357 through captured sequence 11950 (1593 rows), found 5 raw CountUpUseBlast callbacks, 5 accepted blast_used events, zero duplicate/invalid-context/missing-identity/invalid-slot rejections, zero callback errors, zero drops, zero sequence gaps, match_active=true throughout. All in-context P1/team0 Kefla form 0920_00 BlastSkill1 reflected slot 3 on object address:2161491312656. Sequence: cb50 raw19 ID1 +0ms event25 count7; cb51 raw88 ID1 +1516ms event26 count8; cb52 raw144 ID1 +9822ms event27 count9; cb53 raw142 ID2 +11324ms event28 count10; cb54 raw88 ID2 +13224ms event29 count11. Decomposes into a 2-stage pair (19 then 88, ID unchanged) plus an 8.3s gap plus a 3-stage triad (144,142,88, ID 1,2,2). The triad is the third independent exact match of the established single-Blast signature (identical to PRECHARGED-1 and three-bar PRECHARGED). The 2-stage pair matches the only accepted pair from the TEL-KI-ONLY control (raw 19 then 88, ID unchanged, zero real Blast activations that trial), supporting a hypothesis that Ki-charge/threshold-crossing alone produces a separable 2-stage 19-then-88 sub-signature distinct from the 3-stage 144-142-88 single-Blast sub-signature. Hypothesis only; no semantic/dedupe/T1-gate change made. Accepted as trial 1 of 3 for the signature-stability comparison.
