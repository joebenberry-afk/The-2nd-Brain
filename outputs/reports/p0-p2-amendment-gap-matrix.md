# P0–P2 Amendment Baseline Gap Matrix (Amendment Phase A)

- **Date:** 2026-08-16 (session)
- **Amendment:** `Second_Brain_P0-P2_Maximum_Prime_Agent_Harness_Amendment.md` (read fully)
- **Original plan:** grep-only (sec 22/23/24/28/30/31 consulted for conflicts)
- **Role:** EXPLORER — read-only; only this report written; no commits.

## 1. Identity

| Item | Value |
|---|---|
| Branch / HEAD | `brain/p0-p2-production-core` @ `ead00bb` (brain(adapter): advisory/active low-authority injection Prime + Codex, Phase 0D) |
| Working tree | clean except untracked `memory/semantic/mem-ae7a34f105c5.md` (pre-existing, untouched) |
| Prime version | `0.7.2` (`C:/Tools/prime-agent/package.json`; coding-agent 0.7.2, commit `83a0f9f95` chore(release): prepare v0.7.2) |
| Extension revision | `brainstem/prime-extension` `0.1.0`, source-synced to live deployment `C:/Users/assas/.prime/agent/extensions/second-brain/` (config.ts, driver-orchestrator.ts, index.ts, orchestrator-guard.ts, recall-gate.ts, rtd.ts, sensors.ts, storage.ts, types/) |
| DB schema version | `8` (`0001..0008_deliveries`; `schema_version` table) |
| Test totals | pytest 694 passed / 2 skipped; vitest 226 passed; ruff/pyright clean on changed files |
| Harness state | `~/.prime/agent/harness/harness_state.json`: 2 prompt notes + 6 memories + 0 skills + 0 subagents; `refinements.jsonl`: 6 refinement records |

## 2. Baseline — already present (amendment §1 / §35)

Status legend: **PROVEN** = tested + committed; **NOT-PROVEN** = implemented, no live/formal proof; **PARTIAL**; **MISSING**.

| Capability | Repo evidence | Status |
|---|---|---|
| Prime extension deployment | `brainstem/prime-extension/` (9 source files) + live copy in `~/.prime/agent/extensions/second-brain/`; 11 lifecycle events wired; telemetry JSONL in live brain | PROVEN |
| Bounded recall | `recall-gate.ts` (maxRows=3, minChars=40, timeout 5s, spawn bounds); `runBrainRecall` env-clean execFile | PROVEN (unit/integration; live smoke in earlier campaign) |
| SQLite FTS5 retrieval | `semantic.py search_memories` (bm25, lazy `memory_fts`, linear fallback) + migration 0007 | PROVEN |
| Stale/duplicate filtering | Phase-7 filters (superseded/archived/REJECTED), Phase-8 dedupe, delivery ledger 0008 `ALREADY_DELIVERED` | PROVEN |
| Contradiction-aware retrieval | `contradiction_with`, `CONTRADICTORY_UNRESOLVED` withhold, contradicted item labeling | PROVEN |
| Runtime-driven retrieval/router config | `config/retrieval.toml` + `config/context.toml` (load_retrieval_config), `config/skills.toml [router]`, `config/autoinject.toml` + env overrides | PROVEN |
| Telemetry | `telemetry.py`, `SCHEMA.md` v2, `sensors.ts` builders (incl. `autoinject_shadow_decision`, `codex_hook_shadow_decision`), live `telemetry/agent-performance/*.jsonl` | PROVEN |
| Role/orchestration policy | `brainstem/policies/driver-orchestration.md`, `sol-minimal-orchestrator.md`; `driver-orchestrator.ts`, `orchestrator-guard.ts`; harness prompt `luna_delegation_orchestrator_policy` | PROVEN |
| Sol hard-orchestrator policy + guard | `SOL_ORCHESTRATOR_CONTRACT` in index.ts; blocks bash/edit/websearch for Sol models; violation telemetry | PROVEN |
| Direct-execution guard | `orchestrator-guard.ts` (block decision + runtime guard); tests | PROVEN |
| Proof/report infra | `outputs/reports/` (milestone-01..14, driver-orchestration-proof, experiments 141–145) | PROVEN |
| Canonical Markdown + derived SQLite state | `memory/semantic/*.md` canonical; `memory_index`/`memory_fts` derived; `brainctl memory reindex`; doctor | PROVEN |
| Tests | 39 pytest files (694 pass), 9 vitest files (226 pass), property tests for migrations/backup | PROVEN |
| Live deployment structure | extension deployed, telemetry flowing, `state/` layout, backups, doctor/status commands | PROVEN |

## 3. Gap matrix (core deliverable)

Gap: NONE / SMALL / LARGE / MISSING. Where: phase+task (amendment phases A–J).

### 3.1 P0 acceptance (§30)

| Requirement | Current state (file/symbol) | Gap | Where |
|---|---|---|---|
| Real Prime event path auto-invokes Brain logic | index.ts session_start + before_agent_start → autoinject.ts (shadow fire-and-forget; advisory/active awaited custom_message) | NONE | C (live dogfood in I) |
| Relevant recall without explicit user instruction | recall-gate brief + AutoInject pipeline | NONE (live proof pending) | C/I |
| Recall bounded | maxRows/timeout/budget caps (800/2000 tokens) | NONE | C |
| Stale-aware | Phase-7 filters + supersede deltas | NONE | C |
| Duplicate-aware | deliveries ledger + ALREADY_DELIVERED | NONE | C |
| Contradictions surfaced | contradiction_with / withhold / labeling | NONE | C |
| Active capsule compact | JIT capsule + packet budget; no live size measurement | SMALL | H |
| Raw evidence externally accessible | artifacts.py blobs + brain:// refs + /brain-expand | NONE | C |
| Irrelevant task gets no flood | NO_INJECTION sparse (10 reasons) | NONE | C |
| Capture records durable facts only | writeback_candidate (candidate status, OBSERVED) + gate | SMALL (unit-proven, not live) | C/D |
| Outcome linkage | writeback sources `session:<id>`, delivery records | SMALL | C/D |
| Canonical Markdown/SQLite agree | dual-write semantic.py + doctor + reindex | NONE | C |
| FTS5 intended path live | lazy FTS5 + fallback parity tests | NONE | C |
| OBSERVE evidence | experiments 141–145 (baseline) | NONE (collected) | C |
| SHADOW evidence | unit + CLI smoke + wiring tests | NONE | C |
| ADVISORY evidence | unit-proven (custom_message patch); no live session evidence | SMALL | C/I |
| ACTIVE dogfood passes real tasks | not started | MISSING | I |
| Rollback/deactivation works | env `SECOND_BRAIN_AUTOINJECT_MODE=off`, uninstall scripts, mode ladder | NONE | C/J |
| Stable prompt prefix not destroyed | epoch/fingerprint contracts defined; no measurement | LARGE | H (1C) |

### 3.2 P1 acceptance (§31)

| Requirement | Current state | Gap | Where |
|---|---|---|---|
| Driver gets compact harness-native policy | Sol contract + driver contract (policies/*, index.ts) | NONE | D |
| Primitive selection kernel/deterministic/skill/reuse/new/fan-out/recursion | delegation policy prompt (tier list); no enforced selector code | LARGE | D |
| Driver may do trivial deterministic work (amendment) | current policy FORBIDS most driver execution — CONFLICT | LARGE | D (policy+prompt edit) |
| Driver does not personally execute substantial work by default | Sol contract forbids; driver role partial | SMALL | D |
| Retained child preferred over respawn | harness memory `rlm_subagent_reuse_preference` (policy only) | SMALL | D/F |
| Named persistent child reuse live-proven | child registry dirs exist (`daemon-workers/`); no probe/test | LARGE | B/D |
| Active steering live-proven | agent_message follow-ups used in this campaign (informal) | SMALL | B/D |
| Follow-up to completed/idle child | agent_message to completed child (used in session) | SMALL | B/D |
| Parallel fan-out live-proven | not exercised | MISSING | B/D |
| Fan-out width adaptive/config | hard `max two` in Sol contract/policy — CONFLICT | LARGE | D |
| Controlled recursive worker delegation | not exercised | MISSING | D |
| Simple work does not recurse | policy wording only | SMALL | D |
| A2A direct communication | agent-message skill supports siblings; not exercised | SMALL | B/D |
| Fresh verifier path for consequential work | no verifier role wiring | MISSING | D |
| Driver review blocks unsupported worker claims | policy text only | PARTIAL | D |
| Worker ownership prevents micromanagement | policy text (recursive ownership) only | PARTIAL | D |
| Kernel state deliberately reused | persistent IPython kernel (this session reuses vars); no policy/test | SMALL | B/D |
| Large intermediate data not stuffed into context | artifacts.py blobs + RTD distillation + distilled previews | NONE | D |
| Role assignment deterministic/configurable | resolveAgentRole(model→role) + env config | NONE | D |
| Hard-orchestrator not weakened | Sol guard blocks + tests | NONE | D |
| Local resource limits respected | envsteward.py, doctor shutdown checks, timeout guards | NONE | D |

### 3.3 Skills / Continual Harness (§32)

| Requirement | Current state | Gap | Where |
|---|---|---|---|
| Repeated P0–P2 procedure evaluated for promotion | experiment-143 precedent; no in-campaign eval | SMALL | E |
| Python-backed skill created/tested/used if justified | skillforge.py exists; harness skills=0 | PARTIAL | E |
| Evidence if nothing qualifies | n/a yet | MISSING | E |
| Brain truth vs harness operating memory separate | Brain repo vs `harness_state.json` — separate by construction; no test | SMALL | F |
| Harness CRUD exercised safely | harness CRUD APIs + 6 recorded refinements | SMALL | F |
| Reusable subagent spec used | harness subagents=0 | MISSING | F |
| /refine on real evidence-backed pattern | refinements.jsonl has 6 entries (real usage) | NONE | F |
| Refinement comparatively evaluated | recent refinements carry outcomes; no A/B harness test | SMALL | F |
| Rollback proven | harness update/delete exists; rollback not tested | SMALL | F |
| No uncontrolled self-modification loop | constitution + policy; harness edits gated | NONE | F |
| Base system prompt immutable | harness notes never mutate prompt | NONE | F |

### 3.4 P2 (§33)

| Requirement | Current state | Gap | Where |
|---|---|---|---|
| Canonical append-only session/event truth | contracts (BrainLifecycleEvent/LedgerHeader/versioning) + deliveries table only; no session events table | MISSING | G |
| Derived projections deterministic/rebuildable | `state/projections/` empty; working_set capsules derived ad hoc | MISSING | G |
| Prime-owned artifacts referenced, not duplicated | `~/.prime/agent/session-artifacts/<session>/` exists (currently empty); no Brain integration | MISSING | G |
| Session state survives compaction | nothing wired (extension only records before/after compact) | MISSING | G |
| Kernel-state restoration verified | `kernel-venv` exists; not verified | MISSING | B/G |
| Retained child registry survives restoration | `daemon-workers/` persists on disk; unproven | MISSING | B/G |
| TUI detach/reattach proven | not tested | MISSING | B/G |
| Worker/supervisor restart recovery | not tested | MISSING | G |
| Branch/fork lineage no false truth | RequestEpoch/SessionSegment contracts exist; no lineage store | MISSING | G |
| Corrupted derived state rebuildable | `brainctl memory reindex` (index rebuild only) | PARTIAL | G |
| Brain doctor/integrity passes | doctor + tests | NONE | G |
| Replay verification | none | MISSING | G |
| Harness state survives as expected | harness_state.json persists; unproven formally | PARTIAL | G |
| Refinement history durable | refinements.jsonl append-only | NONE | G |
| No unreconciled canonical-vs-derived state | doctor + index checks | PARTIAL | G |

### 3.5 Cache / cost (§34)

All ten metrics (stable prefix, cached/uncached input, root vs child usage, worker reuse rate, duplicate investigation, capsule size, fan-out width/depth, skill usage, refinement outcomes, cost per accepted change): **MISSING** — no measurement layer exists; amendment rule applies: report `UNAVAILABLE — not inferred`, never fabricate. Contracts for epochs/fingerprints (RequestEpoch/RequestFingerprint) are the substrate. Where: Phase H (+ 1C cache metrics when provider exposes).

## 4. Conflicts with the original plan

| # | Original plan constraint | Amendment replacement | Repo files that must change (NO edits now) |
|---|---|---|---|
| 1 | Hard worker ceiling: default 1 / max 2 (§P1, Sol contract: "spawning several subagents merely to gain confidence" forbidden) | Adaptive fan-out: default conservative + config/env max + hard resource ceiling + telemetry (§12.2) | `brainstem/prime-extension/src/index.ts` (SOL_ORCHESTRATOR_CONTRACT), `brainstem/policies/sol-minimal-orchestrator.md`, harness prompt `luna_delegation_orchestrator_policy` |
| 2 | Driver must not perform routine execution (Sol FORBIDDEN list) | Driver MAY execute trivial deterministic work; must not personally do substantial work when delegation wins (§31) | same policy files + `orchestrator-guard.ts` blocked-tool list |
| 3 | Skill learning/evolution explicitly OUT of scope (orig §24) | Phase E skill promotion + §32 acceptance (evaluate → promote Python-backed skills) | `skillforge.py` usage path, harness skill CRUD (no code change required; process change) |
| 4 | Continual harness / /refine not in original scope | §14–16: harness CRUD + evidence-backed /refine are active P0–P2 components | none (harness_state.json/refinements.jsonl are Prime-owned) |
| 5 | Recursive delegation not specified (Sol: delegate one level) | §12.3 recursive ownership with just-cause rules | policy prompt + Sol contract text |
| 6 | A2A messaging limited to parent→child (P1B) | §8 direct sibling A2A where it reduces micromanagement | none (agent-message skill already supports siblings); policy text |
| 7 | General autonomous daemon OUT of scope (orig §24) | §20 deliberately unattended bounded tasks + heartbeats allowed | policy text; no daemon code |
| 8 | P2 = Brain-side ledger only | P2 extends to Prime harness state (kernel snapshot, child registry, TUI detach, harness survival) (§19/§33) | new Phase G work items (ledger 0009+, Prime artifact refs) |
| 9 | Phase names 0A–2F | Amendment phases A–J (A = baseline audit ≈ 0A; J = proof package ≈ final gate) | campaign sequencing only |

## 5. What exists in P2 already (and what Prime owns)

**Brain-side (usable substrate):**
- Content-addressed artifact store: `state/artifacts/blobs/<sha256>.bin` + `meta/` (`artifacts.py`) — object refs for ledger rows.
- Session state capsules: `state/sessions/<id>/{active-state,requirements,read-ledger}.json` (`working_set.py` JIT) — current-state only, not append-only.
- Delivery ledger: `deliveries` (migration 0008) — first canonical append-only table (AutoInject only).
- Contract substrate: `contracts.py` — BrainLifecycleEvent, RequestEpoch/Fingerprint, SessionSegment, LedgerHeader + `LEDGER_SCHEMA_VERSION=1` + upgrader registry (empty).
- Telemetry: JSONL v2 per Prime session under `telemetry/agent-performance/` (measurement kinds).
- `state/projections/` — empty (no derived projections yet).

**Prime-owned artifacts to REFERENCE (not duplicate) per §19.3:**
- `C:/Users/assas/.prime/agent/sessions/*.jsonl` — transcript JSONL per session (entry tree with id/parentId, compaction entries).
- `C:/Users/assas/.prime/agent/session-artifacts/<session-id>/` — per-session artifact dirs (currently empty on this install).
- `C:/Users/assas/.prime/agent/kernel-venv/` + `bin/` — persistent kernel runtime.
- `C:/Users/assas/.prime/agent/daemon-workers/<id>/` — retained RLM child session dirs (child registry on disk).
- `C:/Users/assas/.prime/agent/harness/{harness_state.json, refinements.jsonl}` — continual harness truth.
- `C:/Users/assas/.prime/agent/telemetry.json`, `session-leases/`, `models.json`, `settings.json`.

Ledger/replay code: **MISSING** (only deliveries + contracts; no event table, no replayer, no projections).

## 6. Phase-by-phase plan (draft, for parent review)

| Phase | Scope (amendment §28) | Concrete tasks | Owner |
|---|---|---|---|
| A | Baseline audit | THIS REPORT; identity/baseline/gap/conflicts | Explorer (this agent) |
| B | Harness capability probe | Probe kernel persistence across compaction; named child create/list; follow-up to retained child; steering; sibling A2A; harness CRUD; /refine dry-run; detach/reattach; recovery path. Output: harness capability matrix (SUPPORTED+PROVEN/NOT-PROVEN/BROKEN) | Explorer worker + Verifier |
| C | P0 AutoInject complete | Live ADVISORY evidence in isolated Prime session; ACTIVE dogfood on 1 real task; OBSERVE/SHADOW/ADVISORY/ACTIVE evidence collection; `outputs/reports/p0-autoinject-gate.md` | Worker (pipeline) + Verifier (gate) |
| D | P1 RLM orchestration | Policy edits for conflicts 1/2/5/6/7 (adaptive fan-out, trivial-work allowance, recursion rules); primitive-selection prompt; verifier path; A2A test; kernel-state policy; `p1-orchestration-cache-gate.md` | Worker (TS) + Worker (policy) + Explorer |
| E | Skill promotion | Evaluate repeated procedures (autoinject smoke, hook install, gap audits) → promote 1 Python-backed skill or document why not | Explorer + Worker |
| F | Continual Harness dogfood | One evidence-backed refinement cycle on a real pattern (e.g. delegation policy); comparative evaluation; rollback proof; base-prompt immutability check | Worker |
| G | P2 durability/replay | Migration 0009 events table (BrainLifecycleEvent rows); session ledger writer in BrainLifecycle; derived projections; Prime artifact references (transcript/child registry); replayer + invariant tests; compaction/kernel/child-registry recovery tests | Worker (python) + Worker (TS) + Verifier |
| H | Cache/economics | Measurement layer: capsule size, prefix stability, root/child tokens, reuse rate, fan-out width, cost/change; provider metrics where exposed; UNAVAILABLE-not-inferred otherwise | Explorer/Verifier |
| I | Full dogfood campaign | Representative real tasks under OBSERVE→SHADOW→ADVISORY→ACTIVE; Brain itself as target; holdout tasks not used for calibration | Driver + workers |
| J | Proof package | `P0_P2_FINAL_IMPLEMENTATION_REPORT.md` per §35; commit; clean tree; STOP; no P3 | Driver/Verifier |

## 7. Known unknowns (honest)

- Prime 0.7.2 harness primitive limits (child naming, steering API shape, detach/reattach) are NOT yet probed — Phase B resolves before Phase D design.
- `session-artifacts/<session>/` currently empty — cannot yet cite what Prime persists there per session on this install.
- Provider cache metrics availability (OpenAI responses API via Prime) unknown — Phase H reports UNAVAILABLE where true.
- Live extension deployment is a source copy; a rebuild/sync step may be needed after TS changes (unverified deploy mechanism).
