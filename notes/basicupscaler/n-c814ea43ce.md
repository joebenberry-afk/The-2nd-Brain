---
id: n-c814ea43ce
kind: procedure
at: 2026-11-25T21:01:15Z
source: agent
errors:
  - "TimeoutError: no ['P3R.exe'] process with a window within the start timeout"
evidence:
  - arena/m1_gate.py
  - tools/bench.py
evidence_sha:
  - arena/m1_gate.py=a3063df459e5
  - tools/bench.py=ef0b5b1bc1e2
replaces: n-2c1cd7e5b7
replaced_by: n-b4676cc416
retired: 2026-11-25T21:05:49Z
---

P3R.exe start timeout: check Steam/logs/content_log.txt for AppID 228980; queue needs 600 s owner idle. Re-record an old M1 candidate (done for K48, 10 Nov 2026): git worktree add C:/BU-wt/m1-k48 m1-k48; zstd -d C:/BU-gen/m1-gate/<cohort>/runs/<step>/bufg_m1_<sha8>.exe.zst into <wt>/target/release/ (seen 25 Nov 2026: D:/BasicUpscaler and D:/BU-gen do not exist; archives moved to C:, cohorts K0-K10, each with MOVED.json). bu-record.exe is in main runs/frame_generation/<stamp>_m1-cohortK*-tools/. Old freezes bind the original bu.exe bytes, so re-plan: python -m arena.m1_gate plan --candidate <exe> --out <new dir> [--inputs <json>] (arena/m1_gate.py:215); then python -m tools.m1_preflight <queue dir>; then python -m tools.m1_queue <queue dir>. IDLE_S=600 s (tools/bench.py:128). game_driver start timeout defaults to 180 s (tools/game_driver/runner.py:611) unless a profile overrides. Not re-seen: K48 cohort archive location, bu.exe non-archival.
