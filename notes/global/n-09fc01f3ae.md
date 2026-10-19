---
id: n-09fc01f3ae
kind: decision
at: 2026-10-19T16:34:59Z
source: agent
evidence:
  - docs/intake/2026-10-17-layer4-reversible-rendering.md
evidence_sha:
  - docs/intake/2026-10-17-layer4-reversible-rendering.md=3d3ef1cfe319
---

OMP compaction: global thresholdTokens 140000 (set 2026-10-17); modelThresholds anthropic/claude-opus-5-5 f180000, anthropic/claude-sonnet-5-5 f200000 (2026-10-19, owner-approved).
Before 10-17 compaction was reserve-based, so 1M-window sessions ran to about 850k tokens (27% of Opus requests were above 400k). Model: reads of a context growing from 51k to T plus a rewrite and summary per compaction. The optimum is Opus 170-190k and Sonnet 200-230k (modeled -2.6..-5.4% / -9.4..-11.3% vs 140k). OpenAI stays at 140k because remote compaction reads uncached (optimum 155-170k, <2% gain).
The "f" prefix means an exact trigger; a bare number is a base the policy scales.
Details: docs/intake/2026-10-17-layer4-reversible-rendering.md §7.
