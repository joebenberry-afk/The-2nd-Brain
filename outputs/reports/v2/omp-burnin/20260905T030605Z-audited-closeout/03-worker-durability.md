# Worker durability and recovery

## Reproduced defects

Initial source f5089ac consumed correlation before persistence and ignored a resolved `{ok:false}` acknowledgement. The Python receiver generated a new result timestamp/hash on each replay and acknowledged that newly generated hash even when the lifecycle transaction was already terminal. Malformed or unauthorized transport also changed a real WORKING task into FAILED.

Evidence: `artifacts/worker-paging-before.json`, `artifacts/receiver-before.txt`. Three receiver regressions fail against immutable initial source for changed replay hashes and manufactured failures.

## Authoritative transaction

Migration `0022_worker_result_receipts.sql` adds `worker_task_results` to the **existing Brain worker lifecycle database**, not a second result database. Canonical result payload/hash and terminal state commit in one SQLite transaction. Replayed terminal outcomes return the original stored result hash. Host-ledger mirroring is supplementary; its failure cannot destroy the durable receipt. Existing corrected-result ledger bindings remain supported.

The OMP adapter validates task/packet/parent ownership at its boundary. Generic worker-protocol callers retain the pre-existing driver-owned-ledger behavior when a child worker session submits a result. Invalid transport returns an error without manufacturing a worker outcome. Failed workers carry generic `OMP_WORKER_FAILED` provenance, not an invented provider diagnosis. Failed and cancelled outcomes remain those outcomes, never successful completions.

The TypeScript bridge requires terminal status and valid packet/result hashes for acceptance and binds the receipt to the requested task, packet, and status. Thus an accepted failed outcome is not confused with a transport failure.

## Recovery semantics and bounds

An in-flight claim serializes simultaneous hub and auto-delivery observations. The accepted set advances only after a positive persistence acknowledgement. Rejection/exception leaves the pending correlation available for redelivery. Original observation telemetry is not rewritten.

Existing native OMP custom journal entries retain pending jobs/results and accepted markers. On native resume or first observed result, the adapter reconstructs pending work and resubmits the original bounded summary/outcome. These journal entries are bookkeeping recovery input, not proof of Brain acceptance and not injected into model context. Recent seen sets are bounded to 1024 identities. New dispatch is rejected at the pending limit. A resume submits at most 128 pending results; overflow remains in the journal with a recovery-limit diagnostic. There is no retry loop or mandatory hub polling.

No exactly-once network claim is made. The durable terminal transition is idempotent. Host journaling relies on native session persistence/flush; an interrupted session before any durable host observation still requires real-host qualification.

## Executed proof

- Focused Python gate: **154 passed**, exit 0, across adapter, worker protocol/lifecycle, governor, ledger, installer, DB and migration suites (`artifacts/pytest-after.txt`).
- Fault injection: receipt insertion abort rolls back terminal state; retry succeeds. Host-ledger failure does not erase the receipt. Lost acknowledgement replay returns the original hash. Wrong parent is rejected. Migration reapplication and SQLite backup/reopen preserve the receipt.
- Actual runtime smoke, not a mocked test: Bun loads the candidate TypeScript bridge, invokes the real venv Python CLI against a scratch home, and persists **completed, failed, cancelled**. Every replay returns the same hash; every wrong-parent submission is rejected. `artifacts/receiver-real-bridge-smoke.txt`, exit 0.
- This scratch smoke contributes **zero** natural-worker qualification successes. It makes no provider request and does not bypass a populated-home budget gate.

Post-review proof: canonical payload/hash agreement and ownerless-task refusal
are now enforced before transition. Concurrent dispatch reservations, journal
write failure and bounded recovered correlation are covered by the final
**684/684** extension run (`artifacts/vitest-final-source.json`). The repeated
real bridge smoke uses fresh task IDs and again accepts/replays all three
terminal outcomes with matching hashes (`artifacts/receiver-final-real-smoke.txt`,
exit 0). A preliminary rerun reused already-terminal scratch IDs and correctly
returned `completed` rather than `prepared`; it was a smoke setup failure, not
a receiver regression.

## Compatibility and rollback

The migration is additive. Existing task tables, packets, events and historical telemetry are retained. Rollback does not drop the receipt table or rewrite outcomes. Historical terminal tasks without this new durable receipt are not retroactively credited: the OMP receiver returns RESULT_NOT_RECORDED rather than inventing a receipt. Final deployed/native restart and rollback proof remain separate gates.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
