---
name: lean-code
status: candidate
version: 1
created_at: 2026-08-16T06:38:45.694425+00:00
---

# Purpose

Lean Code minimizes total engineering + agent cost subject to correctness. It is the minimum sufficient change: the smallest complete, correct, maintainable change that delivers the requested value.

# Positive Triggers

- implementation
- bug fix
- refactor required to deliver current behavior
- adding or changing tools
- adding dependencies
- repository modification
- tests for changed behavior
- agent implementation work

# Negative Triggers

- pure explanation
- pure research with no requested code change
- user explicitly requests exploratory prototypes where disposable breadth is the value
- security or emergency procedure whose explicit protocol overrides Lean
- task whose acceptance condition explicitly requires exhaustive implementation

# Inputs

- current user goal
- Requirement Ledger (brainctl requirements)
- Active State Capsule (brainctl capsule)
- exact repository evidence
- current diff
- risk result (brainctl risk assess)
- existing project resources, tools, and dependencies

# Procedure

1. Define observable acceptance.
2. Inspect existing resources first.
3. Use the reuse ladder: config/no-code before code; existing behavior before new code; extend/compose before new modules.
4. Choose the minimum complete change that satisfies acceptance.
5. Use exact evidence (current source, tests, and diff) — verify, do not assume.
6. Apply the new-tool, dependency, and abstraction gates: only for a current need, with a stable contract, when net complexity and token cost decrease.
7. Allow scoped preparatory simplification only when the current change requires it.
8. Verify proportionally to risk and reversibility.
9. Check that material requirements are verified before stopping.
10. Stop at acceptance; record unrelated cleanup as simplification debt, do not perform it.

# Tools

Do not invent tools; use existing primitives:

- RepoWise or direct source inspection
- git
- project tests, typechecker, linter
- brainctl capsule
- brainctl requirements
- brainctl read-ledger
- brainctl risk assess
- brainctl verify build-brief
- existing project tools and commands

# Safety

- Protect correctness, security, integrity, compatibility, and readability.
- Never modify protected or constitution-governed files as a side effect of unrelated change.
- Never introduce credentials or secrets; never add a dependency or tool to satisfy a hypothetical future need.
- Preserve existing behavior outside the requested scope; do not perform unrelated cleanup.
- A high-risk or hard-to-reverse change gets proportionally stronger verification, not faster delivery.

# Verification

- Task acceptance is demonstrated with exact evidence.
- No material requirement is left unverified.
- No unnecessary dependency, tool, or abstraction was added.
- Test depth is risk-appropriate.
- No unrelated scope entered the change.
- No P0-P2 regression: the existing test suite and checks still pass for the touched surface.

# Output

Keep output concise:

```text
implemented result
key reuse decision (only if material)
tests/evidence
remaining risk (only if material)
```

Do not narrate every Lean decision.

# References

- Second Brain P3 Lean Code One-Shot Plan v2 (reuse ladder, gates, stop rule): C:\Users\assas\Downloads\Second_Brain_P3_Lean_Code_One_Shot_Plan_v2_ACTIVE.md
- episode success-20260814-2c753d99 (isolated exploration reduced solve-session tool calls; exploration discipline)
- episode correction-20260814-a6299e22 (reported evidence must match independent collection; exact evidence)
- git:26f9d45 P3-B minimal-diff economics instrumentation
- git:64e0661 P3-A probe retirement (stop and retire, do not extend)
- git:6a2c7a0 P3-A reuse audit (reuse before new machinery)

# Runtime Kernel

LEAN CODE: deliver the smallest complete, correct, maintainable change that proves the requested value. Reuse order: config/no-code -> existing behavior -> extend/compose -> stdlib/platform -> installed dependency -> small local code -> new abstraction/tool -> new dependency/service. New abstractions/tools require current need, a stable contract, and net complexity/token reduction; duplication may remain until the pattern is proven. Protect correctness, security, integrity, compatibility, readability, required tests/observability. Search/locate first; read exact evidence; expand only to resolve material uncertainty. Effort and verification scale with risk/reversibility. A small preparatory refactor is allowed only when it directly simplifies the current change. When material requirements are proven, STOP; record unrelated cleanup as simplification debt.

# Nudge

LEAN NUDGE: make the minimum sufficient change to meet acceptance; reuse existing code, avoid new abstractions or dependencies, and stop at acceptance.
