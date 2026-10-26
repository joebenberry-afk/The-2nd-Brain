---
id: n-7e6591aaee
kind: note
at: 2026-10-25T23:36:55Z
source: agent
---

BUFG pacer fixes 25 Oct, branch bufg-pacer-fixes 725df2da (worktree C:/BU-wt/bufg-pacer-fixes, not merged): Cadence::vetted bridges up to 3 missing ETW Present events at arrival minus median offset (C091); bypass_generation takes real periods + factor, 2x bypasses only below 0.95*2*refresh, leaves at 0.975 (C092; 82.5 fps on 165 Hz was fully bypassed). Bridged frames log as etw_present (no counter). fg_pace.rs was not rustfmt-clean on main. bu-replay frame4258 test fails on main (fixed on m1-k43 30667962).
