# Audited release readiness — HOLD

Branch: `brain/v2-omp-final-p1-repair`.

- Repair start: `f5089ac1b6e27f0b3329196cec7e74f402cd0636`.
- Final runtime candidate: `75b80d2aab33929923d4d9323bcaf639bc69591b`.
- Runtime implementation: `64694bb32f02cd6a736ec65a24660bd8acd6a3f6`; the following candidate commit changes only verification files.
- Qualified runtime source: **NONE**.
- Evidence HEAD: identified externally after the evidence commit; no self-referential SHA is embedded here.
- Artifact remains **2.0.0-rc.1**, schema 22. **No v2.0.0 tag or release is created.**

## Results

Final Python: **1823 passed**. Final extension: **684 passed**. TypeScript and changed-file ESLint pass. Installer: **18/18** scratch cases. Sealed doctor: **19 checks, zero failures/warnings**. Real local bridge plus independent SQLite read-back proves matching packet/result receipts for completed, failed and cancelled outcomes; that smoke is not natural worker qualification.

Task fields, dispatch identity, durable acknowledgement/recovery and stale current-context handling have offline regression proof. Canonical ancestry has ledger/CLI and direct mirror coverage; the native marker-to-index-to-ledger integration path remains unproven under Gate 23. Windows manifest-reader contention was additionally reproduced on baseline/candidate and repaired without suppressing permanent failure.

## Exact open blockers

| Class | Open gate / finding | Smallest next action |
|---|---|---|
| Product / P1 | Native async-result framing can lose an otherwise valid completion containing literal unescaped task-result text; structured jobs metadata lacks the terminal outcome/content needed to disambiguate it. | Obtain a pinned native host contract with structured terminal results or unambiguous escaped framing, then pass arbitrary-output and spoof-resistant delivery regressions. Do not substitute tight polling. |
| Performance / P1 qualification risk | Populated 165-ledger budget checks measured roughly 729–776 ms candidate medians versus about 201 ms baseline; current full scan remains expensive. | Controlled paired profiling under comparable load; review only a bounded existing-reader improvement if required. Preserve live WAL visibility, root scope, real caps and history. Re-measure before acceptance. |
| Mandatory automated gate | Pyright still reports 85 errors. Ruff has 434 unchanged diagnostics; every finding is classified, not waived by count. | Resolve the exact type-error worklist and retain focused regression proof. No blanket suppression or source-wide formatting. |
| Missing deployment evidence | Actual default installed extension differs in five files from the candidate. No new host loaded C1. | After correctness passes, install from the exact source, compare manifests, launch flag-free native OMP, verify roots and one binding. |
| Gate 22 missing repaired-path proof | **0/20** eligible meaningful natural successes; historical eight were six completed/two failed fixed-text diagnostics under another source/profile/loading epoch. | Complete the twenty remaining meaningful, independently accepted tasks, one worker by default and maximum two; capture authoritative receipts and genuine hub/redelivery overlap. Preserve failures and costs. |
| Gate 22 provenance reconciliation | Historical activity is retained, but source-linked restart, controlled-switch and canary-qualified totals are not fully reestablished. | Reconcile available raw sequences and timestamped manifests; fill only demonstrated gaps. Do not reset the campaign or count shutdowns/handoffs as successful restarts/launches. |
| Gate 23 missing integration proof | Final provider-visible injection/isolation, named-agent effective options, compaction, restart, routing, safe failure and default rollback/redeploy remain unrun. | Reuse the natural-worker sample for the exact matrix in `11-final-candidate-regression.md`. |
| Economics missing evidence | Historical W1 is one +0.42% token pair; W2/W6 are reported cost pairs with explicit profile caveats. Worker/continuation paired controls and C1 delta are missing. | Run the bounded comparable pairs specified in `12-economics-and-latency.md` once preceding gates pass; include main/children, failures, retries and verification without double counting. |

P0 open: **0 identified**. P1 open: **2 identified above**, plus unmet mandatory type/live/economics gates. P2: legacy `v2_policy.load_policy` does not accept newer canonical metadata; no current production caller was found. Removing a mutable-default test did not repair that compatibility issue.

## Provider and publication boundaries

No new live qualification arm or quota probe was started while local blockers remained. Current provider availability is **UNASSESSED**, not declared unavailable from an old HTTP 429. No new DeepSeek qualification, account change, `/agents` remapping, or advisor/prewalk change was made. Repair/review-agent work is not credited as candidate live qualification; its unavailable aggregate cost is not represented as zero.

The original repair/evidence head was published and remote-verified first. The final source/evidence commits are pushed on that same branch without force; exact evidence HEAD and fresh remote equality are supplied by the final external publication verification. Private original transcripts remain local; public reports contain bounded excerpts, identities and hashes.

`QUALIFICATION_INHERITANCE.md` supersedes conflicting historical readiness interpretations without rewriting their raw observations. This is **HOLD**, not a release approval and not a promise of unattended future execution.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
