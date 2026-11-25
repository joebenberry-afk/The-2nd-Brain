---
id: n-c69cad5ebc
kind: gotcha
at: 2026-11-24T23:29:19Z
source: agent
errors:
  - Download for failed after 5 tries
---

lap2 remote_build: re-shipping into a job needs the old src's .cache\cpm copied over
`ship` refuses an existing src; after `ren src src-old` + ship, cmake reconfigure fails with "CMake Error at CMakeModules/CPMUtil.cmake:114: Download for failed after 5 tries" (wasted 30 min). Fix: `ssh lap2 'robocopy C:\eg\m-<job>\src-old\.cache C:\eg\m-<job>\src\.cache /E'` before `build`. Also harness: mode `normal` already adds gpu_accuracy=0, so DEEP_ALLOW=gpu_accuracy=2 makes the emulator exit at once (use mode noprof for Accurate); a failed run can leave nvidia-smi loggers holding gpu.csv.
