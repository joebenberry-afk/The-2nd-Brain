---
id: n-aed96987dd
kind: fact
at: 2026-09-28T05:18:29Z
source: agent
tested: "true"
---

Agent token cost is turns × context, not prose: 24h all sessions = 611M cache-read tokens vs 2.6M output; per GPT request ~26k schema tokens (eval ~17.5k, 11 unused mcp__jev_* ~4.8k), system prompt ~3.8k (skills 1.1k). Measure changes with `node scripts/agentbench.ts` (brain/), compare within one batch; batches drift ±5-10%.
