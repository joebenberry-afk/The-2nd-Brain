---
id: n-2c1cd7e5b7
kind: procedure
at: 2026-11-25T21:01:09Z
source: agent
errors:
  - "TimeoutError: no ['P3R.exe'] process with a window within the start timeout"
evidence:
  - arena/m1_gate.py
  - tools/bench.py
evidence_sha:
  - arena/m1_gate.py=a3063df459e5
  - tools/bench.py=ef0b5b1bc1e2
replaces: n-8f85ddb9e5
replaced_by: n-c814ea43ce
retired: 2026-11-25T21:01:15Z
---

To re-record an old M1 candidate: git worktree add C:/BU-wt/m1-k48 m1-k48, zstd -d C:/BU-gen/m1-gate/<cohort>/runs/<step>/bufg_m1_<sha8>.exe.zst into <wt>/target/release/, re-plan, preflight, queue. Seen 25 Nov 2026 (done for K48 on 10 Nov): D:/BasicUpscaler and D:/BU-gen do not exist; archives moved to C: (cohorts K0-K10, each has MOVED.json). bu-record.exe is in main runs/frame_generation/<stamp>_m1-cohortK*-tools/. Old freezes bind the original bu.exe bytes, so re-plan: python -m arena.m1_gate plan --candidate <exe> --out <new dir> [--inputs <json>] (arena/m1_gate.py:215); then python -m tools.m1_preflight <queue dir>; then python -m tools.m1_queue <queue dir>. Queue needs IDLE_S=600 s owner idle (tools/bench.py:128). game_driver start timeout defaults to 180 s (tools/game_driver/runner.py:611) unless a profile overrides; a Steam update for AppID 228980 can outlast it (Steam/logs/content_log.txt). Not re-seen: K48 cohort archive location, bu.exe non-archival.
