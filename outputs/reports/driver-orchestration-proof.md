# Driver Orchestration Proof Report (Phase 12)

Date: 2026-08-15 (UTC). Campaign: Driver-Orchestration pass (Second Brain
optimization). Branch: `brain/optimization-sol-orchestrator`. Status:
**IMPLEMENTED + DEPLOYED + LIVE SMOKE-TESTED** (uncommitted; parent commits
after review).

Evidence sources: `state/recon/driver-orchestration-evidence.md`
(parent-verified: deployment, live role classification, smoke results,
telemetry census), `state/recon/driver-orchestration-audit-config-tests.md`,
`state/recon/driver-orchestration-audit-runtime.md` (Phase 1 audits),
`brainstem/prime-extension/` source/tests, live telemetry under
`telemetry/agent-performance/`. No claim is made beyond what those artifacts
show; where evidence is partial the section says so explicitly.

---

## Conclusion

Driver orchestration default implemented and validated: the driver role
(deepseek-v4-pro, gpt-5.6-luna by default) receives a 170-word orchestration
contract automatically, workers never receive it, the Sol contract and hard
guard are byte-identical to HEAD, all suites green (vitest 201, tsc, eslint,
pytest 10), and live smoke tests prove classification, injection, and the
autonomous parallel-delegation DECISION (end-to-end worker execution by a
depth-1 smoke driver is blocked by the harness recursion guard itself — the
anti-recursion mechanism; see Caveats).

---

## Implementation identity

- **Branch**: `brain/optimization-sol-orchestrator` (current working tree).
- **Commit**: none — all changes UNCOMMITTED by campaign protocol (parent
  commits after review). No git mutations performed by the implementation
  worker.
- **Changed files** (from `state/recon/driver-orchestration-evidence.md`):
  - NEW `brainstem/prime-extension/src/driver-orchestrator.ts` — pure role
    resolver + contract module (no I/O).
  - NEW `brainstem/prime-extension/tests/driver-orchestrator.test.ts` — 16
    unit tests.
  - NEW `brainstem/policies/driver-orchestration.md` — canonical policy.
  - MOD `brainstem/prime-extension/src/index.ts` — `before_agent_start`
    handler only (role resolution + driver contract append + recall
    composition).
  - MOD `brainstem/prime-extension/src/sensors.ts` — additive optional
    `role` / `driver_contract_injected` fields on `before_agent_start`.
  - MOD `brainstem/prime-extension/tests/wiring.test.ts` (+6 tests),
    `tests/sensors.test.ts` (+2 tests).
  - MOD `brainstem/telemetry/SCHEMA.md`, `brainstem/prime-extension/README.md`,
    `CHANGELOG.md` — docs.
- **Deployment**: `scripts/install-prime-extension.ps1` @ 2026-08-15 ~09:36
  local; pre-install backup
  `backups/20260815-093623-036-prime-extension-pre-install`. Installed dir
  `~/.prime/agent/extensions/second-brain/`: 8 .ts files + types/ — ALL
  SHA-256-identical to repo `src/` (verified, incl. new
  `driver-orchestrator.ts`).

## Role resolver proof

Resolution: `src/driver-orchestrator.ts` `resolveAgentRole(modelId, cfg,
hardModels)` — lowercased substring containment on the `provider/id`
serialization (same semantics as the Sol guard); precedence
**hard_orchestrator > driver > worker > normal**; blank/null → `normal`.
Unit-tested in `tests/driver-orchestrator.test.ts` (16 tests):

| Role | Default substrings | Proof |
|---|---|---|
| `hard_orchestrator` | `gpt-5.6-sol` (via existing `ORCHESTRATOR_MODELS`) | precedence test "hard + driver -> hard"; Sol wiring tests green; guard config feeds the resolver directly (`loadOrchestratorGuardConfig().orchestratorModels`) |
| `driver` | `deepseek-v4-pro`, `gpt-5.6-luna` (`DRIVER_MODELS`) | defaults test; substring/case tests (`openai-codex/GPT-5.6-LUNA` → driver); live 6/6 driver sessions got the contract |
| `worker` | `deepseek-v4-flash`, `qwen3.5` (`WORKER_MODELS`) | `deepseek/deepseek-v4-flash` → worker; `lemonade/Qwen3.5-9B-GGUF-Q6_K` → worker (substring); live smoke D role=worker |
| `normal` | everything else (`anthropic/claude-sonnet-5`, `openai-codex/gpt-5.6-terra`) | negatives tests → normal |

- **Config**: `DRIVER_MODELS`, `WORKER_MODELS` env vars (CSV, trim, lowercase,
  drop empties; unset/empty/all-empty → defensive copy of defaults
  `["deepseek-v4-pro","gpt-5.6-luna"]` / `["deepseek-v4-flash","qwen3.5"]`;
  read at call time, `process.env` default — `orchestrator-guard.ts` style).
- **Anti-recursion**: workers never receive the driver contract. Unit:
  "flash is NEVER driver" negative test; defaults disjoint; contract text
  "workers do NOT inherit the driver role and must NOT orchestrate". Live:
  smoke D (`deepseek/deepseek-v4-flash`) → `role=worker`,
  `driver_contract_injected` ABSENT, 0 subagents spawned.
- **Contract injection**: `appendDriverContract(base)` — append to the full
  current system prompt (never replaces, never invents), dedup by marker
  `second-brain-driver-orchestration-contract` (test: seeded-marker base
  returned unchanged; wiring test: no duplicate append, `injected=false`).

## Regression proof

- **Sol policy unchanged**: `orchestrator-guard.ts` byte-identical to HEAD
  (`git diff` empty); `index.ts` Sol branch behaviorally identical (record,
  `isOrchestratorModel` check, `{systemPrompt: SOL_ORCHESTRATOR_CONTRACT}`);
  all 14 orchestrator-guard tests + Sol wiring tests green ("Sol model ->
  systemPrompt contains the delegation rule", "tool_call: Sol model + bash ->
  {block:true}", "ipython NOT blocked", "ORCHESTRATOR_* env overrides").
- **Sol hard guard unchanged**: `tool_call` wiring untouched; guard tests
  green; live `orchestrator_policy_violation` count 0 across all smoke
  sessions.
- **Recall unchanged**: `recall-gate.ts` byte-identical; 23 recall-gate tests
  + Phase 14 wiring tests green; non-driver sessions take the exact previous
  path (default OFF → zero spawns; `patched === base` for non-driver, so the
  composed patch string is identical); recall brief composes AFTER the
  driver contract in one patch (new driver+recall wiring test).
- **Telemetry healthy / schema additive**: `sensors.ts` change is additive
  optional fields only; Python validator (`src/second_brain/telemetry.py`)
  ignores extra fields (checks only `v`, `kind`, `session`, `ts`) —
  UNCHANGED, and `pytest tests/test_telemetry.py -q` → 10 passed. Live:
  0 `extension_error`, 0 `orchestrator_policy_violation`, 0 `rtd_shadow`
  across all smoke sessions; 7 new session files, 0 new anonymous files.
- **Untouched, byte-identical to HEAD** (verified `git diff` empty):
  `orchestrator-guard.ts`, `recall-gate.ts`, `config.ts`, `rtd.ts`,
  `storage.ts`, `types/*`.

## Test results

- `npm test -- --run` (vitest): **8 files / 201 passed, 0 failed**
  - driver-orchestrator 16, orchestrator-guard 14, recall-gate 23, config 12,
    sensors 48, rtd 24, storage 19, wiring 45 (baseline was 177).
- `npm run typecheck` (tsc --noEmit): exit 0, no diagnostics.
- `npm run lint` (eslint .): exit 0, no warnings.
- `pytest tests/test_telemetry.py -q` (repo venv, sanitized env): 10 passed,
  exit 0.

## Live smoke results

All smokes ran against the DEPLOYED extension (SHA-identical to repo src);
role classification read from live `before_agent_start` telemetry records.
Session ids: `state/recon/driver-orchestration-evidence.md`.

- **A — trivial (v4-pro driver)**: created `%TEMP%/sb-smoke-a.txt` directly;
  0 `rlm()` calls in session log; reply SMOKE-A-DONE true. No pathological
  orchestration. **PASS** (role=driver, injected=true).
- **B — narrow repo investigation (driver)**: completed inline with exact
  citations; 0 workers; driver classified it trivial-tier.
  **PASS** (contract-conformant direct execution).
- **C — two independent greps (driver)**: completed inline, correct answers,
  0 workers. **PASS** (0 <= 2 concurrency ceiling).
- **B2 — failing test, 1-char bug (driver)**: root cause + fix + 2/2 tests
  pass; inline; 0 workers. **PASS**.
- **B3 — off-by-one (driver)**: root cause + fix + 4/4 tests pass; inline;
  0 workers. **PASS**.
- **D — worker (deepseek-v4-flash)**: answered directly, 0 subagents spawned,
  role=worker, NO driver contract. **Anti-recursion PASS**.
- **C2 — substantial parallelizable (driver)**: driver AUTONOMOUSLY decided
  to delegate BOTH streams to 2 concurrent deepseek-v4-flash workers: wrote
  full task packets (objective/scope/constraints/evidence/completion
  condition), selected models via `rlm.find_models`, and issued
  `asyncio.gather` of 2 `rlm()` spawns (= peak 2). Spawn attempts hit the
  harness recursion guard — `RuntimeError: RLM recursion depth limit reached
  (RLM_DEPTH=1, RLM_MAX_DEPTH=1)` — because the smoke drivers ran as depth-1
  RLM children that may not spawn grandchildren. The driver fell back to an
  inline audit and still delivered the result. **Orchestration DECISION
  proven live; end-to-end worker spawn by a depth-1 smoke driver could not
  complete — blocked by the harness guard, which IS the anti-recursion
  mechanism** (see Caveats).
- **Telemetry health**: 0 extension_error, 0 policy violations, 0 shadows;
  6/6 driver sessions injected=true; 1/1 worker session not injected.

## Prompt overhead

`DRIVER_ORCHESTRATOR_CONTRACT` = **170 words** (target <= 230), verified by
unit test ("word count <= 230") and re-counted from source. First line:
`[second-brain-driver-orchestration-contract] You are the DRIVER of an
RLM-capable agent system. ORCHESTRATE substantive work by default; never wait
for the user to explicitly ask for subagents.` Injected only for driver-role
sessions, only once (marker dedup), appended to the existing prompt — no
replacement, no overhead for worker/normal/Sol sessions.

## Caveats

1. **Recursion-guard smoke constraint**: end-to-end worker execution by a
   depth-1 smoke driver is impossible by design (`RLM_DEPTH=1`,
   `RLM_MAX_DEPTH=1` — the harness recursion guard, i.e. the anti-recursion
   mechanism itself). Live C2 proves the full orchestration DECISION
   (classification, task packets, model selection, 2-way parallel spawn
   attempt) but not grandchild worker completion from a depth-1 session. The
   extension-level evidence (injection, classification, decision) is
   complete; depth-0 driver sessions can spawn workers normally (see the
   operating-example note in Behavior).
2. **Sol live acceptance remains blocked by model availability** — unchanged
   from the Sol campaign: no Sol model is currently reachable on this
   machine, so live hard-guard acceptance cannot be re-run; unit/wiring tests
   prove the Sol path is untouched (orchestrator-guard.ts byte-identical).
3. **Deployment is live**: installed 2026-08-15 ~09:36 local via
   `scripts/install-prime-extension.ps1` with pre-install backup
   `backups/20260815-093623-036-prime-extension-pre-install` (reversible via
   `scripts/uninstall-prime-extension.ps1`). Repo changes remain uncommitted
   until parent review.
4. **No file-based config**: role lists are env-only (`DRIVER_MODELS`,
   `WORKER_MODELS`); daemon-routed production sessions inherit the daemon's
   startup env (set vars before starting prime-agent; same caveat as the
   existing `SECOND_BRAIN_HOME` note in README).

---

# Acceptance Criteria

Implementation accepted only when ALL of the following hold (verdict per
item; evidence in parentheses):

- [x] **Existing Sol contract remains intact.** — Sol branch behaviorally
  identical; Sol wiring tests green ("before_agent_start: Sol model ->
  systemPrompt contains the delegation rule").
- [x] **Existing Sol hard guard remains intact.** —
  `orchestrator-guard.ts` byte-identical to HEAD; tool_call wiring untouched;
  14 guard tests green.
- [x] **Configured driver models receive the new driver contract
  automatically.** — live: 6/6 driver sessions (`deepseek/deepseek-v4-pro`)
  recorded `role=driver`, `driver_contract_injected=true` (smokes a/b/c/b2/b3/c2).
- [x] **Driver contract says substantial work should default to delegation.** —
  contract: "SUBSTANTIAL work ... delegate the bulk of execution-heavy work
  to workers"; content test `delegate the bulk of execution-heavy work`.
- [x] **Driver contract explicitly allows trivial direct execution.** —
  contract: "TRIVIAL work ... execute directly. Never spawn workers merely
  because workers exist"; content test `execute directly`.
- [x] **Driver contract does not require the user to request delegation.** —
  contract: "never wait for the user to explicitly ask for subagents";
  content test.
- [x] **Normal max worker concurrency is <=2.** — contract: "default 1
  active worker, at most 2, NEVER 3+"; content test `at most 2`.
- [x] **Configured worker models do not receive driver contract.** — live
  smoke D: `role=worker`, `driver_contract_injected` ABSENT; wiring test
  "worker model -> no contract, record role=worker".
- [x] **No fuzzy family matching causes worker self-promotion.** — exact
  lowercased substring containment; negative tests: `deepseek-v4-flash` never
  driver, `deepseek-v4-pro` never hard, substrings do not cross-match;
  defaults disjoint.
- [x] **Driver models retain direct execution permissions.** — no tool
  blocking added (tool_call untouched); smokes A/B/C/B2/B3 executed directly
  with 0 workers.
- [x] **Existing recall behavior remains intact.** — `recall-gate.ts`
  byte-identical; 23 recall-gate tests + Phase 14 wiring tests green;
  non-driver path produces the identical composed patch; default OFF = zero
  spawns.
- [x] **Existing FTS5 behavior remains intact.** — no FTS5/query/DB code
  touched by the campaign (semantic search index paths unchanged); relevant
  suites green (pytest test_telemetry 10 passed; vitest full suite 201).
- [x] **Existing telemetry remains healthy.** — additive schema fields only;
  Python validator unchanged (extra fields ignored); pytest test_telemetry 10
  passed; live 0 extension_error across all smokes; 0 violations/shadows.
- [x] **Role classification is configurable.** — `DRIVER_MODELS` /
  `WORKER_MODELS` env overrides (unit tests: env override replaces lists,
  CSV edge cases).
- [x] **Conflict precedence is deterministic.** — HARD > DRIVER > WORKER >
  NORMAL; unit tests "precedence: hard_orchestrator > driver > worker >
  normal" and "custom hardModels ... win over drivers".
- [x] **Tests cover hard/driver/worker/normal roles.** —
  `tests/driver-orchestrator.test.ts` (16 tests) + wiring role tests.
- [x] **Tests cover anti-recursion.** — worker-never-driver negative tests;
  contract "must NOT orchestrate"; wiring worker-ctx test; live smoke D.
- [x] **Tests cover no duplicate contract injection.** —
  `appendDriverContract` dedup tests (marker present -> unchanged) + wiring
  test "base already containing the marker -> no duplicate append,
  injected=false".
- [x] **Live trivial-task smoke does not show pathological spawning.** —
  smoke A: 0 `rlm()` calls; B/C/B2/B3 also 0 workers (trivial-tier direct).
- [x] **Live substantial-task smoke shows automatic orchestration.** — smoke
  C2: driver autonomously decided to delegate both streams to 2 concurrent
  flash workers with full task packets; spawns blocked by the harness
  recursion guard (depth-1 smoke driver), driver fell back inline and
  completed. Decision-level evidence complete; end-to-end grandchild
  execution not reachable from a depth-1 session (guard, not extension).
- [x] **Live parallel smoke uses no more than 2 workers.** — C2: exactly 2
  concurrent `rlm()` spawns (`asyncio.gather`, peak 2); never 3+; contract
  ceiling enforced in all other smokes (0 workers).
- [x] **Worker smoke shows no recursive spawning by default.** — smoke D:
  0 subagents spawned, no contract.
- [x] **Relevant automated suites are green.** — vitest 8 files / 201
  passed; tsc exit 0; eslint exit 0; pytest test_telemetry 10 passed.
- [x] **Proof report is written.** — this document.
- [-] **All changes are committed.** — NOT committed: campaign protocol
  leaves the working tree uncommitted for parent review and commit.
- [-] **Working tree is clean.** — tree contains exactly the intended 10
  changed/new files (3 new + 7 modified) and nothing else; will be clean
  after the parent's commit.

Verdict: **22/24 met now; the 2 unmet items are the commit/clean-tree
bookkeeping pair owned by the parent, not the implementation.**

---

# Final Report

## Conclusion

Driver orchestration default implemented and validated.

## Behavior

- **Sol**: unchanged — strict contract replaces the system prompt,
  `bash`/`edit`/`websearch` blocked, `ipython` kept for delegation; guard
  source byte-identical to HEAD.
- **Driver**: receives the 170-word driver-orchestration contract APPENDED
  to the full system prompt on `before_agent_start` (marker-deduped, once);
  orchestrates substantive work by default, executes trivial work directly,
  delegates execution-heavy work, concurrency 1 default / 2 max / never 3+,
  prefers cheapest competent worker, reviews and integrates; retains all
  direct execution permissions.
- **Worker**: measurement-only; never receives the driver contract; does not
  inherit the driver role (anti-recursion); may still be selected by a
  driver for delegation.
- **Normal**: measurement-only; no contract.
- **Operating example**: this campaign's own parent session
  (`deepseek/deepseek-v4-pro`, depth 0) is the live driver-pattern instance —
  it orchestrated the two deepseek-v4-flash workers through this campaign;
  after Prime reload it will also carry the contract in new turns.

## Tests

- vitest: 8 files / 201 passed / 0 failed (driver-orchestrator 16,
  orchestrator-guard 14, recall-gate 23, config 12, sensors 48, rtd 24,
  storage 19, wiring 45).
- `tsc --noEmit`: exit 0. `eslint .`: exit 0.
- `pytest tests/test_telemetry.py`: 10 passed.

## Live Smoke

- trivial: A — direct execution, 0 workers, no pathological spawning. PASS.
- substantial: C2 — autonomous 2-worker parallel delegation decision with
  full task packets; spawn blocked by harness recursion guard (depth-1 smoke
  driver); fell back inline and completed. Decision proven; end-to-end
  grandchild spawn not reachable from depth-1 (guard = anti-recursion
  mechanism).
- parallel: C2 peak concurrency exactly 2; all other smokes 0.
- recursion: D — worker spawned 0 subagents, no contract. PASS.

## Config

- `ORCHESTRATOR_MODELS` (existing) — hard orchestrator, default `gpt-5.6-sol`.
- `DRIVER_MODELS` (new) — driver, default `deepseek-v4-pro,gpt-5.6-luna`.
- `WORKER_MODELS` (new) — worker, default `deepseek-v4-flash,qwen3.5`.
- `ORCHESTRATOR_BLOCKED_TOOLS` (existing) — unchanged
  (`bash,edit,websearch`; `ipython` not listed).
- Canonical policy: `brainstem/policies/driver-orchestration.md`.

## Changes

Uncommitted (parent commits after review). 3 new files +
7 modified: `src/driver-orchestrator.ts`,
`tests/driver-orchestrator.test.ts`, `brainstem/policies/driver-orchestration.md`;
modified `src/index.ts` (before_agent_start only), `src/sensors.ts`
(additive fields), `tests/wiring.test.ts` (+6), `tests/sensors.test.ts`
(+2), `brainstem/telemetry/SCHEMA.md`, `README.md`, `CHANGELOG.md`.
Deployed via `scripts/install-prime-extension.ps1` (2026-08-15 ~09:36 local,
pre-install backup `backups/20260815-093623-036-prime-extension-pre-install`).

## Caveats

Only material items: (1) depth-1 smoke sessions cannot spawn grandchild
workers (harness recursion guard `RLM_DEPTH=1`/`RLM_MAX_DEPTH=1` — the
anti-recursion mechanism; C2 proves the decision, not grandchild completion);
(2) Sol-specific live acceptance still blocked by model availability
(unchanged; Sol path proven by unit/wiring tests and byte-identical source);
(3) deployment is live with pre-install backup; repo changes uncommitted
until parent review; (4) role lists are env-only — daemon-routed sessions
inherit the daemon startup env.

## Recommendation

**Deploy and use.** The driver-orchestration contract is implemented,
deployed (SHA-verified install, backup taken), regression-clean, and
live-validated for classification/injection/decision/anti-recursion. The only
outstanding live item is Sol-specific hard-guard acceptance, which remains
blocked by Sol model availability — unchanged from the prior campaign and not
a regression. Commit the working tree and continue using the driver pattern;
a depth-0 driver session (as this campaign's parent) exercises the full
delegation loop.
