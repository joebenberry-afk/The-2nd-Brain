# Stage D / B6 — Governor Scope Reproduction

## Scope and execution status

This audit read the historical ledger and telemetry corpus in place and changed only `src/second_brain/governor.py` plus `tests/test_governor.py`. SQLite inspection used `mode=ro`; historical ledgers, telemetry, configuration, deployment, and provider state were not modified.

Per the closeout concurrency contract, **no test, lint, formatter, build, provider call, or live smoke was run in this worker**. The commands below are for Main after convergence. No PASS/FAIL result is claimed here.

## Source trace

- Budget contract and caps: `config/governor.toml:34-40` (`session_tokens=400000`, `worker_tokens=120000`, `soft_ratio=0.8`).
- Governor ownership: `src/second_brain/governor.py:718-730,771-922`.
- Ledger identity schema/writer: `src/second_brain/ledger.py:93-106,390-410`.
- Default OMP ledger init omits ancestry: `brainstem/prime-extension/src/ledger-mirror.ts:140-160,199-222`; the receiving CLI creates `BrainSessionIdentity` without `root_parent_session_id` at `src/second_brain/cli.py:3488-3503`.
- AutoInject role default: `brainstem/prime-extension/src/autoinject.ts:447-449` defaults an omitted `roleProfile` to `worker`.
- OMP integration currently omits that field in `autoinjectCall`: `brainstem/prime-extension/src/index.ts:1374-1387`, although the later budget call uses the resolved role at `index.ts:1695-1707`.
- Hard tool guard is driven by the cached session state at `brainstem/prime-extension/src/index.ts:2340-2346` (line numbers may move as Main's concurrent integration lands).

## Historical contribution audit

Read-only corpus facts at audit time:

- 164 `state/sessions/*/ledger.sqlite` files were readable.
- They contained 164 session rows, 164 distinct `internal_session_id` values, and 164 distinct `host_session_id` values.
- **All 164 rows had `root_parent_session_id = NULL`.** There was therefore no historical descendant row capable of contributing to either questioned decision.
- The eight workers named in `final-p1-repair/10-live-8worker-autodelivery-proof.md` also had `root_parent_session_id = NULL`.

### Query and decision identity

| Reported used | Query host session | Internal/root identity computed by governor | Telemetry role | Requested cap(s) seen in durable budget decisions | Expected used under stored identities | Actual used |
|---:|---|---|---|---|---:|---:|
| 510,751 | `2026-09-05T01-52-15-071Z_01a06f44-30df-76b9-8b43-5f783f6ebe2c` | `a648d2e843d12bdaddd0cdddbf48cb0fc2a98b3352fd0843f9d30140d2ddeb65` | `driver` in all 17 `before_agent_start` records | 120,000 for the manual worker-role check; 400,000 for the driver check | 510,751 own + 0 descendants | 510,751 |
| 755,888 | `2026-09-05T02-26-23-339Z_01a06f63-71eb-7582-ae62-29547cdd692a` | `1697665ac017b2e964b7e9e167757b2f6093039408adbdf3762e09a8da5f1d4e` | `driver` in all 17 `before_agent_start` records | 120,000 for the later manual worker-role check; normal driver cap is 400,000 | 755,888 own + 0 descendants | 755,888 |

### Contributing records

| Decision | Contributing telemetry identity | Input | Output | Cache read | Cache write | Total | Inclusion reason | Duplicate or unrelated-root disposition |
|---|---|---:|---:|---:|---:|---:|---|---|
| 510,751 | same host session as query | 12,460 | 17,139 | 481,152 | 0 | 510,751 | Own session is always included | One telemetry identity; no descendant row matched query root |
| 755,888 | same host session as query | 20,372 | 25,244 | 710,272 | 0 | 755,888 | Own session is always included | One telemetry identity; no descendant row matched query root |

The queried ledger rows themselves have `host='prime'`, project `54dd51f5ee7906d4`, and `root_parent_session_id=NULL`. The 510,751 session had 20 usage rows; the 755,888 session had 21. They were active, cache-heavy driver sessions, not unused identities.

The reported delta is 245,137. The eight worker telemetry totals preserved for the successful auto-delivery batch are 39,194; 39,815; 39,274; 39,729; 39,761; 39,771; 39,657; and 40,844, totaling **318,045**, not 245,137. None was included by `_descendant_total_tokens` because every worker ledger root was NULL.

## Verdict on the original finding

`P2-GOVERNOR-BUDGET-LEDGER-OVERSCOPE`: **NOT_REPRODUCED; the historical contribution evidence disproves the proposed cross-root cause.**

The two questioned values came entirely from each queried session's own `assistant_usage.total_tokens`. The 510,751 and 755,888 checks were legitimate HARD results against the configured 400,000 driver cap when the correct role is used. Passing `--role worker` manually selects the intentional 120,000 worker cap; it does not make a previously used driver session a new worker root.

The prior report's statement that a “brand-new, never previously used” session was charged unrelated worker history is inconsistent with the preserved telemetry and durable decision rows. The global ledger scan alone was not evidence of overscope because the implementation filters exact `root_parent_session_id` before adding usage.

## Actual findings and disposition

| Finding | Disposition | Severity / release effect |
|---|---|---|
| Exact root filtering charges unrelated A/B/C roots | **NOT REPRODUCED.** Existing exact root comparison is retained. | Close the original overscope allegation; it is not a P1 on this evidence. |
| Same descendant identity duplicated across valid ledger files is counted twice | **REPRODUCED by deterministic fixture from the permitted per-file schema; FIXED in governor.** Contributions are keyed by internal and host identity and summed once; conflicting identities degrade instead of being guessed. | B6 correctness defect; minimal owning-layer repair ready for validation. |
| Python-sanitized telemetry stem can hide the raw OMP telemetry file | **REPRODUCED against historical files.** `UnitedPuma.ColouredHawk.jsonl:15` contains 28,418 usage tokens, while `UnitedPuma-ColouredHawk.jsonl:1-2` is a no-usage sidecar. The old governor opened only the latter. **FIXED** by bounded raw/sanitized candidate reads with record identity checks. | Supported-path undercount/budget-bypass risk; owning-layer repair ready for validation. |
| Missing or malformed accounting is returned as factual `used=0` | **REPRODUCED from source behavior; FIXED.** Governor remains fail-open (`state=OK`) but returns `used=null` and `error=ACCOUNTING_UNAVAILABLE`. | Required honesty/safety behavior; bridge propagation remains open below. |
| Legitimate SOFT/HARD caps and boundary comparisons | **ALREADY CORRECT; preserved.** Existing boundary tests remain at `tests/test_governor.py:898-928`; the new nested worker fixture also pins the worker HARD boundary. | No cap inflation or governor disablement. |
| Default OMP ancestry reachability | **REPRODUCED integration defect.** All 164 real rows, including the eight named workers, have NULL roots because mirror/CLI init has no ancestry input. Parent checks therefore undercount real descendants rather than overcount unrelated roots. | **P1 release blocker for B6 until Main wires authoritative root identity and proves it.** Governor must not infer ancestry from project or global history. |
| AutoInject role consistency | **REPRODUCED integration defect.** `autoinjectCall` omits `roleProfile`, so Python defaults driver sessions to the worker cap for the pre-retrieval SOFT decision, while the later budget bridge correctly passes the resolved driver role. | **P1 release blocker for B6 until Main passes one resolved role consistently.** This can cause a false SOFT/no-injection decision; it does not explain the historical 510,751/755,888 totals. |
| Recovery from a stale cached HARD | Governor has no cache. The cache is the `index.ts` `sessionBudgetStates` map. | Main-owned regression required: a later complete OK result and a degraded fail-open result must replace stale HARD; no global/session-root leakage. |

Until the three Main-owned integration items above are repaired and validated, the honest B6 gate is **HOLD**, but not for cross-root ledger overscope.

## Regression fixture coverage authored

`tests/test_governor.py:1058-1180` now defines deterministic offline cases for:

- independent roots A and B in one project and root C in another;
- A's direct child and nested child, with exact root contribution and the nested worker's own HARD cap;
- a duplicate nested-child ledger row copied into a second valid ledger file;
- repeated/resumed A evaluation retaining the same accounting result;
- an unrelated high-usage historical root in the same home;
- raw-versus-sanitized telemetry identity;
- missing telemetry, malformed telemetry, and an unreadable ledger;
- explicit fail-open degradation with `used is None`, never a claimed zero;
- existing exact SOFT/HARD cap boundaries and unrelated-root exclusion.

The fixture expects A usage `10 + 15 + 40 = 65` exactly once, B usage `5`, C usage `90`, and nested worker usage `40` at its hard cap. The historical root has usage `500` but contributes to none of A/B/C.

## Main-owned integration changes required

1. **Role:** resolve the role before constructing the AutoInject call and pass it as `roleProfile`; use the same role for AutoInject, budget bridge, routing, and telemetry. Do not change provider mappings.
2. **Root identity:** extend the existing OMP ledger-init path to carry an authoritative root parent identity from the worker dispatch/correlation metadata into `BrainSessionIdentity.root_parent_session_id`. Preserve the root across nested children and resume. Do not infer parentage from project, model, task text, or filesystem proximity.
3. **Degradation propagation:** update `BudgetCheckResult.used` to allow `null`; preserve Python's `error` field in `budget-bridge.ts`. Do not coerce degraded `null` to zero. The fail-open state remains `OK`.
4. **Cache recovery:** in `wiring.test.ts`, preseed HARD, return complete OK and degraded OK on later checks, and prove both replace the stale HARD for the same session while unrelated roots remain isolated.

## Exact commands for Main

Run after all concurrent edits converge. These commands deliberately isolate the pre-fix source at `f5089ac1b6e27f0b3329196cec7e74f402cd0636` without changing the candidate branch.

### Pre-fix regression proof

```powershell
$Repo = 'C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot'
$Scratch = Join-Path $env:TEMP ('second-brain-governor-f5089ac-' + [guid]::NewGuid())
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
git -C $Repo worktree add --detach $Scratch f5089ac1b6e27f0b3329196cec7e74f402cd0636
Copy-Item (Join-Path $Repo 'tests\test_governor.py') (Join-Path $Scratch 'tests\test_governor.py') -Force
$env:PYTHONHOME = $null
$env:PYTHONPATH = (Join-Path $Scratch 'src')
Push-Location $Scratch
& $Python -m pytest tests/test_governor.py -q
$PreFixExit = $LASTEXITCODE
Pop-Location
$env:PYTHONPATH = $null
git -C $Repo worktree remove $Scratch
Write-Output "pre-fix pytest exit=$PreFixExit"
```

The new assertions are designed to expose the old duplicate charge, dotted-identity zero, and silent degraded zeros. Record the actual failing IDs/output; do not substitute this design expectation for execution evidence.

### Post-fix focused proof

```powershell
$Repo = 'C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot'
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
Push-Location $Repo
& '.\.venv\Scripts\python.exe' -m pytest tests/test_governor.py -q
$PostFixExit = $LASTEXITCODE
Pop-Location
Write-Output "post-fix pytest exit=$PostFixExit"
```

Main should then run its owned `budget-bridge.ts`/`wiring.test.ts` focused command and the single converged project gate, recording results separately.

## Remaining unknowns

- Which authoritative OMP 18.1.10 event/metadata field should populate a worker session's root identity on first ledger init. This must be established in Main's worker-correlation integration; governor cannot safely reconstruct it.
- Whether Main's concurrent `index.ts` work changes the exact line locations or cache semantics described above.
- Focused pre-fix/post-fix outcomes, local timing on the realistic fixture, and paired live old-root/new-root behavior remain unmeasured because execution was explicitly deferred to Main.
- Provider/live campaign behavior remains untested here; no provider call was made.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
