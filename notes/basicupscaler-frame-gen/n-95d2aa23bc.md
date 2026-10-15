---
id: n-95d2aa23bc
kind: procedure
at: 2026-10-14T23:49:54Z
source: agent
evidence:
  - runs/frame_generation/20261015T000000Z_raw-throttle/listen.py
evidence_sha:
  - runs/frame_generation/20261015T000000Z_raw-throttle/listen.py=70542852301f
tested: "true"
tested_by: agent
tested_at: 2026-10-14T23:49:54Z
tested_sha: 241b52a39015
---

Windows 25H2 (build 26200.9457) background raw-mouse throttle.
- Values: Enabled default 1 (range 0..1), Forced 0 (0..1), Duration 8 ms (1..20), Leeway 2 ms (0..5). They are read by ReadRawMouseThrottlingThresholds from the per-user loader, so only RawMouseThrottleEnabled=0 can disable it.
- 2026-10-14 23:44Z: set HKCU\Control Panel\Mouse\RawMouseThrottleEnabled=dword 0.
- `rundll32 user32.dll,UpdatePerUserSystemParameters` did NOT apply it: the background listener still showed p50 8.3 ms over 4,602 messages.
- It needs a sign-out or reboot. After that, rerun runs/frame_generation/20261015T000000Z_raw-throttle/listen.py and expect about 1 ms.
- Revert: delete the value, then sign out.
