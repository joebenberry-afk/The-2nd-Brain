---
id: n-2835eced0d
kind: decision
at: 2026-11-25T21:00:34Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-25T21:17:00Z
tested_sha: dc09eb038672
checked: holds
checked_at: 2026-11-25T21:08:11Z
checked_why: 50 patches in wt_patches; worktree list 174, branches 293; rest labelled not re-verified
checked_sha: dc09eb038672
replaces: n-8539abc38a
---

Repo cleanup 2 (2026-11-17, owner asked 'get rid of anything we are not using') removed 135 worktrees, 11 builds, 19.6 GiB of frame captures; record only, current state differs
Recorded then (not re-verified): 50 dirty worktrees saved as git diff HEAD --binary patches in src/fe-lab/archive/wt_patches/<name>_<head>.patch (50 patches present 2026-11-25; restore: git worktree add <path> <branch>; git apply). Build exe hashes in src/fe-lab/cleanup/builds_removed_*.json. nx2-frame-*.tga purged except gates/wave7ingame, wave7games34, third_game_stall, fourth_game_first_boot. Owner word was needed then for baselines/, bisect/, repo-backups/, runs/, upstream zips, C:\eg\build-1..7 and m-* trees. Today: git worktree list shows 174 entries (many src/acc-*) and 293 branches, so the '11 worktrees / 115 branches' figures are obsolete.
