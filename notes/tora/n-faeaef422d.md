---
id: n-faeaef422d
kind: fact
at: 2026-10-08T01:52:41Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-08T01:52:41Z
tested_sha: bfc08451baef
---

Sparking Zero 7 Oct 2026 ~21:46–21:49:32 local: periodic ~110–120 ms frame stall exactly every 2.0 s during a match (PresentMon, both with Tora idle and busy), then it stopped and never returned. Not Tora (Tora A/B: fps +0.10 ± 0.34, p99 +0.18 ± 1.88 ms). Cause unknown: suspect a 2-s poller (sensor/monitor such as G-Helper/RTSS polling, a mod/telemetry hook) or game-side; data in Tora/results/ingame-20261007-214619/.
