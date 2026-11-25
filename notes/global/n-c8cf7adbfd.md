---
id: n-c8cf7adbfd
kind: decision
at: 2026-11-06T01:21:06Z
source: agent
replaces: n-e5576d711d
---

Owner-approved agent split for RE/port work:
1. Haiku (`sonic` or `scout`, model haiku) gathers raw facts: table dumps, Ghidra grep, xrefs, strings, CLI logs. The results are written to files.
2. One Sonnet/Opus `feature-implementer` interprets those facts and ports the code.
3. `implementation-verifier` runs the gates and returns PASS/FAIL.
Never default to generic `task`. Keep 2-4 agents at a time; the lead integrates.
