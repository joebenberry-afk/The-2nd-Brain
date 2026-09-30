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

OMP hashline edits use [path#tag] then PUT N.=M: with +content, not unified diffs.

An input-header rejection means the wrong edit grammar; copy the read tag and use anchored PUT rows.
