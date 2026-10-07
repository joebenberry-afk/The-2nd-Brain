---
id: n-f34deb6af6
kind: fact
at: 2026-10-05T07:36:52Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-05T07:36:52Z
tested_sha: f0f6f409d141
---

RTSS benchmarking facts (measured 5 Oct, FramePacing §46):
- RTSS async (SyncLimiter=0, owner default) waits AFTER Present (frame-start sync); front-edge sync (SyncLimiter=1) waits before Present (2.4 µs Present SD, +1 period latency).
- RTSSHooksProfileOverride honours ONE property per UpdateProfiles(); sequential overrides keep only the last.
- Trick: run the owned fixture as a copy named after an owner profile exe (SparkingZERO-Win64-Shipping.exe Limit=60, granblue_fantasy_relink.exe Limit=120) -> RTSS applies that profile; override SyncLimiter,1 then gives front-edge sync at that cap. No RTSS file edits.
- RTSS OSD adds ~0.52 ms before the real Present at 60 FPS (up to 250 µs SD at 120); BUFP hooks RTSS's relay so that jitter lands after BUFP's wait.
- Short (<3 ms) high-res timer requests wake ~0.5 ms late (tick-quantized) on this laptop; a timer cascade did not help.
