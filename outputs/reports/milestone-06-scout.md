# Milestone 06 — Scout (Phase 6)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-05 (Sensory Gateway / RTD) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

`brainctl scout run` — an isolated repository explorer: deterministic pre-pass
(git freshness, RepoWise probe, rg candidate scan) writes a 9-field Evidence
Map (plan §23); a fresh print-mode agent (read-only mandate) fills it; the
lead context receives only the map, never the trajectory. Plus the v4.2
Project #1 rekey and Stage-0 documentation kickoff.

### Exact files

- `src/second_brain/scout.py` — Evidence Map schema/template, repo resolution,
  deterministic pre-pass, atomic map writes, prime-agent command builder,
  `run_scout` spawn (named-pipe daemon socket fix)
- `src/second_brain/cli.py` — `scout run [--no-agent]`
- `tests/test_scout.py` — 15 tests
- `outputs/plans/phase6-scout-experiment.md` — experiment protocol
- `config/context.toml` + defaults — `[reserve]` completion-reserve heuristics
- Project #1: registry id rekeyed `e8d8d8e1…` -> `second-brain`, project dir
  git-moved, self-attached (`.brain/project.toml` + AGENTS.md marker)
- `outputs/reports/milestone-06-scout.md` (this file)

## Requirement-to-evidence (Phase 6 acceptance, plan §102)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Isolated Scout | evidence maps in outputs/evidence-maps/; agent sessions are separate Prime sessions (telemetry-visible); parent sees only the map |
| 2 | RepoWise → rg → ast-grep → direct read priority | SCOUT_PROMPT_TEMPLATE mandates the priority; pre-pass uses RepoWise probe + rg |
| 3 | Return only Evidence Map | all 9 §23 fields rendered; agent fills in place, final reply constrained to `<map>|<summary>` |
| 4 | Baseline vs Scout comparison | live experiment: 2 localization tasks x 2 arms (below) |
| 5 | Promote to advisory only if beneficial | T2: 3 vs 7 tool calls, -7.9s, equal correctness + one extra actionable finding; T1: -5.2s, equal correctness/tools. PROMOTED to advisory (manual, suggested for unfamiliar-localization work) |

### Experiment (model deepseek-v4-flash, telemetry-measured)

| Arm | wall | tools | bytes | peak ctx | correctness |
|---|---|---|---|---|---|
| T1 baseline | 34.3s | 3 | 14942 | 1.62% | correct |
| T1 scout | 29.1s | 3 | 23870 | 1.86% | correct |
| T2 baseline | 33.9s | 7 | 10372 | 1.50% | correct |
| T2 scout | 26.0s | 3 | 10206 | 1.46% | correct + found real config-wiring gap |

The T2 scout bonus finding (verification.toml
`material_unverified_blocks_completion` documented but not read by code —
hardcoded) is logged as Phase 7 scope.

## Commands / checks actually run

```text
ruff check / ruff format --check / pyright / pytest -q -> all green (164 tests)
2 scout agent runs + 4 experiment sessions (real prime-agent, flash)
brainctl doctor -> 16/16 after rekey
backup before rekey: backups/backup-20260814-060833-738077
```

## Deviations

1. Evidence-map files land in outputs/evidence-maps/ (derived, gitignored) —
   plan lists evidence maps under outputs/ too; consistent.
2. Scout tool allowlist `ipython,bash` (Prime v0.7.2's tool surface); the
   read-only mandate is prompt-enforced — a truly enforced read-only tool set
   needs harness work (recorded for Phase 8).
3. RepoWise freshness "unknown" (no index exists on this machine) — the probe
   records that honestly per map.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: project registry (Project #1), telemetry (experiment
  metrics), working set (Phase 6 task gating), scout (T1/T2 arms), backup
  (pre-rekey).
- How they were used: the Brain is now its own registered project with the
  stable id `second-brain` (doctrine requirement); telemetry measured every
  experiment session; the working-set capsule `build-phase6-scout` tracked the
  experiment requirements; scout produced the maps the scout-arms consumed.
- Observed benefit: scout-arm parity-or-better correctness with fewer tool
  calls on T2 (3 vs 7) and faster walls; the map file gave the resume surface
  without any search trajectory in the lead context.
- Observed overhead: pre-pass ~1-2s deterministic; agent run ~25-30s flash.
- Token/context effect: lead context received 2 map files (~2-4K chars total)
  instead of 2 exploration trajectories (10K+ result bytes each).
- Failures or friction: initial scout spawn used an invalid named-pipe socket
  (daemon crash) — fixed and regression-tested; print-mode flash agents
  occasionally decline bash (recorded, harness-level trigger test deferred).
- Knowledge captured: 2 evidence maps; 1 improvement finding (verification
  config gap) promoted into Phase 7 requirements; experiment JSON at
  state/recon/phase6-experiment.json.
- Memory/episode IDs: n/a (episodic memory lands in Phase 9).
- Candidate improvements: wire `material_unverified_blocks_completion` into
  check_requirements (Phase 7); enforce read-only tools at harness level
  (Phase 8).
- Promotion decision: Scout -> ADVISORY (manual suggestion for unfamiliar
  localization); not ACTIVE (needs cross-task repetition + read-only
  enforcement first).

## Rollback

- Git: revert commits since milestone-05.
- Rekey rollback: restore `backups/backup-20260814-060833-738077` + `git mv`
  back; or rerun registry logic with the old id.
- Scout is a manual command: nothing active to disable.

## Next gate

**Phase 7 — Accuracy** (plan §103): risk controller, Requirement Ledger
enforcement thresholds, Intent Verifier workflow; HIGH-risk only; planted
requirement/test mismatch eval.
