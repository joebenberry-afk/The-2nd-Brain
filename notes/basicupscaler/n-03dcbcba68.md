---
id: n-03dcbcba68
kind: procedure
at: 2026-10-09T02:45:48Z
source: agent
evidence:
  - BasicUpscaler/tools/space_guard.py
  - BasicUpscaler/tools/space_guard.json
evidence_sha:
  - BasicUpscaler/tools/space_guard.py=053e9dd7daa6
  - BasicUpscaler/tools/space_guard.json=6e7a9911782f
tested: "true"
tested_by: agent
tested_at: 2026-10-09T02:45:48Z
tested_sha: 3d665e1ac7bf
---

Free-space floor 100 GiB on C: and D: (DECISIONS 54, owner 8 Oct). Tool: BasicUpscaler/tools/space_guard.py {status|check --path P --need GiB|reclaim [--apply]|watch}, rules in space_guard.json (reclaim to 125). omp hook ~/.omp/agent/hooks/pre/space-guard.ts blocks bash/eval/task under floor (cleanup cmds pass). Scheduled task "BasicUpscaler Space Guard" runs watch every 10 min + logon (pythonw C:\Python314). Log %LOCALAPPDATA%\BasicUpscaler\space-guard\log.jsonl. Analyzed fg_live grab PNGs auto-deleted after 24 h (owner-approved). D: exFAT 1 MiB clusters: cargo targets go on C:. Bash eats $_ in powershell -Command; run PowerShell via Python subprocess list args.
