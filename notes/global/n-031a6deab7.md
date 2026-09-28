---
id: n-031a6deab7
kind: gotcha
at: 2026-09-28T03:54:18Z
source: agent
errors:
  - payload line has no preceding hunk header
tested: "true"
---

Payload line without a hunk header: an OMP hashline edit needs an op row (PUT N.=M:, PUT <N:, PUT >N:, CUT N.=M) before any +content row; start the body right after the [path#tag] header with that op.
