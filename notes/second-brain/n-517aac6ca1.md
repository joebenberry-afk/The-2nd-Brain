---
id: n-517aac6ca1
kind: gotcha
at: 2026-11-25T20:56:17Z
source: agent
errors:
  - "fatal: could not read Username for 'https://github.com'"
tested: "true"
tested_by: agent
tested_at: 2026-11-25T20:56:17Z
tested_sha: 33740ce93d15
---

Second Brain push fails from agent shells when the active gh account is logicdelos: origin is joebenberry-afk/The-2nd-Brain and logicdelos has no access.
Fix (set 2026-11-25, repo-local in .git/config, not committed): credential.https://github.com.helper is reset to "" (stops the global `manager` helper) and then set to a shell function that returns username joebenberry-afk and `gh auth token --user joebenberry-afk`. It works whichever gh account is active; no token is stored. Do not use the stock `gh auth git-credential`: it hands out the active account's token.
A fresh clone needs the same two config entries. Check a push landed with `git ls-remote origin main`, not the local origin/main ref.
