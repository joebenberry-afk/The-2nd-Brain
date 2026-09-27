---
id: mem-f20ea3f2f8ce
kind: fact
at: 2026-08-28T09:57:05.411866+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
---

TEL-KI-ONLY contamination result

User confirmed KI_ONLY_DONE after charging Ki, stopping, performing no Blast, and remaining idle. Parsing the installed BuildID 24497537 diagnostic snapshot after baseline sequence 3844 through captured sequence 4404 found 6 CountUpUseBlast callbacks, 2 accepted blast_used events, 0 duplicate-window rejections, 4 invalid-context rejections, 0 missing-identity rejections, 0 queue drops, and 0 sequence gaps. All callbacks used reflected combo slot 3 / BlastSkill1 and current Blast ID 0. Callback timestamps were 4415808, 4415809, 4420338, 4420338, 4468238, and 4469789 ms. Object address:2161770299408 had callback sequences 11,13,15,16 and raw args 88,88,19,88; object address:2157426376720 had sequences 12,14 and raw args 88,88. First four lacked identity/context; callbacks 15 and 16 were in-context P1/team0 Kefla form 0920_00 and produced accepted BlastSkill1 events at snapshot rows 4108 and 4114 with counts 1 and 2. This proves semantic contamination under the Ki-only protocol but does not isolate charging versus settling/action transition as the exact trigger. PRECHARGED-1 remains safe; native instrumentation is not yet required.
