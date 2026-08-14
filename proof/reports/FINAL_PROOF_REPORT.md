# The Second Brain — v4.3 Proof Report

## 1. Verdict level

**P1 mechanism substrate: partial. P2/P3/P4/P5/P6: not proven as end-to-end
claims. P7 production-ready: fail.**

The campaign stopped before final holdout creation because the supplied ACTIVE
contract is not automatic: Prime observes lifecycle events, but no official
handler recalls memory, routes a skill, injects context, records an episode, or
learns. A manually invoked Python API is not C3 and cannot satisfy G16.

## 2. Candidate

- Repair commit: `06bf24642aad61a4bf527fc97ddb8d5d08a07f1d`
- Campaign runner commit at measurement: `1bccbe6`
- Plan SHA-256: `EE8F245D2F0A5D02D584B0448C49C242EA3DE42F2837C45CF05944E21A9B2791`
- Prime selector: `deepseek/deepseek-v4-flash`
- Thinking: `minimal`
- Prime: `0.7.2`; Python `3.13.7`; Node `v25.7.0`

## 3. Pre-proof faults

Fixed before campaign data: false transfer on zero-success/one-overlap data;
inconsistent skill lifecycle/frontmatter; stale frontier approvals; global
negative-model masking; stale authority/control-character documentation.

Narrowed or retained honestly: substring-only retrieval; non-operative config
keys; observability-only Prime integration; retrospective/small historical
experiments; missing broad corpus and portability evidence.

## 4. Dataset and integrity

- Smoke: 10 short-response training tasks.
- Candidate overhead stage: 30 paired short-response training tasks, randomized
  per task with seed `20260814`.
- Retrieval: fresh synthetic labeled corpora of 100, 1,000, and 10,000 memories.
- Calibration: not created.
- Final holdout: **not created**; `proof/hashes/holdout.sha256` intentionally
  does not exist.
- No holdout labels were sent to workers or solvers.

## 5. Conditions

C0 OFF and C1 observability were executed with fresh workspaces, Brain homes,
session directories, identical model policy, and deterministic oracles. C2,
C3, C4, C5, C6, and C7 were refused by the runner until automatic integration
is verified; they are not silently substituted with manual calls.

## 6. Correctness and overhead

The 30 paired C0/C1 runs succeeded 30/30 in both conditions. Paired success
delta was `0.0 pp`, bootstrap seed `20260814`, 10,000 resamples, 95% interval
`[0.0, 0.0] pp`. Median wall-time overhead was `1.01%`; p95 overhead was
`1.88%`. C1 had 30/30 session-shutdown records, zero failed tool calls, and
mean peak context usage `1.0632%`. Input/output token counts were unavailable,
so token-economy gates remain open.

## 7. Retrieval

At all three corpus sizes, Recall@5 was `1.0000`, but Recall@1 was `0.0000`,
Precision@5 was `0.3333`, duplicate injection was `0.3333`, stale activation
was `0.3333`, and contradiction surfacing was `0.0000`. At 10,000 memories,
latency was p50 `1,374.5167 ms` / p95 `1,426.1416 ms`. This fails the realistic
retrieval-quality gates; Recall@5 is not useful evidence without ranking and
stale handling.

## 8. Skills, learning, and transfer

The router fixture reported precision/recall/F1 `0.083/0.083/0.083` versus the
natural baseline `0.333/0.333/0.333`; no unseen-language or blinded skill
execution claim is made. The focused promotion/security/immune/backup/transfer
suite passed 70 tests, including stale-approval refusal, incomplete-active
refusal, poison heuristics, guarded rollback, restore sidecar handling, and
false-transfer regressions.

Natural learning, cross-session retrieval, cross-model uplift, and
cross-project leakage were not run because the official Prime path cannot
capture or inject the needed Brain state automatically. The transfer guard is
tested; transfer benefit is not.

## 9. Scale and recovery

An isolated eight-worker stress wrote 200 memories with 200 rows,
`integrity_check=ok`, and an empty foreign-key check. Python’s full suite passed
431 tests; proof deterministic checks passed 9 tests (440 combined); the scoped Prime
extension passed lint, typecheck, and 66 tests; the real enabled/disabled Prime
integration smoke passed. The 10,000-memory retrieval quality/latency failure
prevents a P5 scale claim.

## 10. Gate summary

| Gate | Verdict | Evidence |
|---|---|---|
| P0 proof integrity | pass | blockers reproduced and repaired separately |
| P1 mechanisms | partial | deterministic, lifecycle, safety, and recovery substrate pass |
| G1/G3 correctness/rework | unassessed | no ACTIVE holdout |
| G4 token economy | unassessed | token fields unavailable |
| G5 retrieval | fail | precision/stale/contradiction/10k latency failures |
| G6 no-memory discipline | unassessed | no ACTIVE condition |
| G7 routing | fail on current fixture | 0.083 precision/recall/F1 |
| G8 learning | unassessed | no automatic episode/learning path |
| G9–G15 | unassessed/partial mechanism only | no C3 history or final dataset |
| G16 autonomy | fail | no automatic Prime Brain event path |

## 11. Required continuation

Implement and verify a real Prime event contract for automatic targeted recall,
routing, bounded injection, outcome capture, and safe learning. Then create a
new candidate commit, calibration set, and frozen/hash-bound holdout. Do not
reuse this report’s non-holdout results as final efficacy evidence, and do not
claim P7 from the current observability-only integration.
