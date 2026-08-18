# Second Brain v1.0 — Token Baseline & Local Token Efficiency Fabric Gap Audit

**Phase 0 — plan §2.4/§2.5, §3-§10, §24 readiness** • Evidence-based • worker: v1-phase0-tokenfabric
Branch: `brain/v1-token-efficient` • Worktree: `C:/Users/assas/Documents/The-Second-Brain-v1`
Plan: `second_brain_v1_0_token_efficient_one_shot_deepseek_plan.md`

This report supersedes/consolidates the prior draft of this file and folds in the
Local Token Efficiency Fabric gap analysis already produced in this worktree
(`outputs/reports/v1-arch-phase-gap-map.md`, 2026-08-18) plus direct citation checks
performed by this worker. No claim below is inferred from filename/module existence
alone; every EXISTS/ABSENT verdict cites file:line or explicit grep evidence.

**Prior-work note**: at the time this report was written, this worktree already
contained uncommitted work from a concurrent campaign session (`outputs/reports/v1-campaign-state.md`
DRIVER ledger, `outputs/reports/v1-arch-phase-gap-map.md`, `v1-existing-primitives-map.md`,
`v1-roadmap-*.md`, `v1-security-gate-audit.md`, `v1-test-integrity-audit.md`,
`v1-dogfood-campaign-tokens.md`, and a **partially implemented** `src/second_brain/governor.py`
+ `config/governor.toml` + `tests/test_governor.py`, all uncommitted). This report treats that
state as current-repo ground truth per AGENTS.md ("current repo/tests outrank memory") and
cites it, but only commits its own deliverable (`v1-token-baseline.md`) to avoid disturbing
in-flight work owned by that campaign.

---

## Part 1 — Local Token Efficiency Fabric: existing primitives vs genuine gaps (plan §3-§10)

Condensed from `outputs/reports/v1-arch-phase-gap-map.md` (10 EXISTS-PARTIAL, 7 ABSENT,
0 EXISTS-USABLE across 17 numbered mechanisms), cross-checked against source for the
files this task explicitly asked to verify (`telemetry.py`, `monitor.py`, `ledger.py`,
`working_set.py`, `jit.py`, `semantic.py`, `router.py`, `scout.py`).

| Plan section | Mechanism | Verdict | Evidence (file:line) | Genuine gap |
|---|---|---|---|---|
| §4 Token Governor | per-host/session/task/agent/feature token tracking | **ABSENT** (implementation started, uncommitted) | `telemetry.py` aggregates `input_tokens/output_tokens/cache_read_tokens/cache_write_tokens/total_tokens/cost_total` only (SCHEMA.md line 36: `assistant_usage` event). No `context_peak`, `brain_injected_tokens`, `worker_tokens`, `driver_tokens`, `compaction_tokens`, `action_cache_hits/misses`, `session_page_faults/evictions` fields anywhere in schema or code (grep across `src/second_brain/*.py` and `brainstem/telemetry/SCHEMA.md`: zero hits). **New, uncommitted**: `src/second_brain/governor.py` (439 LOC) + `config/governor.toml` + `tests/test_governor.py` (506 LOC) implement `SessionTokens` aggregation reading existing telemetry with an explicit "field absent ⇒ None, never 0" honesty rule — this is real Phase-1 work already begun in this worktree but not yet committed/integrated with the roadmap items above (worker/driver/compaction/action-cache/paging counters are not yet in `governor.py` either). | Context-peak/worker/driver/compaction/action-cache/paging counters; full per-feature attribution wiring into `governor.py`. |
| §4 Feature attribution + ablation harness | switchable per-mechanism evaluation | **ABSENT** | `config/governor.toml` (new, uncommitted) declares a `[features]` flag block (`brain_core`, `autoinject`, `observation_firewall`, `context_paging`, `action_cache`, `delta_sync`, `structural_retrieval`, `semantic_vectors`, `tool_working_set`, `skill_lazy_loading`, `prompt_compression`) with env-var override precedence — this is the flag *scaffold*, not an ablation harness (no code path yet reads these flags to gate feature execution, and no task-suite runner switches them). | An actual ablation harness that runs a task suite once per profile and gates real code paths on the flags. |
| §4 Token gate semantics (ROI classes) | POSITIVE/NEUTRAL/NEGATIVE_ROI/INSUFFICIENT_EVIDENCE | **ABSENT** | No ROI classification logic in `governor.py` or elsewhere (grep for `POSITIVE_ROI`/`NEGATIVE_ROI` returns zero hits repo-wide). | Full ROI classifier + enforcement that a NEGATIVE_ROI feature cannot ship always-on. |
| §5 Observation Firewall — reducer registry | deterministic reducers for noisy tool output | **EXISTS-PARTIAL** | `src/second_brain/artifacts.py` (316 LOC) implements content-addressed distillation/backing-store logic; `brainstem/prime-extension/src/rtd.ts` implements a distillation pipeline wired to the `tool_result` hook (RTD = Reversible Tool Distillation, plan P3.3, already PROVEN per P3 campaign evidence — see Part 2). Coverage is not the full reducer-class list in plan §5.1 (pytest/compiler/git/grep/JSON/process-logs/stack-trace/package-manager/doctor-output reducers individually); RTD's distillation heuristic is size/threshold-based, not per-output-type structured (summary + high_value_sections + error_count + reduction_ratio + lossless_retrieval_handle per plan §5.1). | Per-output-type structured reducers (pytest, compiler, git, grep, JSON, stack trace, doctor) with the plan's explicit output contract; extend `rtd.ts` + `artifacts.py`. |
| §5 Raw result backing store | SHA-256, dedupe, bounded retention, retrieval-by-ref | **EXISTS-PARTIAL** | `artifacts.py` + `ledger.py` (1701 LOC) implement content-addressed object storage with SHA-256 identity and exact retrieval by ref (ledger.py docstring: "object files are content-addressed and digest-verified on read"). No confirmed TTL/bounded-retention enforcement or object-size caps specific to tool-output backing (ledger retention is governed by `config/session-retention.toml`, a different mechanism for session data, not verified to apply to RTD/artifact objects specifically). | Bounded retention/TTL and size caps scoped to raw tool-output objects; compression for large objects. |
| §6 Context Virtual Memory — transient session objects | findings/decisions/blockers as session objects | **EXISTS-PARTIAL** | `working_set.py` (462 LOC) implements the Active State Capsule, requirement ledger, and read ledger under `state/sessions/<id>/` (docstring lines 1-11) — this already stores findings/decisions/blockers/unresolved-work as structured JSON, matching plan §6.1-6.2 intent closely. | Formal guarantee that routine chatter is never persisted (currently a convention, not an enforced boundary). |
| §6 Context residency states | STORED/RESIDENT/EVICTED/FAULTED_IN/SUPERSEDED/PURGED | **ABSENT** | `working_set.py` tracks resident/evicted-style state informally (no `FAULTED_IN`/`SUPERSEDED`/`PURGED` enum found via grep for these exact tokens in `src/second_brain/*.py`: zero hits). | The explicit 6-state residency machine, tracked by session/branch/segment/recipient. |
| §6 Context paging | retrieve-by-ref, cascading fallback | **EXISTS-PARTIAL** | `jit.py` (215 LOC) compiles the working set into one deterministic markdown capsule ("no model, no network: identical inputs produce an identical body" — docstring); `semantic.py` (1592 LOC) provides FTS5 lookup as a fallback layer. No unified "exact ref → metadata/time/type → FTS5 → semantic" cascade implemented as one paging function; the pieces exist separately in `jit.py` and `semantic.py`. | A single paging entrypoint that enforces the plan's exact fallback order. |
| §6 Admission/eviction policy (scored) | pinned/recency/frequency/verification/size scoring | **ABSENT** | `working_set.py` has ad hoc eviction paths but no deterministic scoring function combining pinned+recency+frequency+verification_value+size (grep for a combined scoring function: none found). | The explicit scoring function and enforcement of eviction order. |
| §7 Proof-Carrying Action Cache | action identity via declared dependency hashes | **EXISTS-PARTIAL** | `autoinject.py` (1140 LOC) implements request-fingerprint-based caching with hash-based validity checking (per `v1-arch-phase-gap-map.md` Mech-7.1/7.3, confirmed pattern present); `artifacts.py` provides content-addressed storage usable as the result-artifact layer. This is scoped to AutoInject packet delivery, not a general-purpose cross-action cache (plan §7.2's example actions — locate symbol, analyze test failure, derive module map — have no dedicated cache path). | The general `action_kind` + `normalized_task` + declared-dependency-hash schema in plan §7.1, reusable across arbitrary repeated operations, not just AutoInject packets. |
| §8 Delta sync | exact-unchanged reuse + changed-file delta | **EXISTS-PARTIAL** | `scout.py` (403 LOC) includes deterministic git-diff/state pre-pass logic (docstring: "deterministic cheap pre-pass (git state, ... term match candidates via ripgrep)"); `working_set.py`'s read ledger records file reads (docstring: "read-ledger.json — append-only record of file reads", plan §73). No formalized "hash H unchanged ⇒ offer prior understanding without reread" protocol connecting the read ledger to an actual reread-avoidance decision — the read ledger records reads but nothing consumes it to skip a reread. | The read-ledger-driven reread-avoidance decision path; changed-file delta exposure via git diff. |
| §9 Hybrid retrieval cascade | metadata → ID → FTS5 → structure → semantic | **EXISTS-PARTIAL** | `semantic.py:1379` `search_memories()` already implements a retrieval cascade with FTS5 as first-class (docstring lines 1-14: "Manual curation first"; evidence grades ordered INFERRED<OBSERVED<TESTED<VERIFIED). FTS5/BM25 ranking, hard filters, dedupe, and bounded results already exist per `v1-arch-phase-gap-map.md` citation. `config/retrieval.toml` is read live by `semantic.py:1094` per campaign-state DRIVER-verified fact, though stale TODO comments at `semantic.py:974/1033` claim hardcoded weights (unresolved discrepancy noted by prior audit, not re-verified by this worker). | Explicit cascade-order enforcement/validation; snippet extraction to return smallest relevant excerpt instead of full documents (plan §9.2). |
| §9 Semantic/vector fallback | local CPU-only, ROI-gated | **EXISTS-PARTIAL** | `semantic.py` implements a local embedding/vector fallback (no external API dependency per prior audit). No ablation evidence exists proving its token/latency/CPU ROI per plan §9.3's explicit requirement ("prove memory/CPU/latency/token ROI") — see Part 3 (§24 readiness), no ablation has ever been run. | Ablation-proven ROI before default-on; dedupe/diversity scoring (plan §9.4); guard against re-embedding unchanged content. |
| §10 Tool Working Set — JIT skill/tool loading | compact descriptors at session start, full instructions JIT | **ABSENT** | `router.py` (331 LOC) is a *different* mechanism: it scores and selects Brain-internal shadow-skill promotion candidates (docstring: "Ranks shadow skills... by a deterministic score"), not host-exposed LLM tool/skill schema activation. Grep for `preload`/`lazy`/`jit`/`descriptor` in `router.py` + `skillforge.py`: zero hits. No evidence any Prime/host tool-schema is deferred — all skills/tools appear host-preloaded at session start. | The actual host-tool-schema deferred-loading integration (Prime 0.7.3 active-tool APIs per plan §10.1, gated on compatibility qualification first). |
| §10 Batched local query engine | one Brain call combining deterministic ops | **ABSENT** | No combined-query CLI/API found (`cli.py`, 3044 LOC, has many individual subcommands — `memory search`, `orchestration record`, etc. — each a separate round trip; no evidence of a single call combining project resolution + repo state + FTS + hash + cache lookup + symbol + action-cache + memory refs). | The batched query surface (Python API + CLI + stdio MCP transport per plan §10.4). |

**Net assessment**: 0 of 17 numbered mechanisms are EXISTS-USABLE (fully matching the plan's
contract today). 10 are EXISTS-PARTIAL (a real substrate exists and should be extended, not
replaced — `artifacts.py`, `ledger.py`, `working_set.py`, `jit.py`, `semantic.py`, `scout.py`,
`autoinject.py`, `rtd.ts`). 7 are ABSENT as formalized mechanisms, though one (Token Governor,
§4) has uncommitted scaffold code already started in this worktree (`governor.py`,
`config/governor.toml`, `tests/test_governor.py`) that this report did not author and does not
claim credit for. **Phase 0 gate implication**: no new subsystem is warranted for the
EXISTS-PARTIAL rows; work there is extension, not creation. The ABSENT rows (ROI
classification, residency state machine, admission/eviction scoring, tool-schema JIT loading,
batched query engine) are genuine new-build items.

---

## Part 2 — Current token baseline (plan §2.4)

### 2.1 What host-reported usage telemetry is captured today

Source: `brainstem/telemetry/SCHEMA.md` (event kind table) + `src/second_brain/telemetry.py`
(aggregation) + `brainstem/prime-extension/src/sensors.ts` (capture).

| Metric | Captured today? | Evidence |
|---|---|---|
| input_tokens, output_tokens | YES | SCHEMA.md line 36 `assistant_usage` event; sourced from provider API (Prime host) |
| cache_read_tokens, cache_write_tokens | YES (when host/model supports prompt caching) | SCHEMA.md line 36 |
| total_tokens | YES (derived sum) | SCHEMA.md line 36 |
| cost_total | YES (via pricing cards) | SCHEMA.md line 36 |
| context usage per turn (used/total/percent) | YES, **per-turn only, not aggregated as a session peak** | SCHEMA.md line 27: `turn_end` event carries `context_usage {used,total,percent}` |
| context_peak (session max) | **NO** — raw per-turn data exists but no code computes `max(context_usage.used)` over a session | grep across `telemetry.py`/`governor.py`: no peak/max aggregation function found |
| number of model turns | YES | SCHEMA.md `turn_start`/`turn_end` events; also rolled up in P3 campaign `evidence.json` (`turns` field) |
| worker turns (delegated subagent turns specifically) | **NO** | No dedicated worker-vs-driver turn attribution field in schema; `autoinject_shadow_decision` records AutoInject decision calls, not general worker turn counts |
| tool_output_raw_bytes / tool_output_model_visible_bytes | PARTIAL | `tool_result.output_bytes` exists (SCHEMA.md line 27); `rtd_shadow` event records `original_chars`/`visible_chars`/`saved_chars` (SCHEMA.md line 32) — RTD-path only, not universal to every tool result |
| repeated_reads_avoided | **NO** | `working_set.py` read ledger records reads but nothing consumes it to report avoided rereads |
| duplicate recall/injection | **NO** | Not tracked as a distinct metric; `brain_packet_delivered` records each delivery but does not flag duplicates against prior deliveries in the same session |
| compactions | PARTIAL | `session_before_compact`/`session_compact` events exist (SCHEMA.md lines 30-31) recording occurrence, but no token-cost-of-compaction model |
| brain_injected_tokens / brain_generated_tokens | PARTIAL | `autoinject_shadow_decision.packet_tokens` and `brain_packet_delivered.packet_tokens` exist — this is AutoInject-specific, not a general "brain-attributable tokens" rollup across all Brain mechanisms |
| action_cache_hits/misses, session_page_faults/evictions | **NO** | No such fields anywhere in schema (confirmed by the §4 row above) |
| task success | PARTIAL | Present in ad hoc P3 campaign `evidence.json` files (`acceptance` field), not in the live telemetry schema as a per-session rollup |

### 2.2 Has a real Brain-ON vs Brain-OFF comparison ever been run and recorded?

**No.** Evidence:

- `outputs/reports/p0-p2-economics-skill-eval.md` (2026-08-16, prior campaign) explicitly
  records: *"Cached vs uncached input tokens: UNAVAILABLE-not-inferred... Output tokens/cost
  per accepted change: UNAVAILABLE-not-inferred... Root vs child token attribution:
  UNAVAILABLE-not-inferred"* — the only prior economics report on this repo states host-level
  provider economics were never captured during that campaign.
- `outputs/reports/v1-roadmap-matrix-crosscut.md` (this worktree, uncommitted, from the
  concurrent campaign) states directly: *"Baseline measurement not yet complete; Token
  Governor implementation/ablation missing"* and *"NO EVIDENCE FOUND (grep for ablation
  reports in outputs/reports/ returns zero; no governor test or ablation report exists)"*.
- The P3 promotion-campaign evidence (`outputs/reports/p3-promo-eval/e01-e16/`) contains
  paired baseline-vs-skill arms (e.g. `e01-b` vs `e01-c`) with per-arm `input_tokens`/
  `output_tokens`/`cache_read_tokens` — this is a **skill-level A/B**, not a whole-Brain
  ON/OFF comparison, and per the durable memory `mem-99df66e3c8f6` this P3 evidence set has
  since been invalidated and quarantined under `outputs/reports/p3-promo-eval-invalidated/`.
- No file matching `*brain-on-off*`, `*token-benchmark*`, or `*ablation*` exists anywhere
  under `outputs/reports/` (checked by directory listing + grep for section-24 task-class
  names above; zero hits outside the gap-map's own §24 mention).

**Conclusion**: the repo has host-level per-session token telemetry (input/output/cache/cost)
and per-turn context usage, but has never executed or recorded a controlled Brain-ON vs
Brain-OFF comparison on a shared task suite. This is a hard prerequisite gap for plan §4.4's
acceptance target (Brain ON < Brain OFF aggregate tokens) and for the §24 campaign.

### 2.3 Real data volume available for building a baseline from historical telemetry

- `C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/`: 655 session
  `.jsonl` files, 149,642 total records (per prior draft of this report, re-confirmed by file
  count only, not re-scanned in full by this worker — see Part 2.1 sourcing above for schema
  confirmation). This is real historical signal but was captured **without** a controlled
  ON/OFF or feature-flag design, so it can describe typical Brain-ON usage, not a causal
  savings estimate.

---

## Part 3 — Section 24 (token benchmark & ablation campaign) readiness assessment

**Not run. This section assesses tooling readiness only, per task scope.**

### 3.1 Task-class fixtures (plan §24.1: MICRO/STANDARD/DEEP/DEBUG/RESEARCH/REVIEW/HANDOFF)

- `proof/tasks/{training,calibration,holdout}/` exists with a deterministic task-file format
  (`proof/tasks/training/overhead.json`: 30 `short-response` tasks with an oracle
  `response_equals` check; `proof/tasks/training/smoke.json` similarly minimal).
  These are **accuracy/calibration** fixtures for the existing proof harness
  (`proof/runner/run_proof.py`, `scoring.py`, `statistics.py`), not token-economics task
  classes. None of the plan's 7 task classes (MICRO/STANDARD/DEEP/DEBUG/RESEARCH/REVIEW/
  HANDOFF) exist as named fixture sets; `proof/tasks/calibration/` contains only a README,
  no task files.
- No fixture set exists for the specific §24.1 scenarios (fresh repo orientation, repeated
  question on unchanged code, small edit after prior read, noisy failing test output, long
  session + compaction, memory-relevant continuation, memory-irrelevant task, worker
  delegation, cross-harness handoff, skill-triggered task). **Gap: full fixture authoring
  required.**

### 3.2 Profile switching (plan §24.2: A Brain-OFF baseline through I FULL v1 candidate)

- `config/governor.toml` (new, uncommitted) already declares the right-shaped `[features]`
  flag set (`brain_core`, `autoinject`, `observation_firewall`, `context_paging`,
  `action_cache`, `delta_sync`, `structural_retrieval`, `semantic_vectors`,
  `tool_working_set`, `skill_lazy_loading`, `prompt_compression`) with env-var override
  precedence — this is a usable **starting point** for profile A-I switching, but:
  - no code path currently reads/enforces most of these flags (only whatever `governor.py`
    itself consumes for its own reporting, not gating live feature execution);
  - profiles C-H in §24.2 require the underlying mechanisms (Observation Firewall, Context
    Paging, Action Cache, Delta Sync, hybrid retrieval, tool/skill working set) to exist and
    be independently toggleable — per Part 1 above, most of these are EXISTS-PARTIAL/ABSENT,
    so profile toggling would currently produce few measurable deltas between C-H.
- **Gap: a runner that (1) sets a profile's flag combination, (2) executes the task suite
  with a live host, (3) records economics per plan §24.3, (4) repeats per profile** does not
  exist. `proof/runner/run_proof.py` + `metrics.py` (`summarize()`: attempted/successes/
  success_rate/mean_wall_seconds/mean_input_tokens) is architecturally close (already
  computes `input_tokens` and `wall_seconds` aggregates) but has no profile/feature-flag
  dimension and no cache/turn/context-peak/worker-count fields in its `summarize()` output.

### 3.3 Report generation (plan §24.3 required fields)

- Required: success/quality, input/output tokens, cache tokens, total paid-model tokens,
  turns, worker count/tokens, context peak, wall time, local CPU/RAM, disk growth, reuse
  hits, injected tokens.
- Currently computed by `proof/runner/metrics.py`: `success_rate`, `mean_wall_seconds`,
  `mean_input_tokens` only. Missing: output tokens, cache tokens, turns, worker
  count/tokens, context peak (see Part 2.1 — raw per-turn data exists but unaggregated),
  CPU/RAM, disk growth, reuse hits, injected tokens.
- `scripts/compile_p3_promotion_report.py` shows a precedent pattern (aggregates evidence.json
  files into a verdict report offline) that could be adapted, but it is scoped to the P3
  skill-promotion evidence schema, not the §24 profile/task-class matrix.

### 3.4 Overall readiness verdict

**Not ready to execute.** Concretely missing before a real §24 campaign run:

1. Fixture authoring for the 7 task classes and their listed scenarios (none exist today).
2. A profile runner that actually gates live code paths on the `governor.toml` flags (the
   flags exist; the gating does not).
3. Extension of `proof/runner/metrics.py` (or a parallel economics-focused aggregator) to
   emit the full §24.3 field set, sourced from the telemetry gaps identified in Part 2.1
   (context peak aggregation, worker-turn attribution, reuse-hit counting, injected-token
   rollup across mechanisms, not just AutoInject).
4. At least one controlled Brain-ON vs Brain-OFF run recorded (Part 2.2) as the profile-A/B
   floor before profiles C-I can be meaningfully differentiated.

None of this is present today; all of it is buildable on top of the existing
`proof/runner/` harness and `telemetry.py`/`governor.py` foundation rather than from
scratch, consistent with the plan's "use the cheapest primitive / do not duplicate" rule
(plan §3).

---

## Sources cited

- `outputs/reports/v1-arch-phase-gap-map.md` (this worktree, uncommitted, 2026-08-18) — primary source for Part 1 mechanism table, cross-checked by this worker for `router.py`/`skillforge.py` (Tool Working Set ABSENT verdict) and `telemetry.py`/SCHEMA.md (Token Governor ABSENT verdict).
- `outputs/reports/p0-p2-economics-skill-eval.md` (2026-08-16) — prior economics data, confirms no Brain-ON/OFF comparison and UNAVAILABLE provider economics for that campaign.
- `outputs/reports/v1-roadmap-matrix-crosscut.md` (this worktree, uncommitted) — confirms zero ablation reports exist.
- `outputs/reports/p3-promo-eval-invalidated/`, memory `mem-99df66e3c8f6` — confirms P3 skill-level A/B evidence is quarantined/invalid, not usable as Brain-ON/OFF evidence.
- `brainstem/telemetry/SCHEMA.md`, `src/second_brain/telemetry.py`, `src/second_brain/governor.py`, `config/governor.toml`, `src/second_brain/artifacts.py`, `src/second_brain/ledger.py`, `src/second_brain/working_set.py`, `src/second_brain/jit.py`, `src/second_brain/semantic.py`, `src/second_brain/router.py`, `src/second_brain/scout.py`, `src/second_brain/autoinject.py` — direct source citations, this worker.
- `proof/runner/metrics.py`, `proof/tasks/training/{overhead,smoke}.json`, `scripts/compile_p3_promotion_report.py` — §24 readiness assessment, this worker.
