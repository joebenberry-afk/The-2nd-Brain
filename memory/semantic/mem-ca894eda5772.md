---
id: mem-ca894eda5772
title: In installed OMP18.1.15, Brain session identity must bind the native header time
scope: project
project: second-brain
status: candidate
grade: TESTED
version: 1
created_at: 2026-09-10T23:07:52.058956+00:00
---

In installed OMP18.1.15, Brain session identity must bind the native header timestamp and UUID, not a custom transcript basename. Commit79483dd preserves verified legacy bindings and refuses unbound existing history, including user-only history. Real same-basename sessions used separate ledgers; renamed Main and named-worker snapshots preserved event prefixes and four historical STOP receipts. Old3b rollback must hold candidate named/custom or renamed sessions unless its basename and ancestor keys match the established canonical bindings.
