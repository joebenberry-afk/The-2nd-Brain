---
id: n-47e6afbb3b
kind: gotcha
at: 2026-11-16T14:17:56Z
source: agent
evidence:
  - src/fe-lab/lab_series.py
evidence_sha:
  - src/fe-lab/lab_series.py=e40acc8c1cd2
tested: "true"
tested_by: agent
tested_at: 2026-11-16T14:17:56Z
tested_sha: 398ccc35b8c9
---

fe-lab series runner silently reuses old results: lab_kit.series() skips any tag already present in results.json and lab_series.py then prints the OLD row as if the run had just finished.
Symptom: a relaunched series prints finished rows within seconds, numbers identical to the previous binary. Before relaunching a series on a new build, rename or delete the stale tags in results.json (and runs/<tag>), and assert no spec tag is in results.json. Never treat a row as evidence for a build unless runs/<tag>/eden_log.txt is newer than the binary.
