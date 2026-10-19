---
id: n-cfe53fccec
kind: note
at: 2026-10-19T03:33:50Z
source: agent
evidence:
  - target/release/bu-t06-camera.exe
evidence_sha:
  - target/release/bu-t06-camera.exe=063c005c13f4
---

K11 (2026-10-19): fresh worktree had no target/release/bu-t06-camera.exe, freeze bound null sha, execute refused exit 2 (same as K4). Fix: copy exe from m1-k9 (Rust unchanged) before plan. Plan-time refusal tried, reverted: breaks many test fixtures that plan with absent recorders.
