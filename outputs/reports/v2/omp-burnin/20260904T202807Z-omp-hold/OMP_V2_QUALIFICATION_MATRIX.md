# Second Brain v2 OMP Qualification Matrix

Run ID: `20260904T202807Z-omp-hold`  
Candidate SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`  
Branch: `brain/v2-omp-qualification`  
OMP: `18.1.10`  
Decision: **HOLD**

| Gate | Capability | Live? | Automated? | Evidence | Result | Blocking defect |
|---:|---|:---:|:---:|---|---|---|
| 0 | baseline/rollback protected | yes | yes | `19-rollback/ROLLBACK_VERIFICATION.md` | PASS | |
| 1 | exact OMP runtime/build identity | yes | yes | `20-final-regression/FINAL_REGRESSION.md`; `doctor` output | PASS | |
| 2 | lifecycle integration map | n/a | n/a | `../02-static-integration-audit/OMP_EVENT_MATRIX.md` | PASS | |
| 3 | metadata/package audit | n/a | yes | `../03-regression/TEST_DELTA.md`; extension `package.json` | PASS | |
| 4 | pre-live regressions | no | yes | `../03-regression/TEST_DELTA.md`; `20-final-regression/FINAL_REGRESSION.md` | PASS* | Known baseline failures remain; no candidate-only failure established |
| 5 | OMP native startup | yes | optional | `../05-deploy-exact-build/DEPLOY_VERIFICATION.md`; current `doctor` | PASS | |
| 6 | lifecycle telemetry/identity | yes | yes | `../02-static-integration-audit/OMP_EVENT_MATRIX.md`; telemetry corpus | PASS | |
| 7 | canonical project resolution | yes | yes | `../10-cross-project-isolation/CROSS_PROJECT_ISOLATION.md`; telemetry corpus | PASS | |
| 8 | AutoInject actual context injection | yes | yes | `../20260904T163000Z-0129e235/07-autoinject/GATE8-injection-proof.md` | PASS | Prior proof is behaviorally invariant on current candidate; current live rerun held by provider quota |
| 9 | AutoInject cache correctness | yes | yes | `../09-cache-correctness/CACHE_CORRECTNESS.md`; `../09a-autoinject-cache-corpus-generation-fix.md` | PASS | |
| 10 | cross-project isolation | yes | yes | `../10-cross-project-isolation/CROSS_PROJECT_ISOLATION.md` | PASS | |
| 11 | worker context capsule | yes | yes | `../11-worker-context-capsule/WORKER_CONTEXT_CAPSULE.md` | PASS | |
| 12 | worker result lifecycle | yes | yes | `../12-worker-result-lifecycle/WORKER_RESULT_LIFECYCLE.md` | PASS | |
| 13 | model routing | yes | yes | `../13-model-routing/MODEL_ROUTING.md` | PASS | |
| 14 | skill/visibility | yes | yes | `../14-skills-visibility/SKILLS_VISIBILITY.md` | PASS | |
| 15 | compaction continuity | yes | yes | `../15-compaction-continuity/COMPACTION_CONTINUITY.md` | PASS | |
| 16 | restart persistence | yes | yes | `../16-restart-persistence/RESTART_PERSISTENCE.md` | PASS | |
| 17 | runtime/state separation | yes | yes | `../17-runtime-state-separation/RUNTIME_STATE_SEPARATION.md` | PASS | |
| 18 | backup/restore | yes | yes | `../18-backup-restore/BACKUP_RESTORE.md`; `19-rollback/ROLLBACK_VERIFICATION.md` | PASS | |
| 19 | fail-open behavior | yes | yes | `../19-failure-injection/FAIL_OPEN_MATRIX.md` | PASS | |
| 20 | token efficiency | yes | yes | `../20-token-efficiency/TOKEN_EFFICIENCY.md` | PASS | |
| 21 | latency | yes | yes | `../21-latency-qualification/LATENCY_QUALIFICATION.md` | PASS | |
| 22 | sustained burn-in | yes | partial | `22-sustained-burn-in/SUSTAINED_BURN_IN.md` | HOLD | Worker, compaction, and project-switch count minima unmet; provider HTTP 429 |
| 23 | final clean-candidate regression | yes | yes | `20-final-regression/FINAL_REGRESSION.md` | HOLD | Critical live reruns unavailable under the provider throttle; local suite retains baseline failures |
| 24 | rollback from final candidate | yes | yes | `19-rollback/ROLLBACK_VERIFICATION.md` | PASS | |

\* Gate 4 is a baseline-delta result, not a claim that the repository's
pre-existing failures are resolved. Every mandatory row must be PASS before a
`v2.0.0` tag; therefore this candidate remains unreleasable.
