---
id: n-11effd28d4
kind: gotcha
at: 2026-11-17T18:55:53Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-17T18:55:53Z
tested_sha: f67268ce4f34
---

Orchestration gotchas (Eglantine fork lab): (1) a finished reviewer agent that is revived with a new message returns its OLD report: always spawn a fresh reviewer. (2) `tools/publish_release.py` notes template needs each placeholder exactly once: {{TEST_TABLE}}, {{SHA256_ZIP}}, {{ZIP_NAME}}, {{ZIP_SIZE_MB}}, {{COMMIT}}; push fork-main first; tag commit = built commit. (3) Pipeline prepare cache: records beyond the ready cap (128) are asked for before ready ("Late record", 8 per second launch on pre3); raise the cap only if held_back is large and late_records not small. (4) D: on the test laptop is removable and usually absent: never put lab paths there. (5) The `wait` tool returns after 5 s; to idle cheaply use kernel block(names, limit) with cell timeout > limit+30.
