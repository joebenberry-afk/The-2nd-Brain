---
id: n-95d2aa23bc
kind: procedure
at: 2026-10-14T23:49:54Z
source: agent
evidence:
  - runs/frame_generation/20261015T000000Z_raw-throttle/listen.py
  - runs/frame_generation/20261015T000000Z_raw-throttle/inject_probe.py
evidence_sha:
  - runs/frame_generation/20261015T000000Z_raw-throttle/listen.py=70542852301f
  - runs/frame_generation/20261015T000000Z_raw-throttle/inject_probe.py=c3d82f94b5fa
tested: "true"
tested_by: agent
tested_at: 2026-10-14T23:49:54Z
tested_sha: 241b52a39015
replaces: n-204700ebfc
---

Windows 25H2 (build 26200.9457) background raw-mouse throttle: disable via RawMouseThrottleEnabled=0, then sign out/in; parameter refresh is insufficient. Injected probe input is not real input, so passive listeners during a probe record the probe's sends, not the owner's mouse (FG-290).
- Values: Enabled default 1 (range 0..1), Forced 0 (0..1), Duration 8 ms (1..20), Leeway 2 ms (0..5). They are read by ReadRawMouseThrottlingThresholds from the per-user loader, so only RawMouseThrottleEnabled=0 can disable it.
- 2026-10-14 23:44Z: set HKCU\Control Panel\Mouse\RawMouseThrottleEnabled=dword 0.
- `rundll32 user32.dll,UpdatePerUserSystemParameters` did NOT apply it: the background listener still showed p50 8.3 ms over 4,602 messages.
- It needs a sign-out or reboot. After that, rerun runs/frame_generation/20261015T000000Z_raw-throttle/listen.py and expect about 1 ms.
- Check without the owner: runs/frame_generation/20261015T000000Z_raw-throttle/inject_probe.py 2000 OUT under `tools.bench run --desktop` (unthrottled = 2000 packets at 1.0 ms; throttled ≈ 310 at 8 ms). Caveat: this injected probe differs from the owner's real mouse, so a listener running during it measures the probe.
- Revert: delete the value, then sign out.
