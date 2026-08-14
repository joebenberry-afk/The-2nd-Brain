# Milestone 04 — Working Set / JIT Context (Phase 4)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md`
Prior gate: milestone-03 (Project Integration) — complete, verifier findings fixed.

## What changed

Active State Capsule (plan §17), Requirement-to-Evidence Ledger (plan §18 with
a material-unverified completion gate), Read Ledger (plan §73), and a
deterministic JIT Context Compiler (plan §25) producing Task Context Capsules.
Advisory/shadow only; nothing prunes anything.

### Exact files

- `src/second_brain/working_set.py` — capsule/requirements/read-ledger (atomic
  JSON writes, enum validation, session-id path safety, sha256 read hashes)
- `src/second_brain/jit.py` — deterministic compiler (Tier 1+2 sources only,
  whole-word lexicon matching, `(none)` markers, never crashes)
- `src/second_brain/cli.py` — `capsule init|update|show`,
  `requirements add|evidence|status|show|check`, `read-ledger record|show`,
  `context compile`; `--home` accepted after every leaf subcommand
- `tests/test_working_set.py` (35 tests), `tests/test_jit.py` (15 tests)
- `outputs/plans/phase4-working-set-design.md`
- `outputs/reports/milestone-04-working-set-jit.md` (this file)

## Requirement-to-evidence (Phase 4 acceptance, plan §100)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Active State Capsule | init/update/show round-trip; enum + type validation; atomic writes; 3 Hypothesis property suites |
| 2 | Requirement Ledger | auto ids, evidence append-only, status transitions; `requirements check` exits 1 while material requirements are unverified (live demo: 3/3 unverified -> rc 1) |
| 3 | JIT Context Compiler | live compile: task + 3 requirements + active state + project current-state + read ledger summary in one 61-line capsule; deterministic body (unit-tested) |
| 4 | Context Capsule | written to outputs/context-capsules/; sources listed in header; relevant to resuming the task (see Dogfooding below) |
| 5 | Read ledger | hash-verified entries (sha256 of real build files), append-only, show |
| 6 | Fresh agent resumes task | capsule + ledger + compile suffice to reconstruct the Phase 5 task state (Dogfooding section) |
| 7 | No key requirement lost | `requirements check` blocks completion until verified; update/merge semantics preserve entries (Hypothesis round-trip tests) |
| 8 | Advisory/shadow, no pruning | no code path mutates agent context or deletes data |

## Commands / checks actually run

```text
ruff check src tests            -> 0 errors
ruff format --check             -> clean
pyright src tests               -> 0 errors
pytest -q                       -> 118 passed (50 new; 3 Hypothesis suites, 60 examples each)
live: capsule init/update, requirements add/check (rc 1 correctly),
      read-ledger record/show, context compile --project "The Second Brain"
```

## Metrics

- Python suite: 118 tests. Hypothesis: 3 suites x 60 examples (round-trip
  validity, unique ids + append-only evidence, session-id acceptance).
- Live capsule: 61 lines covering task/requirements/state/read-ledger — the
  compile is the artifact a fresh agent would read first.

## Deviations

1. `verification` capsule field restricted to JSON scalars (string keys) —
   stricter than "a dict"; keeps JIT rendering compact.
2. `check_requirements` returns material-unverified entries only (the gate
   list); `material_total` counts all material requirements.
3. `updated_at` is auto-managed (never user-settable).
4. Missing ledgers load as empty; corrupt files always raise BrainError.
5. JIT renders corrupt inputs as `(none)` (never crashes); strictness is the
   store's job.
6. Min-update interval from context.toml is not enforced (no write rate issue
   in advisory use; revisit when automation writes the capsule).

## Known risks

- No memory subsystems yet: JIT pulls only project state + lexicon (Tier 1/2).
  Memory-ranked retrieval arrives in Phases 9-10.
- Working-set files live under state/ (gitignored derived data) — they are
  per-session scaffolding, not canonical knowledge; capsules in
  outputs/context-capsules/ are also derived.

## Dogfooding / Self-Hosting (goal mandate)

The Brain is its own first registered project (since Phase 1) and now uses its
own Phase 4 subsystems on the build itself:

- **Working set created for the real Phase 5 task**:
  `state/sessions/build-phase5-rtd/` — capsule with objective + 2 safety
  constraints, 3 material requirements (artifact hashing/collision,
  deterministic distillation, byte-identical expand). `requirements check`
  correctly blocks completion until each gains evidence.
- **Read ledger used on real files** (telemetry.py, SCHEMA.md) with purposes.
- **JIT capsule compiled for the Phase 5 task** with `--project "The Second
  Brain"`: requirements + active state + project current-state in one 61-line
  artifact — the exact resume surface a fresh agent needs.
- Measured so far: no reconstruction needed to resume Phase 5 (objective,
  constraints, requirements all in the capsule). Reread/context-reduction
  numbers accumulate over Phase 5 and are reported in milestone-05.
- Completion-reserve: retrieved-material token accounting starts when memory
  retrieval exists (Phases 9-10); current context 33% — no reserve pressure.
- Self-hosting evidence is supplementary: acceptance above rests on the test
  suite and tool outputs, not on the dogfooding claims.

## Rollback

- Git: revert this milestone's commits.
- Working-set data is derived: delete `state/sessions/*`.

## Next gate

**Phase 5 — Sensory Gateway / RTD** (plan §101): hash-addressed artifact
storage, deterministic distillation (pytest/git/search first), byte-identical
expand; shadow-only substitution gated behind a flag until verified.
