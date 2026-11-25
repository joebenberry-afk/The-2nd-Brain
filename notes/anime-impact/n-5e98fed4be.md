---
id: n-5e98fed4be
kind: gotcha
at: 2026-11-10T08:08:55Z
source: agent
evidence:
  - tools/anim_lab.gd
evidence_sha:
  - tools/anim_lab.gd=779a193b49f3
tested: "true"
tested_by: agent
tested_at: 2026-11-10T08:08:55Z
tested_sha: d6ac52b4158a
---

Anime Impact clip acceptance: strips alone are not enough — also run the lab rows before accepting.
Aqua Hit/Death v3 passed my front+side strip check and an independent still review, but `anim_lab.gd --hero=aqua --no-sheets --out=<scratch>` showed `arm Right in body` 5.6 % / 8.3 % (limit 3 %, fail > 5 %). `test_measure` parity failures ("Blender only: … in_body / fail") were the first hint. Haiku animators do not run the lab unless told: put the lab command and the three limits in every clip brief.
