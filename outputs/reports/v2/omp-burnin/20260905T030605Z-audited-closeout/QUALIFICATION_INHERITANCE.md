# Qualification inheritance — authoritative audited closeout

Decision: **HOLD**. Historical observations remain evidence; neither an old PASS label nor a large counter qualifies the repaired runtime.

## Epochs and provenance

- **H1:** `86585e114115bc43bf932145e716f2ed4d3dd30e`, OMP 18.1.10, RC/schema 21. The historical `20260904T202807Z-omp-hold/OMP_V2_QUALIFICATION_MATRIX.md` is the source of the gate names and original decisions below. Its Gate 8 expressly inherits an earlier `20260904T163000Z-0129e235` proof.
- **H2:** deployment-alignment decision `ad1384bf30088c5aa9bb9dec0bb5009c9a63c5d0`; reported adapter fingerprint `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68`. The source report says this interval changed deployment/evidence only. It used the corrected native extension root, but worker collection used tight hub polling and compaction used a temporary threshold override.
- **H3:** worker repair `a9ff745fe30f681862d15ed2ed026881bbbf4cb0`, installer repair `2d3901636e09ef57059e41bc46e162c93899428a`, evidence head `f5089ac1b6e27f0b3329196cec7e74f402cd0636`. The eight-worker run used profile `p1-live-proof2`, explicit `-e`, and DeepSeek. It is not flag-free default-loading proof.
- **C1:** this audited candidate, still `2.0.0-rc.1`, schema 22. Source/config/lock manifests are recorded in `08-candidate-identity-and-deployment.md`. No provider accounts, `/agents` mapping, advisor/prewalk settings, or canonical profile configuration were changed. This candidate has not completed a frozen live qualification epoch.

Old full effective-profile hashes are not reconstructed from prose. Reported overrides above and the economics visibility override below remain explicit. Where exact historical deployment/config linkage is unavailable, it is **UNAVAILABLE**, not silently equated with C1. `artifacts/inheritance-sources.json` hashes the cited public reports. Native transcript and telemetry hashes are in `artifacts/coverage-raw-inventory.json`; those private originals are local-only, not GitHub-downloadable artifacts.

`INHERIT` below preserves an unchanged historical capability's evidence. It does **not** waive the candidate-specific Gate 23 integration check. `TARGETED_RETEST` retains history while reopening only the affected behavior. All paths below are relative to `outputs/reports/v2/omp-burnin/`.

| Gate | Capability | Historical source/evidence | Disposition | Changed component and exact remaining proof |
|---:|---|---|---|---|
| 0 | Baseline/rollback protected | H1: `20260904T202807Z-omp-hold/19-rollback/ROLLBACK_VERIFICATION.md` | INHERIT | Protected historical baseline retained; new pre-schema-22 backup recorded. Candidate deployment rollback remains Gate 24. |
| 1 | Exact OMP runtime/build identity | H1: `20260904T202807Z-omp-hold/20-final-regression/FINAL_REGRESSION.md` | TARGETED_RETEST | Python and extension changed. Need fresh native host, source/install equality, runtime and state roots, one binding. |
| 2 | Lifecycle integration map | H1: `02-static-integration-audit/OMP_EVENT_MATRIX.md` | TARGETED_RETEST | Updated observer/journal/ancestry paths are mapped in current worker reports; native ambiguous framing remains open. |
| 3 | Metadata/package audit | H1: `03-regression/TEST_DELTA.md` | INHERIT | RC version retained; no dependency change. New source/config/lock hashes identify C1 independently. |
| 4 | Pre-live regressions | H1/H3: `03-regression/TEST_DELTA.md`; `20260904T202807Z-omp-hold/final-p1-repair/05-verification-results.md` | TARGETED_RETEST | Current full/focused suites and exact baseline deltas are in `07-regression-delta.md`; old failure counts are not waivers. |
| 5 | Native startup | H1/H3: `05-deploy-exact-build/DEPLOY_VERIFICATION.md`; `20260904T202807Z-omp-hold/final-p1-repair/08-deploy-verification.md` | TARGETED_RETEST | Installer changed. Scratch default-path tests pass; final no-override deployment and new process remain unrun. |
| 6 | Lifecycle telemetry/identity | H1: `02-static-integration-audit/OMP_EVENT_MATRIX.md`; local telemetry | TARGETED_RETEST | Worker observation/acknowledgement and ancestry changed. Current live candidate records required; fixture records are excluded. |
| 7 | Canonical project resolution | H1: `10-cross-project-isolation/CROSS_PROJECT_ISOLATION.md` | INHERIT | Resolution source unchanged. Preserve old controlled-project proof; final worker boundary/isolation smoke still required. |
| 8 | AutoInject model-visible input | Earlier proof: `20260904T163000Z-0129e235/07-autoinject/GATE8-injection-proof.md` | TARGETED_RETEST | Role passed consistently before AutoInject now; actual provider-visible positive/negative sentinel proof required, not telemetry alone. |
| 9 | AutoInject cache correctness | H1: `09-cache-correctness/CACHE_CORRECTNESS.md`; `09a-autoinject-cache-corpus-generation-fix.md` | INHERIT | Cache implementation unchanged. Final integration continuation still required. |
| 10 | Cross-project isolation | H1/H2: `10-cross-project-isolation/CROSS_PROJECT_ISOLATION.md`; H2 controlled-project reports | INHERIT | Retrieval predicates unchanged; corrected fixtures preserve shared domain knowledge and explicitly reject foreign/default project memories. Final controlled sequence remains required. |
| 11 | Worker context capsule | H1: `11-worker-context-capsule/WORKER_CONTEXT_CAPSULE.md` | TARGETED_RETEST | Task options, dispatch IDs and parent linkage changed. Offline coverage passes; effective native agent/model/schema/isolation must be observed. |
| 12 | Worker result lifecycle | H1/H3: `12-worker-result-lifecycle/WORKER_RESULT_LIFECYCLE.md`; H3 eight-worker report | TARGETED_RETEST | New receipt transaction, ownership, bounded correlation, status handling and journal recovery require natural requalification. Ambiguous native framing blocks closure. |
| 13 | Model routing | H1: `13-model-routing/MODEL_ROUTING.md` | INHERIT | Mapping/accounts unchanged. Final requested/selected/effective chain must still be captured. |
| 14 | Skills/visibility | H1: `14-skills-visibility/SKILLS_VISIBILITY.md` | INHERIT | No skill/visibility policy change. Historical enforced-mode benefits are not default-profile benefits. |
| 15 | Compaction continuity | H1/H2: `15-compaction-continuity/COMPACTION_CONTINUITY.md`; H2 recalculation | TARGETED_RETEST | Paging and pending-worker recovery changed. Need native compaction with current requirements/canary and continuation, without unsafe preservation bypass. |
| 16 | Restart persistence | H1: `16-restart-persistence/RESTART_PERSISTENCE.md` | TARGETED_RETEST | Durable receipt and journal recovery changed. Need clean shutdown/resume plus authoritative read-back; shutdown count alone is insufficient. |
| 17 | Runtime/state separation | H1: `17-runtime-state-separation/RUNTIME_STATE_SEPARATION.md` | INHERIT | Separation design retained; installer source independence passes scratch tests. Reconfirm roots in final host. |
| 18 | Backup/restore | H1: `18-backup-restore/BACKUP_RESTORE.md` | TARGETED_RETEST | Additive schema 22. Fresh/reopen/idempotency/backup tests and real pre-migration backup pass; final canonical recovery evidence remains linked to C1. |
| 19 | Failure containment | H1: `19-failure-injection/FAIL_OPEN_MATRIX.md` | TARGETED_RETEST | Degraded accounting is unknown, not zero; rejected bridge and journal failures remain recoverable. Final safe auxiliary failure and compaction preservation check required. |
| 20 | Whole-workflow token efficiency | H1: `20-token-efficiency/TOKEN_EFFICIENCY.md` | TARGETED_RETEST | Retain W1 measured token pair and W2/W6 cost pairs with their actual metrics/profile. No worker/continuation paired control existed; C1 delta and missing classes remain unrun. |
| 21 | Latency | H1: `21-latency-qualification/LATENCY_QUALIFICATION.md` | TARGETED_RETEST | New durability and read-only governor work measured locally; populated-home regression remains a qualification risk. No new index/service added to evade scope constraints. |
| 22 | Sustained burn-in | H1/H2/H3 decisions and raw inventory below | TARGETED_RETEST | Keep applicable general activity. Repaired-path natural successes are 0/20; restart/switch/canary counts need sequence/provenance reconciliation, not a campaign reset. |
| 23 | Final clean-candidate regression | H1: `20260904T202807Z-omp-hold/20-final-regression/FINAL_REGRESSION.md` | TARGETED_RETEST | Candidate-specific live matrix is NOT RUN. Earlier PASS rows cannot close this gate. |
| 24 | Rollback from final candidate | H1/H3 rollback reports | TARGETED_RETEST | Scratch failure/restore tests pass. Default deployed candidate restore/redeploy and byte comparison remain unrun. |

## Gate 22 contradiction resolved

H2 `deployment-alignment/10-phase22-final-recalculation.md` reported 146 sessions, 366 turns, 321 tool calls, 58 handoffs, 26 terminal observations/23 completed, 12 compaction pairs, 149 shutdowns and 24 globally adjacent project transitions. It called the auto-delivery defect non-blocking despite explicitly using a tight-polling workaround.

H2 `11-final-release-decision.md` **supersedes that non-blocking conclusion**: ordinary auto-delivery silently lost results, therefore P1 open and release HOLD even if historical numeric coverage was met. H3 `final-p1-repair/17-release-gate-checklist.md` retained Gate 22/23 HOLD. Its stale count-shortfall language does not erase H2's later activity, and its worker PASS does not establish C1 durability or meaningful task acceptance.

The audited interpretation is:

1. Historical activity is preserved, not reset.
2. Handoffs are not host launches; shutdowns are not verified clean restarts; globally interleaved project IDs are not controlled switches.
3. `recalculate_coverage.py` currently links 95 native session identities to available telemetry, with 295 deduplicated turn events, 212 tool-call identities, 56 prepared handoffs, 25 completed/2 failed Brain observations, and four ordered compaction pairs. These are **observed inventory**, not source-qualified release totals. Unmatched/ambiguous identities remain available for provenance reconciliation, not rejected as fake.
4. The H3 eight comprise six completed observations with legacy result receipts and two FAILED states without matching result receipts. They used fixed-text diagnostic tasks and a different source/loading epoch. Credit to C1's natural successful sample: **0**; remaining target: **20**.
5. Full restart, controlled-switch and canary-qualified totals are **UNAVAILABLE in this recalculation**, not zero. Preserve the old reports/raw artifacts and finish only the missing linked proofs.

This matrix supersedes earlier release-readiness interpretations, not raw history. Gate 22 and Gate 23 remain **HOLD**.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
