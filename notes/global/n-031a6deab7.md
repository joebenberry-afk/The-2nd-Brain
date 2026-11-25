---
id: n-031a6deab7
kind: gotcha
at: 2026-09-28T03:54:18Z
source: agent
errors:
  - payload line has no preceding hunk header
tested: "true"
checked: holds
checked_at: 2026-11-25T17:59:08Z
checked_why: "The current hashline spec requires an op row before +TEXT body rows, matching the note. [edit tool spec in this session: ops PUT N.=M:, PUT <N:, PUT >N:, CUT; body rows follow an op]"
checked_sha: fe83d930d89a
host: omp
---

Payload line without a hunk header: an OMP hashline edit needs an op row (PUT N.=M:, PUT <N:, PUT >N:, CUT N.=M) before any +content row; start the body right after the [path#tag] header with that op.
