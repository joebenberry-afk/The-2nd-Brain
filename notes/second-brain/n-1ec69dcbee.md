---
id: n-1ec69dcbee
kind: gotcha
at: 2026-09-28T04:10:48Z
source: agent
tested: "true"
---

Never pair `git stash -- <path>` with `git stash pop` in a script: when the path has no changes no stash is created, and pop applies the user's older stash instead. This repo keeps two owner stashes (v1-rc4 era). Compare old code with `git show <rev>:<path> > /tmp/x` instead.
