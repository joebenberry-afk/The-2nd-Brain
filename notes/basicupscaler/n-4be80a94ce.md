---
id: n-4be80a94ce
kind: gotcha
at: 2026-10-17T21:50:21Z
source: agent
errors:
  - "refused: code differs from the freeze binding (changed: arena/arm_label_smoke.py, arena/baseline_library.py, ..."
evidence:
  - arena/hud_label.py
evidence_sha:
  - arena/hud_label.py=7b017614f6ae
tested: "true"
tested_by: agent
tested_at: 2026-10-17T21:50:21Z
tested_sha: 0f3dd5095ba4
checked: holds
checked_at: 2026-11-25T18:00:11Z
checked_why: m1_code hashes working-tree bytes so line endings count and it needs the same checkout as the freeze. Main is LF here, and bound roots include tools/game_driver/profiles. The specific byte counts (17510 vs 17849) and the ~70 file count can't be confirmed, because hud_label.py is now 17592 bytes. [Ba
checked_sha: 0f3dd5095ba4
---

m1_code check of a worktree freeze cannot be run from the main checkout: the main checkout's files are LF, the worktree (core.autocrlf=true, fresh checkout) has CRLF, so sha256 differ for ~70 files that git calls identical (e.g. arena/hud_label.py 17510 vs 17849 bytes). Run `python -m arena.m1_code check <freeze>` with cwd = the worktree that made the freeze. To predict drift from moving a worktree, use `git diff --name-only <old> <new>` against the binding's roots (tools/game_driver/profiles/** PNGs and json are bound).
