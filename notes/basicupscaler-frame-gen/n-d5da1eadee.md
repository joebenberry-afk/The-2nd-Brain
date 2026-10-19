---
id: n-d5da1eadee
kind: note
at: 2026-10-18T22:51:32Z
source: agent
---

m1_gate plan freezes a missing executable as sha256 null without refusing; execute then refuses exit 2 'executables missing'. K10 freeze 20261018T224759Z referenced K9 tools under C:/BU-wt/m1-k9/runs/... but they lived only in main repo runs/; fixed by copying tools dir into worktree + re-freeze 20261018T225041Z (queue K10b 20261018T225100Z). Check freeze code.executables sha256 non-null before queueing.
