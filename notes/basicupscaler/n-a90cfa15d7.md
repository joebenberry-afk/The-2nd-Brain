---
id: n-a90cfa15d7
kind: gotcha
at: 2026-10-06T10:44:44Z
source: capture
errors:
  - "ModuleNotFoundError: No module named 'arena'"
evidence:
  - events:d6a39786-624e-45ab-bb86-35dc90fc8944.jsonl#140906-141556
tested: "true"
tested_by: capture
tested_at: 2026-10-06T10:44:44Z
tested_sha: f034dafa62bf
---

python: python .superpowers/sdd/2026-10-04-bufg-proof-plan-1-discove fails (ModuleNotFoundError: No module named 'arena'); PYTHONPATH=. python .superpowers/sdd/2026-10-04-bufg-proof-p works

python .superpowers/sdd/2026-10-04-bufg-proof-plan-1-discovery/diag_selftest.py

PYTHONPATH=. python .superpowers/sdd/2026-10-04-bufg-proof-plan-1-discovery/diag_selftest.py

Error: Exit code 1
Traceback (most recent call last):
  File "C:\Users\assas\Documents\BasicUpscaler\BasicUpscaler\.claude\worktrees\bufg-proof\.superpowers\sdd\2026-10-04-bufg-proof-plan-1-discovery\diag_selftest.py", line 9, in <module>
    from arena import fg_metrics as fm
ModuleNotFoundError: No module named 'arena'
