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
