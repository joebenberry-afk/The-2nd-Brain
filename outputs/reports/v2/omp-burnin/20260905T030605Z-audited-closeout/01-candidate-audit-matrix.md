# Frozen candidate audit acceptance matrix

Starting candidate: f5089ac1b6e27f0b3329196cec7e74f402cd0636. Audit basis: supplied published-source findings against 0b2aaf9; tested against actual repaired source. Status is not release approval.

| Check | Starting disposition | Evidence / remaining proof |
|---|---|---|
| B1 native observer | ALREADY_FIXED for basic auto-delivery; REPRODUCED invalid-status settlement | Prior 12-test report; new isolated starting-source regression rejects pending status (currently fails). Spoofing and full delivery matrix required. |
| B2 installer defaults | ALREADY_FIXED defaults; REPRODUCED backup safety and manifest defects | Published 2d39016; artifacts/installer-before.json directly reproduces missing/wrong backup acceptance and unrelated-latest selection. 5 passed / 13 failed; setup-blocked rows are not independent reproductions. |
| B3 task-item fields | REPRODUCED | artifacts/worker-paging-before.json: named agent/options absent from transformed batch. |
| B4 dispatch identity | REPRODUCED | artifacts/dispatch-identity-before.json: two batch items with identical text collapse to one identity. New host call ID plus item position separates dispatch from replay. |
| B5 durable acknowledgement | REPRODUCED at observer and authoritative receiver | artifacts/worker-paging-before.json; artifacts/receiver-before.txt shows retry returns a different result hash, and malformed/unauthorized transport changes WORKING to FAILED. Additive atomic receipt migration and recovery are under validation. |
| B6 governor | NOT_REPRODUCED historical cross-root claim; REPRODUCED duplicate, dotted-ID, degraded-accounting defects | 04-governor-scope-reproduction.md traces 510751/755888 entirely to own usage, descendants zero. artifacts/governor-before.txt reproduces real defects; one malformed fixture initially failed setup and was corrected before its final reproduction. Root propagation and role consistency require integration proof. |
| B7 paging | REPRODUCED | Same artifact: no-breakpoint returns previous array, omits appended current user/tool exchange. |

No provider qualification calls made. Four new hook regressions executed against isolated immutable starting source, all failed for targeted assertions. Shared working source not validated while independent edits were active.

These seven dispositions are frozen independently of final acceptance.
Source fixes, focused tests, real host behavior, inheritance, natural successful
outcomes, and remote publication remain separate mandatory gates.

## Post-repair discoveries and final disposition

The starting dispositions above are retained. Current offline evidence closes
B3/B4/B5/B7 and the reproduced B6 counting defects; B2 scratch install/rollback
passes. B1's ordinary terminal statuses pass, but full native acceptance is
still blocked by the first row below. Default deployment/live integration are
not inferred from tests.

| New finding | Severity / disposition | Reproduction and owner |
|---|---|---|
| Native result framing is ambiguous for literal unescaped worker output | P1 OPEN | Final wiring regression leaves an unmatched literal `<task-result>` output pending, then settles via explicit hub recovery. Native `details.jobs` lacks structured terminal outcome/content. Pinned OMP renderer/host contract must provide unambiguous framing or structured results; no tight-polling workaround accepted. |
| Populated-home governor latency | P1 OPEN qualification risk | 165-ledger measurements rose from roughly 201 ms baseline to 729–776 ms candidate medians. Cost profile attributes the delay chiefly to SQLite reads/connections. Correct counts and legitimate HARD caps are preserved. See `12-economics-and-latency.md`; do not add an unreviewed cache/index or ignore live WAL state. |
| Canonical receipt hash/payload and ownerless task binding | P1 FIXED offline | Canonical result validation and OMP parent ownership precede transition. Forged payload rollback and ownerless-task rejection are explicit Python regressions. |
| Concurrent admission, recovered-state bounds, supplementary journal failure | P1 FIXED offline | Reserve before awaiting; cap recovered correlation; journal failure cannot prevent the authoritative runner. Final 684-test extension suite passes the added boundary/recovery scenarios. |

The final authority is `14-release-readiness.md`, not a historical PASS label.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
