# E02 — corrected lexical vs small local dense encoder vs hybrid (dev split)

Date: 2026-09-24 · Branch `brain/v3-s2` @ `036e69e` (+ uncommitted S2 work) · Instrument:
`scripts/v3_e02_semantic.py` (frozen for the run: `script_fingerprint` in `results.json`
equals the on-disk file hash).
Raw results: `results.json` (arms × cases, floor sweeps, RAM, latency, offline evidence),
`child_*.json` (per-arm process records), `cases.used.jsonl` (the frozen case set the run
measured), `models.manifest.json` (model file hashes).

## Verdict

**Lexical ships. No semantic component qualifies.** The corrected lexical decision is at
the dev ceiling (required-memory recall 10/10 = 100%, no-benefit abstention 11/11 = 100%),
above the contract's 95% bar. Every dense and hybrid arm delivers **0 of 10** required
memories when held to the lexical baseline's abstention (0 false injections); to match the
lexical recall they must accept a wrong-project injection (1/11). No arm beats the
baseline by ≥ 5 points at equal-or-better abstention, so none ships. `verdict.any_qualifies
= false` in `results.json`.

## Method

- **Corpus**: read-only snapshot of the live home (SQLite `backup` from a `?mode=ro`
  handle + config/memory/constitution/templates/skills/frontier), taken by
  `scripts/v3_matched_arms.py::snapshot_corpus`. 116 memories (111 pass the Phase-7
  status/grade filters), schema 28, `db_sha256 b911aff2058ddc48…`. Each arm runs in its own
  copy of the snapshot.
- **Cases**: `outputs/reports/v3-s2/dev/cases.jsonl` only (21 cases: 10 memory-needing,
  11 no-benefit, sha256 `f1b256b94be8fff5…`). The run copies it to `cases.used.jsonl` and
  every arm reads that copy, so all five arms measured the identical case set
  (`dev_cases.case_set_consistent = true`). The held-out set is never opened —
  `_load_cases` refuses any path containing `heldout`.
- **Arms** (project `second-brain`, role `worker`, candidate ceiling 10):
  - `lexical` — the production pipeline, unmodified: `autoinject.prepare_injection` =
    full query → contribution decision → focused retry (`idf_focused`) → narrowed retry
    (`idf_narrowed`) → validity/freshness/role/budget. Its decision numbers are produced by
    that function; its ranking numbers come from a mirror of the same retrieval chain that
    uses the product's own `semantic.query_match_plan` / `contribution_filter` (mirror vs
    production decision agreement: **21/21** cases).
  - `dense:<enc>` — exact cosine over all 111 admissible memories (union pool allowed by
    production's scoped+unscoped supplement rule), then the same admission tail
    (validity → freshness → role → delivered → budget). The ROI token-cost stage
    (`p_need*value < token_cost_ratio`) is reported per case (`roi_dropped_ids`) but not
    applied: it is calibrated to the product's lexical score scale and would reject every
    dense/RRF candidate for scale reasons.
  - `hybrid:<enc>` — RRF (k=60) fusion of the lexical and dense rankings.
- **Encoders** (CPU only, `prefetch`ed once into local files, loaded by path):
  `minishlab/potion-base-8M` (model2vec static, 256-dim, 29.3 MiB) and
  `Xenova/all-MiniLM-L6-v2` (`onnx/model_quantized.onnx`, 384-dim int8, 22.6 MiB) via
  `onnxruntime` 1.30.0 + `tokenizers` 0.23.2 (mean pooling, L2, batch 16, max_len 256).
  Installed into the worktree venv only (numpy 2.5.3, model2vec 0.9.0, huggingface-hub
  1.33.0); `pyproject.toml` untouched — no mandatory dependency added.
- **Offline**: every child ran with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and a dead
  HTTP(S) proxy; a network probe inside the same process reports `reachable: false`
  (WinError 10061). Encoder children additionally ran the whole measured path with every
  socket connect blocked in-process (`offline_guard.sockets_blocked_during_encode: true`)
  and completed normally — the encoder path uses no network.
- **Thresholds**: the production gate shape (floor ≥ 0.55, `top1 − top2 ≥ 0.08`) as-is for
  every arm, plus a full floor sweep under both the production gap rule and a
  threshold-only rule (gap 0). The lexical baseline's authoritative numbers are
  `prepare_injection`'s, not the sweep.
- **Resources**: Win32 `GetProcessMemoryInfo` (resident + peak working set) per arm's own
  process; cold load = fresh-process model load; index build = encoding the 111 admissible
  memories; warm latency = 5 reps × 21 prompts after warmup.

## Results (21 dev cases: 10 memory-needing, 11 no-benefit)

Retrieval level — required memory present in the arm's candidate ranking:

| arm | recall@1 | recall@3 | recall@10 |
|---|---|---|---|
| corrected lexical | 1.00 (10/10) | 1.00 | 1.00 |
| dense m2v-potion-8M | 0.80 (8/10) | 0.80 | 0.80 |
| dense MiniLM-L6 int8 | 0.90 (9/10) | 0.90 | **1.00** |
| hybrid m2v-potion-8M | 1.00 | 1.00 | 1.00 |
| hybrid MiniLM-L6 int8 | 1.00 | 1.00 | 1.00 |

Decision level — required memory actually injected / no-benefit cases that inject:

| arm | delivered recall | no-benefit false injections | packet tokens (median) |
|---|---|---|---|
| **corrected lexical (production)** | **1.00 (10/10)** | **0.00 (0/11)** | 123 (max 322) |
| dense MiniLM — production gate as-is | 0.60 | 0.091 (1/11, D20) | — |
| dense m2v — production gate as-is | 0.50 | 0.091 (1/11, D20) | — |
| hybrid MiniLM — production gate as-is | 0.00 | 0.00 | — |
| hybrid m2v — production gate as-is | 0.00 | 0.00 | — |

Frontier over every floor (dev-calibrated, i.e. optimistic for the semantic arms):

| arm | best recall at 0/11 false | best recall at 1/11 false | floor / rule for that point |
|---|---|---|---|
| dense MiniLM | **0.00** | 1.00 (10/10) | 0.387, threshold-only |
| hybrid MiniLM | **0.00** | 1.00 (10/10) | 0.032, threshold-only |
| dense m2v | **0.00** | 0.60 | 0.604, threshold-only |
| hybrid m2v | **0.00** | 0.80 | 0.033, threshold-only |

The single case that blocks every semantic arm is **D20** (`wrong_project`: "What delay and
factor does the brain-pilot-demo retry helper use?" — must abstain under project
`second-brain`). Its top-1 score is the arm's strongest score over the whole dev set for
every encoder — MiniLM 0.804, m2v 0.859, RRF 0.033 vs the arms' best memory-needing
top-1 of 0.764 / 0.756 / 0.033 — so no floor separates it from the positive class.
Mechanism (measured, not inferred): the dense arm's top-1 there is `mem-f9b4deb601eb`
("brain-pilot-demo retry helper…", scope `project: brain-pilot-demo`), which the lexical
path retrieves and then rejects (`WRONG_PROJECT`), while the semantic arms rank it first and
whose shared admission tail admits a *different*, project-eligible but irrelevant memory
(e.g. MiniLM injects `mem-3693230ebaf0` + `mem-ad3d80115ee2`). Cosine similarity cannot
express "applies to this request".

Resources (own process, Win32 working set; shared workstation, indicative):

| arm | cold model load | index build (111 docs) | encode/query | warm rank median | peak resident |
|---|---|---|---|---|---|
| corrected lexical | — (no model) | — | — | 29.7 ms | 40.3 MiB |
| dense m2v-potion-8M | 431.7 ms | 124.1 ms | 0.08 ms | 0.10 ms | 129.3 MiB |
| dense MiniLM-L6 int8 | 252.8 ms | 1182.1 ms | 1.80 ms | 2.11 ms | 366.9 MiB |
| hybrid m2v-potion-8M | 457.2 ms | 131.3 ms | 0.07 ms | 28.7 ms | 129.3 MiB |
| hybrid MiniLM-L6 int8 | 277.6 ms | 1466.8 ms | — | 44.4 ms | 365.3 MiB |

All encoders are CPU-only (`CPUExecutionProvider` / numpy), offline and within the
≤ 1024 MiB resident budget — resources are not what blocks adoption. The real lexical
decision costs 80.5 ms median / 160.6 ms p95 in this harness (whole-pipeline numbers are
E01's, not E02's).

## Adoption rule (S2 contract §E02)

| arm | best recall at ≤ lexical false rate (0.00) | Δ vs corrected lexical | within 1024 MiB | qualifies |
|---|---|---|---|---|
| dense MiniLM-L6 int8 | 0.00 | −1.00 | yes (366.9 MiB) | **no** |
| hybrid MiniLM-L6 int8 | 0.00 | −1.00 | yes (365.3 MiB) | **no** |
| dense m2v-potion-8M | 0.00 | −1.00 | yes (129.3 MiB) | **no** |
| hybrid m2v-potion-8M | 0.00 | −1.00 | yes (129.3 MiB) | **no** |

Independently, the baseline's recall is 100% > the 95% bar, which disqualifies every
semantic component on this split. The semantic arms' floors were calibrated on the same
dev cases (optimistic) and still only tie the baseline at a *worse* abstention rate.

## Findings for the integrator

1. There is no retrieval-quality gap to close: hybrid RRF reaches lexical's recall@10
   (1.00), and MiniLM alone reaches it too. What dense arms lack is the **decision stage**
   (contribution + project admission), which is exactly where the corrected lexical path
   wins. Adding an encoder without an equivalent decision rule makes no-benefit abstention
   worse, which the contract forbids.
2. The product already has the seam for a dense tier (`Cascade.retrieve(vector_searcher=…)`,
   Tier 3, `_canonical_vector_row`), but no encoder implementation exists in
   `src/second_brain` and no caller passes `vector_searcher`, so that tier is currently
   unreachable dead code (`semantic_vectors` in `governor.py` is a capability flag only).
3. Shipping a dense tier would require recalibrating two lexical-scale components, not just
   adding an encoder: the gate floor/gap (MiniLM's correct top-1s have gaps 0.056–0.528,
   with two of ten below the production 0.08 rule, while the must-abstain D20 has the
   *largest* gap of the whole dev set at 0.373 — the rule separates the classes backwards)
   and the ROI token-cost stage (drops 9/10 candidates at lexical scale, every dense
   candidate as-is). Both are visible per case in `results.json` (`threshold_sweep`,
   `roi_dropped_ids`).
4. If a semantic tier is revisited, `hybrid` (RRF) is the better shape than raw dense: it
   matches the lexical ranking without extra model cost, and its no-benefit failure set is
   the same single case (D20). Re-run E02 against the held-out split before acting on this.
5. Dense packets are 5–6× larger for the same recall (median 650–685 tokens vs lexical's
   123) because the admission tail keeps several candidates: token cost, not just accuracy,
   favours the lexical path.

## Caveats

- Dev split only; the held-out set is the binding measurement (S2 campaign). Nothing here
  is held-out evidence. Per-case granularity is 10 points, so "≥ 5 points" is not
  resolvable finer than a case.
- The dev split grew from 10 to 21 cases at 06:05:42 while this experiment was running.
  This note reports only the final 21-case run (`cases.used.jsonl`, sha256
  `f1b256b94be8fff5…`); the earlier 10-case run is superseded. Per-case results were
  bit-identical across both runs for the shared cases, and across two independent 21-case
  runs (verified for lexical/dense rankings, scores, decisions).
- Latency and RAM were measured on a shared workstation with other agents active
  (indicative, not a frozen profile; S1's `RESOURCE_PROFILE.frozen.json` remains that).
  Recall, abstention, token and ranking numbers are deterministic.
- Dense/hybrid decisions come from a mirror of production's post-retrieval tail (minus the
  scale-dependent ROI stage); the lexical arm's authoritative numbers are the real
  `prepare_injection`, whose decision output the mirror reproduced on 21/21 cases.
- The semantic arms were given the same candidate ceiling (10), project/role configuration
  and admission tail as the lexical arm, so the comparison isolates ranking + the decision
  rule.
