---
id: n-0bbbc638a2
kind: gotcha
at: 2026-09-28T06:41:26Z
source: agent
errors:
  - "re:/dev/fd/\\d+: The system cannot find the path specified"
tested: "true"
checked: holds
checked_at: 2026-11-25T17:52:17Z
checked_why: A native Windows program cannot open the path that Git Bash process substitution hands it. [Git Bash `python -c 'open(sys.argv[1])' <(echo hi)` -> FileNotFoundError '/proc/<pid>/fd/63']
checked_sha: b08d02abf9a7
---

Git Bash on Windows: process substitution <(...) hands native programs a /dev/fd path they cannot open; write each side to a temp file (or pipe) and pass the file paths instead.
