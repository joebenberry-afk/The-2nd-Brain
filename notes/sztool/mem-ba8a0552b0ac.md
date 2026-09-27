---
id: mem-ba8a0552b0ac
kind: fact
at: 2026-08-28T14:46:46.594487+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Live Kefla actor instance located via SZ-Tool component-owner scan

For the restarted BuildID 24497537 game process (PID 30616, module base 0x7ff612a30000 unchanged across restart, runtime_instance_id changed), the live Kefla ASSCharacter instance was located purely via read-only SZ-Tool GObjects/GNames reflection with no telemetry dependency. Exact-name search for Kefla or SSCharacter only finds the base class and its CDO, because playable fighters are Blueprint subclasses named BPCHR_<numeric_key>_C, e.g. BPCHR_0920_00_00_C for Kefla (0920_00 matches the form_key seen in every prior telemetry trial). Discovery method: tally live objects by owning-class for a known component type (KoratCharacterMovementComponent, 11 live instances), then resolve each real (non-Default__) instance's Outer to get the owning actor and its own class name. Confirmed live Kefla actor address 0x20547a1aab0, class BPCHR_0920_00_00_C, name equals class name (no Default__ prefix meaning it is a spawned instance not the CDO), 256-byte header read-verified, vtable inside the SparkingZERO module range. This address is the target for the pending Part B memory-delta capture (snapshots A-E around one Blast lifecycle).
