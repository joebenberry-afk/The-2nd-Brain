---
id: n-5befcfac52
kind: gotcha
at: 2026-11-25T21:03:01Z
source: agent
evidence:
  - src/eglantine-fork/build/release/CMakeCache.txt
  - src/fe-lab/plans/order_T0_compile.md
replaces: n-424e5c10a1
---

Eglantine fork build tree src/eglantine-fork/build/release/CMakeCache.txt has YUZU_TESTS=ON and DYNARMIC_TESTS=ON (seen 2026-11-25); compile_commands.json has 352 src/tests entries. No build/tests directory exists (only build/release and build/c3-no-mcp). Catch2 v3.13.0 for syntax checks: -I ROOT/src/deps/Catch2-3.13.0/src -I ROOT/src/deps/catch2_gen with C:/msys64/ucrt64/bin/clang++.exe (exists; not on bash PATH). Heavy-lane compile order plan: src/fe-lab/plans/order_T0_compile.md (separate dir build/tests, ninja -k 0). Not re-tested: network/curl advice from 2026-11-17 (curl in an eval cell hung the kernel; use async bash with --max-time).
