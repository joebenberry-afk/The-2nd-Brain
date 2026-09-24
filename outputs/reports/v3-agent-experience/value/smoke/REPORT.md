# V3 agent-experience value suite

- command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value/smoke --reps 1 --tasks VG-M05,VG-N02 --arms native,candidate --seed 20260924 --keep-work --work-dir C:/tmp/vvalue/valuesmoke3`
- full campaign command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value --reps 3 --arms native,candidate --seed 20260924 --model deepseek/deepseek-flash --thinking low`
- model: `deepseek/deepseek-flash` (thinking `low`)
- arms: native, candidate; reps: 1
- tasks: 2 (1 memory, 1 no_benefit)
- omp: omp/18.3.0
- verdict: **PASS**

## Method and caveats

- cwd per run: a fresh copy of `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v3-s1` minus .venv, .git, .worktrees, node_modules, __pycache__, .hypothesis, .pytest_cache, .ruff_cache, db, state, telemetry, memory, outputs/reports/v3-s2, outputs/reports/v3-agent-experience, outputs/reports/v3-agent-experience/value/smoke, outputs/reports/v3-agent-experience/value/smoke/raw. The Brain's own store (`memory/`, `db/`, `state/`, `telemetry/`) is excluded so a run cannot read answers out of the database it is measured against, and the frozen held-out set is excluded by contract. `outputs/reports` otherwise stays in the copy as legitimate hunting ground.
- home per run: a fresh copy of the corpus snapshot with the candidate's shipped config applied over it (files listed in `manifest.json/arms/candidate`).
- unknown usage stays null: a field some side never reported is never presented as a partial sum. Metrics compare `input+output` tokens (cache reads billed separately are recorded in `provider_usage.tokens_all`) and total tool calls.
- failures (timeouts, non-zero exits, harness errors) are retained as rows with `correct=false`; run status counts: {'ok': 4}.
- retrieval coverage before any model call (`probe.json`, decision path only): 1/1 memory tasks inject, 1 carry the expected memory id in the packet, 0 no-benefit tasks delivered anything.
- answer anchors (`anchors.json`): 1/1 memory tasks are answerable from the repository copy by hunting (native can succeed) and 1/1 are covered by the memory store; anchor defects: none.

## Pass rule

Memory tasks pass when the candidate shows a net reduction over native in either total provider tokens (input+output) or total tool calls - paired per task, median of the candidate-minus-native deltas < 0 - with candidate correctness not below native. No-benefit tasks pass when the paired median delta for BOTH tokens and tool calls is <= 0 plus the configured slack, with candidate correctness not below native. The campaign passes only when both classes pass.

## Class results (paired per task, candidate - native)

| class | metric | native median | candidate median | median delta | bootstrap 95% CI | tasks paired |
|---|---|---|---|---|---|---|
| memory | tokens_in_out | 12256.0 | 13066.0 | 810.0 | n/a | 1 |
| memory | tool_calls | 5.0 | 2.0 | -3.0 | n/a | 1 |
| memory | correct (native) | 2/2 | rate 1.0 | - | - | - |
| memory | correct (candidate) | 2/2 | rate 1.0 | - | - | - |
| no_benefit | tokens_in_out | 1400.0 | 1389.0 | -11.0 | n/a | 1 |
| no_benefit | tool_calls | 0.0 | 0.0 | 0.0 | n/a | 1 |
| no_benefit | correct (native) | 2/2 | rate 1.0 | - | - | - |
| no_benefit | correct (candidate) | 2/2 | rate 1.0 | - | - | - |

## Verdict detail

- **memory**: PASS
- **no_benefit**: PASS

## Brain overhead and delivery coverage

| task | class | arm | injected chars | memories injected | deliveries (expected) | tool calls | tokens (in+out) | status |
|---|---|---|---|---|---|---|---|---|
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 13066 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1389 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1400 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 5 | 12256 | ok |

## Raw artifacts

- manifest: `outputs\reports\v3-agent-experience\value\smoke/manifest.json`
- runs: `outputs\reports\v3-agent-experience\value\smoke/runs.json`
- summary: `outputs\reports\v3-agent-experience\value\smoke/summary.json`
- per-run model streams: `outputs\reports\v3-agent-experience\value\smoke/raw/`
- decision probe (no model calls): `outputs\reports\v3-agent-experience\value\smoke/probe.json`
