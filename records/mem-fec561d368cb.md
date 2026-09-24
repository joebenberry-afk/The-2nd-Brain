---
id: mem-fec561d368cb
title: Side swap confirmed; first synchronized UI/telemetry blast_stock_current checkpoint matches
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T19:20:55.127886+00:00
origin: MODEL_INFERENCE
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Side swap confirmed via telemetry: player1 active fighter changed from kefla to vegito (raw form 0100_00) at sequence 66113, elapsed_ms 662182. Telemetry at that moment: Vegito blast_stock_current=2/5, ki=20000/50000, sparking=False. First synchronized UI/telemetry checkpoint (user provided zoomed HUD screenshots boxing the gold circular gauge): UI gold-circle gauge showed 2, UI blue box beside it showed 5. Telemetry at the same reported moment (sequence 66113) showed blast_stock_current=2, blast_stock_max=5. MATCH on both: UI gauge (2) equals telemetry blast_stock_current (2); UI blue box (5) equals telemetry blast_stock_max (5). This is a single synchronized data point (n=1) supporting the hypothesis that the gold circular gauge represents blast_stock_current for the currently active fighter and the blue box represents blast_stock_max. NOT yet treated as proven across repeated checkpoints -- a clean initial match with no contradiction, but further synchronized checkpoints (e.g. after a Blast consumes stock, or across another swap) are needed before promoting this mapping beyond CANDIDATE. No production semantic acceptance change made.
