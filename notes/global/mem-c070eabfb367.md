---
id: mem-c070eabfb367
kind: fact
at: 2026-08-28T19:53:31.870500+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

T1 Step 6 post-restart verification PASSES; telemetry file resets per launch

Post-restart verification after the user fully exited and relaunched Sparking Zero: new process PID 12716 (SparkingZERO-Win64-Shipping.exe, StartTime 3:48:08 PM, vs previous PID 30616 at 10:37:17 AM -- genuinely new process). BuildID unchanged at 24497537. runtime_bundle_id unchanged (sha256:e2a7cb9d70169dbc770730557baf9453997303476920a750f47edac77134e58a) -- same UE4SS/telemetry bundle loaded. mapping_build_id unchanged (SZ-9f72dad62d1b-MAP-36acb77935ba). runtime_instance_id suffix changed (...1787946491-3331000-1405626044 vs ...1787927840-3556000-1708636030), confirming a genuinely new session identity. Critical procedural discovery: the telemetry snapshot file itself is RESET/TRUNCATED on each game process launch -- it does NOT append across restarts. Sequence numbering restarted at 1 in the new file (145 rows observed post-restart vs 72571 in the pre-restart file). match_active was False with elapsed_ms 0, confirming no stale match identity carried over -- game was idle at menu. source field confirmed ue4ss, telemetry hook live and producing data. Queue drops 0, sequence gaps 0, clean from sequence 1 of the new file. Procedural note for future work: post-restart baseline math must key off the NEW file's own sequence numbering, not the pre-restart sequence range, which no longer exists in the live file after a restart. No runtime address, pointer, or offset was carried forward from before the restart, per the user's explicit instruction. Awaiting the user to start a fresh match for the restart validation trial (first real Blast, expecting 0 to 1 to 1 pattern).
