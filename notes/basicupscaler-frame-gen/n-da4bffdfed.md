---
id: n-da4bffdfed
kind: gotcha
at: 2026-10-13T04:31:42Z
source: agent
evidence:
  - target/release/bu.exe
evidence_sha:
  - target/release/bu.exe=e7294fa47937
tested: "true"
tested_by: agent
tested_at: 2026-10-13T04:31:42Z
tested_sha: 78a0daade12e
---

Before queueing any one-shot live run (FG-235 style, attempt.json written before acquisition), run every precondition its code checks, including space needs: fg216.run_arm needs C: >=12 GiB and D: >=1 GiB above the 100 GiB floor per arm. FG-235 attempts 1-2 (13 Oct) were burned before acquisition by a guard API mismatch (fg216 called RunGuard.wait(settle=...)) and then by C: space eaten by parallel cargo target dirs. Share one CARGO_TARGET_DIR across diet worktrees (target-diet-s4) instead of one ~4.5 GiB target per agent; verify copied bu.exe by an embedded shader snippet since the uplifted target/release/bu.exe is overwritten by whichever worktree built last.
