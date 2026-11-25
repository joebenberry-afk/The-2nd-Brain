---
id: n-dcacad3099
kind: fact
at: 2026-11-15T15:09:47Z
source: agent
evidence:
  - src/Eglantine-f7c0cc30ac/src/shader_recompiler/frontend/ampere/lower_to_maxwell.h
evidence_sha:
  - src/Eglantine-f7c0cc30ac/src/shader_recompiler/frontend/ampere/lower_to_maxwell.h=b19609866100
tested: "true"
tested_by: agent
tested_at: 2026-11-15T15:09:47Z
tested_sha: 8afa54dec766
checked: holds
checked_at: 2026-11-25T17:59:35Z
checked_why: The commit message and diff match the claim (NaN to zero, padding 1920x1152, 1088 rows, row 68 cycle, cache v35); hardware semantics are admitted as inferred and are not checkable. [commit 0aae940355 (lower_to_maxwell.h, CACHE_VERSION 34->35, NX2_NOTES row 156)]
checked_sha: 8afa54dec766
---

Ampere HFMA2.RELU must turn NaN into zero (not keep 0x7fff): Switch 2 upscaler networks leave tensor padding unwritten.
XC2 S2 (0400E95004038001) showed block noise bottom right: network canvas padded 1920x1152, first pass writes 1088 rows, last 16 quarter-res input rows = stale arena scratch. A NaN there cycled every frame (input pad -> layer 1 row 68 -> layer 2 scratch -> input pad) and leaked into valid rows. Fix 0aae940 (fe-buf), lower_to_maxwell.h, cache version 35. Cross-check: zeroing those rows before each evaluation also cleans it. HW semantics inferred (game clean on console, cuDNN default NOT_PROPAGATE_NAN), not measured on hardware.
Method that worked: EDEN_NX2_FRAME_DUMP with buffers, then EDEN_NX2_SHADER_DUMP + `nvdisasm -b SM86 <raw .bin>` (raw mode needs no cubin template / nvcc; CUDA v13 on this PC).
