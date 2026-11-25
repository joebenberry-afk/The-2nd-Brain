---
id: n-d0fbaec5d4
kind: note
at: 2026-10-18T08:55:58Z
source: agent
---

K6 FT-1 owned fail (b3+refresh, 18 Oct) was NOT clip loss: gate opens less after machine change in 07:34-07:46 owner window. Signature in fg.jsonl: content_clock.before.present_observed_qpc-raw_qpc (ETW Present delivery) p50 ~7ms healthy vs 12-13ms bad; AF-12 fresh residual 0.2-0.3 vs 0.5-0.6px. timebase.rs flush_loop uses park_timeout(4ms) without raised timer res. Receipt runs/frame_generation/20261018T085337Z_m1-k6-ft1-midqueue/. Refresh mode separately breaks read_plan_trace (held real copy goes back a pair).
