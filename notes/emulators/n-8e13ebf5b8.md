---
id: n-8e13ebf5b8
kind: decision
at: 2026-11-18T11:16:05Z
source: agent
checked: holds
checked_at: 2026-11-25T17:59:48Z
checked_why: Checkable facts agree (own firmware dump present, gen 0x16 key missing, fe-lab/build/src layout and Lichii worktrees exist), but the rules themselves are owner decisions I can't confirm. [Firmware/prod.keys (master_key_00..15 only, no _16); src/fe-lab, build/, src/omp06-lichii, src/lichii-core-cmp.g
checked_sha: cfc965a3ff54
replaces: n-3468810809
---

Owner rules (2026-11-18): (1) ADOPT ALL Lichii (zortos293/Lichii nx2) frontend features: UI (game grid, Properties, icon detect/upload), per-game options incl. game-specific enhancements (e.g. OoT FSR 3.1), FSR/DLSS/LSFG upscaling + frame generation, HDR, post-processing. Goal: games must run correctly WITHOUT them; enhancements optional, never required, never a substitute for an accuracy fix. (2) Keep everything in one place (src/fe-lab lab, build/ builds, worktrees under src/). (3) Firmware analysis allowed (own dump C:/Users/assas/Documents/Emulators/Firmware; keys gen 0x16 missing, study parked). (4) Launch cap 10 per game per testing round. (5) Orchestrate up to 20 agents, token-efficient; compile locally when no game runs, lap2 otherwise. (6) Keep recomp goal out; roadmap stays emulator.
