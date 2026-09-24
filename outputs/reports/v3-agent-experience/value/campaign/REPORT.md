# V3 agent-experience value suite

- command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value/campaign --reps 3 --arms native,candidate --seed 20260924 --model deepseek/deepseek-flash --thinking low`
- full campaign command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value --reps 3 --arms native,candidate --seed 20260924 --model deepseek/deepseek-flash --thinking low`
- model: `deepseek/deepseek-flash` (thinking `low`)
- arms: native, candidate; reps: 3
- tasks: 20 (10 memory, 10 no_benefit)
- omp: omp/18.3.0
- verdict: **FAIL**

## Method and caveats

- cwd per run: a fresh copy of `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v3-s1` minus .venv, .git, .worktrees, node_modules, __pycache__, .hypothesis, .pytest_cache, .ruff_cache, db, state, telemetry, memory, outputs/reports/v3-s2, outputs/reports/v3-agent-experience, outputs/reports/v3-agent-experience/value/campaign, outputs/reports/v3-agent-experience/value/campaign/raw. The Brain's own store (`memory/`, `db/`, `state/`, `telemetry/`) is excluded so a run cannot read answers out of the database it is measured against, and the frozen held-out set is excluded by contract. `outputs/reports` otherwise stays in the copy as legitimate hunting ground.
- home per run: a fresh copy of the corpus snapshot with the candidate's shipped config applied over it (files listed in `manifest.json/arms/candidate`).
- unknown usage stays null: a field some side never reported is never presented as a partial sum. Metrics compare `input+output` tokens (cache reads billed separately are recorded in `provider_usage.tokens_all`) and total tool calls.
- failures (timeouts, non-zero exits, harness errors) are retained as rows with `correct=false`; a harness error reports its counts as unknown, never as a measured 0. Run status counts: {'ok': 120}.
- retrieval coverage before any model call (`probe.json`, decision path only): 10/10 memory tasks inject, 10 carry the expected memory id in the packet, 2 no-benefit tasks delivered anything.
- answer anchors (`anchors.json`): 10/10 memory tasks are answerable from the repository copy by hunting (native can succeed) and 10/10 are covered by the memory store; anchor defects: none.

## Pass rule

Memory tasks pass when the candidate shows a net reduction over native in either total provider tokens (input+output) or total tool calls - paired per task, median of the candidate-minus-native deltas < 0 - with candidate correctness not below native. No-benefit tasks pass when the paired median delta for BOTH tokens and tool calls is <= 0 plus the configured slack, with candidate correctness not below native. The campaign passes only when both classes pass.

## Class results (paired per task, candidate - native)

| class | metric | native median | candidate median | median delta | bootstrap 95% CI | tasks paired |
|---|---|---|---|---|---|---|
| memory | tokens_in_out | 11174.0 | 12066.5 | -564.0 | [-4857.0, 3640.0] | 10 |
| memory | tool_calls | 4.0 | 3.5 | -1.5 | [-2.5, 1.0] | 10 |
| memory | correct (native) | 20/30 | rate 0.6667 | - | - | - |
| memory | correct (candidate) | 28/30 | rate 0.9333 | - | - | - |
| no_benefit | tokens_in_out | 1450.0 | 1480.5 | 3.5 | [-2.0, 111.0] | 10 |
| no_benefit | tool_calls | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | 10 |
| no_benefit | correct (native) | 30/30 | rate 1.0 | - | - | - |
| no_benefit | correct (candidate) | 30/30 | rate 1.0 | - | - | - |

## Verdict detail

- **memory**: PASS
- **no_benefit**: FAIL
  - measurable increase: median delta tokens=3.5, tool_calls=0.0 against slack (0.0, 0.0)

## Brain overhead and delivery coverage

| task | class | arm | injected chars | memories injected | deliveries (expected) | tool calls | tokens (in+out) | status |
|---|---|---|---|---|---|---|---|---|
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2122 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1440 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 24 | 48850 | ok |
| VG-N06 | no_benefit | candidate | 804 | mem-b67de5057f76 | - | 0 | 1692 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 2 | 6820 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 4 | 12493 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1415 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1772 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1666 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1442 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 0 | 1712 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 8674 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 3 | 5428 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 7 | 17193 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1411 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 20 | 35463 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1946 | ok |
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 4 | 5984 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1411 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1415 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 4 | 12573 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 13915 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 3 | 12103 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 1 | 1764 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 6 | 11640 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 1 | 2046 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 10 | 24628 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 5 | 24109 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 6 | 24304 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 0 | 1465 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1427 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 0 | 1459 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1420 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 15 | 25098 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1411 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 4 | 14466 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1466 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 5274 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1481 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 2 | 5921 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1704 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 2 | 6237 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 7793 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 4 | 8379 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 0 | 1436 | ok |
| VG-N06 | no_benefit | candidate | 804 | mem-b67de5057f76 | - | 0 | 1671 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1412 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 5 | 14724 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 6 | 15158 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 0 | 2254 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 19 | 24060 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1415 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 0 | 1460 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1411 | ok |
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2236 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1415 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1556 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 5266 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1420 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 8 | 19771 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 1 | 8931 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 2 | 9288 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 0 | 1442 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1454 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 2 | 9203 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 8307 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 15 | 43270 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1730 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 7 | 8930 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 3 | 16022 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1459 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 19 | 53018 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 0 | 1442 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 4 | 10231 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1411 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1495 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1948 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 24 | 44491 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1453 | ok |
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 4 | 15694 | ok |
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2236 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1410 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1415 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 3 | 10293 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 0 | 2042 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1415 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 0 | 1565 | ok |
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 3 | 5508 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 11048 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1718 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1534 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 1 | 2072 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 12 | 31322 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 0 | 1442 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1938 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 9 | 17935 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 5337 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 0 | 1788 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 0 | 1594 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 18 | 54471 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 12 | 28633 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 4 | 11300 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1774 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1410 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 15 | 13515 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 6 | 9043 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 10 | 19538 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1429 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1441 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1526 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1524 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 0 | 1908 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1446 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 5951 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 0 | 1442 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 3 | 13626 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1416 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 20 | 36634 | ok |
| VG-N06 | no_benefit | candidate | 804 | mem-b67de5057f76 | - | 0 | 1676 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 3 | 9949 | ok |

## Raw artifacts

- manifest: `outputs\reports\v3-agent-experience\value\campaign/manifest.json`
- runs: `outputs\reports\v3-agent-experience\value\campaign/runs.json`
- summary: `outputs\reports\v3-agent-experience\value\campaign/summary.json`
- per-run model streams: `outputs\reports\v3-agent-experience\value\campaign/raw/`
- decision probe (no model calls): `outputs\reports\v3-agent-experience\value\campaign/probe.json`
