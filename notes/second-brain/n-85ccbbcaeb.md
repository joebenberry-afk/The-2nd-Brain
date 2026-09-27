---
id: n-85ccbbcaeb
kind: decision
at: 2026-09-27T20:08:03Z
source: agent
evidence:
  - docs/intake/2026-09-27-plan-v4-agent-experience.md
  - brain/test/eval.test.ts
---

V4 architecture: TypeScript package brain/, plain Markdown notes in git, no database; the OMP extension runs it in-process

Chosen 2026-09-27 (owner accepted all recommendations). Node >= 22.18 or Bun run the .ts files directly, no build step. Search is in-memory BM25 reproducing SQLite FTS5 bm25() exactly (test/search.test.ts parity test); frozen recall equals V3 (dev 13/15, held-out 7/8). Revisit an index only when a real corpus passes ~2000 notes or warm recall exceeds 50 ms.
