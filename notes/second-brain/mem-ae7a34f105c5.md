---
id: mem-ae7a34f105c5
kind: fact
at: 2026-08-15T19:41:33.421155+00:00
source: convert
evidence:
  - M02 live validation 2026-08-15 (runtime memory probe, both arms)
  - Archived/rejected as a Second Brain project memory because the content belongs to the Sparking Zero project. Technical evidence may remain valid; project assignment was invalid.
retired: 2026-08-15T19:41:33.421155+00:00
---

SZ build 24497537 AiTypeAsset_M_02 【割込み】変身 LevelCurve is Curve_AiLevelLinear_0001 in the base game

Verified via UE4SS probe + ReadProcessMemory in BOTH the candidate boot and the control boot (candidate pak absent): base game M_02 ProbabilityMap[【割込み】変身].LevelCurve = Curve_AiLevelLinear_0001. The offline 08-07/08-09 mappings saying 0002 are mislabeled. N1 hypothesis baseline invalid for this build.
