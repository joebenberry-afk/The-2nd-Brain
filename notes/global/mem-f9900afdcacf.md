---
id: mem-f9900afdcacf
kind: fact
at: 2026-08-28T19:45:34.601954+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

T1 Step 6 pre-restart checkpoint: full identity/state snapshot before game exit

Pre-restart checkpoint recorded before the user fully exits and relaunches Sparking Zero for the full game restart validation (T1 Step 6). BuildID: 24497537. Process identity: PID 30616, SparkingZERO-Win64-Shipping.exe, StartTime 28/8/2026 10:37:17 AM. UE4SS/runtime identity: runtime_instance_id runtime-sha256:e2a7cb9d70169dbc770730557baf9453997303476920a750f47edac77134e58a-1787927840-3556000-1708636030, runtime_bundle_id sha256:e2a7cb9d70169dbc770730557baf9453997303476920a750f47edac77134e58a, mapping_build_id SZ-9f72dad62d1b-MAP-36acb77935ba, telemetry_schema_version 2. Current SIDE1+TEAM_SLOT0 current_blast_id evidence: 3 (last observed at sequence 69927, from Step 5's transformed-form Blast). Telemetry sequence at checkpoint: 72489 (tail); full-file audit showed 72571 candidate snapshots, 18298 health snapshots, 145 blast_events total, zero queue drops, zero sequence gaps across the entire file up to this point. Most recent hook_health: blast_use_hook_calls=237, blast_events_accepted=145, blast_callback_errors=0, blast_rejected_invalid_context=8, blast_rejected_missing_identity=4, blast_rejected_invalid_slot=0, blast_rejected_duplicate_window=80. Per the user's explicit instruction, no runtime address, UObject pointer, raw callback value, or memory offset is assumed to survive the process restart -- all will be re-resolved fresh post-restart rather than reused. This is the reference checkpoint for comparing pre- and post-restart process/session/build identity.
