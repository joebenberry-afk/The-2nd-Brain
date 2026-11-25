---
id: n-4ccf8cf0e9
kind: gotcha
at: 2026-11-23T21:59:04Z
source: agent
evidence:
  - src/omp07-fastpath/src/tests/video_core/maxwell_fast_method.cpp
evidence_sha:
  - src/omp07-fastpath/src/tests/video_core/maxwell_fast_method.cpp=5809b8898969
tested: "true"
tested_by: agent
tested_at: 2026-11-23T21:59:04Z
tested_sha: d0d0b5f0b276
checked: uncheckable
checked_at: 2026-11-25T17:59:46Z
checked_why: "Both named test cases exist at a370145 and that commit exists. Line numbers differ slightly: the test starts at 1657 and the 1691 assertion line is not checked. Flakiness and the base-commit repro need repeated test runs. The lap2 targets are passed via --targets with no fixed default, so that part "
checked_sha: d0d0b5f0b276
---

Pre-existing flaky unit test at a370145: "Fast graphics preview leaves a split GPU thread to the legacy path" (src/tests/video_core/maxwell_fast_method.cpp:1691, rings 8 == 10). Fails on some runs/seeds and passes alone; reproduced on the base commit, so not caused by work/07-backcost. "Distinct recent errors keep one slot per source line" (nx2_diagnostics.cpp:213) also flakes in whole runs. Fix before 0.7 qualification; lap2 build targets are `yuzu-cmd` and `tests` (not eden-cli).
