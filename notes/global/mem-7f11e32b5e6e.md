---
id: mem-7f11e32b5e6e
kind: fact
at: 2026-08-28T15:00:56.805722+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

Part B candidate field cluster promoted to SUPPORTED (2/2 reproducible)

A second isolated Blast in the same session (baseline A3, 60s poll, 1194/1194 successful reads) reproduced the exact same 23-offset candidate field cluster found in capture 2, with byte-for-byte identical transition values: offsets 0x64a-0x64e go 140,65,41,92,143 to 12,66,154,153,153; offsets 0x6fb, 0x6ff, 0x703 all go 0 to 191; offset 0x721 goes 0 to 1 (clean boolean). The internal timing gap between the transient clear block (0x330-0x370, clears to 0 then restores) and the persistent commit cluster matched to within 1ms across both trials (0.403s vs 0.402s). Before capture 3, all group b/c/d offsets from capture 2 (including 0x721) had reverted exactly to the original idle baseline, confirming these fields are Blast-lifecycle-scoped and resettable, not permanent one-shot markers. Telemetry raw slot values were also identical between the two trials in this session (95, 22, 88 both times), consistent with values being session-stable but resetting across game/process restarts. The memory-to-telemetry lag (memory changes preceding the first accepted blast_used) was consistent across both trials (roughly 1.0-1.6s). DECISION: this field cluster is promoted from CANDIDATE to SUPPORTED per the user's PROVEN/SUPPORTED/CANDIDATE framing, based on 2 independent reproducible isolated activations. Still not PROVEN (no native/disassembly confirmation of what each field represents). Not implemented into any semantic acceptance, dedupe, or T1 gate. Offset 0x721 remains the single cleanest Blast-activation-edge candidate.
