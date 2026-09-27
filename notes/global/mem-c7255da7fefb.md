---
id: mem-c7255da7fefb
kind: fact
at: 2026-08-28T09:01:02.557264+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

T1 Blast canary run 1 cardinality failure

Observed controlled run after baseline sequence 285: user reported one Kefla Blaster Ball activation. BuildID 24497537 and runtime bundle sha256:873fa66e7b12fbcef5cbd6defce3f82a3fb79004262fe5b31f29f0479c720ab7 were loaded. Audit found 11 raw CountUpUseBlast callbacks, 6 accepted blast_used events, 5 duplicate-window rejections, 0 missing-identity rejections, 0 invalid-context rejections, 0 queue drops, and 0 sequence gaps. All accepted events were side 1/team slot 0 Kefla form 0920_00 BlastSkill1 via reflected_combo_slot. Accepted events spanned 1.533s to 22.783s, so the 1500ms duplicate window did not collapse the repeated callbacks. T1 cardinality failed; stop before 5 and 10 runs; do not change deduplication until callback semantics are understood.
