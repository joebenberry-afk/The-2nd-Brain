# Phase 4 — Working Set / JIT Context (design)

Spec: plan §100 (Working Set / JIT Context). Advisory/shadow only. No pruning.

## Components

1. **Active State Capsule** (plan §17 schema) — `state/sessions/<session-id>/active-state.json`
   - fields: objective, task_mode, risk, constraints[], confirmed_facts[],
     current_hypotheses[], decisions_this_session[], files_touched[],
     open_questions[], verification{}, next_action, brain_refs[], artifact_refs[],
     updated_at
   - updated at checkpoints, not per token
   - brainctl: `capsule init <session-id>`, `capsule update`, `capsule show`
2. **Requirement Ledger** (plan §18) — `state/sessions/<session-id>/requirements.json`
   - entries: id, requirement, importance, evidence[], status
     (unverified/partially_verified/verified/not_applicable/blocked)
   - material requirement remaining `unverified` blocks completion
   - brainctl: `requirements add <session-id> <text> --id --importance`,
     `requirements evidence <id> <text>`, `requirements status <id> <status>`,
     `requirements show`
3. **Read ledger** (plan §73) — `state/sessions/<session-id>/read-ledger.json`
   - rows: path, hash, range, purpose, turn, artifact
   - recorded via `brainctl read-ledger record ...`; Prime extension hook in Phase 5+
4. **JIT Context Compiler** (plan §25) — `brainctl context compile <session-id> <task>`
   - deterministic selection: requirement text (Tier 1), active-state capsule
     (Tier 1), project current-state + lexicon matches + recent decisions
     (Tier 2), nothing else (memories arrive in Phases 9-10)
   - output: Task Context Capsule in `outputs/context-capsules/<session-id>-<slug>.md`
     with a header noting freshness and sources
5. **Invariants**
   - no key requirement lost across capsule updates (Hypothesis)
   - compile is deterministic for identical inputs (no timestamps beyond one
     "compiled_at" field excluded from comparison)
   - capsule/ledger JSON always schema-valid or command refuses to write

## Delegation

Implement via a reused idle worker (per user policy: no new sub-agents) with an
exact spec; parent integrates and gates. On hold until Phase 3 merges.
