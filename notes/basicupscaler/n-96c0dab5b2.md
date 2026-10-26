---
id: n-96c0dab5b2
kind: note
at: 2026-10-23T11:32:16Z
source: agent
evidence:
  - tools/locks.py
evidence_sha:
  - tools/locks.py=1fe0c5e4642d
---

BU P1 (23 Oct 2026): a 725-byte placeholder FILE stands at the old FG path C:\Users\assas\Documents\BasicUpscaler Frame-Gen on purpose. Old branches' tools/locks.py fall back to that folder and mkdir(parents=True, exist_ok=True) it; with a file there they raise FileExistsError [WinError 183] instead of making a phantom lock folder that no other session sees. BU_LOCKS_DIR (User env) points sessions at the main checkout's runs\locks. Do not delete either while any branch has the fallback (53 local branches on 23 Oct); count: git grep -l -F 'BasicUpscaler Frame-Gen' $(git for-each-ref --format='%(refname)' refs/heads) -- tools/locks.py
