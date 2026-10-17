---
id: n-d2c9c9ced1
kind: fact
at: 2026-10-17T07:37:10Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-17T07:37:10Z
tested_sha: f1cffce308e1
replaced_by: n-6fafdf606c
retired: 2026-10-17T08:32:03Z
---

probebench recall items never show compaction loss; only tool-output detail probes do. — E2 2026-10-17: user-message facts survived 1, 3 and 10 compactions on Claude Code, OMP and Codex (32-33/33 per arm). Detail probes (one value in a single log line, asked from memory at depth ≥2) at depth 3: CC default 3/6, Codex default 0/6 (answered "unknown"), never-compacted arms 6/6. Use detail probes as the bench's positive control; they are layer 3's measurable target. OMP has no detail-probe run yet.
