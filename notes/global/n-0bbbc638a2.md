---
id: n-0bbbc638a2
kind: gotcha
at: 2026-09-28T06:41:26Z
source: agent
errors:
  - "re:/dev/fd/\\d+: The system cannot find the path specified"
tested: "true"
---

Git Bash on Windows: process substitution <(...) hands native programs a /dev/fd path they cannot open; write each side to a temp file (or pipe) and pass the file paths instead.
