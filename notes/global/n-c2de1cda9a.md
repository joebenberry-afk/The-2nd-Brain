---
id: n-c2de1cda9a
kind: decision
at: 2026-10-19T11:35:04Z
source: agent
replaced_by: n-c2f1ac3e24
retired: 2026-10-19T16:34:59Z
---

Keep OMP's 1-hour Anthropic prompt-cache TTL; 5-minute writes cost more overall.
14 days of OMP requests (2026-10-19): 997 came 5m-1h after the previous one; at 5m Opus input cost +77%, Sonnet +19.5%. Short TTL plus idle cache warming modeled Opus +0.3%, Sonnet -12% (warming pings priced as full-prefix reads), not applied: OMP cfg change needs the owner.
