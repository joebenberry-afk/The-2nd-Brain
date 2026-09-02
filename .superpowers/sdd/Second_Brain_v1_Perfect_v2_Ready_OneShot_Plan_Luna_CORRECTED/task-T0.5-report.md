# T0.5 Paired economics evidence report

## Scope

Implemented paired economics for the corrected v2 one-shot plan:

- Host-reported usage is the only source of run measurements.
- Missing usage and missing model prices remain unknown; dollar values remain `null`.
- OFF and ON runs use separate detached worktrees at the fixture commit.
- Synthetic values exist only in focused unit tests and are never written to the evidence output tree.

## RED/GREEN evidence

### RED

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py -q
```

Initial result: collection failed because `second_brain.economics` did not exist. This established the expected pre-implementation failure.

### GREEN

Command:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py tests/test_v2_policy.py -q
```

Result: `15 passed`.

The focused economics tests cover:

- CUPED on a correlated synthetic fixture and variance reduction.
- mSPRT abstention for fewer than three pairs.
- mSPRT detection of a known negative relative effect.
- Exact cache multipliers in cost computation.
- Null dollar semantics when model pricing is unavailable.
- Economics defaults loaded from v2 configuration.
- Governor delegation to `economics.verdict`.
- Fixture schema requirements.

A focused compatibility check also passed:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -k ROIClassification -q
```

Result: `5 passed`.

## Math checks

`src/second_brain/economics.py` implements:

- Cost: `base_in * (uncached_in + 0.10 * cache_read + 1.25 * cache_write) + base_out * output`; multipliers are configurable and defaults are exactly `1.0`, `0.10`, and `1.25`.
- Pair deltas as ON minus OFF.
- CUPED with OFF as the same-task covariate, population covariance/variance, and `d_adj = d - theta * (X - mean(X))`.
- Relative effects `d_adj / OFF`, with zero/unknown OFF excluded from valid evidence rather than fabricated.
- The specified mSPRT likelihood ratio, alpha threshold, and POSITIVE/NEGATIVE/INSUFFICIENT verdicts. Fewer than three valid pairs abstain. A zero-variance non-zero effect is treated as deterministic evidence (`lambda = infinity`) without changing the formula for non-degenerate data.
- Mean success, turns, and dollar deltas; dollar delta is null when dollars are not available.

`config/v2.toml` now carries `[economics]` defaults and a verified DeepSeek per-token price entry. `v2_policy` accepts optional economics/prices tables while retaining its existing required policy sections and strict validation for policy keys.

## Fixtures

Added exactly two real-repository task prompts to each of:

```text
proof/tasks/economics/MICRO.json
proof/tasks/economics/STANDARD.json
proof/tasks/economics/DEEP.json
proof/tasks/economics/DEBUG.json
proof/tasks/economics/RESEARCH.json
proof/tasks/economics/REVIEW.json
proof/tasks/economics/HANDOFF.json
```

Every task has `task_id`, a real Second Brain repository prompt, the frozen fixture commit `e64aac8e0432a87bd899f52efcbaf928960925e4`, and an existing repository acceptance command with `expect_exit: 0`. The runner validates this schema before execution.

## Runner behavior

Added `scripts/run_paired_economics.py`:

```text
PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --help
```

Result: help rendered with bounded choices `{prime,claude-code,hermes}`, `{OFF,ON}`, and a bounded `--pairs` argument.

For an available host, the runner executes each selected task OFF then ON, each in a fresh detached worktree at the fixture commit. It captures only normalized telemetry aggregates (`assistant_usage`/accepted model invocation usage sums, model turns, tool calls, telemetry-derived wall milliseconds), acceptance exit status, and run metadata. Raw artifacts use unique IDs of the form `<harness>-<task_id>-<profile>-<utc>` and are written only after a real host attempt returns, including a bounded timeout with `usage_capture: false`; they never contain fabricated usage.

The runner suppresses host stdout/stderr and never persists prompts, tool content, or model output. Timeouts are bounded (30 seconds per host invocation and 300 seconds for acceptance). No adaptive release decision is made from insufficient evidence.

Unavailable-host smoke command:

```text
PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --harness prime --profile OFF --pairs 1
```

Result:

```text
host_available=false, pairs_recorded=0, usage_capture=false,
verdict=INSUFFICIENT, n=0, r_bar=null, lambda=null,
turns_delta=null, dollars_delta=null, success_delta=null
```

No synthetic raw run was emitted. The qualification artifact was written at:

```text
outputs/reports/v2/v2-0/qualification.json
```

with `usage_capture: false`, `pairs_recorded: 0`, null deltas, and an `INSUFFICIENT` verdict for the unavailable Prime host.

## Real-host availability and evidence

- Prime: unavailable (`where prime` found no executable). Therefore no Prime pairs are claimed and no usage values are fabricated.
- Claude Code: executable is present (`C:\Users\assas\.local\bin\claude.exe`), but bounded real-host attempts produced three raw timeout records with `telemetry: null`, `usage_capture: false`, and `acceptance_pass: null`. No Claude pair is claimed from those attempts.
- Hermes: executable is present (`C:\Users\assas\AppData\Local\hermes\bin\hermes.cmd`), but no completed Hermes qualification run is claimed.
- `outputs/reports/v2/economics/raw/` contains no synthetic artifacts.

The plan's five-real-pairs-per-host DONE-WHEN is consequently not asserted: the required host evidence is unavailable/incomplete, and qualification remains observational with insufficient evidence.

## Files and focused commands

Changed/added:

- `src/second_brain/economics.py`
- `src/second_brain/governor.py`
- `src/second_brain/v2_policy.py`
- `config/v2.toml`
- `proof/tasks/economics/*.json` (seven fixtures)
- `scripts/run_paired_economics.py`
- `tests/test_economics.py`
- `outputs/reports/v2/v2-0/qualification.json`

Commands run:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py tests/test_v2_policy.py -q
# 15 passed

PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_governor.py -k ROIClassification -q
# 5 passed

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --help
# help rendered successfully

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --harness prime --profile OFF --pairs 1
# bounded unavailable-host result; no pairs/raw telemetry
```

Project-wide validation, formatter, and linter were intentionally skipped per T0.5 instructions.

## Concerns

The environment does not provide completed Prime or Claude Code five-pair telemetry, so the qualification verdict must remain `INSUFFICIENT`; this is an evidence limitation, not a positive/negative ROI claim. Dollar calculations require both complete host usage counters and a verified model price. The runner intentionally does not infer prices, usage, run IDs, or acceptance outcomes when hosts fail or time out.

## Review-fix evidence

The review identified evidence-integrity risks; these were corrected in the scoped fix:

- Qualification updates now preserve every existing top-level field, including metadata, gates, `source_identity`, `generation_basis`, and phase. Economics data is merged under `economics.<harness>` and an existing `results` list is updated only for that harness.
- OFF maps explicitly to the existing `A_BRAIN_OFF` profile and ON to `I_FULL_V1`. The requested profile label is retained in metadata; execution order is always OFF then ON.
- Every dollar is recomputed from complete host counters with `economics.cost_per_run` and configured `[prices.<model>]`; host `cost_total` is never authoritative. Missing counters or prices produce null dollars.
- Aggregation reads every JSONL file for an attempt and preserves each usage counter independently as null when absent/partial. Pair identity and non-token metrics are retained even when token evidence is unusable.
- Fixture loading enforces exactly seven class files, exactly two non-empty tasks per class, unique task IDs, 40-hex fixture commits, non-empty acceptance commands, and integer `expect_exit = 0` (booleans rejected).
- mSPRT's zero-variance branch now triggers only for exact zero variance; no tolerance-based verdict is added.

Additional focused tests:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py -q
# 16 passed

PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_v2_policy.py tests/test_governor.py -k 'ROIClassification' -q
# run after review fixes; no project-wide validation
```

Raw Claude timeout artifacts remain host-attempt records only: all have null telemetry and `usage_capture = false`; they contain no prompt or model output. No missing Prime/Claude pairs were fabricated.

Final review-fix command results:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py tests/test_v2_policy.py tests/test_governor.py -k 'ROIClassification or not test_nonexistent_marker' -q
# 58 passed

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --help
# help rendered successfully

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --harness prime --profile OFF --pairs 1
# host_available=false, usage_capture=false, pairs_recorded=0, verdict=INSUFFICIENT
```

## Review-fix round 2

Restored the exact pre-T0.5 `qualification.json` baseline (`base_commit`, all
gates, `source_identity`, `generation_basis`, and `phase`) and merged economics
under a dedicated `economics.<harness>` key. The runner now preserves all
unrelated qualification fields and always executes OFF then ON, regardless of
the requested profile label. OFF maps to `A_BRAIN_OFF`; ON maps to
`I_FULL_V1`.

All telemetry files from one attempt are aggregated. Missing or partial usage
counters, no-telemetry timeouts, model turns, tool calls, and wall evidence
remain null where unobserved. Mixed models refuse a single-price calculation
and record `dollars_reason: mixed_model`. Host `cost_total` is ignored in favor
of the exact configured economics formula.

Round-two focused proof:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py tests/test_v2_policy.py tests/test_governor.py -q
# 61 passed

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --help
# help rendered successfully

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --harness prime --profile ON --pairs 1
# host_available=false, usage_capture=false, pairs_recorded=0, verdict=INSUFFICIENT
```

The round-two tests include temporary-host end-to-end normalization and
privacy checks, OFF-before-ON assertions for both profile labels, committed
baseline preservation, multi-file summing, null/partial counters, exact
pricing, mixed-model refusal, strict seven-class fixture validation, and an
exact `lambda = infinity` known-effect assertion. No synthetic test data is
written to repository output evidence.

## Review-fix round 3

The final evidence-integrity fixes require each fixture's JSON `class` to
match its filename stem, rejecting renamed or duplicate class content. Each
normalized raw run now records `usage_capture`; it is true only when every
required host counter and model-turn count was observed. Summary capture is
true only when both arms of every recorded pair have complete capture.

Model identity is conservative: a usage event with a missing or non-string
model marks the attempt mixed/unknown, so dollars remain null even when
another event names a priced model. The Windows command override parser
preserves executable paths for bounded temporary-host integration.

Round-three focused proof:

```text
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py -q
# 22 passed

PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_economics.py tests/test_v2_policy.py tests/test_governor.py -q
# 64 passed

PYTHONPATH=src .venv/Scripts/python.exe scripts/run_paired_economics.py --help
# help rendered successfully
```

The public `run()` integration test uses a temporary host script and
temporary fixture/output paths. It exercises the real bounded subprocess,
OFF-then-ON arms, telemetry normalization, configured dollar pricing,
qualification merging, and prompt/tool-output exclusion without writing
synthetic data to repository outputs.
