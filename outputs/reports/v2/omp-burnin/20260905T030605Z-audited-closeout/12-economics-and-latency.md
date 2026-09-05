# Economics and latency — HOLD

Sign convention: `(Brain-on − control) / control`; positive means more measured usage/cost. Direct cost and token counts are different metrics. No post-repair savings claim is made.

## Historical paired evidence retained

Source: `../20-token-efficiency/TOKEN_EFFICIENCY.md`, H1-era OMP transcript `message.usage` / `message.usage.cost.total`; report hash in `artifacts/inheritance-sources.json`. Control disabled extensions. This is historical evidence, not a C1 measurement.

| Workload | Control | Brain-on | Actual measured result | Applicability |
|---|---:|---:|---|---|
| W1 simple/no reuse | 33,082 total tokens | 33,221 total tokens | +0.42% token overhead | One pair; preserves a historical bounded observation, not a population guarantee. Wall times 3.99 s versus 10.53 s. |
| W2 skill reuse | $0.09464; six turns | $0.04483; one turn | −52.6% reported cost | Brain-on used **enforced** skill visibility. Shipped shadow-mode comparison showed no measurable benefit. Not default-profile token savings. |
| W6 project switch | $0.07741; five turns | $0.05671; three turns | −26.7% reported cost | Historical controlled-project outcome; token-category equivalence is not established by the cost table. |
| W3 compaction / W4 workers / W5 continuation | No strict paired control | Mechanism evidence only | UNPROVEN paired economics | Bounded packets and successful retrieval do not establish whole-workflow savings. |

The old report's final paragraph conflates W2/W6 cost reductions with total-token reductions. This closeout does not inherit that inference. The ≤5% whole-workflow token target is met only by the reported W1 pair, not by every representative class or the repaired worker workflow.

## Required C1 paired delta

No live qualification arm was started. After correctness and clean native deployment are established, retain applicable historical pairs and run the missing bounded controls: comparable authorized provider/model/reasoning settings, independently accepted outputs, and three matched pairs per inadequately covered class (simple/no-reuse, reuse/continuation, representative workers). Do not add arbitrary larger samples or new providers.

Input, output, reported reasoning, cache reads/writes, main/children, natural retries/failures, verification and abandoned work must be reconciled without double counting. Capsule/injected tokens are attribution within input, not an extra charge. Current campaign-wide repair/review-agent token categories and direct costs are **UNAVAILABLE**, not zero; subscription usage is not assumed to be dollar-billed. No reliable p95 is claimed from these small samples.

## Local latency and investigation

The governor's 165-ledger populated home reports the legitimate result `HARD`, `used=579890`, `cap=400000`. This is not evidence of unrelated-root overcounting. Initial historical 510751/755888 diagnoses are separately resolved in `04-governor-scope-reproduction.md`.

Measured candidate medians were approximately **729–776 ms**, versus the roughly **201 ms** starting-source measurement; the small fixture median was approximately **0.66 ms**. Raw eight-sample runs: `artifacts/governor-final-latency.json` and `artifacts/governor-canonical-uri-latency.json`; earlier run artifacts are retained. These are local scans, not provider or whole-workflow latency measurements, and background filesystem load makes them unsuitable as a calibrated latency percentile.

`artifacts/governor-final-cost-profile.txt` attributes a 1.400 s instrumented check chiefly to 165 SQLite `execute` calls (0.936 s), connection creation (0.254 s cumulative), and filesystem metadata checks (0.139 s). The return value remained correct. A separate warm connection-mode probe reached roughly 149 ms, showing substantial filesystem/cache sensitivity; it does not erase the repeated end-to-end regression.

**P1 OPEN qualification risk:** ordinary pre-agent budget checks scan the populated ledger set. Investigation supports an I/O cost, not a safe one-line correctness-preserving optimization. No new service/database/index, immutable-SQLite shortcut that ignores live WAL, inflated cap, empty qualification home, or discarded history was introduced. The smallest next action is controlled paired end-to-end profiling after resolving native framing, followed by a separately reviewed bounded-reader improvement only if required. Re-measure the final path before acceptance.

The real bridge smoke additionally exercises local IPC plus durable storage for completed/failed/cancelled results (`artifacts/receiver-final-real-smoke.txt` and its execution sidecar); it has no provider component and is not a token-efficiency sample.

**Gate 20 / Gate 21: HOLD.** Removing polling is not booked as savings without a comparable complete workflow measurement.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
