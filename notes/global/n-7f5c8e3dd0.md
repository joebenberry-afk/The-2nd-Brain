---
id: n-7f5c8e3dd0
kind: gotcha
at: 2026-09-28T06:41:26Z
source: agent
errors:
  - ERR_UNSUPPORTED_ESM_URL_SCHEME
tested: "true"
replaces: n-7742a45edd
---

Node ESM on Windows rejects bare C:/ absolute import paths (protocol 'c:'); import with a relative path or pathToFileURL(path).href, or run the script with bun, which accepts C:/ paths.
