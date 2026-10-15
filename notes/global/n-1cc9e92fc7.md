---
id: n-1cc9e92fc7
kind: decision
at: 2026-10-07T19:30:05Z
source: agent
---

omp modelRoles set 2026-10-07: smol/tiny/commit/memory = claude-haiku-5-5:auto; default = Opus 5.5; plan = Opus 5.5:auto (same model as the system-architect agent); slow/vision/advisor = gpt-6-astra; task = gpt-6.1-sol:auto (same model as the task agent override). judge/web/image/speech roles were left unset on purpose.
To verify a role: `omp -p --model @<role> --mode json "..."` and grep "model". Eval completion() only accepts smol/default/slow.
