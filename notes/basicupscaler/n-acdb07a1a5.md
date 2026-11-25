---
id: n-acdb07a1a5
kind: note
at: 2026-10-21T15:41:17Z
source: agent
evidence:
  - target/release/bu-t06-camera.exe
evidence_sha:
  - target/release/bu-t06-camera.exe=4581f4448314
---

BUFG m1_gate plan in a fresh worktree without target/release/bu-t06-camera.exe binds overlay_camera sha256 null and every execute refuses with exit 2 (K37). Copy the camera exe before planning. Cyberpunk FT-2 flick arms have settings_extra m1_flick_blur_off, so they need their own execute-block launch, separate from the motion arms.
