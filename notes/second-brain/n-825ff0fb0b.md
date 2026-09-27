---
id: n-825ff0fb0b
kind: procedure
at: 2026-09-27T20:08:03Z
source: agent
evidence:
  - brain/package.json
tested: "true"
---

After changing brain/: npx eslint src test && npx tsc --noEmit && npx vitest run

Run inside brain/. The suite includes the frozen recall eval on the committed notes (must stay dev >= 13/15, held-out >= 7/8) and, where pwsh exists, the real installer round trip with a Bun load of the installed extension.
