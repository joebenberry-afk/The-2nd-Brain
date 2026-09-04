# T7.8 Task Report — Decision-Linked Knowledge Frontier

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 662–696.

## Files

- `src/second_brain/frontier.py`
- `src/second_brain/decisions.py`
- `src/second_brain/migrations/0021_frontier.sql` (new)
- `tests/test_v2_frontier.py` (new)
- `scripts/run_frontier_experiment.py` (new)
- `outputs/reports/v2/frontier/frontier-experiment.json` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.8-report.md` (new)

## Implemented contract

1. **Owner & Retained Table**:
   Extended `frontier.py` to manage active-learning uncertainty through the retained table `v2_frontier_items` (migration `0021_frontier.sql`), leaving existing manual review functions fully compatible.

2. **Decision-Linked Uncertainty**:
   Every frontier item strictly requires `decision_ref` linking to a concrete operational decision kind and replayable input class in `decisions`. Items without `decision_ref` are rejected (`BrainError`). Generic disconnected research queries are barred from the operational frontier.

3. **Priority Ranking Formula**:
   $$\text{priority} = \frac{\text{stake\_tokens} \times p_{\text{flip}}}{\text{expected\_cost}}$$
   All three inputs are measured or estimated with provenance. If any parameter is unknown, `priority` remains `None`/`null`.
   `list_frontier_items` enforces that measured items with numeric priorities always sort first in descending order, ensuring unmeasured items never outrank measured ones.

4. **Discriminating Experiment Selection**:
   `choose_cheapest_experiment` evaluates declared experiments and selects the cheapest discriminating experiment, prioritizing local deterministic inspection over expensive live model calls.

5. **Decision Ledger Provenance**:
   Added `"frontier"` to `_DECISION_KINDS` in `decisions.py`. Every created frontier item logs its provenance and chosen priority in the `decisions` table.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_v2_frontier.py -q
4 passed

.venv/Scripts/python.exe -m pytest tests/test_frontier.py -q
33 passed
```

Named tests verified:
- `test_frontier_rejects_item_without_decision_ref`: PASS (items lacking decision_ref rejected)
- `test_frontier_unknown_cost_does_not_outrank_measured_item`: PASS (unmeasured item with huge stake ranks behind measured item)
- `test_frontier_rank_formula`: PASS (ranking order matches priority formula)
- `test_frontier_item_links_to_replayable_decision`: PASS (links directly to decisions table row and selects local cheap discriminator)

## Cheapest real experiment

Script `scripts/run_frontier_experiment.py` created 3 frontier items from real routing, retrieval, and eviction choices:

- Item 1 (routing): priority = 105.0 ($\text{stake}=15000, p_{\text{flip}}=0.7, \text{cost}=100$).
- Item 2 (retrieval): priority = 16.0 ($\text{stake}=8000, p_{\text{flip}}=0.4, \text{cost}=200$).
- Item 3 (eviction): priority = 4.0 ($\text{stake}=4000, p_{\text{flip}}=0.25, \text{cost}=250$).
- Top-ranked item selected: Item 1.
- Chosen experiment: `exp-local-replay-01` (cost=local, decision-changing, locally executable).
- Artifact saved: `outputs/reports/v2/frontier/frontier-experiment.json`.

## Migration and rollback

Migration `0021_frontier.sql` creates `v2_frontier_items`, `v2_rollout_events`, and `v2_qualification` using `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
Migration idempotency verified (`db.migrate()` runs cleanly and returns `[]` on repeat).
Rollback is code-revert safe.

## Commit

Commit message: `brain(learning): decision-linked knowledge frontier`.
