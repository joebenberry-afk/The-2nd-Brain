---
id: n-6d0ca6eb63
kind: gotcha
at: 2026-11-09T22:14:35Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-09T22:14:35Z
tested_sha: 157eef986606
---

Meshy image_to_image multi-view matting eats pale/grey characters; use single 16:9 sheet on #FF00FF and key locally
generate_multi_view:true always mattes+splits server-side (remove_background:false has no effect): erased legs/backs on low-contrast designs, 2 images for flat props, merged views for long creatures, and left opaque magenta patches when the prompt asked for a magenta background. Reliable route: generate_multi_view off, aspect_ratio "16:9", remove_background false, prompt "three views front/side/back in one row, wide gaps, flat #FF00FF background, no magenta on the character" -> raw 1376x768 RGB; chroma-key m=(min(R,B)-G)/255 > 0.72 and split by connected components locally. Always review alpha on a contrasting colour (not the key colour). 4 credits per task with nano-banana-2-1.
