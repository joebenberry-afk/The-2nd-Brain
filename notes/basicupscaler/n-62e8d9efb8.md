---
id: n-62e8d9efb8
kind: gotcha
at: 2026-09-28T19:33:31Z
source: agent
tested: "true"
---

ffmpeg's scale filter treats left-tagged H.264 (chroma_location=left) as centre-sited unless given in_chroma_loc=left / out_chroma_loc=left. Chroma-siting measurements against ffmpeg references show a false ~0.5 source px horizontal offset without it. Also: Media Foundation's hardware video processor ignores MF_MT_VIDEO_CHROMA_SITING entirely (bit-identical output for 0/1/5/6/7).
