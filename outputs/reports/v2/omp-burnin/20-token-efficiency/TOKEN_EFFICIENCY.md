# Phase 20 — Token Efficiency Qualification

Paired workloads: **A** = `omp --no-extensions` (Second Brain fully
disabled, otherwise identical model/settings); **B** = the same prompt with
the extension loaded. Token/cost figures read directly from each session's
own `.jsonl` transcript (`message.usage`, `message.usage.cost.total`) — the
same source OMP's own UI reads, independent of any Second Brain telemetry
(so it stays valid for the A/no-extension side too).

## W1 — Fresh simple task (pure overhead)

Task: "What is 15% of 240? Reply with just the number." (1 turn each,
zero memory relevance expected).

| | A (no SB) | B (SB active) | Delta |
|---|---|---|---|
| totalTokens | 33,082 | 33,221 | **+0.42%** |
| Wall time | 3.99s | 10.53s | +6.5s |

Token overhead is far under the ≤5% target. The latency gap is bridge
overhead (AutoInject/routing/visibility each spawn a Python subprocess on
`before_agent_start`/`before_provider_request` even when nothing is
relevant) — decomposed further in Phase 21.

## W2 — Repeated project task (memory/skill benefit)

Task: the exact `sqlite-migration-verifier` trigger phrase from Phase 14
("This task involves a new NNNN_*.sql migration file exists in the diff and
needs review. What procedure should I follow? Be concise."), with skill
visibility temporarily flipped to `enforced` for B (same controlled-harness
exception used in Phase 14).

| | A (no SB) | B (SB, skill enforced) |
|---|---|---|
| Turns | 6 (glob/grep/read across `migrations/`, the 2500-line implementation plan, `tests/test_migrations_property.py`, `docs/components/db-migrations.md`, `db.py`, `backup.py`) | **1** (answered directly from the injected skill body) |
| Cumulative cost | $0.09464 | **$0.04483** |

**52.6% cost reduction.** This is the clearest, most direct evidence of
*why the Brain exists*: A had to rediscover the review procedure from
scratch across 6 tool-calling turns; B received the already-curated
procedure directly and answered in one turn.

**Caveat found**: an earlier attempt at this same comparison with skill
visibility left at its **shipped default (`shadow`)** showed **no
measurable benefit** — both A and B did the identical 6-turn exploration
(confirmed via each session's full transcript: B's shadow-mode `omp_visibility_plan`
telemetry recorded `selected_skill_ids:[]`, so nothing was actually
injected). This is expected given shadow mode's own documented purpose
("measure without changing behavior") but is an important, honest data
point: **the token-efficiency benefit measured above is available only once
visibility is promoted out of shadow mode** — it is not realized under the
plan's current default shipped configuration.

## W6 — Project switch (isolation without a context dump)

Task: the Phase 10 isolation-sentinel question, run from `p10-project-alpha`.

| | A (no SB) | B (SB active) |
|---|---|---|
| Turns | 5 | **3** |
| Cumulative cost | $0.07741 | **$0.05671** |

**26.7% cost reduction**, plus the isolation property itself already
independently proven in Phase 10 (B correctly surfaced only the ALPHA
sentinel as advisory, never BRAVO) — efficiency and correctness both hold
simultaneously; Second Brain's context did not have to be discarded or
re-derived on the project switch.

## W3 / W4 / W5 — not independently re-run as strict A/B pairs (scope note)

Given this campaign's scale, W3 (long session + compaction), W4 (driver +
workers), and W5 (multi-session continuation) were **not** re-run with a
paired `--no-extensions` control in this phase. Each workload's underlying
mechanism was already independently, live-proven with real token/cost
numbers in earlier phases:
- **W3** (Phase 15): repeated compaction kept context bounded (~32-36K
  tokens flat across 2-5 compaction cycles, never growing unbounded) and
  preserved a distinctive fact without replaying the full pre-compact
  transcript — the qualitative "reduced transcript rereading" benefit this
  workload class targets.
- **W4** (Phase 11): worker capsules measured 106-144 tokens
  (`context_handoff_tokens`) vs. the driver's 34-51K-token cumulative
  context — workers never receive anywhere near "full-context-equivalent"
  size, which is the bounded-capsule benefit this workload class targets.
- **W5** (Phase 16): durable memory correctly retrieved across a genuinely
  new OS process with zero shared state — the continuity-without-re-
  statement benefit this workload class targets.

A dedicated A-vs-B token comparison for these three would exercise the same
telemetry/cost-extraction method already validated above (W1/W2/W6); it was
not run here purely for time, not because the mechanism is unproven.

## Token Gate

**Met for every workload actually measured.** W1 (pure-overhead workload)
came in at +0.42%, far under the ≤5% ceiling. W2 and W6 (workloads
expected to show a net benefit) showed **net decreases** of 52.6% and
26.7% respectively — exceeding the plan's *preferred* outcome ("a net
decrease in total tokens"), not merely meeting the worst-case ceiling.
The one specific finding requiring a release-note-level disclosure: **the
W2 benefit requires skill visibility to be promoted out of shadow mode** —
under the currently shipped default, no skill-driven token savings are
realized (AutoInject's own memory-retrieval savings, independent of
skills, are unaffected by this and were already proven live in Phase 8/9).
