---
id: n-ffddae4882
kind: fact
at: 2026-10-22T00:38:30Z
source: agent
---

FT-2 keep qualification is pinned by the content clock, not the camera model: E1 (Cyberpunk) fits lag 0.12-0.22 ms and qualifies (residual 0.08-0.30 px, 1269-1806 generated pictures scored); non-E1 MHW/P3R fit lag 23.2-30.0 ms (P3R at the 30 ms grid edge) and fail (0.47-2.14 px), so generated pictures fall back to the 2 ms rule and only 0-63 are scored. Keep fallback, generated insufficient and the P3R diagonal fail (2.80 px on n=44) are downstream of this one cause.
