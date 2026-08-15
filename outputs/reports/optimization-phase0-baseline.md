# Optimization Phase 0 — Baseline (Sol Minimal-Orchestrator pass)

Date: 2026-08-15 (UTC). Plan:
`Second_Brain_Optimization_Sol_Minimal_Orchestrator.md` (P0.1–P0.3).
Branch: `brain/optimization-sol-orchestrator` (forked from
`brain/security-remediation` @ 3fd5c5e; SEC-01..08 remediation merged in, no
optimization work yet).

Status labels: **IMPLEMENTED** = wired and proven; **PROVEN** = measured with
reproducible evidence; **ADVISORY** = guidance only, no hard enforcement;
**NOT WIRED** = capability exists but nothing emits/consumes it;
**PLANNED** = accepted, not yet built.

## 1. Telemetry baseline (PROVEN — measured this pass)

Method: enumerate `<home>/telemetry/agent-performance/*.jsonl`, count records
per file (non-empty lines, parsed as JSON). Home = this repo root. Measurement time: 2026-08-15 UTC; filesystem mtimes span 2026-08-14T05:03Z .. 2026-08-15T00:55Z.

| Metric | Value |
|---|---:|
| Total telemetry files | 360 |
| Anonymous (`anon-*`) files | 304 |
| Files with <= 2 records | 310 (304 exactly 1, 6 exactly 2) |
| Total records across all files | 13,032 |
| Anonymous records | 304 (1 per anon file) |
| Largest session file | 4,686 records |

Interpretation: every anonymous file holds exactly one record — the classic
fragmentation signature (fallback identity regenerated per event). 304 anon
files / 304 anon records, i.e. one tiny file per event. Non-anon session files
(56) are healthy aggregates. Fix target: Phase 2 of the optimization plan
(one stable anonymous session id per extension lifecycle).

Honesty note: an earlier interim note claimed "150 files with <= 2 records";
that number could not be reproduced on this snapshot — the measured count is
310. Measured values above are authoritative for this baseline.

## 2. Retrieval baseline (PROVEN — prior campaign artifacts)

Source: `proof/reports/retrieval.md` (proof/runner/retrieval.py, fresh temp
Brain homes, current `semantic.search_memories` engine — linear file scan +
substring match, no ranking/filters/dedupe/budget).

| Corpus | Recall@1 | Recall@3 | Recall@5 | Precision@5 | Dup rate | Stale rate | Contradiction surfaced | p50 ms | p95 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 11.5 | 12.0 |
| 1,000 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 123.4 | 129.0 |
| 10,000 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 | 0.3333 | 0.0000 | 1,374.5 | 1,426.1 |

Raw result hashes (provenance): `retrieval-100-1000.json`
`2BCB80538DE1C1E98FD431684080FE8AF7794F2680D3B7033D3ACFE1A8018D17`;
`retrieval-10000.json`
`63564B88AD351E370DAFFDBECE0BED5B4C02D222D528219A7921C7B6E2F7B9A2`.

Gates vs plan §23: p95 <= 200 ms @ 10k (measured 1,426 ms) — FAIL;
Recall@1 — FAIL (0.0); duplicate/stale injection 0.33 — FAIL; contradiction
surfacing 0.0 — FAIL. Plan Phases 6–11 (FTS5 + filters + dedupe + rank +
budget) are **PLANNED** (not built).

## 3. Router baseline (PROVEN — prior campaign artifacts)

Source: `outputs/reports/milestone-17-skill-router.md` (real-grounded tasks)
and `outputs/reports/experiment-143-repeated-workflow-skill.md`:

- Router trigger noise 1 vs natural-baseline noise 3; recall 5/5 vs 3/5;
  F1 0.417 vs 0.250 (milestone-17).
- Real shadow skill `delivery-integration` routes fresh task at score 4.0 vs
  other shadow skill 0.0; labeled trigger recall 6/6, zero noise
  (experiment-143).
- Router reads SKILL.md from disk on every call — no compiled index/cache
  (router.py `_skill_sections`). Plan Phase 13 (cache + margin + negative
  veto) is **PLANNED**.

## 4. Configuration baseline (NOT WIRED / PARTIAL)

- `config/*.toml` (8 files) are tracked and seeded; there is no canonical
  loader module — `tomllib` is used ad hoc in cli.py / doctor.py /
  registry.py / working_set.py.
- `config/retrieval.toml` (`scoring`, `lateral_inhibition`, `decay` keys) is
  **NOT WIRED**: no src module reads those keys (verified by grep; only
  `src/second_brain/paths.py` references the file name as a required seed).
- `src/second_brain/router.py` hardcodes `max_active = 3` and
  `SELECTION_THRESHOLD = 1.0` — not config-driven.
- Plan Phase 12 (one canonical loader; every setting ENFORCED /
  INFORMATIONAL / PLANNED) is **PLANNED**.

## 5. Orchestration / Sol baseline

- `brainstem/policies/` was empty (only `.gitkeep`); this pass adds
  `sol-minimal-orchestrator.md` (**ADVISORY** policy; enforcement status
  documented inside).
- Prime per-model tool restrictions: **NOT CONFIGURED / UNVERIFIED** — active
  settings expose model enablement/defaults but no configured per-model tool
  restrictions were verified; global Prime configuration was NOT modified.
- `orchestrator_policy_violation` telemetry: **IMPLEMENTED as capability**
  (schema v2 kind, Python aggregation, pure TS sensor builder), **NOT WIRED**
  (no emitting hook; sensor is report-only).
- Automatic Prime integration (recall/skill injection): **BLOCKED BY
  CONTRACT** — `proof/conditions.json` C2–C7 are `blocked_until_contract`.

## 6. Baseline health

- Python test suite: full `tests/` run passes (rc=0, ~99 s, 2 skipped) —
  measured 2026-08-15 on this branch before edits.
- Vitest / ESLint / tsc on the Prime extension: NOT re-run in this pass before
  edits (targeted run after edits; see optimization milestone report).

## Provenance

- Telemetry counts: direct filesystem measurement this pass (method above).
- Retrieval numbers: `proof/reports/retrieval.md` + raw hashes (prior
  campaign, engine unchanged since).
- Router numbers: `outputs/reports/milestone-17-skill-router.md`,
  `outputs/reports/experiment-143-repeated-workflow-skill.md`.
- Config wiring: grep of `src/second_brain/*.py` + `proof/**/*.py` for
  `max_results|lateral_inhibition|retrieval.toml|surface_contradictions|decay|scoring`.
