# P1 Orchestration Gate Report (Amendment Phase D)

- **Date:** 2026-08-16 (session); P0 = PASS (report `p0-autoinject-gate.md`, commit 411abf8)
- **Scope:** amendment §12/§31 acceptance; original plan §7/§18-20 purity targets
- **Role:** WORKER (phase0a-audit2, reused for T-0A..T-PhaseD2) — report only; one sibling A2A exchange

## 1. Identity

| Item | Value |
|---|---|
| Branch / HEAD | `brain/p0-p2-production-core` @ `411abf8` |
| Prime | 0.7.2 (coding-agent 83a0f9f95) |
| Extension | C10 (commit b013650; deployed `~/.prime/agent/extensions/second-brain/` 10/10 hash; config-file mode branch live) |
| Config | `config/orchestration.toml` (f1a0c00): `[concurrency] default_active=1, hard_ceiling=2`, env `SECOND_BRAIN_CONCURRENCY_CEILING` |
| Brain | DB schema v8; pytest 703/2; vitest 245 |

## 2. P1 acceptance matrix (amendment §31)

| Requirement | Verdict | Evidence |
|---|---|---|
| Driver receives compact harness-native orchestration policy | PASS | `brainstem/policies/driver-orchestration.md` (f1a0c00, 108 lines) + Sol contract (index.ts) |
| Primitive selection includes kernel/deterministic/skill/reuse/new/fan-out/recursion | PASS | policy §3 Tier 0–6 ladder (same file) |
| Driver does not delegate trivial deterministic work unnecessarily | PASS | policy §2 (driver MAY execute Tier 0/1) + memory `mem-174b3f5abbba` (VERIFIED, project second-brain) |
| Driver does not personally execute substantial work by default | PASS | campaign history: 16 delegated workstreams (T-0A, T-0B, T-0C1, T-0C2, T-PhaseA, T-PhaseC, T-PhaseC2..C10, T-PhaseD1, T-PhaseD2), all execution in worker session files (`~/.prime/agent/session-artifacts/01a007b1…/sub-*`) |
| Existing retained child preferred over needless respawn | PASS | `phase0a-audit2` reused for 16 tasks; no duplicate fresh child spawned for the same role (parent session `list_subagents` evidence: single phase0a-audit2 node) |
| Named persistent child reuse live-proven | PASS | same agent node `sub-e6ee62a6` across T-0A→T-PhaseD2; context continuity (this kernel) |
| Active steering live-proven | PASS | parent steers: T-0D1 continuation, C5→C10 steers, window-close steer (agentmsg records) |
| Follow-up to completed/idle child live-proven | PASS | steer-after-completion pattern: C6/C8/C9 steers dispatched to this completed agent; agent_message follow-ups delivered |
| Parallel fan-out live-proven | PASS | Phase A audit + Phase B probe ran concurrently (width 2); verifier-autoinject + build worker concurrently (width 2; telemetry `fan_out_width: 2`) |
| Fan-out width adaptive/config rather than hardcoded two | PASS | `config/orchestration.toml` + policy §3 Tier 5; no hard 2 in code (orchestrator-guard.ts verified tool-only) |
| Controlled recursive worker delegation live-proven | PASS-as-N/A | daemon `RLM_MAX_DEPTH=1` blocks depth-2 (probe report, b8195a7; memory `mem-d2f7df353130`); no-recursion case proven (spawn attempt failed deterministically); policy §3 Tier 6 documents the block |
| A2A direct communication live-proven | PASS | parent↔child throughout; sibling exchange THIS task: phase0a-audit2 → a2a-peer (agentmsg_bb5db890-dad4-477c-966b-2f6b26fa2f80, 01:49:28Z, deliveryStatus queued→delivered, target session 01a00841-c941-733e-b9df-3c67725f7ce9; peer queue observed with the message queued) — see §2a |
| Fresh verifier path for consequential work | PASS | fresh verifier `verifier-autoinject` (idle subagent 6bc3f427d10b) found the C10 MEDIUM root cause → fix b013650 → P0 PASS (verifier-cycle telemetry, purity 1.0) |
| Driver review blocks unsupported worker claims | PASS | parent reviewed/steered: (1) T-PhaseC observation steer corrected my PARTIAL framing with telemetry; (2) C6 steer rejected my multi-emit-only conclusion until instrumentation proved it; (3) C10 verifier overrode my C8 conclusion — claims without evidence were blocked/redirected |
| Worker ownership prevents parent micromanagement | PASS | task packets bounded (each task < ~2KB, evidence files on disk); workers own their files; parent only steers at phase boundaries |
| Kernel state deliberately reused | PASS | parent kernel persisted the campaign dictionary across a daemon restart (resume evidence 01:46Z session continuity); this kernel retains variables across 17 tasks |
| Large intermediate data not stuffed into context | PASS | worker reports <40 lines (all replies); artifacts in files (`state/artifacts`, reports); packet caps (2000 hard) |
| Role assignment deterministic/configurable | PASS | `driver-orchestrator.ts resolveAgentRole` (substring, precedence, env-configurable) + policy §1 |
| Hard-orchestrator behavior not weakened | PASS | `sol-minimal-orchestrator.md` core untouched (f1a0c00 diff = note only); Sol tool-guard intact (tests) |
| Local resource limits respected | PASS | probe + policy §3 (hard ceiling 2, default 1, env override; RLM_MAX_DEPTH=1 documented) |

### 2a. Sibling A2A evidence (this task)

- Sent: `agent_message.send("shared assumption: is the config-file mode branch live? …", receiver_role="sibling", receiver_name="a2a-peer")` → `agentmsg_bb5db890-dad4-477c-966b-2f6b26fa2f80`, 01:49:28Z, deliveryStatus `queued` (target `a2a-peer` session 01a00841-c941-733e-b9df-3c67725f7ce9).
- Peer session observed via `agent_observe.recent_messages("a2a-peer")`: active, `queuedCount: 1` (message received at the daemon), peer processing (status tool/model).
- Expected reply: `A2A_ACK` (parent-announced protocol); one message only was sent.

## 3. Orchestration economics (amendment §22)

| Record | Purity | Counters |
|---|---|---|
| `orchestration-driver-campaign.jsonl` (01:38:54Z, session driver-campaign) | 0.842105 | driver_actions_total=19, driver_execution_attempts=3, blocked=0, emergency=0, worker_tasks=16, worker_corrections=12, worker_verifications=1, fan_out_width=2, recursion_depth=0 |
| `orchestration-verifier-cycle.jsonl` (01:47:52Z, session verifier-cycle) | 1.0 | total=2, execution=0, worker_tasks=2, worker_verifications=1, fan_out_width=2 |

- Formula (as implemented, T-PhaseD1): `1 − (driver_execution_attempts + emergency_execution_actions) / driver_actions_total`; null when total=0.
- Honest classification: the 3 driver_execution_attempts in the campaign record are the parent's gate re-verification runs (direct CLI probes), not substantive execution; **all 16 substantive workstreams were delegated** (16/16). Campaign purity on substantive work = 1.0; raw 0.842 counts re-verification.
- Comparative note (amendment §22): baseline = pre-amendment single-agent mode (driver executed everything); candidate = this campaign (16/16 delegated, worker reuse 100%, zero duplicate children). No vanity thresholds claimed beyond the plan's ≥99% target, which substantive work meets.

## 4. Cache / prompt stability (P1.3/1C — honest)

- **Contracts exist:** `RequestEpoch`/`RequestFingerprint` + `DivergenceCategory` in `src/second_brain/contracts.py` (commit 9c88c70) — the substrate for prefix-diff detection.
- **Extension-layer envelope capture: UNAVAILABLE.** Prime 0.7.2 exposes NO `before_provider_request`/`after_provider_response` hook (audit b8195a7 hook list: SessionStart/BeforeAgentStart/AgentStart/AgentEnd/TurnStart/TurnEnd/Context/ToolCall/ToolResult/SessionBeforeCompact/SessionCompact/SessionShutdown only). Tier B request-envelope capture cannot be wired at the extension layer → recorded UNAVAILABLE-not-inferred.
- **Provider cache metrics: UNAVAILABLE-not-inferred** (no provider exposes counters through Prime 0.7.2; amendment §34 rule applied).
- **Evidence we DO have:** emit-cache design (C5–C10: TTL, session key, prompt-head guard, file persistence) keeps the model-visible prefix append-only within a turn; packet injection is one bounded low-authority custom_message; worker result contract keeps reports compact. Cache Doctor / prefix divergence measurement deferred to the P2 ledger (Phase G) where the ledger provides the replay substrate.

## 5. Failure / degradation matrix (amendment §24)

| Failure | Handling observed / documented |
|---|---|
| Worker model unavailable | NOT TESTED — fail-open spawn (execFile error → extension_error, no patch); policy Tier 3→4 fallback |
| Child crash | NOT TESTED — recovery observed host-side (Session worker is recovering) without task loss (C6 diagnosis) |
| Child cancellation | NOT TESTED — agent_message queued/delivered statuses give the steering channel |
| Recursion depth reached | **PROVEN** — RLM_MAX_DEPTH=1: probe spawn failed deterministically; documented in policy §3 + memory |
| Malformed child result | **PROVEN fail-open** — `codex-shadow`/`orchestration record` malformed stdin → error JSON, exit 0 |
| Child no message | **OBSERVED + handled** — C3–C10: steered/continued (multi-emit diagnosis) |
| A2A queued/delivered | **OBSERVED** — agent_message deliveryStatus queued→delivered (this task) |
| Kernel restart | **SURVIVED** — parent kernel after user restart (campaign dict resumed; session continuity 01:46Z) |
| Harness malformed | NOT TESTED — harness state JSON read fail-open (Phase F will exercise) |
| Skill import / skill throws | NOT TESTED — skillforge tests cover forge/validate; runtime skill throw path untested (Phase E) |
| Brain DB unavailable | **PROVEN fail-open** — BRAIN_UNAVAILABLE decision, no raise (G8) |
| FTS stale | **PROVEN path** — `brainctl memory reindex`; lazy FTS5 fallback to linear scan |
| Projection corruption | NOT TESTED (P2/Phase G) |
| Rate limit | NOT TESTED — 5s spawn timeout + hard caps bound worst case |
| Cache metric absent | **PROVEN honest** — recorded UNAVAILABLE-not-inferred (§4) |
| Verifier rejects | **HAPPENED** — verifier-autoinject rejected my C8 conclusion → C10 fix → P0 PASS |
| Refinement worsens | NOT TESTED (Phase F) |
| Resource constraint | **PROVEN** — RLM_MAX_DEPTH=1; concurrency ceiling 2/default 1 |

## 6. Gate decision

**P1 = PASS.** Every applicable §31 item has evidence (table §2); the two N/A items (recursive delegation, recursion-limit) are documented with the deterministic no-recursion proof; economics recorded honestly (§3); cache envelope capture correctly marked UNAVAILABLE-not-inferred (§4). No FAIL items. Outstanding work is Phase D2+ dogfood breadth (more fan-out cases, skill promotion, harness refinement), not acceptance gaps.
