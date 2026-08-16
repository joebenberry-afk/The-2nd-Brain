# P0–P2 Economics & Skill Evaluation (Phase E + Phase H)

- **Date:** 2026-08-16 · branch `brain/p0-p2-production-core` @ `1967562`
- **Sources:** telemetry/agent-performance/*.jsonl (live), orchestration-*.jsonl, deliveries table, session artifacts, reports dir. No invented numbers; unavailable metrics marked UNAVAILABLE-not-inferred.

## Part E — Skills evaluation (amendment §13/§32)

Promotion rule: repeated enough times · clear inputs/outputs · deterministic code replaces model reasoning · trust understood · materially reduces prompt/tool overhead.

| Candidate procedure | Campaign executions (evidence) | Deterministic implementation already exists? | Verdict |
|---|---|---|---|
| (a) AutoInject pipeline (`brainctl autoinject shadow` / codex-shadow) | **101 retrieval attempts** (94 or_fallback, 7 legacy) + 30 packet deliveries + 71 no-injections across live mirrors + probes | YES — `autoinject.py` + `cli.py` + `autoinject.ts` ARE the deterministic implementation; zero model reasoning remains in the procedure | **NOT PROMOTED** — the brainctl subcommand already replaces the reasoning |
| (b) Ledger procedures (append/verify/search/segment/rehydrate) | **137-event live mirror-check + ~15 CLI smoke runs** (G1–G6-fix) + full test suite usage | YES — `ledger.py` + `ledger-mirror.ts` implement all of it deterministically | **NOT PROMOTED** — CLI subcommands already are the skill |
| (c) Orchestration record | **2 records** (driver-campaign, verifier-cycle) | YES — `brainctl orchestration record` computes purity deterministically | **NOT PROMOTED** — already a CLI command |
| (d) Gate-report production | **6 reports** (0A audit, gap matrix, P0 gate, P1 gate, dogfood evidence, P2 gate) + this one | NO — report writing still requires model synthesis of evidence | **BORDERLINE** — but no stable single input/output schema yet (each gate differs); promotion deferred until the final proof report repeats the pattern (candidate for `brain_proof_bundle` in Phase I/J) |

**Verifier note:** `brain_query` / `brain_reindex` / `brain_orchestration_report` candidates already exist as `brainctl` subcommands (`memory search`, `memory reindex`, `orchestration record`) — promoting them as NEW Python-backed skills would duplicate existing deterministic code. Evidence of "no repeated model reasoning left to replace": 0/4 candidates require model reasoning inside the procedure.

## Part H — Economics data (amendment §21/§22/§34)

| Metric | Value | Source |
|---|---|---|
| Worker spawn count (fresh children) | **16 child sessions** under parent (incl. phase0a-audit2, observers 1–9, verifier-autoinject, a2a-peer, …) | session-artifacts/sub-* (16 dirs) |
| Worker reuse rate | **57.1% task-weighted**: retained worker phase0a-audit2 served **20 task packets** of 35 total (25 task packets to me + 15 fresh children ≈ 40 task deliveries; 20/35 ≈ 57%) — 0 duplicate fresh children for the same role | transcript task count (25 to phase0a-audit2) + 16 sub-dirs |
| Max parallel fan-out width | **2** (telemetry fan_out_width:2 in both orchestration records; Phase A+B concurrent) | orchestration-*.jsonl |
| Recursion depth | **0** (RLM_MAX_DEPTH=1 config-blocked; no depth-2 ever spawned) | daemon config + memory mem-d2f7df353130 |
| A2A message count | **1 sibling exchange** (a2a-peer, 1 message + A2A_ACK); parent↔child: **94 message markers** in the retained worker transcript (tasks + steers + follow-ups) | agent artifacts |
| Steer count | **5 explicit STEER messages** + 25 task packets (steers within-task follow-ups) | transcript |
| Follow-up count (post-completion) | ≥8 (window-close steer, 3 re-sync steers, C4/C6/C8/C9 diagnosis steers to the completed agent) | transcript |
| Context capsule / packet sizes | packet_tokens n=30: **p50 = 498, p95 = 735** (min 219, max 735; hard cap 2000) | autoinject_shadow_decision records |
| Brain retrieval accepted | **30 packets delivered** (brain_packet_delivered) | telemetry |
| Brain retrieval ignored | **71 NO_INJECTION** decisions + 101 attempts total (accepted 30/101 ≈ 29.7%) | telemetry |
| Delivery ledger rows | **112 deliveries** (canonical db, incl. campaign + probe lineages) | db |
| Purge receipts | 0 (no live purge run; purge path fully tested) | db |
| Delegation purity records | **2**: driver-campaign **0.842105** (19 actions / 3 gate re-verification runs; substantive 16/16 delegated → 1.0) · verifier-cycle **1.0** | orchestration-*.jsonl |
| Cached vs uncached input tokens | **UNAVAILABLE-not-inferred** — campaign audit originally marked this unavailable; P3 reconciliation against the installed v0.7.2 runtime proved the hook exists; the earlier local ambient type/audit surface was incomplete. Historical campaign measurements remain unavailable because they were not captured at the time. | P1 gate §4 |
| Output tokens / cost per accepted change | **UNAVAILABLE-not-inferred** — same reconciliation note as above: the installed v0.7.2 runtime does expose provider usage counters (P3 reconciliation); they were not captured during the P0–P2 campaign. | same |
| Root vs child token attribution | **UNAVAILABLE-not-inferred** | same |
| Duplicate investigation count | **0** measured (no duplicate child for the same role; dedupe tests) | transcripts |
| Skill invocation count | 0 new skills promoted (see Part E) | — |

### Comparative note (amendment §22)
Baseline = pre-amendment single-agent execution (driver executed everything). Candidate = this campaign: 16/16 substantive workstreams delegated, retained worker at 57% task share, zero duplicate children, fan-out 2 used once, purity 1.0 on substantive work. No vanity thresholds claimed.

## Honest limitations
- Packet-token percentiles are over the 30 delivered packets only (observers' 735-token packets dominate p95).
- "Worker reuse rate" is task-weighted from transcript counts; daemon-worker dirs (33) include pre-campaign history and are NOT counted.
- Provider-side economics remain fully UNAVAILABLE — never inferred.
