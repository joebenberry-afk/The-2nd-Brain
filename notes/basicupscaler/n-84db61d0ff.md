---
id: n-84db61d0ff
kind: gotcha
at: 2026-11-04T06:38:24Z
source: agent
errors:
  - "Error: A device attached to the system is not functioning. (0x8007001F)"
tested: "true"
tested_by: agent
tested_at: 2026-11-04T06:38:24Z
tested_sha: 01053b8ec9ef
replaced_by: n-5a765f4091
retired: 2026-11-04T06:38:33Z
---

bu_d3d12_source hung then died 0xC0000409 on RTX 5070 Ti (driver 32.0.16.2101) in a 33-rect ClearRenderTargetView; WARP is fine. Fixed bufc-d3d12hw b7f428f8 (one rect per clear). The injector's 0x8007001F "device not functioning" was QueryFullProcessImageNameW on an already-exited target (ERROR_GEN_FAILURE), not a hook bug.
