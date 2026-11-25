---
id: n-6fc7816cef
kind: decision
at: 2026-11-18T10:30:28Z
source: agent
evidence:
  - src/fe-lab/plans/ledger_main.json
evidence_sha:
  - src/fe-lab/plans/ledger_main.json=13310425e1aa
replaces: n-c4ffe14360
replaced_by: n-15b68b80ac
retired: 2026-11-18T10:37:02Z
---

Owner launch rule: at most 10 launches per game per testing round (one fix/test cycle), not a lifetime cap. Purpose: no relaunching 30 times per build fix; make each launch count (build, unit tests and review first, then one baseline + one candidate). Goal is games that work and are accurate. Ledger 'used' counts in ledger_main.json are per round; reset at the start of a new testing round.
Context kept: DK Bananza and Splatoon Raiders loading stalls fixed at c59e637e4c (advance-only syncpoint publication). Local builds: build/head-src .git points into the live worktree gitdir, never run git there; export with git archive. lap2 syncs must set mtimes to now.
