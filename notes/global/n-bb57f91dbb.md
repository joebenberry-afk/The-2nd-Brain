---
id: n-bb57f91dbb
kind: gotcha
at: 2026-10-14T12:06:24Z
source: agent
evidence:
  - tools/integer_q_experiment.py
evidence_sha:
  - tools/integer_q_experiment.py=abeceb91a714
---

Python one-liner trap: open(p,'wb').write(open(p,'rb').read()...) truncates p before the inner read runs, so it writes an empty file. On 14 Oct this emptied tools/integer_q_experiment.py; it was committed as 62acb2f and restored in f5459f4. Always read into a variable first, then write.
