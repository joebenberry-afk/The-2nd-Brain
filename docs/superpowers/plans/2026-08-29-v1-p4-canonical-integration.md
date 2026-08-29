# v1.0 P4 Canonical Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the frozen P4 roadmap against the existing Second Brain control plane, qualify it with raw evidence and an independent read-back, and freeze/tag the known-good `v1.0.0` baseline.

**Architecture:** Extend the primary SQLite database, existing JSONL telemetry, Improvement Radar, Prime lifecycle bridge, Frontier, Immune, Plasticity, SkillForge, and counterfactual evaluator. Replace the unqualified P4 sidecar persistence with one idempotent primary migration. Use event-driven, bounded local operations; never add an always-on daemon or a second canonical subsystem.

**Tech Stack:** Python 3.11 virtual environment, SQLite/WAL migrations, JSONL telemetry, pytest/ruff/pyright, TypeScript 5/Vitest/ESLint, Prime extension subprocess bridge, Git release artifacts.

## Global Constraints

- Treat `outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md` as the current status authority; historical P4 claims remain untrusted.
- Do not implement V2-A or any later v2 behavior before the v1 release tag.
- Preserve `current raw evidence > current verified memory > historical memory > model recollection`.
- Keep all routine P4 computation deterministic, local, and model-call-free.
- Do not add a hosted service, remote telemetry sink, always-on daemon, vector database, or background dream process.
- Never persist prompts, message content, tool payloads, secrets, or chain-of-thought.
- Preserve missing provider counters as `null`; only the heartbeat's `model_tokens_used=0` invariant is an observed no-model-call result.
- Do not rewrite existing root telemetry; qualify fresh homes and report historical issues honestly.
- Use the existing primary DB, telemetry store, Radar, lifecycle gates, and Prime adapter; no parallel canonical store or policy engine.
- Preserve the 72 untracked user memory files; stage only intentional release files.
- Run Python commands with `PYTHONHOME` and `PYTHONPATH` removed.
- Do not run formatters, linters, or project-wide suites during intermediate tasks; run each required validation once at the final verification gate.

## File map and ownership

| File | Responsibility after this plan |
|---|---|
| `src/second_brain/migrations/0010_p4_operations.sql` | Primary tables for goals, fingerprints, heartbeat state/runs |
| `src/second_brain/goals.py` | Goal lifecycle API backed by primary DB |
| `src/second_brain/fingerprints.py` | Scoped deterministic fingerprint API backed by primary DB |
| `src/second_brain/heartbeat.py` | Configured event-driven probe and due guard |
| `src/second_brain/telemetry.py` | Complete kind/version registry and operational aggregation |
| `src/second_brain/radar.py` | Existing detector plus fingerprint projection |
| `src/second_brain/optimization.py` | Thin proposal/evaluation/activation coordinator over existing authorities |
| `src/second_brain/p4.py` | One bounded CLI operation composing heartbeat and Radar at lifecycle events |
| `src/second_brain/cli.py` | `goals`, `heartbeat`, `p4`, `optimize` command surfaces |
| `brainstem/prime-extension/src/sensors.ts` | Privacy-safe P4 telemetry record builders |
| `brainstem/prime-extension/src/p4-mirror.ts` | Async/final bounded Prime bridge for P4 pulse |
| `brainstem/prime-extension/src/index.ts` | Lifecycle wiring at session start, due turns, and shutdown |
| `brainstem/telemetry/SCHEMA.md` | Current emitted-kind and P4 field contract |
| `scripts/run_v1_p4_qualification.py` | Fresh-home real qualification and raw manifest |
| `scripts/verify_v1_p4_qualification.py` | Separate fresh-process evidence read-back |
| `outputs/reports/v1-p4/` | Raw evidence, manifest, verifier output, final report |
| `outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md` | P4 statuses updated only after proof |
| `projects/second-brain/current-state.md` | Current release state after proof |
| `README.md` | Remove stale P4/v1 completion claims and document verified commands |

P4 contains several coupled capabilities, but they share one persistence schema, one telemetry contract, and one Prime event bridge. Splitting them into independent release plans would leave each subsystem untestable at the required v1 gate; the task boundaries below are independently testable implementation slices.

---

### Task 1: Canonicalize P4 persistence

**Files:**
- Create: `src/second_brain/migrations/0010_p4_operations.sql`
- Modify: `src/second_brain/goals.py:GoalStore`
- Modify: `src/second_brain/fingerprints.py:BottleneckFingerprintStore`
- Create: `tests/test_p4_persistence.py`
- Modify: `tests/test_p4_gaps_live_integration.py`

**Interfaces:**
- Consumes: `second_brain.db.migrate`, `db.connect`, existing `GoalStore` and `BottleneckFingerprintStore` public methods.
- Produces: primary tables `goals`, `goal_events`, `bottleneck_fingerprints`, `heartbeat_state`, and `heartbeat_runs`; both stores migrate and query `paths.db_path(home)`.

- [ ] **Step 1: Write failing persistence tests.**

```python
def test_p4_tables_are_in_primary_database(brain_home):
    GoalStore(brain_home)
    BottleneckFingerprintStore(brain_home)
    conn = db.connect(db.db_path(brain_home))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert {"goals", "goal_events", "bottleneck_fingerprints", "heartbeat_state", "heartbeat_runs"} <= names
    assert not list((brain_home / "state" / "goals").glob("*.sqlite"))
    assert not list((brain_home / "state" / "fingerprints").glob("*.sqlite"))
```

Add a reopen test that creates a goal and fingerprint through one store instance, destroys both instances, opens new instances, and asserts the rows survive. Add a migration-idempotency test that calls `db.migrate()` twice and asserts migration version `10` occurs once. Add a backup/restore test that snapshots the primary database, restores it into a fresh home, and verifies both records survive. Before removing legacy sidecar access, inspect `state/goals/*.sqlite` and `state/fingerprints/*.sqlite`; leave non-empty sidecars untouched and fail with an explicit migration error instead of silently discarding them.

Run:

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_p4_persistence.py
```

Expected: FAIL because migration 0010 and primary-backed stores do not exist.

- [ ] **Step 2: Add the idempotent primary migration.**

Use this SQL shape; keep all user-provided text in parameterized columns and use SQLite checks for statuses and numeric bounds:

```sql
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','BLOCKED','COMPLETED','ABANDONED')),
    milestones_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target_date TEXT,
    completed_at TEXT,
    blocker_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_goals_status_updated ON goals(status, updated_at);
CREATE TABLE IF NOT EXISTS goal_events (
    event_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    milestone_id TEXT,
    evidence_ref TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goal_events_goal_created ON goal_events(goal_id, created_at);
CREATE TABLE IF NOT EXISTS bottleneck_fingerprints (
    fingerprint_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    signal_key TEXT NOT NULL,
    scope_id TEXT NOT NULL DEFAULT '',
    impact_score REAL NOT NULL CHECK (impact_score >= 0 AND impact_score <= 10),
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    description TEXT NOT NULL,
    mitigation TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(category, signal_key, scope_id)
);
CREATE INDEX IF NOT EXISTS idx_bottleneck_rank ON bottleneck_fingerprints(impact_score DESC, occurrence_count DESC);
CREATE TABLE IF NOT EXISTS heartbeat_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_run_at TEXT
);
INSERT OR IGNORE INTO heartbeat_state(singleton, last_run_at) VALUES (1, NULL);
CREATE TABLE IF NOT EXISTS heartbeat_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    issue_codes_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_started ON heartbeat_runs(started_at);
```

- [ ] **Step 3: Move both stores to `db.connect()`.**

In each constructor, call `db.migrate(db.db_path(home))`, retain `Path(home)` normalization, and remove the private `_db_dir`, `_dbfile`, and `executescript(_SCHEMA)` path. Use one connection per operation, commit on success, rollback on `sqlite3.Error`, and close in `finally`. Keep current method names and return dataclasses so existing callers do not change.

- [ ] **Step 4: Bound JSON fields at the storage boundary.**

Cap goal title/description/blocker/evidence strings at the existing project’s small operational limits, cap fingerprint descriptions/mitigations and evidence references at 64 entries, and reject non-finite impact scores or malformed metadata before SQL insertion. Store canonical JSON with sorted keys.

- [ ] **Step 5: Run persistence tests and commit.**

Run the focused test command again; expected: PASS. Commit only the migration, two stores, and persistence tests:

```text
git add src/second_brain/migrations/0010_p4_operations.sql src/second_brain/goals.py src/second_brain/fingerprints.py tests/test_p4_persistence.py tests/test_p4_gaps_live_integration.py
git commit -m "feat(db): canonicalize P4 state"
```

---

### Task 2: Complete the goal state machine

**Files:**
- Modify: `src/second_brain/goals.py:GoalStatus, GoalStore`
- Create: `tests/test_goals_state_machine.py`
- Modify: `tests/test_p4_gaps_live_integration.py`

**Interfaces:**
- Consumes: Task 1 primary `goals` and `goal_events` tables.
- Produces: `GoalStore.transition(goal_id, status, *, evidence_ref=None, blocker_note='') -> LongRunningGoal`, `GoalStore.complete_milestone(goal_id, milestone_id, evidence_ref) -> LongRunningGoal`, `GoalStore.list_goals(statuses=None) -> list[LongRunningGoal]`, and `create_goal(..., initial_status=GoalStatus.ACTIVE)`.
- [ ] **Step 1: Write failing lifecycle tests.**

```python
def test_goal_transitions_and_audit_events(brain_home):
    store = GoalStore(brain_home)
    goal = store.create_goal("release", "finish v1", ["P4", "qualification"])
    assert goal.status is GoalStatus.ACTIVE
    blocked = store.transition(goal.goal_id, GoalStatus.BLOCKED, blocker_note="awaiting verifier")
    assert blocked.status is GoalStatus.BLOCKED
    resumed = store.transition(goal.goal_id, GoalStatus.ACTIVE)
    assert resumed.status is GoalStatus.ACTIVE
    store.complete_milestone(goal.goal_id, "m-1", "test://p4")
    store.complete_milestone(goal.goal_id, "m-2", "report://qualification")
    assert store.get_goal(goal.goal_id).status is GoalStatus.COMPLETED

    conn = db.connect(db.db_path(brain_home))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM goal_events WHERE goal_id = ?", (goal.goal_id,)
        ).fetchone()[0] >= 4
    finally:
        conn.close()
```

Add tests for illegal terminal transitions, empty evidence, unknown milestone, repeated completion, empty-milestone goal, malformed persisted JSON, and `list_goals` status filtering. Run the focused file and expect failure against the current implementation.

- [ ] **Step 2: Define legal transition validation.**

Implement a single transition table in `goals.py`:

```python
_ALLOWED = {
    GoalStatus.PENDING: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.ACTIVE: {GoalStatus.BLOCKED, GoalStatus.COMPLETED, GoalStatus.ABANDONED},
    GoalStatus.BLOCKED: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.COMPLETED: set(),
    GoalStatus.ABANDONED: set(),
}
```

Reject transitions outside this table with `BrainError`, require a non-empty evidence reference for explicit completion, and require a non-empty blocker note when entering `BLOCKED`. Clear `completed_at` only on a legal non-terminal state; set it exactly once on completion.

- [ ] **Step 3: Implement atomic state and audit writes.**

Read the row inside one transaction, parse milestones with `Milestone.from_dict`, validate the requested transition against the current status, update `goals`, insert one `goal_events` row, and commit. For `complete_milestone`, treat an already completed milestone with the same evidence reference as an idempotent success without a second event; reject a different evidence reference. Auto-complete only when the milestone list is non-empty and all milestones are complete.

- [ ] **Step 4: Add list/history accessors and corruption errors.**

Implement `list_goals(statuses=None)` with one ordered query and preserve `list_active_goals()` as an `ACTIVE/BLOCKED` filter. Convert malformed JSON, missing milestone fields, unknown statuses, and missing goal rows into explicit `BrainError` messages naming the goal or database field.

- [ ] **Step 5: Run goal tests and commit.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_goals_state_machine.py tests/test_p4_gaps_live_integration.py
git add src/second_brain/goals.py tests/test_goals_state_machine.py tests/test_p4_gaps_live_integration.py
git commit -m "feat(goals): enforce P4 lifecycle"
```

Expected: all focused tests pass.

---

### Task 3: Implement event-driven heartbeat coordination

**Files:**
- Modify: `src/second_brain/heartbeat.py:LocalHeartbeatEngine`
- Create: `src/second_brain/heartbeat.py:HeartbeatCoordinator, HeartbeatConfig`
- Modify: `src/second_brain/telemetry.py:append_record`
- Modify: `config/brain.toml`
- Modify: `defaults/config/brain.toml`
- Modify: `src/second_brain/cli.py`
- Create: `tests/test_heartbeat_coordinator.py`

**Interfaces:**
- Consumes: Task 1 `heartbeat_state` and `heartbeat_runs`, existing `ActionCacheStore`, existing DB path and Git subprocess conventions.
- Produces: `HeartbeatConfig.load(home)`, `LocalHeartbeatEngine.pulse(repo_dir=None, *, mode='shadow') -> HeartbeatStatus`, `HeartbeatCoordinator.run_if_due(event, session_id, repo_dir=None, *, force=False, now=None) -> dict`.

- [ ] **Step 1: Write failing mode and due-guard tests.**

```python
def test_shadow_is_read_only_and_active_prunes(brain_home, tmp_path):
    shadow = HeartbeatCoordinator(brain_home).run_if_due(
        "session_start", "s1", tmp_path, force=True
    )
    assert shadow["mode"] == "shadow"
    assert shadow["model_tokens_used"] == 0
    assert shadow["maintenance_mutated"] is False

    (brain_home / "config" / "brain.toml").write_text(
        "schema_version = 1\n[heartbeat]\nmode = 'active'\nmin_interval_seconds = 0\n",
        encoding="utf-8",
    )
    active = HeartbeatCoordinator(brain_home).run_if_due(
        "session_shutdown", "s1", tmp_path, force=True
    )
    assert active["mode"] == "active"
    assert active["model_tokens_used"] == 0
```

Add tests for `off`, interval skip, forced shutdown, two concurrent callers yielding one reserved run, missing DB, invalid Git directory, cache-prune failure visibility, and the 256-run retention bound. Run focused tests; expected: failure.

- [ ] **Step 2: Add live configuration with safe defaults.**

Append this to both default and repository `brain.toml` without changing unrelated keys:

```toml
[heartbeat]
mode = "shadow"
min_interval_seconds = 60
max_run_history = 256
```

`HeartbeatConfig.load()` must accept only `off`, `shadow`, and `active`; invalid/unreadable files fall back to shadow/60/256 and return a bounded configuration warning to the caller.

- [ ] **Step 3: Make `pulse()` mode-aware and failure-visible.**

Retain DB `PRAGMA quick_check`, Git dirty detection, and ActionCache integration. In shadow mode inspect expired-cache count without deletion; in active mode call the existing cache prune and include the count. Convert every failed probe to a stable issue code (`db_missing`, `db_integrity`, `cache_probe`, `cache_prune`, `git_probe`) while keeping host failure handling non-throwing. `model_tokens_used` is always integer zero because this code has no model invocation path.

- [ ] **Step 4: Implement the atomic persisted due guard.**

Inside a `BEGIN IMMEDIATE` transaction, read `heartbeat_state.last_run_at`, compare it to `now`, and reserve a new `heartbeat_runs` row only when due or forced. Commit the reservation before probing so concurrent processes cannot duplicate work. Update the row with final status/result and prune the oldest rows after the configured 256 retained runs. If a probe process dies, the reserved timestamp still suppresses retry storms until the interval elapses.

- [ ] **Step 5: Add the CLI surface.**

Add:

```text
brainctl heartbeat run --event session_start --session <id> [--repo <path>] [--force] --json
```

The handler prints the exact coordinator dictionary and appends one privacy-safe `heartbeat_pulse` record through `telemetry.append_record()`; it returns nonzero only for malformed arguments, not for a health result. Keep `--home` inherited from the existing parent parser.

- [ ] **Step 6: Run heartbeat tests and commit.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_heartbeat_coordinator.py
git add src/second_brain/heartbeat.py src/second_brain/cli.py config/brain.toml defaults/config/brain.toml tests/test_heartbeat_coordinator.py
git commit -m "feat(heartbeat): add bounded event coordination"
```

---

### Task 4: Repair telemetry registry and operational reporting

**Files:**
- Modify: `src/second_brain/telemetry.py:KNOWN_KINDS, KIND_SCHEMA_VERSION, validate, report`
- Modify: `brainstem/telemetry/SCHEMA.md`
- Create: `tests/test_operational_telemetry.py`
- Modify: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: existing JSONL records and the exact kind/version inventory emitted by the current Prime/OMP code.
- Produces: strict registry validation for all current kinds plus P4 records; `operational_report(home, since=None) -> dict`; `report()` keeps all existing top-level keys and adds `operational`; `append_record(home, record) -> None` writes only validated bounded records.

- [ ] **Step 1: Write failing registry and report tests.**

```python
def _write_records(home, records):
    path = telemetry.telemetry_dir(home) / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )
def test_current_omp_v3_records_validate(tmp_path):
    _write_records(
        tmp_path,
        [
            {"v": 3, "kind": "omp_routing_invocation", "session": "s", "ts": "2026-08-29T00:00:00Z"},
            {"v": 2, "kind": "heartbeat_pulse", "session": "s", "ts": "2026-08-29T00:00:01Z",
             "mode": "shadow", "event": "session_start", "due": True, "ran": True,
             "healthy": True, "db_ok": True, "cache_pruned_count": 0,
             "git_dirty": False, "issue_codes": [], "latency_ms": 0,
             "model_tokens_used": 0},
        ],
    )
    assert telemetry.validate(tmp_path)["issues"] == []

def test_operational_report_preserves_missing_provider_counters(tmp_path):
    _write_records(
        tmp_path,
        [
            {"v": 2, "kind": "session_start", "session": "s", "ts": "2026-08-29T00:00:00Z",
             "model": "local", "cwd": "/repo"},
            {"v": 2, "kind": "tool_call", "session": "s", "ts": "2026-08-29T00:00:01Z",
             "tool": "read", "input_bytes": 10, "target_sha256": "a" * 64},
            {"v": 2, "kind": "heartbeat_pulse", "session": "s", "ts": "2026-08-29T00:00:02Z",
             "mode": "shadow", "event": "turn_start", "due": True, "ran": True,
             "healthy": True, "db_ok": True, "cache_pruned_count": 0,
             "git_dirty": False, "issue_codes": [], "latency_ms": 0,
             "model_tokens_used": 0},
        ],
    )
    result = telemetry.report(tmp_path)["operational"]
    assert result["provider_tokens"]["input"] is None
    assert result["tool_calls"] == 1
    assert result["heartbeat_runs"] == 1
```

Add a writer test that appends one valid heartbeat record, rejects payload/secret fields, and refuses a session id that escapes the telemetry directory. Run the focused tests; expected: FAIL because the current registry rejects the OMP/P4 kinds, no operational section exists, and no validated writer exists.

- [ ] **Step 2: Register the actual emitted kind set and versions.**

Set `KNOWN_KINDS` to the union of the current repository inventory and the P4 records, including:

```python
KNOWN_KINDS = {
    "OMP_SECOND_BRAIN_READY", "active_state_delivery", "agent_end",
    "assistant_usage", "autoinject_shadow_decision", "before_agent_start",
    "brain_no_injection", "brain_packet_delivered", "brain_retrieval_attempt",
    "claude_code_stop_turn", "codex_hook_shadow_decision", "context",
    "context_paging", "context_structure", "extension_error",
    "hermes_model_decision", "hermes_post_tool_call", "hermes_pre_llm_call",
    "hermes_session_finalized", "hermes_session_started",
    "hermes_worker_context_resolved", "hermes_worker_lifecycle",
    "hermes_worker_result_corrected", "hermes_worker_result_correction_requested",
    "hermes_worker_result_reviewed", "hermes_writeback_candidate", "lean_kernel",
    "model_fallback_used", "model_invocation_completed",
    "model_invocation_failed", "model_invocation_started", "model_routing_decision",
    "omp_routing_decision", "omp_routing_handoff_failure",
    "omp_routing_invocation", "omp_routing_response",
    "omp_visibility_plan", "omp_worker_child_result", "omp_worker_context_failure",
    "omp_worker_context_handoff", "orchestration_record", "orchestrator_policy_violation",
    "preinvocation", "preinvocation_no_task", "prime_tool_surface",
    "provider_request_meta", "provider_response_meta", "rtd_shadow",
    "session_before_compact", "session_compact", "session_finalized",
    "session_shutdown", "session_start", "session_started",
    "simplification_review", "stop_allowed", "stop_blocked",
    "stop_blocked_result", "stop_boundary", "stop_continue",
    "stop_control_result", "stop_finalization_error", "stop_finalized",
    "stop_not_triggered", "tool_call", "tool_result", "turn_end", "turn_start",
    "vmem_compact_prep", "vmem_fault_in", "vmem_hot_context", "writeback_candidate",
    "heartbeat_pulse", "bottleneck_fingerprint", "optimization_proposal",
    "optimization_evaluation", "optimization_activation", "optimization_rollback",
}
```

Set `KIND_SCHEMA_VERSION` to `3` for `assistant_usage`, `provider_request_meta`, `provider_response_meta`, `OMP_SECOND_BRAIN_READY`, `omp_routing_decision`, `omp_routing_handoff_failure`, `omp_routing_invocation`, `omp_routing_response`, `omp_visibility_plan`, `omp_worker_child_result`, `omp_worker_context_failure`, and `omp_worker_context_handoff`; all other registered kinds remain v2. Keep the required common-field checks and never downgrade unknown version evidence.

- [ ] **Step 3: Add bounded P4 field validation and operational aggregation.**

Implement event-specific checks for `heartbeat_pulse` (`mode`, `event`, `due`, `ran`, `healthy`, `db_ok`, `cache_pruned_count`, `git_dirty`, `issue_codes`, `latency_ms`, and `model_tokens_used == 0`), `bottleneck_fingerprint` (category, fingerprint id, non-negative count/impact), and the four optimization records (proposal id, status, and bounded hashes). Return one issue per invalid field with file and line identity.

Implement `operational_report()` in one pass over `iter_records()` using nullable token accumulators. Its returned shape is:

```python
{
    "provider_tokens": {
        "input": int | None,
        "output": int | None,
        "total": int | None,
        "cache_read": int | None,
        "cache_write": int | None,
    },
    "tool_calls": int,
    "tool_result_bytes": int,
    "file_reads": int,
    "file_rereads": int,
    "compactions": int,
    "driver_events": int,
    "worker_events": int,
    "background_events": int,
    "tool_errors": int,
    "extension_errors": int,
    "heartbeat_runs": int,
    "fingerprint_events": int,
    "optimization_events": int,
    "validation_issues": int,
}
```

Use the existing `target_sha256`/tool fields for observable rereads, existing role/model/harness fields for grouped counters, and `None` whenever no provider record reports a counter. Make `report()` call this function and preserve its existing keys. `append_record()` must validate the complete record, enforce the session filename boundary, and append one JSONL line without accepting prompt, payload, secret, or chain-of-thought fields.

- [ ] **Step 4: Document the live schema contract.**

Update `brainstem/telemetry/SCHEMA.md` with the complete current kind table, v3 OMP version rules, and these P4 field contracts:

```text
heartbeat_pulse: mode, event, due, ran, healthy, db_ok, cache_pruned_count,
  git_dirty, issue_codes, latency_ms, model_tokens_used
bottleneck_fingerprint: fingerprint_id, category, scope_id, occurrence_count,
  impact_score, evidence_count, evidence_hash
optimization_*: proposal_id, status, intervention_hash, evidence_hash,
  approval_state, rollback_state
```

State explicitly that P4 telemetry has no content/payload fields and that missing provider economics remain missing.

- [ ] **Step 5: Run telemetry tests and commit.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_operational_telemetry.py tests/test_telemetry.py
git add src/second_brain/telemetry.py brainstem/telemetry/SCHEMA.md tests/test_operational_telemetry.py tests/test_telemetry.py
git commit -m "fix(telemetry): register current operational kinds"
```

Expected: focused tests pass; the existing root stream may still report its three malformed historical lines, which is evidence rather than a reason to rewrite it.

---

### Task 5: Project Radar alerts into scoped fingerprints

**Files:**
- Modify: `src/second_brain/fingerprints.py:BottleneckFingerprint, BottleneckFingerprintStore`
- Modify: `src/second_brain/radar.py:ImprovementRadar.observe_session`
- Modify: `src/second_brain/cli.py:cmd_radar`
- Create: `tests/test_radar_fingerprints.py`
- Modify: `tests/test_radar.py`

**Interfaces:**
- Consumes: Task 1 primary fingerprint table, existing `ImprovementAlert`, Radar telemetry evidence references.
- Produces: `BottleneckFingerprintStore.record_alert(alert, *, scope_id, evidence_refs) -> BottleneckFingerprint`; `ImprovementRadar.observe_session()` still returns the existing candidate list, each candidate gains a bounded `fingerprints` list, and `radar observe --json` flattens those fingerprints at the top level.

- [ ] **Step 1: Write failing Radar-to-fingerprint tests.**

```python
def _write_stream(home, session, target_sha):
    path = telemetry.telemetry_dir(home) / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "v": 2, "kind": "tool_call", "session": session,
            "ts": f"2026-08-29T00:00:0{index}Z",
            "tool": "read", "input_bytes": 10, "target_sha256": target_sha,
        }
        for index in (1, 2, 3)
    ]
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )

def test_radar_observation_deduplicates_scoped_fingerprint(brain_home):
    _write_stream(brain_home, "s1", "a" * 64)
    radar = ImprovementRadar(brain_home)
    first = radar.observe_session("s1", project_id="project-a")
    _write_stream(brain_home, "s2", "a" * 64)
    second = radar.observe_session("s2", project_id="project-a")
    assert first[0]["fingerprints"][0]["occurrence_count"] == 1
    assert second[0]["fingerprints"][0]["occurrence_count"] == 2

def test_fingerprint_scope_does_not_cross_projects(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    a = store.record_bottleneck("TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="a")
    b = store.record_bottleneck("TOOL_CHAIN_THRASH", "same signal", "cache", scope_id="b")
    assert a.fingerprint_id != b.fingerprint_id

def test_fingerprint_has_no_raw_tool_payload(brain_home):
    store = BottleneckFingerprintStore(brain_home)
    row = store.record_bottleneck(
        "UNCOMPRESSED_PAYLOAD", "large result", "artifact", scope_id="p",
        evidence_refs=[{"record_hash": "b" * 64, "output_bytes": 100}],
    )
    encoded = json.dumps(row.to_dict(), sort_keys=True)
    assert "Authorization" not in encoded
    assert "secret-value" not in encoded
```

Run the focused tests; expected: FAIL because the current store has no scope/evidence fields and Radar does not write fingerprints.

- [ ] **Step 2: Add bounded scoped fingerprint storage.**

Extend `record_bottleneck()` with keyword-only `scope_id=""` and `evidence_refs=None`. Normalize a deterministic `signal_key` from category plus a bounded normalized description, hash it into the stable fingerprint id, and upsert by `(category, signal_key, scope_id)`. On repeat, increment occurrence count, retain the maximum impact, update `last_seen`, and merge the latest 64 evidence references by record hash. Return the stored row, not the uncommitted input values. Reject empty categories, non-finite scores, negative counts, and oversized metadata.

- [ ] **Step 3: Map existing Radar patterns without adding a detector.**

Use this deterministic mapping in `radar.py`:

```python
_FINGERPRINT_CATEGORY = {
    InefficiencyPattern.REPEATED_READ: BottleneckCategory.TOOL_CHAIN_THRASH,
    InefficiencyPattern.TOOL_ERROR_LOOP: BottleneckCategory.TOOL_CHAIN_THRASH,
    InefficiencyPattern.SEARCH_THRASH: BottleneckCategory.RETRIEVAL_OVERLOAD,
    InefficiencyPattern.REDUNDANT_TEST_RUN: BottleneckCategory.TOOL_CHAIN_THRASH,
    InefficiencyPattern.CONTEXT_CHURN: BottleneckCategory.PROMPT_BLOAT,
}
```

Convert each alert into a fixed category description and use `project_id` as `scope_id`. Pass only existing Radar `telemetry_evidence_refs` and bounded alert counts. Keep Radar candidate stale validation unchanged. Emit one `bottleneck_fingerprint` record per stored fingerprint through `telemetry.append_record()` without copying the alert summary or raw evidence.

- [ ] **Step 4: Extend the existing Radar CLI payload.**

Add `"fingerprints": [...]` to the `radar observe --json` payload while retaining `candidate_count`, `candidates`, and `radar_overhead_ms`. Make the list deterministic by fingerprint rank and id. Existing callers that ignore the new key remain valid.

- [ ] **Step 5: Run Radar tests and commit.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_radar.py tests/test_radar_fingerprints.py tests/test_p4_gaps_live_integration.py
git add src/second_brain/fingerprints.py src/second_brain/radar.py src/second_brain/cli.py tests/test_radar.py tests/test_radar_fingerprints.py tests/test_p4_gaps_live_integration.py
git commit -m "feat(radar): persist scoped P4 fingerprints"
```

---

### Task 6: Add the governed optimization coordinator

**Files:**
- Create: `src/second_brain/optimization.py`
- Modify: `src/second_brain/cli.py`
- Create: `tests/test_optimization.py`

**Interfaces:**
- Consumes: Task 5 fingerprint ids, existing `credit.counterfactual_result`, `skillforge.record_evaluation`, `frontier`, `promotion`, `immune`, and `plasticity`.
- Produces:

```python
MODES = ("off", "shadow", "active")

def propose(home: Path, fingerprint_id: str, *, skill_name: str,
            intervention_hash: str, mode: str = "shadow") -> dict: ...
def evaluate(home: Path, proposal_id: str, result: dict) -> dict: ...
def activate(home: Path, proposal_id: str, *, session_id: str = "") -> dict: ...
def rollback(home: Path, proposal_id: str, trigger_id: str, reason: str) -> dict: ...
def get_proposal(home: Path, proposal_id: str) -> dict: ...
```

Proposals are immutable evidence records under `outputs/audits/optimization/`; lifecycle changes append a new `<proposal-id>-v<version>.json` record atomically, and `get_proposal()` selects the highest version. No new policy database is allowed.

- [ ] **Step 1: Write failing lifecycle and refusal tests.**

```python
def _seed_candidate(home):
    fp = BottleneckFingerprintStore(home).record_bottleneck(
        "TOOL_CHAIN_THRASH", "candidate signal", "bounded cache", scope_id="second-brain"
    )
    directory = home / "skills" / "candidates" / "candidate"
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- verified"
        for title in (
            "Purpose", "Positive Triggers", "Negative Triggers", "Inputs",
            "Procedure", "Tools", "Safety", "Verification", "Output", "References",
        )
    )
    path = directory / "SKILL.md"
    path.write_text(
        "---\nname: candidate\nstatus: candidate\nversion: 1\n---\n\n" + sections + "\n",
        encoding="utf-8",
    )
    skillforge.bind_candidate(
        home, "candidate", source_type="radar", source_ref=fp.fingerprint_id,
        owner="release-steward", project_id="second-brain",
    )
    return fp.fingerprint_id, skillforge.lifecycle_content_hash(path)

def _passed_evaluation(intervention_hash):
    return {
        "evaluation_id": "eval-candidate", "task_id": "task-candidate",
        "task_hash": "t" * 64, "repository_state_hash": "r" * 64,
        "intervention_hash": intervention_hash,
        "baseline": {"input_tokens": 1000, "output_tokens": 100},
        "candidate": {"input_tokens": 500, "output_tokens": 100},
        "quality": {
            "correctness": True, "requirements": True, "protected_values": True,
            "regressions": False, "verification": True,
        },
        "gates": {
            "trigger": {"failed": 0}, "workflow": {"structural": True, "failed": 0},
            "regression": {"regression": False, "failed": 0},
            "security": {"passed": True},
        },
    }

def test_shadow_proposal_does_not_mutate_skill(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash,
    )
    assert proposal["mode"] == "shadow"
    assert proposal["status"] == "shadow"
    assert not (brain_home / "skills" / "active" / "candidate").exists()

def test_activation_requires_current_evidence_and_frontier(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode="active",
    )
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result == {"activated": False, "reason": "evaluation_not_proven"}

def test_active_proposal_promotes_after_all_gates(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode="active",
    )
    optimization.evaluate(
        brain_home, proposal["proposal_id"], _passed_evaluation(intervention_hash)
    )
    frontier.frontier_review(
        brain_home, "skill-candidate-promotion", "promote", "high",
        "release-reviewer", "approve",
    )
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result["activated"] is True
    assert (brain_home / "skills" / "active" / "candidate" / "SKILL.md").exists()

def test_changed_intervention_cannot_activate(brain_home):
    fingerprint_id, intervention_hash = _seed_candidate(brain_home)
    proposal = optimization.propose(
        brain_home, fingerprint_id, skill_name="candidate",
        intervention_hash=intervention_hash, mode="active",
    )
    optimization.evaluate(
        brain_home, proposal["proposal_id"], _passed_evaluation(intervention_hash)
    )
    frontier.frontier_review(
        brain_home, "skill-candidate-promotion", "promote", "high",
        "release-reviewer", "approve",
    )
    path = brain_home / "skills" / "candidates" / "candidate" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    result = optimization.activate(brain_home, proposal["proposal_id"])
    assert result["activated"] is False
    assert result["reason"] in {"intervention_stale", "evaluation_stale", "frontier_stale"}
```

- [ ] **Step 2: Implement immutable proposal creation.**

Validate identifiers, mode, fingerprint existence, 64-hex intervention hash, and skill existence. Store proposal fields:

```python
{
    "schema_version": 1,
    "proposal_id": "proposal-" + sha256(fingerprint_id + intervention_hash)[:24],
    "fingerprint_id": fingerprint_id,
    "skill_name": skill_name,
    "intervention": {"type": "skill", "id": skill_name, "hash": intervention_hash},
    "mode": mode,
    "status": "shadow",
    "evaluation_ref": None,
    "frontier_change_id": f"skill-{skill_name}-promotion",
    "rollback_policy_id": f"skill-{skill_name}",
    "created_at": utc_now(),
}
```

Use atomic tempfile-plus-`os.replace` writes and refuse replacement when the proposal id already binds a different fingerprint or intervention hash.

- [ ] **Step 3: Attach real evaluation evidence.**

Require the result to contain either a verified `skillforge.record_evaluation()` result or a `credit.counterfactual_result()` reference with distinct run ids, current intervention hash, verification evidence, regression evidence, and actual telemetry economics. Set status `evaluated` only when quality passes and measured net value is positive; otherwise set `hold`. Emit `optimization_evaluation` metadata without copying the evaluation body into telemetry.

- [ ] **Step 4: Gate activation through existing authorities.**

For `active` mode only, re-read the fingerprint and candidate hashes, require `status == evaluated`, `frontier.gate_check(...)["ok"]`, current SkillForge binding/evaluation, explicit owner/version, and no prior immune rollback. Register the exact skill target and baseline hash with `immune.register_policy()`, then call `promotion.promote(home, skill_name, "candidate", "active", session_id)`. On refusal, return `{activated: False, reason: str}` without mutation. Record `optimization_activation` only after a successful move.

- [ ] **Step 5: Wire bounded rollback and Plasticity evidence.**

`rollback()` must require the proposal’s registered trigger/policy identity and delegate to `immune.rollback()`. Record `optimization_rollback` only after the existing guard performs a rollback. Call `plasticity.utility_update()` only from an explicit verified result; never reward every active skill or auto-approve a proposal.

- [ ] **Step 6: Add the CLI lifecycle.**

Add:

```text
brainctl optimize propose <fingerprint-id> --skill <name> --intervention-hash <hex> [--mode off|shadow|active] --json
brainctl optimize evaluate <proposal-id> --result-json <file> --json
brainctl optimize activate <proposal-id> [--session <id>] --json
brainctl optimize rollback <proposal-id> <trigger-id> --reason <text> --json
brainctl optimize show <proposal-id> --json
```

The CLI passes JSON through the coordinator, never accepts raw prompt/tool payload fields, and returns nonzero only for invalid command input or corrupt proposal files.

- [ ] **Step 7: Run optimization tests and commit.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_optimization.py tests/test_promotion.py tests/test_immune.py tests/test_plasticity.py
git add src/second_brain/optimization.py src/second_brain/cli.py tests/test_optimization.py
git commit -m "feat(optimization): gate P4 policy changes"
```

---

### Task 7: Add one bounded Prime P4 bridge

**Files:**
- Create: `src/second_brain/p4.py`
- Modify: `src/second_brain/cli.py`
- Create: `brainstem/prime-extension/src/p4-mirror.ts`
- Modify: `brainstem/prime-extension/src/index.ts`
- Modify: `brainstem/prime-extension/src/sensors.ts`
- Delete: `brainstem/prime-extension/src/radar-mirror.ts`
- Create: `brainstem/prime-extension/tests/p4-mirror.test.ts`
- Modify: `brainstem/prime-extension/tests/wiring.test.ts`
- Delete: `brainstem/prime-extension/tests/radar-mirror.test.ts`

**Interfaces:**
- Consumes: Task 3 heartbeat CLI, Task 5 Radar/fingerprint CLI, existing Prime `TelemetryStore`, `safeHandler`, subprocess timeout, and fail-open conventions.
- Produces:

```python
def pulse(home: Path, *, event: str, session_id: str, repo_dir: Path | None,
          project_id: str | None = None, force: bool = False,
          emit_telemetry: bool = True) -> dict: ...
```

```typescript
export interface P4PulseOptions {
  home: string;
  hostSessionId: string;
  event: string;
  repo?: string;
  projectId?: string;
  force?: boolean;
  python?: string;
  timeoutMs?: number;
}
export interface P4PulseResult {
  ok: boolean;
  sessionId?: string;
  heartbeat?: Record<string, unknown>;
  candidates?: Record<string, unknown>[];
  fingerprints?: Record<string, unknown>[];
  error?: string;
}
export function runP4PulseSync(options: P4PulseOptions): P4PulseResult;
export function runP4Pulse(options: P4PulseOptions): Promise<P4PulseResult>;
```

- [ ] **Step 1: Write failing Python composition tests.**

```python
def test_p4_pulse_runs_heartbeat_and_shutdown_radar(brain_home, tmp_path):
    result = p4.pulse(
        brain_home,
        event="session_shutdown",
        session_id="s1",
        repo_dir=tmp_path,
        project_id="second-brain",
        force=True,
    )
    assert result["heartbeat"]["model_tokens_used"] == 0
    assert "candidates" in result
    assert "fingerprints" in result
```

Add tests that `session_start`/`turn_start` omit Radar unless requested, shutdown includes it, a missing optional project id does not crash, and the default path writes exactly one heartbeat record while `--no-telemetry` leaves the JSONL unchanged. Run focused Python tests; expected: FAIL.

- [ ] **Step 2: Implement `p4.pulse` and CLI dispatch.**

`p4.pulse()` calls `HeartbeatCoordinator.run_if_due()` for every lifecycle event and calls `ImprovementRadar.observe_session()` only for shutdown when `project_id` is present. When `emit_telemetry` is true, append one heartbeat record and any bounded fingerprint records through `telemetry.append_record()`; when false, return the same JSON-safe result without writing P4 records. Return one JSON-safe dictionary:

```python
{
    "session_id": session_id,
    "event": event,
    "heartbeat": heartbeat_result,
    "candidate_count": len(candidates),
    "candidates": candidates,
    "fingerprints": fingerprints,
}
```

Add:

```text
brainctl p4 pulse --event <event> --session <id> [--repo <path>] [--project-id <id>] [--force] [--no-telemetry] --json
```

The handler returns a health result with exit code zero; malformed arguments and corrupt state remain explicit command errors.

- [ ] **Step 3: Add privacy-safe TypeScript sensor builders.**

Add `heartbeatPulse(session, result)`, `bottleneckFingerprint(session, fingerprint)`, and `optimizationEvent(session, kind, metadata)` to `sensors.ts`. Accept only enumerated strings, booleans, non-negative numbers, 64-hex hashes, counts, and bounded issue codes. Never serialize `candidates[].summary`, proposal bodies, command text, or tool payloads.

- [ ] **Step 4: Implement async/final bridge behavior.**

`p4-mirror.ts` follows the existing `radar-mirror.ts` contract: resolve the Brain venv, remove `PYTHONHOME`/`PYTHONPATH`, set `SECOND_BRAIN_HOME`, invoke `python -m second_brain p4 pulse --no-telemetry`, enforce a 5-second timeout and 1 MiB output bound, verify returned `session_id`, and return `{ok:false,error}` on all failures. Async calls use `execFile`; final shutdown uses `execFileSync`.

- [ ] **Step 5: Wire lifecycle hooks without blocking normal turns.**

At `session_start` and `turn_start`, queue `runP4Pulse()` and append returned heartbeat metadata to the existing store. At `session_shutdown`, call `runP4PulseSync()` before the existing final store write, append heartbeat/fingerprint records, and retain the current session-inactive mirror. Every bridge error becomes a bounded `extension_error`; no error changes the host return value.

Remove the direct `radar-mirror.ts` import and its tests after the new bridge wiring is in place. Update wiring mocks to assert the new calls and the existing final-handler guarantee.

- [ ] **Step 6: Run Prime tests and commit.**

```text
cd brainstem/prime-extension
npm test -- --reporter=dot
cd ../..
git add src/second_brain/p4.py src/second_brain/cli.py brainstem/prime-extension/src/p4-mirror.ts brainstem/prime-extension/src/index.ts brainstem/prime-extension/src/sensors.ts brainstem/prime-extension/tests/p4-mirror.test.ts brainstem/prime-extension/tests/wiring.test.ts
git rm brainstem/prime-extension/src/radar-mirror.ts brainstem/prime-extension/tests/radar-mirror.test.ts
git commit -m "feat(prime): wire bounded P4 operations"
```

Run the Python P4 composition tests from the repository root before committing.

---

### Task 8: Build real qualification and independent read-back

**Files:**
- Create: `scripts/run_v1_p4_qualification.py`
- Create: `scripts/verify_v1_p4_qualification.py`
- Create: `tests/test_v1_p4_qualification.py`

**Interfaces:**
- Consumes: all prior P4 APIs, CLI commands, actual repository root, real command/test outputs, and fresh temporary Brain homes.
- Produces: `outputs/reports/v1-p4/qualification-manifest.json`, raw scenario artifacts, `outputs/reports/v1-p4/independent-verifier.json`, and a nonzero exit code for any failed gate.
- API: `run_qualification(out_dir: Path, repo: Path) -> dict` returns the manifest dictionary and leaves all raw artifacts under `out_dir`.

- [ ] **Step 1: Write runner contract tests.**

```python
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
def test_qualification_manifest_has_all_required_scenarios(tmp_path):
    manifest = run_qualification(tmp_path / "out", repo=REPO_ROOT)
    names = {row["name"] for row in manifest["scenarios"]}
    assert names == {
        "fresh_session", "resumed_session", "compacted_session",
        "cross_session_continuity", "harness_isolation", "harness_switch",
        "driver_worker", "failed_worker", "malformed_state", "stale_state",
        "token_pressure", "cache_sensitive", "long_running_goal",
        "brain_off", "brain_on", "recovery_rollback",
        "security_boundary", "genuine_project_dogfood",
    }
    assert manifest["git"]["sha"]
```

The test must assert that all scenario records carry `evidence_refs`, `status`, `commands`, and a `metrics` object whose unavailable counters are `None`. It must reject a manifest with hard-coded fake `model`, `token`, or `success` values not found in raw artifacts.

- [ ] **Step 2: Implement fresh-home setup and raw command capture.**

The runner must create a temporary fresh Brain home, execute the real CLI initialization, register the real repository as project `second-brain`, and write every subprocess command’s return code/stdout/stderr/sha256 to a raw artifact. Use this sanitized environment:

```python
env = {key: value for key, value in os.environ.items()
       if key not in {"PYTHONHOME", "PYTHONPATH"}}
env["SECOND_BRAIN_HOME"] = str(home)
```

Read the source Git SHA with `git rev-parse HEAD`, capture the actual Prime package version from its package metadata, and never substitute a literal model identity or token count.

- [ ] **Step 3: Implement the 18 scenario functions.**

Use the following observable actions and evidence boundaries:

| Scenario | Required real action |
|---|---|
| `fresh_session` | initialize a fresh home, run `doctor --json`, `p4 pulse --event session_start` |
| `resumed_session` | reopen the same home in a new process, read the same goal and telemetry |
| `compacted_session` | append real ledger checkpoint/compact records and run the existing compact path |
| `cross_session_continuity` | create a goal in one session and read it from a second session |
| `harness_isolation` | create two session ids and prove their telemetry files/counters remain separated |
| `harness_switch` | use Python CLI then Prime bridge against the same home and compare primary rows |
| `driver_worker` | invoke the existing bounded worker protocol with real task/result packets |
| `failed_worker` | pass a real failing worker command and capture retryable/status evidence |
| `malformed_state` | corrupt an isolated copy of a goal/ledger record and assert explicit refusal |
| `stale_state` | alter a referenced telemetry line and assert Radar/optimization stale refusal |
| `token_pressure` | feed an oversized real tool result through existing artifact/RTD limits and capture bytes |
| `cache_sensitive` | execute an existing ActionCache proof twice and capture hit/miss evidence |
| `long_running_goal` | create, block, resume, complete milestones across fresh processes |
| `brain_off` | run the same local operation with P4 mode `off` and capture zero P4 mutations |
| `brain_on` | run it with P4 mode `shadow` or `active` and capture actual P4 records |
| `recovery_rollback` | apply a guarded test policy, ingest a real failing metric, and exercise Immune rollback |
| `security_boundary` | attempt path traversal/Constitution target and capture refusal without mutation |
| `genuine_project_dogfood` | run the repository’s real focused P4 test/CLI workflow against the registered project |

Failure-injection rows are labeled resilience evidence; only `genuine_project_dogfood` and actual repository operations support dogfood claims.

- [ ] **Step 4: Capture actual economics and telemetry.**

For every scenario, derive counters from `telemetry.session_usage`, `session_tool_calls`, `session_wall_time_ms`, and `telemetry.report`; keep `None` for absent provider usage. Include incremental P4 process latency, context/tool bytes, compactions, worker/driver counts, background model calls, errors, and rollback records. Mark `background_model_calls=0` only when the raw operation path proves no model invocation occurred.

- [ ] **Step 5: Implement the independent verifier.**

`verify_v1_p4_qualification.py` reads the manifest from disk in a fresh process and rejects it unless:

1. every required scenario exists exactly once;
2. every raw artifact hash matches its manifest reference;
3. source Git SHA and repository root are current;
4. the fresh DB passes `PRAGMA integrity_check`, migration replay is idempotent, and P4 tables are in `brain.sqlite`;
5. fresh telemetry has no parse, kind, version, or P4-field issues;
6. backup/restore preserves a created goal and fingerprint;
7. stale Radar evidence and unsafe rollback targets are refused;
8. OFF does not mutate P4 state and SHADOW performs no maintenance mutation;
9. model/token claims are supported by raw telemetry or remain null;
10. no artifact contains prompt text, tool payloads, secrets, or chain-of-thought markers.

Write the verifier result and return exit code 0 only when all checks pass. The release gate treats a missing verifier result as a failure.

- [ ] **Step 6: Run the qualification and commit raw evidence.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe scripts/run_v1_p4_qualification.py --repo . --out outputs/reports/v1-p4
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe scripts/verify_v1_p4_qualification.py --manifest outputs/reports/v1-p4/qualification-manifest.json --out outputs/reports/v1-p4/independent-verifier.json
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q tests/test_v1_p4_qualification.py
```

Do not continue to release documentation if either command exits nonzero. Commit only the runner, verifier, their tests, and raw evidence that the repository convention tracks.

---

### Task 9: Apply the v1 release gate and freeze the baseline

**Files:**
- Create: `outputs/reports/v1-p4/qualification-report.md`
- Modify: `outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`
- Modify: `projects/second-brain/current-state.md`
- Modify: `README.md`
- Create: `outputs/reports/v1-release-baseline.md`

**Interfaces:**
- Consumes: Task 8 qualification manifest/verifier plus all focused/full validation output.
- Produces: evidence-backed P4 statuses, v1 economics baseline, a clean release commit, and annotated `v1.0.0` tag.

- [ ] **Step 1: Run final required checks once.**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m ruff check src tests scripts
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pyright
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q
cd brainstem/prime-extension
npm run lint
npm run typecheck
npm test -- --reporter=dot
```

Record exact exit codes and output hashes in the release report. Do not call the root historical telemetry clean merely because fresh qualification is clean.

- [ ] **Step 2: Write the evidence-backed release report.**

`qualification-report.md` must link every P4.1–P4.5 row to raw scenario artifacts, list the independent verifier result, state known historical telemetry issues separately, and include these measured baseline keys:

```text
v1_total_tokens
v1_verified_tasks
v1_context_peak
v1_repeated_reads
v1_files_read
v1_tool_calls
v1_compactions
v1_driver_tokens
v1_worker_tokens
v1_premium_model_turns
v1_cache_behavior
v1_user_corrections
v1_rework
```

Use `null` where the host did not expose a metric. Include P4 incremental process latency, model calls, tool calls, context bytes, cache impact, success, verification, and rollback evidence.

- [ ] **Step 3: Update only current documentation.**

Change the authoritative status ledger’s P4.1–P4.5 rows from `NOT QUALIFIED` to `PROVEN` only with direct artifact links and verifier checks. Update `projects/second-brain/current-state.md` and `README.md` to state the actual v1 tag and remaining v2 boundary. Do not rewrite historical `rc2`/`rc3` reports; mark their P4 claims as historical where needed.

- [ ] **Step 4: Record migration and recovery instructions.**

Document that `db.migrate()` applies migration 0010, that goals/fingerprints/heartbeat records live in `db/brain.sqlite`, and that existing backup/restore includes them through the primary DB snapshot. Include commands for fresh init, reopen, backup, restore, telemetry validation, and guarded rollback.

- [ ] **Step 5: Check release staging and create the tag.**

Verify that only intentional tracked files are staged and the 72 untracked memory files remain untouched. Refuse to overwrite an existing tag:

```text
git tag --list v1.0.0
git add src/second_brain/migrations/0010_p4_operations.sql src/second_brain/goals.py src/second_brain/fingerprints.py src/second_brain/heartbeat.py src/second_brain/telemetry.py src/second_brain/radar.py src/second_brain/optimization.py src/second_brain/p4.py src/second_brain/cli.py config/brain.toml defaults/config/brain.toml tests/test_p4_persistence.py tests/test_p4_gaps_live_integration.py tests/test_goals_state_machine.py tests/test_heartbeat_coordinator.py tests/test_operational_telemetry.py tests/test_telemetry.py tests/test_radar_fingerprints.py tests/test_radar.py tests/test_optimization.py tests/test_v1_p4_qualification.py brainstem/telemetry/SCHEMA.md brainstem/prime-extension/src/p4-mirror.ts brainstem/prime-extension/src/index.ts brainstem/prime-extension/src/sensors.ts brainstem/prime-extension/tests/p4-mirror.test.ts brainstem/prime-extension/tests/wiring.test.ts scripts/run_v1_p4_qualification.py scripts/verify_v1_p4_qualification.py outputs/reports/v1-p4 outputs/reports/v1-release-baseline.md outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md projects/second-brain/current-state.md README.md
git commit -m "release: freeze v1.0.0"
git tag -a v1.0.0 -m "Second Brain v1.0.0"
```

The tag is permitted only after the independent verifier and all final checks pass. If any correctness, security, evidence, or economics gate fails, preserve the failure artifacts, do not tag, and do not begin V2-A.

- [ ] **Step 6: Perform post-tag smoke verification.**

In a new process, run `brainctl doctor --json`, `brainctl status`, `brainctl heartbeat run --event session_start --session release-smoke --force --json`, and `brainctl telemetry report --json` against the tagged checkout. Confirm the tag resolves to the release commit and the smoke output references primary P4 tables without mutating Constitution or user memory files.