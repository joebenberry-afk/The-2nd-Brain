# P0-P2 Phase F — Continual Harness refinement record

## Refinement cycle (amendment §16)

- **Trigger:** P0-P2 harness amendment (user-authoritative): adaptive fan-out replaces the hard
  2-worker ceiling; driver MAY execute trivial deterministic work; fresh-verifier role; sibling A2A;
  child recursion is daemon-blocked (RLM_MAX_DEPTH=1).
- **Classified pattern:** the global delegation policy (v3) still encoded the pre-amendment rules
  ("keep at most two children active at once" as a universal cap; no driver trivial-work allowance;
  no verifier role; no recursion note) — stale vs. the amendment and vs. measured campaign behavior.
- **Evidence:** amendment file §12/§31; live campaign practice on brain/p0-p2-production-core:
  adaptive fan-out width 2 used when justified; retained worker reused for 57.1% of task packets;
  fresh verifier caught a MEDIUM root-cause bug that 8 observations missed (C10 -> P0 PASS);
  RLM_MAX_DEPTH=1 proven by capability probe (Phase B).
- **Applied change:** `update_prompt_note(luna_delegation_orchestrator_policy, v3 -> v4)` —
  adaptive concurrency (default 1 active worker, hard ceiling 2 on this machine, config/env adjustable),
  driver trivial deterministic work allowed, fresh-verifier directive, sibling A2A allowance,
  recursion config-limit note. DeepSeek-v4-flash default and reuse-preference retained.
- **Rollback proof (simulated, local scope):** created local test entry `f_rollback_proof_test` v1 ->
  updated to v2 -> restored to original text (v3 entry version) -> verified content restored -> deleted.
  Rollback mechanics proven; the global base system prompt itself was NOT mutated (immutable).
- **Expected outcome:** future sessions orchestrate per the amendment without stale policy friction.
- **Observed outcome:** policy v4 active; subsequent orchestration continued without conflict.
- **Decision:** KEEP.
- **Refinement event id:** refine_0007 (global refinement history).

## Brain-vs-harness boundary verification (amendment §26)

- Project truth (architecture, decisions, implementation state) -> Second Brain canonical stores
  (memory/, decisions/, projects/ + derived SQLite/index) — e.g., the 5 seeded campaign memories
  and the writeback candidate mem-771d74aaa3fd.
- Operating lessons (how to delegate/orchestrate) -> Continual Harness (this policy v4, lean
  orchestration note, reuse preference) — no project facts placed in harness memory.
- The two loops were exercised separately and never merged into one bucket.
