---
id: n-58efb4f97e
kind: gotcha
at: 2026-10-24T23:53:15Z
source: agent
---

Git-bash $$ / $! are MSYS pids, not Windows pids: psutil.pid_exists($$) is False
A watcher bound to `$$` from a Git-bash script (e.g. orphan_reaper.py $$) exits at once with "chain exited". Get the Windows pid with `cat /proc/$$/winpid`, or with psutil (the ppid of the child python process).
