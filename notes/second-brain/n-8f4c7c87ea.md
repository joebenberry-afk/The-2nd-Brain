---
id: n-8f4c7c87ea
kind: decision
at: 2026-10-18T15:13:38Z
source: agent
evidence:
  - CLAUDE.md
evidence_sha:
  - CLAUDE.md=e3b8d1a7f19b
replaces: n-d1efc49765
---

Card footer A/B final (2026-10-18, claude -p haiku, 60 headless sessions in this repo, 3 questions): sessions calling brain 30/30 with footer vs 28/30 without; the 16+16 third batch was identical (16/16, 19 calls each). No detectable effect, so the Claude Code card drops the footer whenever CLAUDE.md carries the agents block (saves ~40 tokens, frees a note slot).
