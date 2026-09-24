# V3 agent-experience value suite

- command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value/campaign2 --reps 3 --arms native,candidate --seed 20260925 --model deepseek/deepseek-flash --thinking low`
- full campaign command: `python scripts/v3_value_suite.py --out outputs/reports/v3-agent-experience/value --reps 3 --arms native,candidate --seed 20260925 --model deepseek/deepseek-flash --thinking low`
- model: `deepseek/deepseek-flash` (thinking `low`)
- arms: native, candidate; reps: 3
- tasks: 20 (10 memory, 10 no_benefit)
- omp: omp/18.3.0
- verdict: **PASS**

## Method and caveats

- cwd per run: a fresh copy of `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v3-s1` minus .venv, .git, .worktrees, node_modules, __pycache__, .hypothesis, .pytest_cache, .ruff_cache, db, state, telemetry, memory, outputs/reports/v3-s2, outputs/reports/v3-agent-experience, outputs/reports/v3-agent-experience/value/campaign2, outputs/reports/v3-agent-experience/value/campaign2/raw. The Brain's own store (`memory/`, `db/`, `state/`, `telemetry/`) is excluded so a run cannot read answers out of the database it is measured against, and the frozen held-out set is excluded by contract. `outputs/reports` otherwise stays in the copy as legitimate hunting ground.
- home per run: a fresh copy of the corpus snapshot with the candidate's shipped config applied over it (files listed in `manifest.json/arms/candidate`).
- unknown usage stays null: a field some side never reported is never presented as a partial sum. Metrics compare `input+output` tokens (cache reads billed separately are recorded in `provider_usage.tokens_all`) and total tool calls.
- failures (timeouts, non-zero exits, harness errors) are retained as rows with `correct=false`; a harness error reports its counts as unknown, never as a measured 0. Run status counts: {'ok': 120}.
- retrieval coverage before any model call (`probe.json`, decision path only): 10/10 memory tasks inject, 10 carry the expected memory id in the packet, 1 no-benefit tasks delivered anything.
- answer anchors (`anchors.json`): 10/10 memory tasks are answerable from the repository copy by hunting (native can succeed) and 10/10 are covered by the memory store; anchor defects: none.

## Pass rule

Memory tasks pass when the candidate shows a net reduction over native in either total provider tokens (input+output) or total tool calls - paired per task, median of the candidate-minus-native deltas < 0 - with candidate correctness not below native. No-benefit tasks pass when the paired median delta for BOTH tokens and tool calls is <= 0 plus the configured slack, with candidate correctness not below native. The campaign passes only when both classes pass.

## Class results (paired per task, candidate - native)

| class | metric | native median | candidate median | median delta | bootstrap 95% CI | tasks paired |
|---|---|---|---|---|---|---|
| memory | tokens_in_out | 14951.0 | 9192.0 | -2032.0 | [-7907.0, 7172.5] | 10 |
| memory | tool_calls | 5.0 | 3.5 | -0.5 | [-3.0, 1.0] | 10 |
| memory | correct (native) | 20/30 | rate 0.6667 | - | - | - |
| memory | correct (candidate) | 27/30 | rate 0.9 | - | - | - |
| no_benefit | tokens_in_out | 1457.5 | 1445.5 | 0.0 | [-13.5, 17.0] | 10 |
| no_benefit | tool_calls | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | 10 |
| no_benefit | correct (native) | 30/30 | rate 1.0 | - | - | - |
| no_benefit | correct (candidate) | 30/30 | rate 1.0 | - | - | - |

## Verdict detail

- **memory**: PASS
- **no_benefit**: PASS

## Brain overhead and delivery coverage

| task | class | arm | injected chars | memories injected | deliveries (expected) | tool calls | tokens (in+out) | status |
|---|---|---|---|---|---|---|---|---|
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 4 | 10087 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 11 | 21371 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 16 | 35852 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 4 | 9375 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1417 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 1 | 3740 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1462 | ok |
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2098 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 0 | 1438 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 2 | 2121 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1509 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1413 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 6 | 13492 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 0 | 1672 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 0 | 1438 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 5 | 14706 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 2 | 6909 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1710 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 5 | 9873 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 5 | 11099 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1428 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1418 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 6 | 29154 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1708 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 36 | 94477 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1424 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 5840 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 0 | 1620 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1956 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 19 | 47272 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1453 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 2 | 10333 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1466 | ok |
| VG-N06 | no_benefit | candidate | 0 | - | - | 0 | 1521 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 6 | 7959 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1412 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 11 | 13924 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 0 | 1444 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 5 | 16726 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1421 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 2 | 11795 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 7 | 22181 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 27 | 72254 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1411 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1504 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 4 | 4274 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 7 | 26616 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1417 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 0 | 1444 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1944 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 7 | 22098 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 0 | 1590 | ok |
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 3 | 15397 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1621 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 0 | 1516 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 3 | 15454 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 15 | 22856 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1599 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 2 | 9614 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1417 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1545 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 7 | 17557 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1497 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 16 | 36878 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 9 | 19990 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1440 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1413 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 3 | 10577 | ok |
| VG-N06 | no_benefit | candidate | 0 | - | - | 0 | 1452 | ok |
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2224 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 0 | 1444 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1413 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1710 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 4 | 22080 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1764 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 13712 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 0 | 1438 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 4 | 7723 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 0 | 2055 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 0 | 1638 | ok |
| VG-N02 | no_benefit | native | 0 | - | - | 0 | 1411 | ok |
| VG-N05 | no_benefit | candidate | 0 | - | - | 0 | 1438 | ok |
| VG-N04 | no_benefit | native | 0 | - | - | 0 | 1478 | ok |
| VG-M01 | memory | native | 0 | - | mem-b67de5057f76:0 | 0 | 1623 | ok |
| VG-M08 | memory | candidate | 2670 | mem-79d7c4fd9876, mem-99df66e3c8f6 | mem-79d7c4fd9876:1 | 14 | 33252 | ok |
| VG-M03 | memory | candidate | 757 | mem-29557f93448f | mem-29557f93448f:1 | 2 | 4854 | ok |
| VG-N09 | no_benefit | native | 0 | - | - | 1 | 1758 | ok |
| VG-N09 | no_benefit | candidate | 0 | - | - | 1 | 1738 | ok |
| VG-M06 | memory | native | 0 | - | mem-f745bcb2eff2:0 | 22 | 50932 | ok |
| VG-N07 | no_benefit | candidate | 0 | - | - | 0 | 1444 | ok |
| VG-N04 | no_benefit | candidate | 0 | - | - | 0 | 1413 | ok |
| VG-N07 | no_benefit | native | 0 | - | - | 0 | 1444 | ok |
| VG-M02 | memory | native | 0 | - | mem-a8d221e64549:0 | 5 | 15196 | ok |
| VG-M05 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 7 | 26610 | ok |
| VG-M10 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 13 | 19951 | ok |
| VG-M09 | memory | candidate | 888 | mem-174b3f5abbba | mem-174b3f5abbba:1 | 28 | 59903 | ok |
| VG-M07 | memory | native | 0 | - | mem-b0d6cc3de0ab:0 | 4 | 10767 | ok |
| VG-M04 | memory | candidate | 1118 | mem-3848b16778bd | mem-3848b16778bd:1 | 4 | 9009 | ok |
| VG-M02 | memory | candidate | 495 | mem-a8d221e64549 | mem-a8d221e64549:1 | 2 | 7289 | ok |
| VG-N08 | no_benefit | native | 0 | - | - | 0 | 1467 | ok |
| VG-M07 | memory | candidate | 733 | mem-b0d6cc3de0ab | mem-b0d6cc3de0ab:1 | 3 | 9342 | ok |
| VG-M10 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 5 | 13837 | ok |
| VG-N03 | no_benefit | candidate | 0 | - | - | 0 | 1440 | ok |
| VG-M03 | memory | native | 0 | - | mem-29557f93448f:0 | 2 | 10196 | ok |
| VG-M01 | memory | candidate | 804 | mem-b67de5057f76 | mem-b67de5057f76:1 | 0 | 1884 | ok |
| VG-N08 | no_benefit | candidate | 0 | - | - | 0 | 1447 | ok |
| VG-N02 | no_benefit | candidate | 0 | - | - | 0 | 1411 | ok |
| VG-M05 | memory | candidate | 1539 | mem-79d7c4fd9876 | mem-79d7c4fd9876:1 | 2 | 6621 | ok |
| VG-M04 | memory | native | 0 | - | mem-3848b16778bd:0 | 4 | 8703 | ok |
| VG-M09 | memory | native | 0 | - | mem-174b3f5abbba:0 | 10 | 22180 | ok |
| VG-N01 | no_benefit | candidate | 0 | - | - | 0 | 1417 | ok |
| VG-M06 | memory | candidate | 895 | mem-f745bcb2eff2 | mem-f745bcb2eff2:1 | 16 | 29274 | ok |
| VG-N10 | no_benefit | candidate | 757 | mem-29557f93448f | - | 1 | 2224 | ok |
| VG-N01 | no_benefit | native | 0 | - | - | 0 | 1417 | ok |
| VG-N03 | no_benefit | native | 0 | - | - | 0 | 1451 | ok |
| VG-N06 | no_benefit | candidate | 0 | - | - | 0 | 1452 | ok |
| VG-N10 | no_benefit | native | 0 | - | - | 1 | 1942 | ok |
| VG-N06 | no_benefit | native | 0 | - | - | 0 | 1442 | ok |
| VG-M08 | memory | native | 0 | - | mem-79d7c4fd9876:0 | 8 | 17504 | ok |
| VG-N05 | no_benefit | native | 0 | - | - | 0 | 1465 | ok |

## Raw artifacts

- manifest: `outputs\reports\v3-agent-experience\value\campaign2/manifest.json`
- runs: `outputs\reports\v3-agent-experience\value\campaign2/runs.json`
- summary: `outputs\reports\v3-agent-experience\value\campaign2/summary.json`
- per-run model streams: `outputs\reports\v3-agent-experience\value\campaign2/raw/`
- decision probe (no model calls): `outputs\reports\v3-agent-experience\value\campaign2/probe.json`
