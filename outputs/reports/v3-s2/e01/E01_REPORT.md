# V3 S2 — E01 runtime attribution and reduction (PERF-02/PERF-04)

Date: 2026-09-24. Worktree `.worktrees/v3-s1`, branch `brain/v3-s2`. Everything below ran
against the candidate tree with the canonical corpus copied per run through the SQLite backup
API (`scripts/v3_e01_latency.py`, snapshot of 116 memories / schema 28, project `second-brain`).

## 1. What changed

Python (`src/second_brain`):

- **`turn_bridge.py` (new)** — one interpreter for the three per-prompt memory phases, in the
  same order and through the same functions the separate CLI commands use:
  `capsule_runtime.ensure_capsule` -> `vmem.VMemStore.render_hot_context` ->
  `autoinject.resolve_project`/`BrainLifecycle`/`prepare_injection`/`render_packet`/`shadow_output`.
  - `prepare_turn(...)` — the batched ("one-shot") entry point. Returns the phase results plus
    `capsule_stdout` / `render_stdout` / `autoinject_stdout`, byte-identical to what
    `capsule ensure --json`, `vmem hot-context --json` and `autoinject shadow --json` print, so
    the adapter reuses its existing parsers and cannot diverge on message construction.
  - `serve(...)` — the reused-interpreter JSON-lines helper (`{"op":"prepare_turn"|"ping"|"shutdown"}`),
    memory operations only. One request at a time; bounded request size (64 KiB), task length
    (4000 chars), request count (256), lifetime (1800 s) and RSS (256 MiB); consecutive start
    failures retire the helper (3 strikes); EOF (`stdin` closed by a dying host), `shutdown` or a
    bound ends the loop. Each request carries its own session/project and is rejected with
    `home_mismatch` if it names a different brain home.
  - `identity()` / `identity_drift()` — code fingerprint `build_identity.source_tree_fingerprint`,
    package `source_mtime_ns`, `build_identity.configuration_fingerprint`, and the DB file
    stat + schema version. The DB baseline is refreshed after every answered request, so the
    helper's *own* delivery/ledger writes are not drift, while a database replaced or migrated
    between two requests still forces the adapter to restart the interpreter
    (`{"error":"identity_changed","drift":"db_changed"}`).
  - Phase spans are appended to `SECOND_BRAIN_E01_TRACE` (epoch-ms) for attribution.
- **`cli.py`** — new `turn prepare` / `turn serve` subcommands and two measurement-only trace
  marks (`python_import_end`, `python_main_enter/exit`) written only when
  `SECOND_BRAIN_E01_TRACE` names a file.

TypeScript (`brainstem/prime-extension/src`):

- **`e01-trace.ts` (new)** — inert-unless-enabled span recorder (`performance.now()` + epoch
  wall clock, one JSON line per span).
- **`turn-bridge.ts` (new)** — the client: `once` (`second_brain turn prepare`, one bounded
  process per prompt) and `helper` (`second_brain turn serve`, one interpreter per
  home+interpreter, reused across prompts). Bounded queue (`SECOND_BRAIN_TURN_QUEUE_LIMIT`,
  default 2), per-request timeout (5 s), one bounded restart on transport failure or
  `identity_changed`, one-shot fallback when the helper cannot answer, `shutdown` + kill on
  `session_shutdown`, `process.once("exit")` kill as a safety net, `unref()` so the host can
  exit, and `null` on every failure (never rejects). **Default mode `once`** (integrator
  decision, §3); `helper` and `current` (the pre-E01 per-phase spawns) stay selectable through
  `SECOND_BRAIN_TURN_MODE`, so the three designs remain directly comparable and `current` is the
  rollback path. An unset or unrecognized value resolves to `once`, never silently to the
  unbatched path.
- **`index.ts`** — wires the bridge into `before_agent_start`: an emit-cache probe runs first
  (a host re-emit of the same prompt must not re-run the Python decision and create a second
  delivery), then one batched call supplies capsule/render/AutoInject. The batched AutoInject
  payload is re-parsed with the production `parseShadowOutput` and handed to the *same*
  `runAdvisoryAutoInject` through its existing runner seam, so records, the emit cache and the
  resolved-project memory stay in one implementation. Any failure leaves the batched payload
  null and the pre-E01 per-phase spawns run unchanged. Spans added for the hook
  (`before_agent_start.hook`, `session_start.hook`) and the background bridges
  (`bg.ledger_mirror`, `bg.environment_assessment`, `bg.p4_pulse`, `bg.visibility_plan`).
- **`active-state-mirror.ts` / `vmem.ts` / `autoinject.ts`** — `parseActiveStateResult`,
  `activeStateRenderResult`, `parseHotContextOutput` and `advisoryEmitCached` exported so the
  batched path shares the per-phase parsers/mappings instead of duplicating them;
  `ledger-mirror.ts`'s `mirrorFireAndForget` now returns its (never-rejecting) chain so the
  mirror span can be closed.

Harness: **`scripts/v3_e01_latency.py` (new)** — one fresh host process per run, two prompts per
process (index 0 = cold, index 1 = warm, same host session), fresh corpus snapshot per run, one
trace file per run, harness clock + epoch per host event, per-run span summary, per-arm
aggregate and a paired cold-prompt reconciliation against the inert arm.

## 2. Critical-path span breakdown (cold prompt, candidate)

Method: raw `/tmp`-free runs under `outputs/reports/v3-s2/e01/`; spans are extension
`performance.now()` durations converted to launch-relative ms through the epoch clock both sides
record. `hook` = `before_agent_start.hook` (the hook the host awaits before dispatch).

| arm (design) | cold total ms | Δ vs inert | Δ launch→session | Δ session→agent_start | hook ms | hook share of segment | segment residual ms | Δ agent_start→user_end |
|---|---|---|---|---|---|---|---|---|
| inert (baseline, n=2) | 2895.5 / 2911.1 | — | — | — | — | — | — | — |
| candidate-current (n=2) | 4416.3 / 4511.2 | +1505.2 / +1615.7 (median **+1560.5**) | +1.1 / −63.5 | +1495.4 / +1605.7 | 1171.0 / 1006.2 | 78.3% / 62.7% | 324.4 / 599.5 | +9.8 / +10.0 |
| inert (baseline, n=1) | 2870.5 | — | — | — | — | — | — | — |
| candidate-once (n=1) | 3427.9 | **+557.4** | +9.4 | +550.2 | 484.8 (turn_bridge 452.8) | **88.1%** | 65.4 | +7.3 |
| candidate-helper-lazy (n=1) | 3617.4 | +746.9 | +109.3 | +736.9 | 560.9 (turn_bridge 533.2, helper start 354.6) | 76.1% | 176.0 | +7.3 |
| candidate-helper-eager (n=1) | 3725.9 | +855.4 | +98.8 | +846.0 | 301.0 (turn_bridge 161.1) | 35.6% | 545.0 | +7.3 |

Reconciliation: the three anchor deltas sum to Δ_total within 1–4% (`+1506.3` vs `+1505.2`;
`+557.5` vs `+557.4`), and the measured hook covers 88.1% of the segment that contains it for
`once` (residual 65.4 ms), 76–78% for `current`/`helper-lazy`, and only 35.6% for
`helper-eager` — where the interpreter start (636.7 ms) moved into the boot window instead.
The residual is not unmeasured work: the hook window overlaps concurrent background bridges
(median overlap 535.3 ms for `once`: environment assessment 1.6–1.7 s, ledger mirrors 0.25–0.6 s,
P4 pulse ~0.3 s, visibility plan ~0.3 s), i.e. it is host/CPU contention from the same extension.

Phase-level costs (cold, median of first occurrence):

| arm | capsule ensure | hot-context render | AutoInject | batched call | helper start | background spawn count in the run |
|---|---|---|---|---|---|---|
| current | 286.2 | 259.0 | 390.9 | — | — | ≥ 8 ledger/env/p4/visibility spawns |
| once | inside `turn_bridge` 452.8 | idem | idem | 452.8 | — | idem |
| helper-lazy | idem | idem | idem | 533.2 | 354.6 | idem |
| helper-eager | idem | idem | idem | 161.1 | 636.7 (during session_start) | idem |

Python-side split of one spawn (trace, median): `spawn -> package import complete` 168 ms for
`turn prepare` (and 162–175 ms for the per-phase commands), i.e. 37% of the `once` hook is pure
interpreter+import cost, vs 0.4–29 ms of actual memory work (capsule 0.5 ms, render 8.3 ms,
AutoInject 29.1 ms on the same corpus).

## 3. Budget verdict (S2 contract, not relaxed)

| budget | requirement | measured | verdict |
|---|---|---|---|
| cold incremental, first prompt after host start | p95 ≤ 100 ms | once +557 ms; helper-lazy +747 ms; helper-eager +855 ms; current +1561 ms | **FAIL** (5.6×–15.6×), n=1–2 |
| warm incremental, later prompt same session | median ≤ 10 ms, p95 ≤ 50 ms | not validly measured: see §5 | **NOT_MET / UNKNOWN** |

No design meets the cold budget. A Python interpreter start plus package import is already
~160–180 ms before any memory work, and the helper's start is ~350–640 ms; the cold budget is
only reachable by work that never starts a Python process on the dispatch path (or by starting
it far enough ahead of the first prompt that no part of it is attributed to dispatch — which the
budget explicitly forbids: "its startup counts").

Simplest design that meets the *reduction* goal: **`once`** — one process per prompt, hook
484.8 ms vs 1006–1171 ms for the current path (−52% to −59%), 87% of the residual Δ explained by
measured spans, no helper state to keep coherent. It is now the implementation behind the
existing code path and the **default** `SECOND_BRAIN_TURN_MODE` value (integrator decision after
this pilot); `helper` remains selectable for the pending clean re-measurement and `current` is
the rollback path. No live campaign was run after the default switch — the machine was loaded by
sibling agents, and the integrator scheduled the clean cold+warm re-measurement (all three
designs, n ≥ 5, warm = the second prompt's hook span, excluding turn-1 model time) for a quiet
window.

## 4. Raw data

- `outputs/reports/v3-s2/e01/smoke/` — n=2, inert + candidate-current (first working run).
- `outputs/reports/v3-s2/e01/smoke2/` — n=2, inert + candidate-current, with anchors and
  reconciliation (`reconciliation.json`).
- `outputs/reports/v3-s2/e01/smoke3/` — n=1, inert + once + helper-lazy + helper-eager.
- Each directory holds `manifest.json`, `runs.json` (per-run prompts costs, anchors, span
  summary), `aggregate.json`, `reconciliation.json` and the raw host `*.jsonl`.

Brain-visible characters and memory delivery were identical across designs in every run that
delivered (`495` chars, `mem-a8d221e64549` delivered, `memory_delivered=true` for the memory
prompt; `0` chars for the cold prompt) — the batched and helper paths did not change what the
model sees.

## 4b. Reviewer findings fixed (post-pilot, no live runs)

| finding | fix | regression test |
|---|---|---|
| 1. batched path passed an *inferred* project (`resolvedProjectIdForSession ?? resolveProject()`) as an explicit `--project`, overriding Python's cwd/registry resolution (project isolation) | the batched request now carries `cwd` only; `project_id` is reserved for a genuine explicit caller override, matching the pre-E01 per-phase spawn | `turn-bridge-wiring.test.ts` — "feeds the batched stdout ..." asserts `cwd === "C:/work"` and `projectId === undefined` |
| 2. a partial batch (`ok:false`) was discarded, so a successful AutoInject delivery was re-run (ALREADY_DELIVERED) and the packet lost; the one-shot transport dropped exit-1 JSON | `prepare_turn` reports `phases_ok`; the adapter keeps partial payloads and consumes per phase (`batchPhaseDone`), retrying only the failed phase's own spawn; the one-shot client parses exit 0 **and** 1; `cmd_turn prepare` documents exit 1 = complete JSON | `test_prepare_turn_reports_per_phase_success`, `test_cli_turn_prepare_exit_1_still_prints_complete_json`, `turn-bridge.test.ts` "forwards the reduced phase set and keeps a partial (exit 1) batch", `turn-bridge-wiring.test.ts` "consumes the successful phases of a partial batch ..." |
| 3. `want` (reduced phase set on an emit-cache hit) reached neither the one-shot CLI nor the helper dispatcher, so AutoInject reran and could ledger-mark unseen memories | new `--phases capsule,render,autoinject` flag (validated; unknown name → exit 2), `turn_bridge.phase_selection`, and `TurnSession.handle` validates + forwards `want` (`invalid_want` on an unknown phase); the one-shot client forwards `--phases` | `test_phase_selection_is_validated`, `test_serve_honours_and_rejects_want`, `test_cli_turn_prepare_phases_flag`, `turn-bridge.test.ts` argv assertion |
| 4. disposal during an in-flight retry revived the helper (`kill()` set `state="idle"`) and could spawn an untracked child after the registry was cleared | a terminal `disposed` flag; `kill()` keeps it dead, `ensureStarted`/`spawnHelper`/`request` refuse after disposal, and disposal is re-checked after every await in the retry loop | `turn-bridge.test.ts` "disposal is terminal: an in-flight retry never spawns a replacement" |

Also fixed: the wiring test's telemetry wait now waits for the *specific* record kind with a 10 s deadline instead of "any line" in 3 s, removing the load-sensitive flake the reviewer saw at `turn-bridge-wiring.test.ts:330`.

Not mine (left to their owners): reviewer findings on `src/second_brain/autoinject.py` (exact-ref contribution evidence, body hydration before the contribution gate), `src/second_brain/semantic.py` (distinct-document counts for the ubiquitous-term fallback) and `scripts/v3_matched_arms.py` (request normalizer scope) — DecisionGate / RequestNeutrality own those files.

## 5. Open issues / not done

1. **No reps=5 campaign.** The numbers above are n=1–2 pilots on a machine that was running
   sibling agents' Python/model workloads concurrently (DecisionGate confirmed overlap). The
   cold deltas are large enough (0.5–1.6 s) to be real, but the contract wants medians/p95 over
   a seeded interleaved campaign; that campaign is not in this deliverable.
2. **Default is now `once`; `helper` warm numbers are still invalid in `smoke3`** — every helper round trip after
   the first waited 5000 ms and fell back (`turn_helper.request` second occurrence = 5001.8 /
   5000.2 ms). Root cause found and fixed: the batched request carried its own `id: 1`, which
   overrode the client's per-round-trip id, so replies to the 2nd+ request never matched.
   Regression test added (`assigns a fresh wire id per round trip`); helper warm latency must be
   re-measured with the fixed build.
3. **Warm metric definition (harness now reports the clean one).** `launch -> 2nd user
   message_end` also contains turn 1's model response, so it is dominated by model behavior, not
   Brain. `scripts/v3_e01_latency.py` now emits a first-class `turn2` block per run — the
   second prompt's pre-dispatch measured from the first `agent_end` (turn 1 fully finished) to
   the second user `message_end`, plus that prompt's own `before_agent_start.hook` /
   `before_agent_start.turn_bridge` durations and its phase spans — and aggregates it as
   `turn2_median_ms`, `turn2_hook_median_ms` and `turn2_incremental_ms` (paired median delta vs
   inert). `turn1_model_ms` is reported alongside to show what is excluded. The raw
   `warm_pre_dispatch_ms` field is retained only for comparability with the S1 definition. The
   metric's arithmetic is verified offline on a synthetic two-prompt event stream (no live runs
   were made while the machine was loaded).
4. **`helper-eager` is strictly worse than lazy** in the one comparable run (Δ +855 vs +747 ms):
   moving the interpreter start into `session_start` does not remove it from the launch→dispatch
   window, and it adds contention while the host boots. It should be dropped unless a longer
   campaign shows otherwise.
5. **Background spawn volume unchanged.** The extension still starts 8+ short-lived Python
   processes per first turn (ledger init + appends, environment assessment, P4 pulse, visibility
   plan, vmem admission). The span data says they overlap the hook window heavily (535 ms of
   overlap) but E01 did not re-route them through the helper; deduplicating/batching that
   background work is the remaining structural cost after this slice.
6. Not run: fault injection against the helper under a live host (kill mid-session, DB locked,
   malformed helper output) — covered by unit tests only
   (`tests/test_turn_bridge.py`, `tests/turn-bridge.test.ts`).
