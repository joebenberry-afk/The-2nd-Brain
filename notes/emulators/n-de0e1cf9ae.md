---
id: n-de0e1cf9ae
kind: gotcha
at: 2026-11-24T01:37:34Z
source: agent
evidence:
  - build/omp07/deep/run_deep.py
evidence_sha:
  - build/omp07/deep/run_deep.py=a50694d6d0bd
tested: "true"
tested_by: agent
tested_at: 2026-11-24T01:37:34Z
tested_sha: 6999a9bd28ab
checked: holds
checked_at: 2026-11-25T17:59:37Z
checked_why: The run_deep.py changes and commit 0f60267 (feedback_skip_unwritten, masked_target_unmodified, feedback_shadow_share) exist as described. Per-10 s frame counts show Bananza at 300-800 fps for about 30 s, then 47-59 fps gameplay. Splatoon steady fps is about 91 with the switches off and about 95 with
checked_sha: 6999a9bd28ab
---

Bananza title enters its DK Artist demo by itself after ~11 s idle (not an emulator input bug, not the + press)
run_deep.py now presses only A for dk, first press at 12 s (PRESS_FROM_DEFAULT); gameplay ("Banana-Mining Site") from ~40 s. DEEP_PRESS_FROM / DEEP_SHOT_EVERY env knobs added.
Bananza gameplay at Fast: 41-52 fps, limited by GPU back thread CPU (91% working), ~8,500 draws/frame, ~2.7 us/draw; top zones update buffers 512 ns/draw, fill image views 305 ns/draw. Earlier 400-600 fps numbers were title/DK Artist, not gameplay. Architect (PerDrawCutDesign): listed cuts total ~326 ns/draw of the 800 needed for 60 fps.
Feedback cuts (EDEN_NX2_PERF_ON=feedback_shadow_share,feedback_skip_unwritten,masked_target_unmodified, HEAD 0f60267, bins bc6): Splatoon GPU busy 9.7->4.0 ms/frame, copies 626->8, fps only 91->95 (then nothing saturated); FE/XC2/Bananza clean by eye, no verify mismatch.
