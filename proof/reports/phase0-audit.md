# v4.3 Phase 0 audit

Date: 2026-08-14. Repository before repair: `b0e5a35` on `main`.
The observations below were collected before the repair edits on the dedicated
proof-blocker branch. Commands were read-only except for isolated temporary
homes under `state/`.

## Reproduced findings

| Finding | Pre-repair observation | Consequence / repair |
|---|---|---|
| F-01 | `transfer_test` returned `transfers` for one shared task where A=FAIL and B=FAIL (`0 >= 0`); it also returned `transfers` for A=FAIL/B=SUCCESS. | Fixed with explicit zero-failure handling, mixed-outcome handling, and a two-overlap strong-evidence floor. |
| F-02 | `semantic.search_memories` scanned title/summary/body substrings; `jit.compile_context` had no semantic retrieval call; `retrieval.toml` scoring keys had no runtime readers. | Scoped honestly to the implemented mechanism; config-consumption matrix records non-operative keys. |
| F-03 | Prime `index.ts` declares `MEASUREMENT ONLY`; handlers return `undefined`; router returns `shadow: true`; RTD records `enabled-not-implemented`. | No automatic ACTIVE claim. `proof/ACTIVE_CONTRACT.md` records the autonomy failure boundary. |
| F-04 | `skills/active/sqlite-migration-verifier/SKILL.md` said `status: candidate` and contained five unresolved placeholders. | Canonical lifecycle directory mapping, status updates, audit command, execution-readiness gate, and repaired skill metadata/content. |
| F-05 | `config/context.toml` declared green through 60%, but `monitor._context_pressure([55%])` returned strength 1; CLI router default was hard-coded to 3; promotion diversity keys were not read. | Config matrix classifies every key; no descriptive config is treated as executed policy. |
| F-06 | In an isolated home, approve skill content A, mutate to B, then promotion returned `promoted: true` under the same change id. | Frontier approvals now bind logical artifact path, normalized content SHA-256, version, and eval-manifest hash; changed content returns `frontier_stale`. |
| F-07 | A 5/5 model plus a 0/5 model produced included=`[good]`, excluded=`[bad]`, success_rate=`1.0`; the failing model disappeared from the aggregate. | Stats retain model-specific inclusion but expose all-model rates, worst-model rate, excluded count, and `global_scope_eligible`. |
| F-08 | Existing E5 report used two models, one overlapping task, one success each, and self/by-elimination model identity. | Reclassified as a mechanism demo; later transfer phase requires fresh paired variants and a no-transfer control. |
| F-09 | Read-only current DB counts: projects=1, episodes=14, memories=6, memory_retrievals=2, memory_activations=2, model_profiles=2, model_skill_outcomes=6. | No scale/generalization claim from v4.2 dogfood. |
| F-10 | E3 report states its three episodes were captured after the real events; E4 used intentionally stale/handcrafted fixtures. | Natural online-learning proof remains a later campaign gate. |
| F-11 | `AGENTS.md`, `README.md`, and `INDEX.md` named v4.1 while milestone 24 declared v4.2 complete; `README.md` byte offset 2025 was control byte 8. | Authority/status docs reconciled and control byte removed. |

## Scoped limitations

F-12 (Windows-shaped persisted paths), F-13 (RTD active substitution not
implemented), and F-14 (RepoWise not initialized) remain explicit limitations.
They do not become portability, RTD-savings, or RepoWise claims in the proof.

## Post-repair deterministic evidence

- `brainctl skills audit --home .` -> `ok=True`.
- Focused Python suite -> all collected tests passed after the test runner was
  given the required non-default Windows execution environment.
- The first two pytest attempts failed during temporary-directory setup with
  `PermissionError: [WinError 5]` / `OSError: [Errno 22] Invalid argument`,
  before test bodies; those are environment evidence, not product failures.
