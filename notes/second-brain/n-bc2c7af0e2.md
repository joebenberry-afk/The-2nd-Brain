---
id: n-bc2c7af0e2
kind: decision
at: 2026-10-18T15:01:22Z
source: agent
evidence:
  - CLAUDE.md
evidence_sha:
  - CLAUDE.md=e3b8d1a7f19b
---

Claude Code card drops its when-to-act footer when CLAUDE.md already loads the brain hook agents-md block (global CLAUDE.md, or project CLAUDE.md directly or via @AGENTS.md): the rules were in context 2-3 times; freed room holds one more note. Module-load trimming of the hook path was measured and skipped: whole cli.ts graph imports in ~45 ms with compile cache, saving at most ~20 ms.
