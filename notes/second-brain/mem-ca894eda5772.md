---
id: mem-ca894eda5772
kind: fact
at: 2026-09-10T23:07:52.058956+00:00
source: convert
evidence:
  - outputs/reports/v1-v2-completion-campaign-20260909T232221Z/native-identity-repair/frozen-native/proof.json@6085cec59596 (repo C:\Users\assas\Documents\The-Second-Brain)
  - outputs/reports/v1-v2-completion-campaign-20260909T232221Z/qualified-79483dd/independent-adoption-review.json@4b05c52d33ff (repo C:\Users\assas\Documents\The-Second-Brain)
retired: 2026-09-28T02:36:29Z
---

In installed OMP18.1.15, Brain session identity must bind the native header time

In installed OMP18.1.15, Brain session identity must bind the native header timestamp and UUID, not a custom transcript basename. Commit79483dd preserves verified legacy bindings and refuses unbound existing history, including user-only history. Real same-basename sessions used separate ledgers; renamed Main and named-worker snapshots preserved event prefixes and four historical STOP receipts. Old3b rollback must hold candidate named/custom or renamed sessions unless its basename and ancestor keys match the established canonical bindings.
