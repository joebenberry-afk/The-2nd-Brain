---
id: n-6fafdf606c
kind: fact
at: 2026-10-17T08:32:03Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-17T08:32:03Z
tested_sha: 26ce0f09e97a
replaces: n-d2c9c9ced1
---

probebench recall items never show compaction loss; only tool-output detail probes do, and the current detail probes are WARN/ERROR-marked.
E2 2026-10-17: user-message facts survived 1, 3 and 10 compactions on Claude Code, OMP and Codex (32-33/33 per arm). Detail probes (one value in a single log line, asked from memory at depth ≥2) at depth 3: CC default 3/6, Codex default 0/6 (answered "unknown"), never-compacted arms 6/6. OMP has no detail-probe run yet.
Gotcha for layer 3: the generator (probebench.ts ~117-121) makes the shard detail the only "checksum mismatch" line (WARN) and the component detail the only ERROR line, so a WARN/ERROR digest answers both by construction. A fair layer-3 test needs details on unmarked lines.
Session rules: status_kept is scored as a reply prefix since 2026-10-17 (startsWithTag); rescoring made CC d3 brain 1/3, and compacted runs breaking a rule 4/24. The Codex vendor/ edit was non-compliance: the rule was verbatim in all 3 compacted histories.
