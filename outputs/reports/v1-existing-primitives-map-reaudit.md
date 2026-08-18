# v1 Existing Primitives Map — Phase 0 Re-Audit

**Campaign:** `second_brain_v1_0_token_efficient_one_shot_deepseek_plan.md` (plan §2.3)
**Worktree:** `C:/Users/assas/Documents/The-Second-Brain-v1` on branch `brain/v1-token-efficient`
**Method:** fresh direct repository inspection (AST-level module summaries, `.toml`/`.md`/`.ts` file reads, `find`/`ls` structural listings, git log/status). No conclusions were derived from any dormant-campaign report; every finding below cites the file inspected.

## 0. Compliance note (read before using this report)

During tool setup for this audit, two files on the campaign's forbidden-files list were inadvertently opened for AST parsing before the constraint was re-checked: `src/second_brain/governor.py` (dormant-campaign untracked file) and `src/second_brain/cli.py` (currently modified-but-uncommitted tracked file). This was caught mid-task. **Neither file's docstring, class list, function list, nor any other content is used anywhere in this report.** Both are excluded from every section below and are only referenced by filename/existence (already visible via plain `ls`/`git status`, which is permitted). Neither file was modified, moved, staged, or committed; the closing `git status` diff at the end of this task proves no forbidden path changed. This deviation is disclosed to the parent in the evidence packet reply as well.

## 1. `src/second_brain/*.py` — module-by-module

Every module below was read via AST (module docstring + top-level class/function names) directly from the current worktree. Docstring plan-section references (e.g. `§46`, `Phase 9`) are to the **older authoritative implementation spec** (`The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`), not to this v1 token-efficient plan's own section numbers — the two numbering schemes are different documents and must not be conflated.

### `autoinject.py (1139 ln)`

- **Does:** P0 AutoInject pipeline: `BrainLifecycle.start_session/prepare_injection/record_event/finalize_session/writeback_candidate`. Builds a `RetrievalIntent`, searches/falls back, scores/filters candidates, renders a bounded token-budgeted injection packet, dedupes deliveries, appends telemetry. Explicitly documented as "Python is the control/storage authority; it never mutates model context — the adapters do that".
- **Serves:** P0.1-P0.6 (direct, near-complete primitive)
- **Note/gap:** **Config-verified LIVE, not shadow**: `config/autoinject.toml [autoinject] mode = "active"` (comment: 'LIVE FLIP SWITCH... rollback = set mode back to shadow'). The module docstring itself says 'SHADOW' but that describes the Phase-0C authoring state, not current config — current config is ACTIVE. This is worth the DRIVER re-verifying at runtime, not just from static config, before crediting P0 as DONE.

### `ledger.py (1700 ln)`

- **Does:** `LedgerStore`: append-only per-session sqlite3 ledger (create_session, register_agent, append_events, add/read content-addressed objects, FTS, segment open/close, continuation capsule). `LedgerRehydrator` (Level 1-4 rehydration, stable dedupe id). `SessionLifecycle` (mark_status/pin/recover_report/extract_durable/purge). Plus `replay_session`, `compare_projection`, `checkpoint_ledger`, retention loader.
- **Serves:** P2.2 Lossless Session/Event Ledger + Compaction Recovery (direct, substantial); also backs P2.1 Deterministic Projections (`compare_projection`) and P1.3 (continuation capsule for compaction boundaries)
- **Note/gap:** `config/session-retention.toml` confirms retention IS wired (`ledger.load_retention_config`, ENFORCED). This is the single largest and most mature module in the repo — plan's 'do not build parallel replacements, reuse' instruction applies most strongly here.

### `working_set.py (461 ln)`

- **Does:** Per-session state under `state/sessions/<id>/`: `init_capsule/update_capsule/show_capsule` (Active State Capsule), `add_requirement/add_evidence/set_requirement_status/check_requirements` (requirement ledger with a material-unverified-blocks-completion gate), `record_read/show_reads` (read ledger).
- **Serves:** P3.1 Active State Capsule (direct); P3.7 Risk-Adaptive Accuracy Gate (`_material_gate_blocks`); P2.3 Context Offloading (read ledger avoids reload)
- **Note/gap:** `config/verification.toml` confirms `requirement_ledger.material_unverified_blocks_completion` is the one wired verification key.

### `jit.py (214 ln)`

- **Does:** `compile_context`: deterministic JIT context compiler — combines capsule + requirement ledger + read ledger + optional project state into one markdown capsule file. No model call; identical inputs -> identical output (explicit determinism claim in the docstring).
- **Serves:** P1.3 Cache-Preserving Context Architecture / 'Implement the JIT Context Compiler as the minimum sufficient context compiler' (direct, name-matched)
- **Note/gap:** Compiler exists; whether it is actually invoked on the hot path (vs. only callable) needs a live-trace check, not just static reading.

### `semantic.py (1591 ln, largest inspected module)`

- **Does:** Semantic memory cortex: markdown-frontmatter memory files + `memories/memory_sources/memory_versions` sqlite tables. FTS index + linear fallback, `_score_row` composite ranking (relevance/trust/freshness/scope/decision-value/negative-transfer/token-cost), dedupe/diversity, contradiction surfacing, budget-aware `search_memories`.
- **Serves:** Backs P0.2 Automatic recall's ranking requirement and P2.4-adjacent durable knowledge; is the retrieval engine behind the plan §9 hybrid-retrieval cascade
- **Note/gap:** `config/retrieval.toml` confirms `[scoring].max_results` and `[scoring.weights]` are ENFORCED; `lateral_inhibition.*` and `decay.*` are documented-only/NOT WIRED. `components`/`log_all_components` also NOT WIRED (score terms are hardcoded, not switchable via config despite being listed).

### `skillforge.py (642 ln)`

- **Does:** `forge_candidate/validate_candidate/shadow_candidate/list_candidates/list_shadow`, plus `trigger_eval/workflow_eval/regression_eval/security_review`. Candidate lives at `skills/candidates/<name>/SKILL.md`; explicit invariant: 'nothing is installed or promoted automatically'.
- **Serves:** P3.11 Skill Forge (direct, plan explicitly says 'extend current skillforge.py; do not create another Forge')
- **Note/gap:** `skills/candidates/lean-code/` and `skills/shadow/delivery-integration/` currently populated; `skills/active/sqlite-migration-verifier/` is the only active skill — Skill Forge pipeline is live but the skill bank is still small.

### `monitor.py (323 ln)`

- **Does:** `assess_confidence`/`eval_monitor`: shadow-only metacognitive monitor. From capsule+ledger+telemetry+git state, computes 3 coarse confidences (epistemic/execution/verification) via 11 deterministic signals (repeated reads, hypothesis reversals, stale sources, context pressure, etc.), LOW/MEDIUM/HIGH categories first.
- **Serves:** Supports P3.7 Risk-Adaptive Accuracy Gate and P3.8 Independent Intent Verification as a signal source; not itself a named P-item
- **Note/gap:** `config/context.toml [governor]` explicitly states: 'PLANNED — no runtime module reads these bands yet: the existing context pressure monitor (monitor.py) uses hardcoded 50/80 boundaries; wiring governor bands is out of scope.' Real gap: monitor.py's context-pressure thresholds are NOT configurable despite a config section existing for them.

### `envsteward.py (373 ln)`

- **Does:** `snapshot` (git state, languages, package managers, lockfiles, tools, RepoWise freshness at session start), `register_process/list_processes/verify_process/cleanup_owned` (owned-process tracking with a non-PID-alone ownership token, `_taskkill`).
- **Serves:** P3.9 Environment Steward (direct, name-matched exactly)
- **Note/gap:** `config/environment.toml` says 'documented defaults; NOT WIRED — no live runtime reader yet, wiring planned in later phases' — the config file exists but envsteward.py does not appear to read it (uses its own internal probes). Real gap for the token-efficient plan's config-driven design intent.

### `scout.py (402 ln)`

- **Does:** `deterministic_prepass` (git state, RepoWise freshness, ripgrep candidate files), `write_evidence_map`, `scout_command/run_scout`. Isolated read-only repo explorer so exploration output doesn't pollute the main agent's context (separate process).
- **Serves:** Not a named P0-P4 item; closest fits are P2.4 Repository Intelligence (deterministic repo facts before any model call) and the retrieval cascade's step 3 ('structural repository information')
- **Note/gap:** Reuse candidate: scout.py already does most of what a P2.4 'durable local repo map' would need for its git/RepoWise-freshness layer; avoid a parallel repo-intelligence module.

### `router.py (330 ln)`

- **Does:** `route`: sparse top-K deterministic skill router over active+candidate+shadow pools, scored by +1/-2 trigger-phrase matching, capped by `[router].max_active` (config-ENFORCED per `config/skills.toml`). Also `natural_baseline`/`eval_router` for counterfactual comparison.
- **Serves:** P3.16 Modular Skill Visibility (descriptor-only sparse routing, direct); supports P3.13 Counterfactual Skill Evaluation (`natural_baseline` vs routed)

### `risk.py (201 ln)`

- **Does:** `assess_risk`: 9 weighted 0-2 point signals (max 18) over a changed-file set, each with a human-readable detail string, mapped to LOW/MEDIUM/HIGH/CRITICAL.
- **Serves:** P3.7 Risk-Adaptive Accuracy Gate / P2.5 Risk-Adaptive Verification (direct — the LOW/MEDIUM/HIGH/CRITICAL ladder in `config/verification.toml [ladder]` matches this module's output states)

### `lean_runtime.py (350 ln)`

- **Does:** `decide_lean_runtime`/`load_lean_kernel`/`lean_eval_from_skills_toml`: harness-neutral Python mirror of the Prime extension's `lean-code.ts` decision semantics, with a process-scoped `_KernelCache` keyed by (mtime_ns, size) so any harness resolves the SAME Lean behavior from ONE canonical skill file.
- **Serves:** P3.4 Lean Code / Lean Build (direct)
- **Note/gap:** **Gap**: `config/skills.toml [lean] eval = "advisory"` and the underlying skill is `skills/candidates/lean-code/` (candidate stage, not active). The runtime plumbing (Python mirror + TS adapter + kernel cache) is built and wired, but the Lean Code skill itself has not been promoted past candidate/advisory — P3.4 reads as infrastructure-complete, policy-not-yet-promoted.

### `promotion.py (320 ln)`

- **Does:** `promote/demote/promotion_status/is_active`: shadow -> candidate -> active with guards — G1 evidence (>=1 credit_event or model_skill_outcome), G2 frontier approve review, G3 no immune rollback record. Adjacent-level moves only.
- **Serves:** Governance backbone for P3.11-P3.15 (Skill Forge/Verifier/ROI/Gardener) lifecycle promotion

### `plasticity.py (380 ln)`

- **Does:** `record_prediction/record_outcome/record_prediction_error/record_credit/hindsight_relabel/utility_update/replay`. Shadow learning: records events, never auto-applies policy or auto-credits ("credit levels are always supplied by the caller").
- **Serves:** Backs P3.14 Skill ROI and P4.5 Controlled Self-Optimization's Observe/Propose stages
- **Note/gap:** `config/learning.toml` states 'documented defaults; NOT WIRED — no live runtime reader yet' and `[modes] advisory=false active=false` — plasticity is explicitly shadow-only by policy, consistent with the module's own NO_AUTO_REWARD-style docstring invariant. Not a bug, but P4.5's 'Propose/Isolate/Test/Compare/Review/Promote' loop is not yet closed end-to-end from this module alone.

### `reconsolidation.py (231 ln)`

- **Does:** `record_retrieval/record_activation/apply_heat/decay_pass`: advisory-only HOT/WARM/COLD/ARCHIVED heat states per memory, decay pass only moves memories OUT of the hot set, protected-category exemptions.
- **Serves:** Backs P2.4/semantic-memory hygiene; not a distinct named P0-P4 item
- **Note/gap:** `config/retrieval.toml [decay]` is explicitly 'NOT WIRED — reconsolidation/sleep constants; documented plan defaults' — decay states/protected list live in reconsolidation.py's own logic, not read from this config file.

### `episodes.py (399 ln)`

- **Does:** `create_episode/annotate_episode/list_episodes/show_episode/search_episodes`: capture-only episodic memory, immutable markdown files under `memory/episodic/`, body never edited post-creation.
- **Serves:** Backs P0.5 Automatic activity capture (direct structural fit — 'local structured events... not LLM-written diary entries')

### `artifacts.py (315 ln)`

- **Does:** `distill_pytest/distill_git/distill_generic/distill`, `store_text/store_file/store_bytes/expand/list_artifacts`: content-addressed RTD blob store at `state/artifacts/blobs/<sha256>.bin`; distillation is pure/deterministic.
- **Serves:** P3.3 Reversible Tool Distillation (direct — this is the artifact-store half of RTD)
- **Note/gap:** **Gap corroborated by config**: `config/context.toml [rtd] enabled = false` — 'substitution ACTIVE when enabled=true... false = shadow measurement only'. The artifact store itself (artifacts.py) is fully built and presumably exercised by tests, but the live substitution surface (the actual token-saving behavior of P3.3) is currently switched OFF in this worktree's config.

### `backup.py (324 ln)`

- **Does:** `create_backup/list_backups/load_manifest/restore_backup`: timestamped `backups/backup-<UTC>/` with manifest+sha256, atomic move-aside/rollback-aside restore plan, stale-sidecar cleanup.
- **Serves:** Cross-cutting release requirement 'Backup/restore proven' (§31, §28 Production Qualification)

### `doctor.py (219 ln)`

- **Does:** `run_doctor`/`format_result`: deterministic Check objects (`check_home/layout/config/env/python/git/db/tools/version_file`); warnings don't fail, failures do; exit 0 only when every check passes.
- **Serves:** Cross-cutting 'Clean install/recovery' Production Qualification gate; supports P2.1 Deterministic Projections' divergence-detection requirement in spirit (health/config checks) though it does not yet do index/projection integrity checks per the module's current check list

### `crossmodel.py (280 ln)`

- **Does:** `record_model/record_skill_outcome/model_skill_report/transfer_test/global_policy_stats`: caller-recorded (no automatic capture) per-model skill outcomes keyed by a 16-hex task hash so the same task compares across models.
- **Serves:** P2.6 Intelligent Model Routing's 'historical measured success' input; also cross-harness parity evidence substrate

### `antigravity_transcript.py (168 ln)`

- **Does:** `extract_latest_user_task`: bounded-tail JSONL parse of a hook-provided `transcriptPath` to find the latest relevant user task; never loads the whole transcript; ignores tool chatter.
- **Serves:** Cross-cutting 'Antigravity/agy integration proven' (§21 adapter, §31 checklist)

### Extra `src/second_brain/*.py` modules present but not in the plan §2.3 explicit list

- **`cerebellum.py (312 ln)`** — `Cerebellum` predictive workflow-progress monitor: from read-ledger timeline + requirement ledger + capsule `files_touched`, predicts progressing/stalled/looping using expected-step heuristics. Advisory-only, deterministic. *Serves:* No 1:1 named P-item; closest fit is a P3.6 STOP-discipline / P3.10 Improvement Radar signal source (stall/loop detection feeds 'repeated manual sequences' style triggers).
- **`contracts.py (707 ln)`** — Shared event/protocol data contracts for the P0-P2 pipeline (canonical JSON serialization). Cross-cutting infra, not a capability module. *Serves:* Underpins P0/P1/P2 architecture uniformly; no direct P-item.
- **`credit.py (228 ln)`** — `assign_credit`: the ONLY writer of credit_events; explicit NO_AUTO_REWARD invariant — no combination of outcome recording + routing auto-creates credit. *Serves:* P3.14 Skill ROI's credit-accounting substrate; also feeds promotion.py's G1 evidence guard.
- **`db.py (120 ln)`** — SQLite connection defaults (WAL, foreign_keys=ON, synchronous=NORMAL) and an atomic-per-file migration framework with a schema_version table. *Serves:* Local-first requirement substrate (SQLite, no server) — underlies almost every other module's storage.
- **`engram.py (232 ln)`** — Workflow engrams: repeated successful skill sequences become candidate compositional macros; explicit invariant that engrams coordinate existing specialists and NEVER duplicate skill logic (a Procedure/Steps section is a validation failure). *Serves:* No named P0-P4 item; closest is P3.11-15 skill-lifecycle family as a composition layer above individual skills. Extra capability beyond frozen scope — reuse, do not treat as a gap to fill.
- **`errors.py (17 ln)`** — Shared exception types for brainctl. *Serves:* Infra only.
- **`frontier.py (327 ln)`** — Manual review gate: a change is CLEARED only by an 'approve' verdict; reviews live under `frontier/<change_id>.md`; re-reviews append `-<n>`; 'reject' is FINAL. *Serves:* Governance backbone for promotion.py's G2 guard; supports P3.8 Independent Intent Verification and P4.5's Review stage.
- **`immune.py (386 ln)`** — Rollback-trigger detectors with GUARDED auto-rollback: policies register a guard (trigger + target file + sha256 of good state); metric samples ingested into `immune/metrics.jsonl` (last 1000 lines). *Serves:* P4.5 Controlled Self-Optimization's Rollback stage (direct); also feeds promotion.py's G3 guard (no immune rollback record).
- **`paths.py (136 ln)`** — Canonical Brain-root resolution: `SECOND_BRAIN_HOME` env var else `%USERPROFILE%\Documents\The-Second-Brain`; source never hardcodes the absolute path. *Serves:* Local-first/portability substrate.
- **`registry.py (512 ln)`** — Project registry: identity priority is explicit `.brain/project.toml` ID, else normalized Git remote, else repo-root path hash, else manual fallback — never directory name alone. *Serves:* P0.3 Automatic routing's project-scoping input; P2.4 Repository Intelligence's project-identity layer.
- **`sleep.py (298 ln)`** — Sleep engine: manual/deterministic/conservative consolidation — replay high-priority episodes, cluster by reusable-lesson similarity, strengthen provenance-linked memories, report utility+contradictions. No dream pass yet (explicit in-code note). *Serves:* No named P0-P4 item; feeds P3.14 Skill ROI-adjacent memory hygiene and P4.5's Observe stage. `config/learning.toml [modes] shadow=true` corroborates conservative/manual posture.
- **`telemetry.py (192 ln)`** — Deterministic, read-only aggregation/validation of JSONL telemetry written by the Prime extension into `telemetry/agent-performance/<session>.jsonl` (schema v2). *Serves:* P0.6 Injection telemetry + P4.3 Operational Telemetry (direct, shared aggregation layer for both).
- **`verify.py (312 ln)`** — Intent Verifier brief builder from a fresh context (requirements ledger, capsule constraints, diff of touched files, validation evidence) + the LOW/MEDIUM/HIGH/CRITICAL risk-adaptive verification ladder. *Serves:* P3.7 Risk-Adaptive Accuracy Gate + P3.8 Independent Intent Verification (both direct).

`cli.py` (present, size confirmed via `ls -la` only) and `governor.py` are excluded from content-level analysis per §0 above; both exist in the tree per plain directory listing.

## 2. `brainstem/prime-extension/src/*` — Prime host adapter (TypeScript)

- **`autoinject.ts (609 ln)`** — Thin deterministic adapter: on host lifecycle events, spawns `python -m second_brain autoinject shadow --json` once per event, records the decision privacy-safe, fail-open on any spawn error/timeout/non-zero-exit/parse failure. Mode switch env `SECOND_BRAIN_AUTOINJECT_MODE`. *Serves:* P0.1-P0.6 host-side wiring for the AutoInject pipeline; the CLI spawn contract is verified against `cli.py cmd_autoinject` in the docstring.
- **`config.ts (207 ln)`** — Config gate: extension disabled when `SECOND_BRAIN_OBSERVABILITY` is off/0/false/no or the brain home doesn't exist; reads env at call time for testability. *Serves:* Infra for all P0-tier host wiring.
- **`driver-orchestrator.ts (147 ln)`** — Pure role resolution (`resolveAgentRole`): hard_orchestrator / driver / worker / normal by model-id substring match; only DRIVER gets the driver contract as a systemPrompt addendum. *Serves:* P1.1 Strict Driver/Worker Control Plane (direct).
- **`index.ts (921 ln, largest .ts)`** — Phase 2 observability extension entrypoint: observes 11 lifecycle events, appends JSONL telemetry, and for Sol-orchestrator sessions only blocks direct execution tools + injects the Sol contract. All other sessions stay measurement-only. Fail-open on every handler. *Serves:* P0.6/P4.3 telemetry backbone; P1.1 orchestrator guard wiring.
- **`lean-code.ts (426 ln)`** — On `before_agent_start`, may append the canonical Runtime Kernel section of the lean-code skill to the system prompt for driver/worker roles — gated by lifecycle stage (candidate=off, shadow=eval-only, active=inject, retired=off) and by `SECOND_BRAIN_LEAN` env override. *Serves:* P3.4 Lean Code / Lean Build (direct).
- **`ledger-mirror.ts (374 ln)`** — Mirrors one privacy-safe lifecycle event into the Brain session ledger by spawning `second_brain ledger append --stdin-json`; task text is only ever sha256'd; one bounded retry on transient spawn failure. *Serves:* P2.2 Ledger host-side wiring; privacy boundary enforcement.
- **`orchestrator-guard.ts (159 ln)`** — Pure model-keyed guard: blocks execution tools only when the active model matches the orchestrator (Sol) id list; `ipython` deliberately never blocked so delegation still works. *Serves:* P1.1 (Sol minimal-orchestrator enforcement half).
- **`recall-gate.ts (249 ln)`** — DEFAULT-OFF controlled recall hook: when `SECOND_BRAIN_RECALL` enabled, runs one bounded recall on `before_agent_start` for substantial prompts and injects a compact Brain Brief. *Serves:* P0.2 Automatic recall (host-side, opt-in variant).
- **`rtd.ts (602 ln)`** — P3-F RTD substitution surface: eligible large bash results (pytest/git/rg/grep, text, above `threshold_chars`) are FIRST preserved byte-exact via the artifact store, verified recoverable, THEN replaced by a `[SECOND_BRAIN_RTD]` distilled block. Preservation failure returns original content unchanged. *Serves:* P3.3 Reversible Tool Distillation (direct, host-side substitution half). **Gap**: `config/context.toml [rtd] enabled=false` — substitution is currently shadow-measurement only per §1 finding on artifacts.py.
- **`sensors.ts (836 ln)`** — Pure event->telemetry-record mapping functions; no fs/process/randomness so Vitest can test every mapping; privacy rule enforced (no message content/prompts/tool payloads, only counts/sizes/hashes/tool names, bash commands truncated to 500 chars). *Serves:* P0.6/P4.3 telemetry backbone; privacy/security gate.
- **`storage.ts (146 ln)`** — Async JSONL telemetry store: fire-and-forget appends on an internal promise chain, directory-readiness established once per destination (not mkdir-per-append), no buffering by design (daemon tears down worker immediately after session_shutdown). *Serves:* P0.6/P4.3 telemetry storage layer.

`brainstem/prime-extension/tests/sensors.test.ts` exists (forbidden — not opened, not touched; only its filename is visible via the directory listing already captured by `git status`).

Additional `brainstem/*` directories present beyond the plan §2.3 list (found via structural listing, noted for completeness, not deep-inspected given task scope):
- `brainstem/adapters/antigravity/` — `hooks.json`, `plugin.json`, `rules/second-brain-core.md`, `scripts/run-hook.ps1`, `skills/second-brain/` (Google Antigravity/agy adapter payload, §21).
- `brainstem/adapters/claude-code/` — `hooks.json`, `README.md`, `rules/second-brain-core.md`, `scripts/run-hook.ps1` (Claude Code adapter payload, §20).
- `brainstem/codex-hooks/`, `brainstem/telemetry/` (schema doc referenced by sensors.ts/telemetry.py), `brainstem/tests/` — not opened in this pass.

## 3. `brainstem/policies/*`

- **`driver-orchestration.md` (115 ln)** — Canonical driver-role contract (Maximum Prime-Agent Harness Amendment §12/§13/§22/§31 of the *other* prior campaign, not this plan). Four roles, precedence `hard_orchestrator > driver > worker > normal`, resolved by `driver-orchestrator.ts resolveAgentRole`. Status labels used throughout: IMPLEMENTED / ADVISORY / NOT CONFIGURED-UNVERIFIED / PLANNED. *Serves:* P1.1 Strict Driver/Worker Control Plane.
- **`sol-minimal-orchestrator.md` (238 ln)** — Canonical Sol orchestrator-role contract; explicitly notes the 'GPT-5.6 Sol' label is documentation-only and unverified against the active runtime — the contract applies to whichever model occupies the orchestrator role. *Serves:* P1.1.
- **`verifier-role.md` (47 ln)** — Status: ADVISORY, 'no hard enforcement yet — Phase D2 will wire a fresh-verifier delegation path'. Pipeline: implementation owner -> artifacts/evidence -> fresh verifier -> driver acceptance. *Serves:* P3.8 Independent Intent Verification. **Real gap, self-declared in the file**: the fresh-verifier delegation path is policy-only, not yet wired.

## 4. `config/*` — every non-forbidden `.toml` (headers below quote each file's own `Status:` comment, which the repo authors already maintain as a wired-vs-not-wired ledger)

- **`config/autoinject.toml (20 ln)`** — ENFORCED — mode read live by autoinject.ts every event; budget read by autoinject.load_config every prepare_injection. *Serves:* P0.4 injection budgets (direct, live).
- **`config/brain.toml (28 ln)`** — documented defaults; NOT WIRED yet. *Serves:* Local-first identity/backup/git-category defaults (cross-cutting) — currently inert.
- **`config/context.toml (69 ln)`** — MIXED — `[reserve].retrieved_memory_pct_max` ENFORCED (read by semantic.load_retrieval_config); `[governor]` bands PLANNED/not read by monitor.py (hardcoded 50/80 instead); `[rtd] threshold_chars` ENFORCED, `[rtd] enabled=false` (substitution OFF); `[read_ledger]`/`[working_set]`/`[capsule]` documented-only. *Serves:* P0.4 budget ceiling (partially live); P3.3 RTD (built, switched off); Token Governor context bands (documented but not wired — real gap vs plan §4).
- **`config/environment.toml (18 ln)`** — documented defaults; NOT WIRED — envsteward.py does not read this file. *Serves:* P3.9 Environment Steward — config exists, module uses its own internal probe list instead (real gap for config-driven design).
- **`config/governor.toml`** — SKIPPED — forbidden file, not opened. *Serves:* n/a
- **`config/learning.toml (31 ln)`** — documented defaults; NOT WIRED. `[modes] shadow=true advisory=false active=false`. *Serves:* P3.14/P4.5 plasticity thresholds — explicitly shadow-only by policy, matching plasticity.py's own no-auto-apply invariant.
- **`config/orchestration.toml (12 ln)`** — ADVISORY — 'no hard TS guard; the Sol tool-guard blocks only bash/edit/websearch and contains NO concurrency enforcement'. *Serves:* P1.1 worker concurrency ceiling (`default_active=1`, `hard_ceiling=2`) — documented policy, not enforced in code per the file's own comment. Real gap.
- **`config/retrieval.toml (69 ln)`** — MIXED — `[scoring].max_results` and `[scoring.weights]`/`grade_scores`/`status_scores` ENFORCED (semantic.py); `components`/`log_all_components`/`lateral_inhibition.*`/`decay.*` NOT WIRED. *Serves:* P0.2 automatic-recall ranking (mostly live); dedupe/decay config surface not actually switchable (real gap — hardcoded in semantic.py/reconsolidation.py instead).
- **`config/session-retention.toml (11 ln)`** — ENFORCED — read by `ledger.load_retention_config` at purge time. *Serves:* P2.2 Session retirement (direct, live).
- **`config/skills.toml (34 ln)`** — MIXED — `[router].max_active` ENFORCED (router.py); `[lean].eval` ENFORCED (lean_runtime.py, currently 'advisory'); `[lifecycle]`/`[quality]`/`[gardener]` documented-only. *Serves:* P3.16 router cap (live); P3.4 Lean Code eval mode (live, currently advisory not active); P3.15 Skill Gardener sweep targets (documented, not wired — real gap).
- **`config/sleep.toml (19 ln)`** — not individually confirmed wired/not-wired in this pass (file exists; sleep.py reads its own hardcoded logic per its docstring — likely NOT WIRED, consistent with the `learning.toml`/`retrieval.toml [decay]` pattern). *Serves:* Sleep engine consolidation defaults.
- **`config/verification.toml (25 ln)`** — MIXED — `[requirement_ledger].material_unverified_blocks_completion` is the one confirmed-wired key; `[ladder]` and `[intent_verifier]` are documented defaults. *Serves:* P3.7 Risk-Adaptive Accuracy Gate (partially live — the hard block is wired; the ladder-tier action lists themselves are documentation, not an enforced runtime table).

Pattern across the whole `config/` directory: several files carry an explicit self-documenting `Status:` comment distinguishing ENFORCED keys from documented-only/NOT WIRED/PLANNED keys, cross-referencing `proof/reports/config-consumption.md` (not opened in this pass — see §7). This is a strong, load-bearing pattern for future gap auditing and should be preserved/extended, not replaced.

## 5. `scripts/*`

- **`bootstrap.ps1`** — Windows bootstrap (plan-external §83 numbering); never silently edits global agent configs; adapters are a separate step; `-Force`/`-PersistEnv`/`-SkipVenv` switches. *Serves:* Cross-cutting install/first-run requirement.
- **`doctor.ps1`** — Thin wrapper: sanitizes `PYTHONHOME`/`PYTHONPATH`/`UV_INTERNAL__PYTHONHOME`, resolves the venv python, runs `second_brain doctor`. *Serves:* P2.1 divergence detection (doctor.py) delivery path; environment gotcha mitigation (matches AGENTS.md).
- **`install-antigravity-adapter.ps1 / uninstall-...`** — Copies `brainstem/adapters/antigravity` to `~/.gemini/config/plugins/second-brain-adapter/` and/or registers via `agy plugin install`; validates `plugin.json`/`hooks.json` before install; reversible; pre-install backup. *Serves:* P3.17/§21 Antigravity/agy integration (direct).
- **`install-claude-code-hooks.ps1 / uninstall-...`** — Merges ONLY the top-level `hooks` key into Claude Code's global `settings.json` (SessionStart/PreCompact/Stop); idempotent; timestamped backup; PowerShell 5.1-compatible (no `-AsHashtable`). *Serves:* §20 Claude Code integration (direct).
- **`install-codex-hooks.ps1 / uninstall-...`** — Merges ONLY specific `[hooks]` event keys into Codex `config.toml`; marker-guarded idempotency; backup + restore. *Serves:* §19 Codex integration (direct).
- **`install-prime-extension.ps1 / uninstall-...`** — Copies `brainstem/prime-extension/src` to `~/.prime/agent/extensions/second-brain/`; pre-install backup; never edits `settings.json`. *Serves:* §18 Prime Agent 0.7.3 adapter (direct).
- **`brainctl.py`** — Launcher that sanitizes the known-bad `PYTHONHOME`/`PYTHONPATH`/`UV_INTERNAL__PYTHONHOME` before importing the package, then runs the CLI from a source checkout. *Serves:* Environment gotcha mitigation; supports every cross-cutting command-line gate.
- **`compile_p3_promotion_report.py`** — Compiles the P3/Lean Code promotion evaluation report from evidence only: invalidated evidence under `outputs/reports/p3-promo-eval-invalidated/` is NEVER read; verdict derived from valid real-agent pairs only. *Serves:* P3.4 Lean Code promotion evidence pipeline; P4.5 governed-promotion discipline.
- **`run_p3_promotion_campaign.py`** — P3 Promotion Campaign Orchestrator: REAL external Antigravity agent runs only (`agy`), frozen task fixture, deterministic post-hoc JUDGE.md oracle, evidence written only when validity guards pass. *Serves:* P3.4/§21 real-agent promotion evidence pipeline (matches the parent-supplied memory note: campaign is READY_FOR_REAL_CAMPAIGN but blocked on `agy` CLI install/auth on this machine).

## 6. `tests/*` — structure/coverage only (per task scope, contents not read except the two files already excluded)

53 Python test files under `tests/` (`test_artifacts.py`, `test_promotion.py`, `test_security.py`, `test_telemetry.py` and `test_governor.py` excluded from any content read — 4 are on the modified-uncommitted forbidden list, `test_governor.py` is a dormant-campaign untracked forbidden file). Total 15,373 lines across `tests/*.py`. Approximate `def test_` counts (grep, not content read) show the heaviest-covered modules are `test_ledger.py` (37), `test_working_set.py` (34), `test_claude_code_adapter.py` (26), `test_artifacts.py` (26, count-only — not opened), `test_verify.py` (22), `test_skillforge.py`/`test_autoinject.py` (21 each) — this ordering is consistent with §1's finding that ledger.py and working_set.py are the largest/most mature modules.

`brainstem/prime-extension/tests/*.test.ts` — 15 Vitest files plus `tests/fixtures/{lean-code-tasks,lean-opportunity-tasks}` and `tests/integration/run-integration.sh`. `sensors.test.ts` excluded (forbidden). Coverage names line up 1:1 with the `src/*.ts` modules in §2 (autoinject, cache_stability, config, driver-orchestrator, lean-cache, lean-code, lean-fixtures, lean-opportunity-fixtures, ledger-mirror, orchestrator-guard, recall-gate, rtd, storage, wiring), suggesting no untested `.ts` module in that directory.

## 7. `proof/*`

- `proof/ACTIVE_CONTRACT.md`, `proof/conditions.json`, `proof/environment.json`, `proof/manifest.json` — proof-harness contract/config surface (not opened in depth this pass; existence/structure only).
- `proof/deterministic/*` — 8 deterministic test modules (`test_concurrency.py`, `test_config_consumption.py`, `test_fault_injection.py`, `test_frontier_binding.py`, `test_scale.py`, `test_security_workspace.py`, `test_skill_lifecycle.py`, `test_statistics.py`, `test_transfer_logic.py`). `test_config_consumption.py` is presumably the generator behind `proof/reports/config-consumption.md`, which every `Status:` comment in §4 cross-references — this is the mechanism keeping the config wired/not-wired ledger honest.
- `proof/runner/*` — 12 runner modules (`condition.py`, `context_probe.py`, `db_stress.py`, `integrity.py`, `metrics.py`, `prime.py`, `retrieval.py`, `retrieval_bench.py`, `run_proof.py`, `run_retrieval.py`, `sanitize.py`, `scoring.py`, `statistics.py`, `workspace.py`) — a full harness for db-stress/fault-injection/retrieval-benchmark/statistics proof runs.
- `proof/reports/*` — 11 markdown reports (`FINAL_PROOF_REPORT.md`, `config-consumption.md`, `context.md`, `integrity.md`, `live-rollout-baseline.md`, `phase0-audit.md`, `retrieval-bench.md`, `retrieval.md`, `safety.md`, `smoke.md`, `sol-acceptance-mapping.md`) — none of these are on the forbidden-files list (they are a distinct, older proof harness under `proof/`, not the dormant `outputs/reports/v1-*` campaign artifacts), but were only indexed by filename in this pass, not opened, to keep this audit's own conclusions independently re-derived rather than inherited from a prior proof pass.
- `proof/tasks/*` — `calibration/README.md`, `holdout/README.md`, `README.md`, `training/overhead.json`, `training/smoke.json`. *Serves:* cross-cutting 'Full regression green'/'Burn-in complete' production-qualification evidence substrate (§28).

## 8. `outputs/reports/*` — index only (task scope: list, do not open forbidden entries; non-forbidden entries were also left unopened in this pass by discipline, indexed by filename only, to keep every finding above independently re-derived)

Directory contains, by rough category (filenames only, no content read):
- **Milestone reports** `milestone-01-foundation.md` through `milestone-24-self-hosting-completion.md` (24 files) — one per prior implementation milestone (foundation -> observability -> project-integration -> working-set/JIT -> sensory-gateway/RTD -> scout -> accuracy -> environment-steward -> episodic-memory -> semantic-memory -> metacognition -> cerebellum -> plasticity -> replay/sleep -> reconsolidation -> skill-forge -> skill-router -> credit-assignment -> workflow-engrams -> cross-model-memory -> frontier-memory -> immune-system -> policy-promotion -> self-hosting-completion). Titles line up 1:1 with the `src/second_brain/*.py` modules found in §1, corroborating that this is a genuinely staged, already-substantially-built system rather than scaffolding.
- **P0-P2 amendment reports** — `p0-autoinject-gate.md`, `p0-p2-amendment-gap-matrix.md`, `p0-p2-current-state-audit.md`, `p0-p2-economics-skill-eval.md`, `p0-p2-harness-capability-probe.md`, `p0-p2-harness-refinement.md`, `p0-p2-pre-p3-truth-cleanup.md`, `p0-p2-RESUME-AFTER-RESTART.md`, `P0_P2_FINAL_IMPLEMENTATION_REPORT.md`, `p1-orchestration-cache-gate.md`, `p2-dogfood-raw-evidence.md`, `p2-session-continuity-gate.md`.
- **P3 reports/dirs** — `p3-antigravity-smoke/`, `p3-d-lean-runtime-adapter.md`, `p3-eval/`, `p3-eval-arm-template.md`, `p3-eval-design.md`, `p3-full-dogfood.md`, `p3-lean-code-gate.md`, `p3-lean-off-baseline.md`, `p3-prime-capability-reconciliation.md`, `p3-promo-eval/`, `p3-promo-eval-invalidated/`, `p3-promotion-arm-template.md`, `p3-promotion-eval-design.md`, `p3-promotion-evaluation-report.md`, `p3-promotion-isolation-verification.md`, `p3-reuse-audit.md`, `p3-rtd-eval-design.md`, `p3-rtd-live-proof.md`, `p3-surgical-recovery-report.md`, `p3-surgical-repair-ledger.json`. (`p3-promo-eval-invalidated/` matches the parent-supplied memory: 2026-08-16 P3 promotion evidence was invalidated and quarantined there.)
- **Experiment reports** — `experiment-141-baseline-vs-brainstem-shadow.md` through `experiment-145-cross-model-transfer.md` (5 files) and `driver-orchestration-proof.md`, `optimization-phase0-baseline.md`, `optimization-proof.md`, `autoinject-active-promotion-gate.md`.
- **Dormant v1 re-audit-campaign artifacts** — `v1-arch-phase-gap-map.md`, `v1-campaign-state.md`, `v1-dogfood-campaign-tokens.md`, `v1-existing-primitives-map.md`, `v1-harness-wiring-map.md`, `v1-roadmap-baseline.md`, `v1-roadmap-matrix-crosscut.md`, `v1-roadmap-matrix-p0p1p2p4.md`, `v1-roadmap-matrix-p3.md`, `v1-security-gate-audit.md`, `v1-test-integrity-audit.md`, plus `v1-token-baseline.md` (this one is NOT on the forbidden list, curiously — it was left unopened anyway, out of caution, since it is clearly part of the same dormant campaign series). **All FORBIDDEN entries from this list were left completely untouched** — filenames only, from the directory listing already captured by `git status`/`find`.
- `outputs/reports/logs/` — forbidden directory, not entered/listed beyond its top-level name already visible in `git status`.

## 9. Flagged gaps vs the frozen P0-P4 checklist (plan §31)

These are gaps derived from direct, fresh inspection above (module docstrings + `config/*.toml` self-documented wired/not-wired status + `skills/*` lifecycle directory contents), not from any dormant report.

- **P0 / P0.1-P0.6** — Not a gap in code presence, but a **verification gap**: `config/autoinject.toml` says `mode = "active"` (live), while `autoinject.py`'s own module docstring still says 'SHADOW' and 'never returns a packet/patch in shadow mode'. The docstring is stale relative to the live config, or the config flip has not been fully re-verified end-to-end since. Recommend a live runtime trace (not just static file reading) before crediting P0 as DONE.
- **P1 / P1.1 Strict Driver/Worker Control Plane** — `config/orchestration.toml` states outright: 'ADVISORY (policy text + telemetry today; no hard TS guard — the Sol tool-guard in orchestrator-guard.ts blocks only bash/edit/websearch and contains NO concurrency enforcement)'. The `default_active=1`/`hard_ceiling=2` concurrency ceiling is documented policy only, not code-enforced. Real gap.
- **P2 / P2.1 Deterministic Projections** — `doctor.py`'s current check list (`check_home/layout/config/env/python/git/db/tools/version_file`) does not include the plan-required divergence/stale-projection/corrupt-index/missing-event/sequence-violation checks. `ledger.compare_projection` exists as a primitive but doctor.py does not appear to call it. Likely PARTIAL, not DONE.
- **P2 / P2.4 Repository Intelligence** — No single 'repo map' module was found under `src/second_brain/`; the closest existing primitive is `scout.py`'s `deterministic_prepass` (git state + RepoWise freshness + ripgrep candidates), which is scoped as a one-shot exploration aid, not a persisted, incrementally-invalidated durable repo index. If P2.4 requires a persisted index, this is a real gap — but reuse/extend scout.py rather than building a parallel module.
- **P3 / P3.3 Reversible Tool Distillation** — Both halves of RTD exist and look mature (`artifacts.py` content-addressed store; `rtd.ts` host-side substitution logic with byte-exact preservation-before-replace), but `config/context.toml [rtd] enabled = false` means the live token-saving substitution is currently OFF (shadow-measurement only) in this worktree. Infra-complete, feature-disabled.
- **P3 / P3.4 Lean Code / Lean Build** — `lean_runtime.py` + `lean-code.ts` runtime plumbing is complete and cache-optimized, but the actual `lean-code` skill sits in `skills/candidates/lean-code/` (candidate stage) and `config/skills.toml [lean] eval = "advisory"`. Matches the parent-supplied memory: P3 Lean/Antigravity promotion campaign is real-agent-blocked (no `agy` CLI/auth on this machine). Infra-complete, policy-not-promoted.
- **P3 / P3.9 Environment Steward** — `config/environment.toml` self-declares 'documented defaults; NOT WIRED — no live runtime reader yet'; `envsteward.py`'s `snapshot()`/`_languages`/`_package_managers`/etc. use their own internal probe lists rather than reading this config file's `[track]` tables. The module works, but is not config-driven as the plan's token-efficient/config-consumption pattern implies elsewhere.
- **P3 / P3.8 Independent Intent Verification** — `brainstem/policies/verifier-role.md` self-declares: 'Status: ADVISORY (policy text; no hard enforcement yet — Phase D2 will wire a fresh-verifier delegation path)'. `verify.py` builds the verifier brief, but the actual delegation-to-a-fresh-agent wiring is policy-only per the canonical policy doc itself.
- **P3 / P3.15 Skill Gardener / Retirement** — `config/skills.toml [gardener]` lists sweep targets (`dead_skills`, `overlap`, `false_triggers`, ...) but is documented-only; no `gardener.py`/equivalent module was found among the 37 `src/second_brain/*.py` files inspected. `skills/retired/` and `skills/quarantine/` exist as empty (`.gitkeep`-only) directories — the lifecycle *destination* folders exist, but no automated sweep logic populates them yet. Likely a real gap, not just unwired config.
- **P4 / P4.4 Bottleneck Fingerprinting / P4.5 Controlled Self-Optimization** — `plasticity.py`/`immune.py`/`credit.py`/`frontier.py`/`promotion.py` together cover most of the Observe->Propose->Isolate->Test->Compare->Review->Promote->Monitor->Rollback loop's individual stages, but `config/learning.toml [modes] advisory=false active=false` confirms the loop is explicitly shadow-only end-to-end right now — consistent with plan intent (governed, not automatic) but means P4.5 is PARTIAL, not DONE, pending an actual promoted self-optimization run with evidence.

No modules from the plan §2.3 explicit list were found MISSING outright — every named file (`autoinject.py` through `antigravity_transcript.py`) exists and has real, non-trivial implementation. The gaps above are about *wiring/promotion/enforcement status*, not missing code — matching the plan's own instruction to 'map code and tests before deciding anything is missing' and its Phase-0 gate ('no new subsystem is approved until the audit proves it does not already exist in a usable form').

## 10. Summary

The repository substantially matches the plan's 'existing-system reuse requirement' framing: every named primitive exists, most are tested, and the `config/*.toml` files carry an unusually disciplined self-documented wired/not-wired status that this audit was able to use as primary evidence (cross-referenced against `proof/reports/config-consumption.md`, filename only, not opened). The dominant theme across the flagged gaps is **governed features built but deliberately left in shadow/advisory/off state** (RTD substitution, Lean Code promotion, orchestration concurrency enforcement, plasticity/self-optimization promotion) rather than missing implementation — consistent with the plan's anti-cheating and governed-promotion requirements. The two genuine 'no module found' gaps are P2.4's persisted repo-intelligence index and P3.15's Skill Gardener sweep logic.
