---
id: n-0debed3d02
kind: fact
at: 2026-11-15T01:17:09Z
source: agent
evidence:
  - Eglantine-latest-FE-test/user/nx2_switches.txt
evidence_sha:
  - Eglantine-latest-FE-test/user/nx2_switches.txt=9e9182a6a15e
checked: moved
checked_at: 2026-11-25T17:59:21Z
checked_why: "The switches exist (EDEN_NX2_PERF_OPT=0, PERF_OFF, PERF_VERIFY), and nx2_perf.h was added in c6d2acd37a, which lies between 78743f30c2 and 06c5c84b55. I found no EDEN_NX2_PERF_SAFE=1 in the note, but the header now documents it. The code does not mention the 'Nx2Perf: bounds=on' log line or a user\\n"
checked_sha: c94b71feba23
replaced_by: n-bd37e48175
retired: 2026-11-25T21:02:41Z
---

Eglantine NX2 master switches for regression hunting: EDEN_NX2_PERF_OPT=0 turns off all 46 Nx2Perf GPU optimisations (src/video_core/nx2_perf.h; file first appears in c6d2acd37a, inside the FE:FW black-scene range 78743f30c2..06c5c84b55). EDEN_NX2_PERF_OFF=<name,...> turns named ones off (bisect by halves), EDEN_NX2_PERF_VERIFY=1 logs old-vs-new differences and uses the old answer. EDEN_NX2_SPLIT=0 runs the GPU on one thread. Log line "Nx2Perf: bounds=on ..." shows the state at boot. Set them in user\nx2_switches.txt (read at startup only).
