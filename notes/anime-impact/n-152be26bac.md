---
id: n-152be26bac
kind: procedure
at: 2026-11-08T07:24:01Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-08T07:24:01Z
tested_sha: aa30a2c33581
replaced_by: n-72b9f3908b
retired: 2026-11-08T07:30:47Z
---

Anime Impact turnaround procedure, for any character:
- Call `meshy_image_to_image` with ai_model nano-banana-2-1, `generate_multi_view: true`, `remove_background: true`. Cost is 4 credits.
- Refs: canon wiki images for canon characters; the Gemini JJK-style concept for original mobs.
- `meshy_download_model` with `save_to=<dir>` writes `<dir>_0.png` etc. next to the dir, not inside it.
- Output order is 0=front, 1=side, 2=back. Rename to `turnaround_v1_0`=back, `v1_1`=front, `v1_2`=side.
- Save under `art/characters/{heroes,bosses,mobs,summons}/<id>/`.
