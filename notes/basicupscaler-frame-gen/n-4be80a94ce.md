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
---

m1_code check of a worktree freeze cannot be run from the main checkout: the main checkout's files are LF, the worktree (core.autocrlf=true, fresh checkout) has CRLF, so sha256 differ for ~70 files that git calls identical (e.g. arena/hud_label.py 17510 vs 17849 bytes). Run `python -m arena.m1_code check <freeze>` with cwd = the worktree that made the freeze. To predict drift from moving a worktree, use `git diff --name-only <old> <new>` against the binding's roots (tools/game_driver/profiles/** PNGs and json are bound).
