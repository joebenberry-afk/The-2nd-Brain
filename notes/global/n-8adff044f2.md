---
id: n-8adff044f2
kind: gotcha
at: 2026-09-27T22:45:56Z
source: agent
errors:
  - input must begin with "[PATH#HASH]" on the first non-blank line for anchored edits
evidence:
  - state/events/01a0e505-94ef-75e3-bfbc-0febcbe69e65.jsonl:31-39
tested: "true"
host: omp
---

OMP edit takes no apply_patch or diff: for `*** Add File` use the write tool; for `*** Update File` read the file, then send `[path#TAG]` with the tag that read printed and ops such as `PUT 12.=14:` followed by `+new line` rows.

Telemetry: 76 of 82 header rejections were apply_patch input (60 Update File, 16 Add File).
