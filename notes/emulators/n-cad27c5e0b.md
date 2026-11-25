---
id: n-cad27c5e0b
kind: gotcha
at: 2026-11-25T21:00:35Z
source: agent
evidence:
  - src/Eglantine-f7c0cc30ac/.gitignore
replaces: n-a17dad80d5
---

Eglantine: .gitignore has `out/` but now `!/src/audio_core/out/` re-includes the dir, and src/audio_core/out/ (audio_out.cpp/.h, audio_out_system.cpp/.h) is tracked
Seen 2026-11-25 in src/Eglantine-f7c0cc30ac: .gitignore lines 10-11, git ls-files src/audio_core/out, commit a9abbdc907 'Track src/audio_core/out'. Edits there show in git status now. General tip still holds: if an edited file is missing from status, run `git check-ignore -v <path>`.
