# T4.3 — Harness capability profiles and three tiers — report

## Migration

`src/second_brain/migrations/0015_harness_capabilities.sql` (new). Number
reconciliation: re-globbed `src/second_brain/migrations/*.sql` immediately
before writing the file; the highest existing prefix was `0014` (T4.1
`0014_worker_leases.sql`) and no other in-flight change claimed `0015`, so
`0015` was used as-is — **no reconciliation was required**.

Schema (exact, per brief):

```sql
CREATE TABLE IF NOT EXISTS harness_capabilities (
    harness_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    supported INTEGER NOT NULL,
    version TEXT,
    observed_at TEXT NOT NULL,
    evidence_json TEXT,
    PRIMARY KEY(harness_id, capability)
);
CREATE INDEX IF NOT EXISTS idx_harness_capabilities_harness ON harness_capabilities(harness_id);
```

`supported` is `INTEGER` storing `0`/`1`, matching this codebase's existing
bool-ish-flag convention (`worker_tasks`/ledger's `pinned INTEGER`).
Self-healing apply follows `worker_protocol._worker_db`'s exact pattern,
replicated locally in `capabilities._capabilities_db` (via `paths.db_path`
+ `db.pending_migrations`/`db.migrate`) — `capabilities.py` still imports
no other `second_brain` module (only `db`, `paths`), so no new cycle risk.

## capabilities.py extension (T4.3)

Added, without touching `get_provider_capabilities` or its constants:

- `KNOWN_CAPABILITIES` — exact frozenset of the 10 required capability
  names.
- `UnknownCapabilityError(ValueError)` — raised by `declare()` (and
  produces an empty no-op, not a raise, from `observe()`; see below) for
  any capability name outside the vocabulary — a caller-contract
  violation, loud by design, unlike `get_provider_capabilities`'s
  fail-open behavior on untrusted config-file input.
- `observe(home, harness_id, event_kind)` — maps a **known telemetry
  event kind** (untrusted/evolving external input) to 1+ capabilities,
  upserting each `supported=1` with `evidence_json={"event_kind":...,
  "observed_at":...}`. Idempotent (`ON CONFLICT ... DO UPDATE`); an
  unmapped `event_kind` is a deterministic no-op (never raises, capability
  table unchanged, returns `()`).
- `declare(home, harness_id, capability, supported, *, version=None,
  evidence=None)` — explicit adapter-declared state; validates
  `capability` against `KNOWN_CAPABILITIES` (raises
  `UnknownCapabilityError`) and requires `supported` to be an actual
  `bool` (raises `TypeError` — no truthy-string coercion, matching
  T4.1/T4.2's strict-bool convention for `approved`/`retryable`). Explicit
  `False` persists distinctly from "never recorded."
- `list_capabilities(home, harness_id)` — always returns all 10 keys;
  never-recorded capabilities read back as
  `{"supported": None, "version": None, "observed_at": None, "evidence":
  None}`. Shared by `harness_tier` and the CLI so neither duplicates SQL.
- `harness_tier(home, harness_id) -> "T0"|"T1"|"T2"` — T2 wins if any of
  `model_rewrite/tool_filter/subagents/budget_enforcement` is
  `supported=true`; else T1 if any of
  `tool_events/usage_telemetry/cache_telemetry/compaction_events` is
  `supported=true`; else T0 (the floor, including zero recorded rows).
- `TIER_BEHAVIOR = {"T0": ..., "T1": ..., "T2": ...}` — declared once in
  `capabilities.py`; the shared source other future tasks should import
  rather than redeclare. This task's own genuinely-touched feature module
  is only `capabilities.py`, so no other module was given a `TIER_BEHAVIOR`
  constant or new tier-gated behavior.
- `tier_behavior(home, harness_id)` — the one narrow, real caller-visible
  read helper proving `harness_tier` actually gates behavior (see test
  below); intentionally not wired into any other adapter.

## Kind-to-capability mapping (evidence)

Ground truth: `telemetry.KNOWN_KINDS` (`src/second_brain/telemetry.py:18-48`)
and `brainstem/telemetry/SCHEMA.md`. `_EVENT_KIND_CAPABILITIES` in
`capabilities.py`:

| capability | mapped event_kind(s) | evidence |
|---|---|---|
| `session_events` | `session_start`, `session_started`, `session_finalized`, `session_shutdown`, `session_compact`, `session_before_compact` | All 6 are in `telemetry.KNOWN_KINDS` and are session-lifecycle kinds per `SCHEMA.md` rows for each (`session_start`, `session_started` "P3a Claude Code adapter... SessionStart", `session_shutdown`, `session_before_compact`, `session_compact`). |
| `prompt_injection` | `brain_packet_delivered`, `brain_no_injection`, `autoinject_shadow_decision`, `codex_hook_shadow_decision` | `SCHEMA.md` rows: `autoinject_shadow_decision` ("decision, reason, ... delivery_id..."), `codex_hook_shadow_decision` ("logged by brainstem/codex-hooks/run.ps1"), `brain_packet_delivered` ("Python AutoInject pipeline, `second_brain/autoinject.py`"); `brain_no_injection` is in `KNOWN_KINDS` and is `autoinject.py`'s no-injection decision counterpart (grepped alongside `brain_packet_delivered` in `governor.py`/`autoinject.py` decision paths). |
| `tool_events` | `tool_call`, `tool_result`, `claude_code_tool_result` | `SCHEMA.md` rows `tool_call`/`tool_result`; `claude_code_tool_result` is in `telemetry.KNOWN_KINDS` (Claude Code adapter tool-result kind, mirrors `tool_result`). |
| `usage_telemetry` | `assistant_usage`, `provider_request_meta`, `provider_response_meta` | `SCHEMA.md` "Additive schema v3 records emitted by the Prime extension... from the provider hooks" section, describing exactly these 3 kinds as token/cost/request/response usage metadata (v=3, P3-B). |
| `cache_telemetry` | **none** (`declare()`-only) | Grepped `cache_read_tokens|cache_write_tokens|cache_hit|cacheRead|cacheWrite` across `src/` and `brainstem/`: every hit is a *field* on a kind whose primary purpose is something else — `cache_read_tokens`/`cache_write_tokens` are fields of `assistant_usage` (already mapped to `usage_telemetry`); `cache_hit` is a field of `autoinject_shadow_decision` (already mapped to `prompt_injection`) and of `omp_worker_context_handoff`/`hermes_worker_lifecycle`/`hermes_worker_context_resolved`/`worker-context-bridge.ts` (subagent context-reuse bookkeeping, already mapped to `subagents`). No kind's own distinct purpose is "report prompt-cache read/write/hit telemetry" — that would double-count an already-mapped kind under a second capability without new evidence. `cache_telemetry` is therefore currently **unreachable via `observe()`** and can only be set via `declare()` (e.g. once a harness's own hooks.json documents native prompt-cache telemetry). |
| `compaction_events` | `session_compact`, `session_before_compact` | Same two kinds also genuinely evidence `session_events` (see above) — `SCHEMA.md`: `session_before_compact` "branch_entries", `session_compact` "from_extension"; `governor.py:434` treats `session_compact` as a compaction counter (`tokens.compactions += 1`). One kind legitimately maps to two capabilities here because both are independently true of the same event. |
| `model_rewrite` | `rtd_shadow` only | `SCHEMA.md` `rtd_shadow` row + the "Phase P3-F addition (RTD substitution)" section: RTD genuinely *replaces the model-visible tool-result content* with a distilled block before the model sees it — the only kind in `KNOWN_KINDS` that evidences content actually being rewritten. `hermes_model_decision` (`hermes_adapter.py:1455-1458`, `SCHEMA.md` absent, only in `KNOWN_KINDS`), `model_fallback_used`, `model_invocation_started/completed/failed`, and `model_routing_decision` (`hermes_adapter.py:1449-1706`, `SCHEMA.md:53-57`) were all grepped and read: every one carries `decision_id`/`selected_provider`/`selected_model`/`selected_tier`/`fallback_used` fields — model **selection/dispatch** bookkeeping (which provider/model was chosen or retried), never prompt/content rewriting. Deliberately **not** mapped to `model_rewrite` to avoid conflating routing with rewriting. |
| `tool_filter` | `stop_blocked`, `stop_allowed`, `orchestrator_policy_violation` | `cli.py:3527-3528` emits `stop_allowed` from the STOP decision path (tool/termination gating); `stop_blocked` is its sibling in `telemetry.KNOWN_KINDS`; `orchestrator_policy_violation` (`SCHEMA.md` "Phase 1 addition") is an explicit tool/action policy-violation detector with an enumerated `violation`/`blocked` field — genuine tool-filtering evidence. |
| `subagents` | `omp_worker_context_handoff`, `omp_worker_child_result`, `hermes_worker_lifecycle`, `handoff_sent` | `SCHEMA.md` rows for `omp_worker_context_handoff`/`omp_worker_child_result` ("OMP task tool bridge"); `hermes_adapter.py:797-798,955-956` emits `hermes_worker_lifecycle`; `hermes_adapter.py:845-846` emits `handoff_sent` for worker dispatch — all four are subagent spawn/handoff/result bookkeeping. |
| `budget_enforcement` | **none** (`declare()`-only) | Grepped `budget|governor` across `telemetry.py`/`SCHEMA.md`: zero hits — `budget_enforcement` has no entry in `telemetry.KNOWN_KINDS` at all. Read `governor.py`'s T3.1 `check_budget()` (lines ~815-839): it returns `{"state": "OK"/"SOFT"/"HARD", ...}` directly to its caller and is **never appended as a telemetry JSONL record**. Its SOFT-state caller-visible trace (`autoinject.py:241-260`, `_record_budget_soft`) writes to the **separate `decisions` ledger** (`decisions.record(..., kind="budget", ...)`), not a `telemetry.KNOWN_KINDS` JSONL kind that `observe()` maps. `budget_enforcement` is therefore currently **unreachable via `observe()`** and can only be set via `declare()`. |

## Tests (focused; `tests/test_capabilities.py` — T2.6 file extended, no
new file created)

Run: `PYTHONHOME` cleared, `PYTHONPATH=src`, `.venv\Scripts\python.exe -m
pytest tests/test_capabilities.py -q` → **22 passed** (13 pre-existing T2.6
tests unchanged + 9 new T4.3 tests):

- `test_migration_0015_fresh_create_and_idempotent` — schema/index shape +
  second `db.migrate` is a no-op (matches `test_memory_index.py`'s
  fresh-create/reopen-idempotent convention).
- `test_tier_from_observed_events` — `observe()` walks a harness T0 → T1
  (`tool_call`) → T2 (`omp_worker_context_handoff`).
- `test_observe_session_compact_maps_to_two_capabilities` — proves the
  one-kind-to-two-capabilities case with real evidence.
- `test_observe_is_idempotent_upsert` — repeat `observe()` never errors.
- `test_feature_degrades_to_lower_tier_behavior` — `tier_behavior()` (the
  real caller-visible helper) degrades T2 → T1 → T0 as `declare(...,
  False)` removes capabilities, not just the tier string.
- `test_unknown_capability_never_assumed` — unmapped `event_kind` is a
  true no-op; `declare()` with an invalid capability name raises
  `UnknownCapabilityError`; never-recorded capability reads back as
  `supported=None` on both an empty and a populated harness.
- `test_declare_rejects_non_bool_supported` — `TypeError` on a truthy
  string.
- `test_declare_persists_explicit_false_distinct_from_never_recorded` —
  explicit `False` != `None`.
- `test_cli_v2_harness_capabilities_json_output_shape` — `brainctl v2
  harness capabilities <id> --json` shape (`harness_id`, `tier`,
  `tier_behavior`, per-capability dict); also proves the command is
  read-only (state before/after a non-`--json` invocation is identical).

Regression spot-check on the shared `cli.py` edit (import list, dispatch
table, new parser block) only — not a full-suite run:
`pytest tests/test_p4.py tests/test_worker_lifecycle.py -q` → **34 passed**.

## CLI

`brainctl v2 harness capabilities <harness_id> [--json]` — new `v2` →
`harness` → `capabilities` nested subparser group (no `v2` group existed
before this task). Read-only: only calls the same self-healing
pending-migration check every other command tolerates (via
`list_capabilities`/`harness_tier`), never mutates rows.

## Real qualification limitations

- No live harness install (no real `hooks.json`/plugin manifest for
  Claude Code, Codex, Antigravity, or Hermes) was available to drive
  `declare()` end-to-end from an actual adapter manifest read. What is
  exercised is unit-level: `declare()`/`observe()` against a real
  migrated `brain_home` SQLite DB, real `db.connect`/`ON CONFLICT` upsert
  semantics, and a real `cli.main([...])` invocation reading the same DB
  back out — i.e., the full storage + tier + CLI contract is proven
  against the real database, just not against a real third-party
  hooks.json parser (none exists in this codebase to adapt to).
- `cache_telemetry` and `budget_enforcement` have no `observe()` path
  today (see mapping table above) — this is a real, documented gap, not
  an oversight: no kind in `telemetry.KNOWN_KINDS` unambiguously reports
  either today. Both remain reachable via `declare()` only.

## Commit

`brain(adapter): capability profiles and tiers`
