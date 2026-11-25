---
id: n-a17dad80d5
kind: gotcha
at: 2026-11-15T20:09:28Z
source: agent
evidence:
  - src/Eglantine-f7c0cc30ac/src/audio_core/out/audio_out_system.cpp
evidence_sha:
  - src/Eglantine-f7c0cc30ac/src/audio_core/out/audio_out_system.cpp=eb7950fab085
tested: "true"
tested_by: agent
tested_at: 2026-11-15T20:09:28Z
tested_sha: 80101a54aee5
checked: moved
checked_at: 2026-11-25T17:59:34Z
checked_why: The ignore rule did hide the dir, but it has since been tracked and un-ignored via a negation rule, so it is now tracked and `git check-ignore` no longer ignores it. [.gitignore:10-11 (`out/` then `!/src/audio_core/out/`); git ls-files src/audio_core shows 4 out/ files; commit a9abbdc907 'Track src/
checked_sha: 80101a54aee5
---

Eglantine repo: .gitignore line 10 `out/` hides src/audio_core/out/ — the directory was never tracked
Edits to audio_out_system.cpp build fine but never show in git status and cannot be committed through the commit namespace. A fresh clone lacks the directory. Check `git check-ignore -v <path>` when an edited file is missing from status.
