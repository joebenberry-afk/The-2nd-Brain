---
id: n-7cc44ae8c8
kind: decision
at: 2026-10-25T09:03:06Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-25T09:03:06Z
tested_sha: 9e76316bbbdf
---

X25 (Win32k token latch) is BUFC's take-time Present lookup by default since 98da3246; `bu live --no-win32k-tokens` restores the back-off key alone.
Why: held-out receipt runs/frame_generation/20261025T040759Z_bufc-x25-flip attempt 2 (protocol v2) passed every frozen gate: served right 0.99891–0.99960 at 60h/120/150/240/gpu60 vs back-off 0.77236–0.99841 same rows; no token-served take wrong; misses = flush timeouts (no key).
Gotchas: fg.jsonl content_time_sigma_qpc is the cadence beat's hypot(fit, raw), not the raw served sigma, and content_qpc is the fitted line — neither identifies the served Present exactly. Take log has 18 columns (+served). Repose/camera lookups stay on the back-off key. Old `--win32k-tokens` flag is gone (clap error).
