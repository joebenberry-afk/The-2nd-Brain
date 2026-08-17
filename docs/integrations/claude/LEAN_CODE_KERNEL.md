# Lean Code — Runtime Kernel

Canonical source: [`skills/candidates/lean-code/SKILL.md`](../../../skills/candidates/lean-code/SKILL.md)
→ `# Runtime Kernel` section. This file mirrors that section verbatim so
Claude Code's native `@import` can load it at session start. No generator
exists yet (P1.1 scope) — if the canonical section changes, update this
mirror by hand in the same commit.

LEAN CODE: deliver the smallest complete, correct, maintainable change that proves the requested value. Reuse order: config/no-code -> existing behavior -> extend/compose -> stdlib/platform -> installed dependency -> small local code -> new abstraction/tool -> new dependency/service. New abstractions/tools require current need, a stable contract, and net complexity/token reduction; duplication may remain until the pattern is proven. Protect correctness, security, integrity, compatibility, readability, required tests/observability. Search/locate first; read exact evidence; expand only to resolve material uncertainty. Effort and verification scale with risk/reversibility. A small preparatory refactor is allowed only when it directly simplifies the current change. When material requirements are proven, STOP; record unrelated cleanup as simplification debt.
