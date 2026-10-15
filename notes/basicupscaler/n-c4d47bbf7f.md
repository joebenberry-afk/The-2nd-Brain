---
id: n-c4d47bbf7f
kind: gotcha
at: 2026-10-07T12:57:47Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-07T12:57:47Z
tested_sha: 6e4aef840227
---

BUFG live: WGC monitor-grab "latency" is not photon latency; tearing FG presents also tear on screen.
FG presents ahead of the refresh (lead). With DXGI_PRESENT_ALLOW_TEARING they flip at once on the overlay plane (GetFrameStatisticsMedia mode 1), mid-scanout: 99.6% report the refresh before the plan. That's a real tear line, invisible to WGC grabs. With vsync 99–100% land on plan, so GetFrameStatistics labels ARE reliable for synced presents.
The grab latency depends on flip phase vs DWM capture composition: 28 ms (tearing, P/2 early) vs 45–53 ms (synced) for ≤2.5 ms of real display difference. Never compare latency with LSFG from grabs; needs photon/PresentMon (elevated).
Synced presents collapse under a saturated GPU (57–81 vs 133–137 pictures/s; testsource gpu-work 3500): unsolved (FG-119). Shipped 9de45e4: FG follows the Vsync setting, synced lead 3/4 refresh.
