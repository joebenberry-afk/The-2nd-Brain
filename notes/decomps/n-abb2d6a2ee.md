---
id: n-abb2d6a2ee
kind: gotcha
at: 2026-11-05T06:54:08Z
source: agent
errors:
  - care tables loaded as all zeros from file_by_id(18)
tested: "true"
tested_by: agent
tested_at: 2026-11-05T06:54:08Z
tested_sha: 97ccf3a06b79
---

dwc-rs Rom::file_by_id() LZ-decompresses; overlays 0,1,3,5-8,10,12,14-18 start with byte 0x10 and get garbled. Read overlays with file_raw_by_id(id) (FAT id = overlay index).
