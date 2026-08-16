# Second Brain Core Rule for Antigravity

This workspace is integrated with The Second Brain.

## Operating Principles

1. **Source Authority**: Current repository source, verified tests, and live tool evidence strictly outrank Second Brain memory. If memory contradicts source, live source wins.
2. **Targeted Retrieval**: Retrieve relevant context on-demand via the Second Brain adapter rather than loading whole-memory dumps into the context window.
3. **Single Source of Truth**: Do not create parallel memory databases, vector indexes, or policy stores inside Antigravity. Reuse the existing Second Brain store and lifecycle.
4. **Lifecycle Writeback**: Durable project knowledge, verified decisions, and reusable learnings must be recorded through the canonical Second Brain writeback lifecycle (`brainctl memory add` / `brainctl autoinject writeback`).
5. **Requirement & STOP Discipline**: Respect the Requirement Ledger (`brainctl requirements`). When all material requirements are proven and verified with no remaining risk gates, STOP. Do not perform speculative refactors or unrequested cleanups.
