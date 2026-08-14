# JIT Context Compiler

## Purpose
Compile a deterministic, dependency-free Task Context Capsule from the working set + optional project state so an agent resumes with relevant context only (plan §25, §100; Phase 4).

## Problem it solves
Resuming agents either re-read the whole repo (expensive) or get nothing; the capsule is the cheap deterministic middle ground.

## Responsibilities
- `compile_context(home, session_id, task, project_key=None)` → `outputs/context-capsules/<session-id>-<slug>.md`.
- Header: title + `compiled_at` (only non-deterministic field) + `sources:`.
- Body sections fixed order: `# Task`; `# Requirements` (id [importance/status] text + indented evidence); `# Active State` (compact, empty lists omitted); `# Project State` (projects/<id>/current-state.md verbatim via `registry.get_project`); `# Lexicon Matches` (whole-word case-insensitive match of `## <term>` headings; "No matching terms."); `# Read Ledger Summary` (count + last 10 path/purpose).
- `make_slug`: lowercase, non-alnum → '-', max 40, fallback 'task'.
- Missing/corrupt inputs → `(none)` markers, never crashes.

## Non-responsibilities
No model/network; no memories (Phases 9-10); no pruning of the working set.

## Inputs
`home`, session_id, task, optional project_key; the three session JSON files; optional projects/<id>/ files.

## Outputs
One markdown capsule per compile (same slug overwritten deterministically).

## State ownership
None (reads working set; writes derived outputs/context-capsules).

## Invariants
Body identical for identical inputs (compiled_at header excluded from comparison); fixed section order; whole-word lexicon matching (no "cap"→"capsule" false hits); never raises on missing state.

## Interactions
Reads `working_set` + `registry`; `brainctl context compile`; Phase 7 intent verifier uses fresh context.

## Failure behavior
Non-string task → BrainError; corrupt files/unknown project → `(none)` sections.

## Verification
`tests/test_jit.py` (15): body determinism, header sources, slug rules, section renderings, no-state compile, lexicon +/-/whole-word, read-ledger last-10, corrupt-capsule degrade.

## Known limitations
Lexicon matches alnum words only; project state verbatim (may be long); no tier ranking.

## Future extension
Memory retrieval (Tier 2+, Phases 9-10); context-pressure trimming (plan §72).

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #9 (completion-reserve: retrieval must not consume task-critical context).

## Relevant tests
`tests/test_jit.py`, `tests/test_working_set.py`.
