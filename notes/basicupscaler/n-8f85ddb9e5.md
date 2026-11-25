---
id: n-8f85ddb9e5
kind: procedure
at: 2026-11-25T21:00:57Z
source: agent
errors:
  - "TimeoutError: no ['P3R.exe'] process with a window within the start timeout"
evidence:
  - arena/m1_gate.py
  - tools/bench.py
evidence_sha:
  - arena/m1_gate.py=a3063df459e5
  - tools/bench.py=ef0b5b1bc1e2
replaces: n-35f1d81b1e
replaced_by: n-2c1cd7e5b7
retired: 2026-11-25T21:01:09Z
---

Re-recording an old M1 candidate (done for K48, 10 Nov 2026): the recipe's archive root moved from D: to C:. Seen 25 Nov 2026: D:/BasicUpscaler and D:/BU-gen do not exist; archives are at C:/BU-gen/m1-gate/<cohort>/runs/<step>/bufg_m1_<sha8>.exe.zst (cohorts K0-K10 only; each cohort has MOVED.json from the D:->C: move). 1) git worktree add C:/BU-wt/m1-k48 m1-k48 (worktree currently exists, branch m1-k48). 2) zstd -d the candidate into <wt>/target/release/. 3) bu-record.exe is in main runs/frame_generation/<stamp>_m1-cohortK*-tools/. 4) Old freezes bind the original bu.exe bytes, so re-plan: python -m arena.m1_gate plan --candidate <exe> --out <new dir> [--inputs <json>] (arena/m1_gate.py:215); preflight with python -m tools.m1_preflight <queue dir>; run python -m tools.m1_queue <queue dir>. Queue needs IDLE_S=600 s owner idle (tools/bench.py:128). game_driver start timeout defaults to 180 s (tools/game_driver/runner.py:611) unless a profile overrides; a Steam update for AppID 228980 can outlast it (Steam/logs/content_log.txt). Not re-seen: K48 cohort archive location, 'bufg_m1_' bytes for K11+ cohorts, non-archival of bu.exe.
