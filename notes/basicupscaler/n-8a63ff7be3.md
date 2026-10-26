---
id: n-8a63ff7be3
kind: note
at: 2026-10-24T03:06:34Z
source: agent
---

Supersedes n-b644e99a24: since commit 9dd228eb (24 Oct) 'python -m tools.bench run ... -- CMD' hands CMD the bench's stdout with stderr merged, so a CLI child's prints and tracebacks are kept (redirect the bench's stdout to a file). Before it, BUFC X2 rerun 2's probe traceback was lost. The API output= workaround is no longer needed.
