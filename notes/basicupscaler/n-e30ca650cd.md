---
id: n-e30ca650cd
kind: note
at: 2026-10-22T12:18:35Z
source: agent
---

pytest on this machine can exit 1 after all tests pass: sessionfinish cleanup_dead_symlinks raises in os.unlink on the default temp root. Pass --basetemp <scratch dir> to get a clean exit code (FG-462a, 22 Oct).
