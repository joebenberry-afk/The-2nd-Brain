# P0 AutoInject Gate Report (Amendment Phase C / original-plan 0D)

- **Date:** 2026-08-16 (session); advisory window opened 00:36:09Z
- **Amendment:** `Second_Brain_P0-P2_Maximum_Prime_Agent_Harness_Amendment.md` §11, §28 Phase C, §30 (read)
- **Original plan:** §6.11 (P0-G1..G12), §15 D1–D2, §16 PHASE 0D (grep)
- **Role:** WORKER — config flip + memory seeding + this report; extension deployment sync (backup taken); no commits.

## 1. Identity

| Item | Value |
|---|---|
| Branch / HEAD | `brain/p0-p2-production-core` @ `b8195a7` |
| Prime | 0.7.2 (`C:/Tools/prime-agent`, coding-agent 83a0f9f95) |
| Extension | `brainstem/prime-extension` 0.1.0; **deployed copy re-synced** to `~/.prime/agent/extensions/second-brain/` (was stale: no autoinject.ts; backup at `second-brain.bak-20260815-203551`) |
| Brain home resolution | deployed `config.ts`: `SECOND_BRAIN_HOME` env (set to the repo in this session) else `%USERPROFILE%\Documents\The-Second-Brain` — repo `config/autoinject.toml` **reaches the live extension** |
| DB schema | v8 (0001–0008) |
| Tests | pytest 694 passed / 2 skipped; vitest 228; ruff clean; pyright 0 |

## 2. Rollout mode ladder

| Mode | Evidence |
|---|---|
| OBSERVE | pre-campaign baselines: `outputs/reports/experiment-141..145` (brainstem shadow/recall, stale/contradiction, cross-model); telemetry JSONL measurement-only kinds (turn/tool/context) live |
| SHADOW | `SECOND_BRAIN_AUTOINJECT_MODE=shadow` (default): unit + wiring vitest (decision recorded, handler returns undefined, no packet), CLI smoke (INJECT→ALREADY_DELIVERED→WRONG_PROJECT), telemetry `brain_retrieval_attempt`/`brain_no_injection` kinds live |
| ADVISORY | mode switch now config-file driven (below); custom_message patch unit/integration proven; **live window opened this session** (§4); Codex `additionalContext` live smoke re-run (§3 G11) |
| ACTIVE | same path as advisory in this adapter (low-authority packet, `authority: advisory` fixed by contracts renderer); dogfood scheduled in Phase I |

**Mode switch (Part 1):** `loadAutoInjectHostConfig(home?)` now reads `<home>/config/autoinject.toml` `[autoinject] mode` (tiny TOML-subset parser mirroring `config.ts`); env `SECOND_BRAIN_AUTOINJECT_MODE` overrides; absent file → shadow. `[autoinject] mode` added to `config/autoinject.toml` + `src/second_brain/defaults/config/autoinject.toml` with rollback comment. Vitest: file fallback + env precedence + absent-file (2 new tests; 228 total). This is the rollback-safe live flip: edit one line, next event picks it up, no redeploy.

## 3. P0 gate battery (G1–G12)

| Gate | Verdict | Evidence |
|---|---|---|
| G1 fresh-session automatic recall | PASS | `tests/test_autoinject.py::test_relevant_current_injects_deterministic_packet` (fresh lineage INJECT); live pipeline INJECT this session (session `01a007b7…`, §4) |
| G2 NO_INJECTION | PASS | `test_no_relevant_memory_yields_no_injection`, `test_wrong_project_memory_not_injected`; live `gate-probe2` run: unrelated task → NO_INJECTION/NO_RELEVANT_MEMORY |
| G3 stale/superseded safety | PASS | `test_superseded_never_current_and_delta_emitted` (v2 supersedes v1; v1 never presented) |
| G4 contradiction surfacing | PASS | `test_contradiction_withheld_per_policy` (CONTRADICTORY_UNRESOLVED); `test_contradicted_item_is_labeled` |
| G5 dedupe (exact dup = 0) | PASS | `test_dedupe_same_lineage_second_call_skips` (ALREADY_DELIVERED, row count 1); vitest advisory same-session-twice (first patch, second undefined); live second-call dedupe via CLI smoke |
| G6 bounded context | PASS | `test_budget_hard_cap_never_exceeded` (cap=200 env override; packet_tokens ≤ cap; IDs-only ladder; CONTEXT_PRESSURE when nothing fits) |
| G7 worker-specific packet | PASS | `test_role_scoped_packets_worker_vs_orchestrator` (worker vs orchestrator packet differ; orchestrator-tagged never reaches worker), `test_role_filter_only_role_tagged_memory_available` |
| G8 fail-open | PASS | `test_fail_open_retrieval_error` (BRAIN_UNAVAILABLE, no raise); vitest spawn failure/timeout → extension_error, handler undefined; run.ps1 malformed payload → `{}` exit 0 |
| G9 write-back candidate | PASS | `tests/test_autoinject_writeback.py::test_writeback_creates_candidate_with_provenance` (status candidate, OBSERVED, session provenance); unverified candidate not retrievable |
| G10 fresh-session reuse | PASS | `test_verified_candidate_is_retrievable_fresh_session_g10` (curate VERIFIED → fresh session retrieves lesson) |
| G11 Codex smoke | PASS | `tests/test_autoinject_codex.py` (5 tests) + live re-run this session: advisory → `{"additionalContext":"[BRAIN_CONTEXT_DELTA v1]…authority: advisory…"}`; malformed → `{}` exit 0 |
| G12 observability | PASS | telemetry kinds `brain_retrieval_attempt` (task_sha256, candidate_count, role), `brain_no_injection` (reason), `brain_packet_delivered` (packet_id, tokens, delivery_count, canonical_packet_hash), `autoinject_shadow_decision`, `codex_hook_shadow_decision`; delivery ledger rows |

## 4. Live advisory window log (window OPEN at 00:36:09Z, mode=advisory)

Seeded 4 genuine campaign memories (project `second-brain`, scope `p0-p2-campaign`, status current):
`mem-d2f7df353130` VERIFIED RLM_MAX_DEPTH=1 blocks recursion · `mem-f745bcb2eff2` VERIFIED adaptive fan-out replaces hard 2-worker cap · `mem-174b3f5abbba` VERIFIED driver MAY execute trivial deterministic work · `mem-cd1f9e0cdac4` OBSERVED decoy (Neapolitan pizza — restraint target).

- `00:36:09Z` flip `config/autoinject.toml` → `mode = "advisory"`.
- `00:36:17Z` gate-probe: task "design the P1 orchestration with adaptive fan-out given recursion is blocked" → NO_INJECTION (FTS AND-semantics: multi-topic tokens not all present in one row — documented limitation; **restraint evidence**).
- `00:36:17Z` gate-probe2: task "refactor the cli parser module" → NO_INJECTION/NO_RELEVANT_MEMORY (**no flood; decoy not injected**).
- `00:38:30Z` G11 Codex advisory smoke (temp brain): `{"additionalContext":"[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-9dc4d9173947ebd1\n…authority: advisory…"}`.
- `00:40:1xZ` live pipeline INJECT (extension-identical spawn, session `01a007b7-c2ae-710b-8150-690069c3a8f8`, agent `phase0a-audit2`): task "adaptive fan-out" → **INJECT, packet_tokens=219, selected [mem-f745bcb2eff2], delivery `del-d11fabcfdcbb4c0afc471955`**, wall 0.242s; delivery row persisted (canonical_hash `b33258e2…ac7c5`).
- Telemetry during window: `brain_retrieval_attempt` ×3, `brain_no_injection` ×3; `brain_packet_delivered` ×1 (from the INJECT run).
- **Observation turn (this session, next task after the window opened):** the `[BRAIN_CONTEXT_DELTA v1]` custom_message was **NOT observed in context**. Root cause (telemetry-proven): the running Prime processes (parent session `01a007b1…` and this daemon worker `01a007b7…`) had loaded the extension **before** the deployment sync — the parent session shows **0 `brain_*` telemetry records across the entire window** (00:36:09–00:41:35Z), and this session's only `brain_*` records are the manual CLI runs (`brain_retrieval_attempt`+`brain_packet_delivered` at 00:39:53Z, packet `pkt-e712c8777a8efe68`, 219 tokens). The synced extension (with the autoinject adapter) loads only at the next Prime session start. Control-path live evidence stands (pipeline INJECT + ledger + Codex `additionalContext` + restraint), but the in-context model-visible observation is **pending a Prime restart**.

## 4b. Live observation findings (observation 1 + 2) and Phase C3 fixes

- **Observation 1 (shadow-era, window open):** no `[BRAIN_CONTEXT_DELTA v1]` in context. Root cause: running Prime processes had loaded the pre-sync extension (no autoinject adapter; parent session 0 `brain_*` telemetry records across the window). Extension re-synced; backups at `second-brain.bak-20260815-203551` and `second-brain.bak-20260815-205157`.
- **Observation 2 (fresh worker-role session, advisory, post-sync):** pipeline fired at `before_agent_start` automatically (G1 automatic arm PROVEN live) and decided INJECT — `brain_packet_delivered` recorded: 735 tokens, 5 items, `pkt-b3810ee18d5643ba` — but NO custom_message reached model context. Two root causes fixed in T-PhaseC2/T-PhaseC3:
  1. **Worker-role drop (Phase C3 FIX 1):** the message return was hardened so EVERY role path returns/merges the patch: orchestrator and driver merge with their systemPrompt patch, worker/normal return a bare `{ message }` result, and a packet already computed by the pipeline is NEVER dropped by a later handler failure (catch returns it bare in advisory/active). Verified against installed SDK: `BeforeAgentStartEventResult.message = Pick<CustomMessage, customType|content|display|details>` (types.ts:956); runtime `runner.ts` `emitBeforeAgentStart` collects `result.message` from every handler and `_appendBeforeAgentStartMessages` inserts it as model-visible `role:"custom"` — a bare `{message}` return IS accepted.
  2. **Project drop (T-PhaseC2 FIX 1 + Phase C3 FIX 2):** a later turn showed `project_id=default` → WRONG_PROJECT. Fixed by cwd-based registry resolution (extension passes `ctx.cwd` → python resolves registry root > env > default) and, when cwd is absent/empty, the Brain home path itself is tried against the registry before env/default (Phase C3 FIX 2).
- **Fix refs (uncommitted working tree):** T-PhaseC2 (`--cwd` + OR-fallback + query_mode) landed on top of `3f35bd1`; T-PhaseC3 (`index.ts` role-path message returns + catch hardening; `autoinject.py` brain-home cwd fallback) is the current working state. Deployed extension re-synced byte-identical (SHA256 10/10).

## 5. Fail-open + rollback proof

- Fail-open: retrieval raises → BRAIN_UNAVAILABLE (tested); spawn timeout/non-zero → extension_error + no patch (vitest); malformed codex stdin → `{}` exit 0 (tests + live); venv-less home → silent no-op.
- Rollback: mode ladder tested (off/shadow never inject); **config flipped back to `mode = "shadow"` at 2026-08-16T00:41:35Z** (repo `config/autoinject.toml`; env override absent); post-flip deterministic verification green (vitest mode=shadow no-spawn/no-patch); uninstall scripts for Codex hooks (`-RestoreBackup` restores exact prior config); extension deployment backup kept; env override `SECOND_BRAIN_AUTOINJECT_MODE=off` wins over file.

## 6. P0 metrics (small-sample, honest)

- Packet tokens: samples {117, 125, 219} → p50 ≈ 125, p95 ≈ 219 (n=3; hard cap 2000; target 800). UNAVAILABLE for larger n until dogfood.
- Retrieval/injection latency: 0.242 s wall (spawn+retrieve+ledger, single sample); recall path timeout ceiling 5 s.
- Duplicate injections: **0** (ledger dedupe tests + live second-call ALREADY_DELIVERED).
- Stale-as-current: **0** on fixtures (superseded excluded; v1 never presented after supersede).
- Usage attribution root-vs-child: **UNAVAILABLE — not inferred** (Phase B finding; provider/runtime does not expose per-session attribution).

## 7. Residual limitations

1. **Recursion config:** daemon blocks child recursion (`RLM_MAX_DEPTH=1`) — P1 must be designed without depth-2 delegation (recorded as memory `mem-d2f7df353130`).
2. **Usage attribution UNAVAILABLE** — root vs child token attribution cannot be measured; economics phase must mark it unavailable-not-inferred.
3. **FTS AND semantics:** multi-topic task strings can legitimately yield NO_RELEVANT_MEMORY (observed twice in the live window) — restraint is correct behavior; per-topic intent splitting is a possible Phase D/1C improvement, not a P0 defect.
4. Live in-session custom_message arrival is scheduled for the next turn; all control-path and integration evidence is already collected.

## 8. Rollback instructions

- Mode: edit `config/autoinject.toml` `[autoinject] mode = "shadow"` (or `SECOND_BRAIN_AUTOINJECT_MODE=off`).
- Codex hooks: `.\scripts\uninstall-codex-hooks.ps1 [-RestoreBackup]`.
- Extension: deployed copy backup `~/.prime/agent/extensions/second-brain.bak-20260815-203551`.
- Commits: previous known-good `b8195a7` (campaign HEAD); nothing committed by this task.

## 9. Verdict

**P0: PARTIAL.** All 12 gates have deterministic evidence (G1–G12 table) and control-path live evidence stands (pipeline INJECT 00:39:53Z with ledger row, restraint runs, Codex `additionalContext` live). The single outstanding item: **in-context model-visible observation of the `[BRAIN_CONTEXT_DELTA v1]` custom_message in a live Prime session** — not observed on the scheduled turn because the running Prime processes had loaded the pre-sync extension (no autoinject adapter; telemetry shows 0 `brain_*` records from the parent during the window). Exact next step: restart/create a Prime session after this gate (the synced extension loads), set `mode = "advisory"`, send a task containing e.g. "adaptive fan-out" — expect the packet custom_message + `brain_packet_delivered` telemetry, then flip back to shadow. Everything else — control path, adapters, ledger, fail-open, rollback (flipped 00:41:35Z) — is proven.
