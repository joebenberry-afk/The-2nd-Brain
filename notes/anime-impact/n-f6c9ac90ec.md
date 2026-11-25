---
id: n-f6c9ac90ec
kind: decision
at: 2026-11-08T13:18:49Z
source: agent
evidence:
  - tests/run_layer.gd
  - sim/run/run_map.gd
evidence_sha:
  - tests/run_layer.gd=9444ad4043d7
  - sim/run/run_map.gd=d79a1cb3737a
tested: "true"
tested_by: agent
tested_at: 2026-11-08T13:18:49Z
tested_sha: 64cb52db4fbd
---

Anime Impact map: every path must draft ≥4 sigils (owner 4–7). The 20-node map (Intel + Curtain Rift) let paths draft 3; fixed in run_map.gd: row-2 non-draft nodes (event/shop/intel) link only to elite or row-3 fight. tests/run_layer.gd asserts lo>=4. Measured 4..5, mean 4.27; hero-shop pace unchanged (6–7 heroes at first clear).
