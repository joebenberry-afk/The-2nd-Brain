---
id: n-f10efdf52b
kind: fact
at: 2026-11-09T22:13:05Z
source: agent
evidence:
  - state/recall-live/policy-report.md
  - brain/test/eval.test.ts
evidence_sha:
  - state/recall-live/policy-report.md=e0aad71ae17a
  - brain/test/eval.test.ts=c7086a38f922
replaces: n-db11669556
---

Live recall eval (2026-11-09, 200 live queries, 535 pairs, 3 blind model votes): the Tora judge bar 0.999 has no clearly better neighbour; lowering it is worse, raising it is a trade.
Current 0.999: 38 right / 31 wrong / 24 miss / 107 silence. 0.9995: 34 / 11 / 39 / 116 (20 fewer wrong, 4 fewer right, 15 more misses). 0.998: 40 / 40 / 18 / 102. Keyword search alone: 26 right / 114 wrong. 123 of 200 queries have no right note among the candidates, so most empty recalls are correct. The first 60-case sample had suggested 0.9995 was a free win (11/6 vs 10/16); 200 cases showed it was not. Sign of the 0.9995 trade depends on label strictness (band 0.999-0.9995: majority labels 17 right / 21 wrong pairs; any-one-vote labels 27 / 11). Labels are model-voted, no owner review; sample is stratified, not proportional. Report: state/recall-live/policy-report.md; rerun: node scripts/recall-policy.ts from brain/. Gate: live block in brain/test/eval.test.ts.
