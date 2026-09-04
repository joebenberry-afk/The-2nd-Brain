"""P0 AutoInject SHADOW pipeline (Phase 0C; plan §6.1-6.8, 6.11, 17.1 AutoInject).

Deterministic decision/packet/delivery tests: sparse injection, validity
gate (project/scope, superseded, contradiction), dedupe on active lineage,
budget caps, fail-open, migration 0008, and the `brainctl autoinject shadow`
CLI. SHADOW means: decide + record only, never mutate model context.
"""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import autoinject, db, paths, semantic
from second_brain.contracts import (
    BrainDeliveryRecord,
    BrainInjectionDecision,
    BrainPacket,
    BrainSessionIdentity,
    InjectionDecision,
    NoInjectionReason,
    PacketItem,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _add(
    home: Path,
    title: str,
    body: str,
    *,
    project_id: str | None = "proj-a",
    scope: str = "project",
    grade: str = "TESTED",
) -> str:
    return semantic.add_memory(
        home, title, body, scope=scope, project_id=project_id, grade=grade
    )


def _activate(home: Path, memory_id: str) -> None:
    semantic.curate(home, memory_id, status="current")


def _seed_current(home: Path, title: str, body: str, **kw) -> str:
    mid = _add(home, title, body, **kw)
    _activate(home, mid)
    return mid


def _inject(home: Path, task: str, **kw) -> BrainInjectionDecision:
    """Default BrainLifecycle prepare_injection for tests (proj-a, s1, main)."""
    session_id = kw.pop("session_id", "s1")
    branch_id = kw.pop("branch_id", "main")
    return autoinject.BrainLifecycle(home).prepare_injection(
        task,
        project_id=kw.pop("project_id", "proj-a"),
        agent_id=kw.pop("agent_id", "a1"),
        role_profile=kw.pop("role_profile", "worker"),
        session_id=session_id,
        branch_id=branch_id,
    )


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=120,
    )

def _make_brain(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal migrated Brain home (mirrors tests/conftest.make_brain)."""
    import shutil

    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home))
    paths.ensure_layout(home)
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    cfg = home / "config"
    for name in paths.REQUIRED_CONFIG_FILES:
        (cfg / name).write_text("schema_version = 1\n", encoding="utf-8")
    shutil.copytree(REPO_ROOT / "templates", home / "templates", dirs_exist_ok=True)
    db.migrate(db.db_path(home))
    return home


def _delivery_rows(home: Path) -> list[dict]:
    conn = db.connect(db.db_path(home))
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM deliveries ORDER BY memory_id, memory_version"
            ).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sparse AutoInject: no memory, wrong project, unrelated project
# ---------------------------------------------------------------------------


def test_no_relevant_memory_yields_no_injection(brain_home) -> None:
    d = _inject(brain_home, "quantum entanglement of pasta shapes")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.NO_RELEVANT_MEMORY
    assert d.selected_ids == []
    assert d.packet_ref is None

def test_gate_uses_computed_score_not_fallback_constant(brain_home, monkeypatch):
    mid = _seed_current(brain_home, "Low score gate memory", "low score gate query")
    config = brain_home / "config" / "retrieval.toml"
    config.write_text(
        "schema_version = 2\n[gate]\nrollout = \"ACTIVE\"\n",
        encoding="utf-8",
    )

    def low_score_rank(rows, *args, **kwargs):
        for row in rows:
            row["_score"] = 0.2
        return rows

    monkeypatch.setattr(semantic, "_rank_rows", low_score_rank)
    d = _inject(brain_home, "low score gate query", session_id="low-score-gate")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.LOW_CONFIDENCE
    assert d.selected_ids == []
    assert mid in d.candidate_ids
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT kind, propensity FROM decisions WHERE session_id = ?",
            ("low-score-gate",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["kind"] == "retrieval"
    assert row["propensity"] == 1.0


def test_wrong_project_memory_not_injected(brain_home) -> None:
    _seed_current(brain_home, "WAL restore safety", "never leave -wal next to restored db")
    d = _inject(brain_home, "WAL restore safety", project_id="proj-b")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.WRONG_PROJECT
    assert d.selected_ids == []


def test_global_scope_memory_valid_for_any_project(brain_home) -> None:
    mid = _seed_current(
        brain_home, "Global law", "always verify before retry", scope="global", project_id=None
    )
    d = _inject(brain_home, "verify before retry", project_id="proj-b")
    assert d.decision is InjectionDecision.INJECT
    assert d.selected_ids == [mid]


# ---------------------------------------------------------------------------
# Canonical packet determinism + supersede deltas
# ---------------------------------------------------------------------------


def test_relevant_current_injects_deterministic_packet(brain_home) -> None:
    _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    a = _inject(brain_home, "migration ordering")
    b = _inject(brain_home, "migration ordering", branch_id="other-branch")
    assert a.decision is InjectionDecision.INJECT
    assert b.decision is InjectionDecision.INJECT
    assert a.packet_ref == b.packet_ref  # stable packet id for same content
    assert a.selected_ids == b.selected_ids


def test_superseded_never_current_and_delta_emitted(brain_home) -> None:
    mid = _seed_current(brain_home, "Retry policy", "retry once then fail")
    semantic.supersede(
        brain_home,
        mid,
        new_title="Retry policy v2",
        new_body="retry twice then fail",
        change_note="policy updated",
    )
    d = _inject(brain_home, "retry policy")
    assert d.decision is InjectionDecision.INJECT
    # The packet must reference v2 only and carry the supersede delta.
    packet = autoinject.render_packet(d)
    assert packet is not None
    assert f"ITEM {mid}@2" in packet
    assert f"UPDATE {mid} v2 supersedes {mid} v1" in packet
    assert f"ITEM {mid}@1" not in packet


def test_contradiction_withheld_per_policy(brain_home) -> None:
    _seed_current(brain_home, "Cache setting", "cache on")
    _seed_current(brain_home, "Cache setting", "cache off")
    d = _inject(brain_home, "cache setting")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.CONTRADICTORY_UNRESOLVED


# ---------------------------------------------------------------------------
# Delivery ledger: dedupe on lineage, branch independence
# ---------------------------------------------------------------------------


def test_dedupe_same_lineage_second_call_skips(brain_home) -> None:
    _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    first = _inject(brain_home, "migration ordering")
    assert first.decision is InjectionDecision.INJECT
    rows = _delivery_rows(brain_home)
    assert len(rows) == 1

    second = _inject(brain_home, "migration ordering")
    assert second.decision is InjectionDecision.NO_INJECTION
    assert second.reason is NoInjectionReason.ALREADY_DELIVERED
    assert len(_delivery_rows(brain_home)) == 1  # no duplicate rows

    third = _inject(brain_home, "migration ordering", branch_id="branch-b")
    assert third.decision is InjectionDecision.INJECT  # different branch delivers again
    assert len(_delivery_rows(brain_home)) == 2


def test_delivery_record_roundtrip_and_hash(brain_home) -> None:
    mid = _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    d = _inject(brain_home, "migration ordering")
    rows = _delivery_rows(brain_home)
    assert len(rows) == 1
    row = rows[0]
    assert row["memory_id"] == mid
    assert row["root_session_id"] == "s1"
    assert row["branch_id"] == "main"
    rec = BrainDeliveryRecord.from_dict(row)
    assert rec.delivery_id == row["delivery_id"]
    assert rec.canonical_hash == row["canonical_hash"]
    # canonical hash equals the stable per-item content hash (deterministic)
    packet = autoinject.render_packet(d)
    assert packet is not None
    item = BrainPacket.parse(packet).items[0]
    assert rec.canonical_hash == autoinject.item_canonical_hash(item)
    # same content on another branch -> identical packet + identical hash
    d2 = _inject(brain_home, "migration ordering", branch_id="branch-x")
    assert d2.decision is InjectionDecision.INJECT
    assert autoinject.render_packet(d2) == packet


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_hard_cap_never_exceeded(brain_home, monkeypatch) -> None:
    _seed_current(
        brain_home,
        "Huge memory",
        "word " * 4000,  # ~4000 words -> far above any cap in tokens
    )
    monkeypatch.setenv("SECOND_BRAIN_AUTOINJECT_HARD_CAP_TOKENS", "200")
    d = _inject(brain_home, "huge memory")
    assert d.decision is InjectionDecision.INJECT or d.decision is InjectionDecision.NO_INJECTION
    if d.decision is InjectionDecision.INJECT:
        assert d.packet_token_size is not None and d.packet_token_size <= 200
        assert autoinject.render_packet(d) != ""  # truncated packet still renders


def _write_telemetry_usage(home: Path, session_id: str, total_tokens: int) -> None:
    """Minimal `assistant_usage` telemetry record for governor.check_budget."""
    tdir = home / "telemetry" / "agent-performance"
    tdir.mkdir(parents=True, exist_ok=True)
    rec = {
        "v": 2,
        "ts": "2026-08-18T10:00:00.000Z",
        "kind": "assistant_usage",
        "session": session_id,
        "total_tokens": total_tokens,
    }
    (tdir / f"{session_id}.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")


def test_soft_cap_disables_retrieval_and_lowers_tier(brain_home) -> None:
    """T3.1: usage at/above cap*soft_ratio (worker cap 120000 * 0.8 = 96000)
    but below cap -> NO_INJECTION(BUDGET_SOFT), no retrieval work performed,
    and a decisions(kind="budget", state=SOFT) row is recorded (the signal
    the Prime tier-floor mechanism reads via `brainctl governor check-budget`)."""
    _seed_current(brain_home, "Soft budget memory", "should never be retrieved under SOFT")
    _write_telemetry_usage(brain_home, "soft-budget-test", 100000)
    d = _inject(
        brain_home,
        "soft budget memory",
        role_profile="worker",
        session_id="soft-budget-test",
    )
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.BUDGET_SOFT
    assert d.candidate_ids == []  # no retrieval work was performed
    assert d.selected_ids == []

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT kind, chosen_json, propensity FROM decisions WHERE session_id = ?",
            ("soft-budget-test",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["kind"] == "budget"
    assert row["propensity"] == 1.0
    chosen = json.loads(row["chosen_json"])
    assert chosen == {"decision": "NO_INJECTION", "state": "SOFT"}


def test_below_soft_threshold_injects_normally(brain_home) -> None:
    """Usage below the SOFT threshold never triggers BUDGET_SOFT."""
    _seed_current(brain_home, "Under budget memory", "under budget memory query")
    _write_telemetry_usage(brain_home, "under-budget-test", 1000)
    d = _inject(
        brain_home,
        "under budget memory",
        role_profile="worker",
        session_id="under-budget-test",
    )
    assert d.decision is InjectionDecision.INJECT
    assert d.reason is None


def test_hard_cap_does_not_block_injection(brain_home) -> None:
    """T3.1 §3 only specifies SOFT behavior for prepare_injection; HARD is
    enforced at the tool/worker-dispatch layer, not the injection layer."""
    _seed_current(brain_home, "Hard budget memory", "hard budget memory query")
    _write_telemetry_usage(brain_home, "hard-budget-test", 500000)
    d = _inject(
        brain_home,
        "hard budget memory",
        role_profile="worker",
        session_id="hard-budget-test",
    )
    assert d.decision is InjectionDecision.INJECT


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------


def test_fail_open_retrieval_error(brain_home, monkeypatch) -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(semantic, "search_memories", boom)
    d = _inject(brain_home, "any task")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.BRAIN_UNAVAILABLE
    assert d.packet_ref is None


# ---------------------------------------------------------------------------
# Migration 0008: fresh, v7 upgrade, idempotent
# ---------------------------------------------------------------------------


def test_migration_0008_fresh_and_v7_upgrade(tmp_path, monkeypatch) -> None:
    # Fresh db: v9 with deliveries table.
    home = tmp_path / "fresh"
    _make_brain(home, monkeypatch)
    conn = db.connect(db.db_path(home))
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v >= 10
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "deliveries" in tables
    finally:
        conn.close()

    # v7 db: apply only 0001..0007, then migrate with the real chain.
    home7 = tmp_path / "v7"
    migs7 = tmp_path / "migs7"
    migs7.mkdir()
    real = db.MIGRATIONS_DIR
    for p in sorted(real.glob("*.sql"))[:7]:
        (migs7 / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migs7)
    _make_brain(home7, monkeypatch)
    conn = db.connect(db.db_path(home7))
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 7
    finally:
        conn.close()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    applied = db.migrate(db.db_path(home7))
    assert applied[:3] == [8, 9, 10]
    assert db.migrate(db.db_path(home7)) == []  # idempotent second run
    conn = db.connect(db.db_path(home7))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "deliveries" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(deliveries)")}
        assert {
            "delivery_id",
            "root_session_id",
            "agent_session_id",
            "branch_id",
            "memory_id",
            "memory_version",
            "canonical_hash",
            "packet_id",
            "delivered_event_id",
            "delivered_at",
            "superseded_by_delivery_id",
        } <= cols
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI: brainctl autoinject shadow --json
# ---------------------------------------------------------------------------


def test_cli_shadow_json_deterministic_and_dedupe(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    _seed_current(home, "Migration ordering", "apply migrations in numeric order")

    args = [
        "autoinject",
        "shadow",
        "--task",
        "migration ordering",
        "--project",
        "proj-a",
        "--session",
        "s1",
        "--agent",
        "a1",
        "--role",
        "worker",
        "--json",
    ]
    r1 = _run_cli(home, *args)
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert out1["decision"] == "INJECT"
    assert out1["reason"] is None
    assert out1["packet"].startswith("[BRAIN_CONTEXT_DELTA v1]")
    assert out1["delivery_id"]
    assert out1["candidate_ids"] == out1["selected_ids"]

    # Same lineage: second call dedupes -> NO_INJECTION, still exit 0.
    r2 = _run_cli(home, *args)
    assert r2.returncode == 0, r2.stderr
    out2 = json.loads(r2.stdout)
    assert out2["decision"] == "NO_INJECTION"
    assert out2["reason"] == "ALREADY_DELIVERED"
    assert out2["packet"] is None

    # Fresh lineage: same task -> byte-identical packet (determinism).
    r3 = _run_cli(home, *args, "--session", "s2", "--branch", "b2")
    out3 = json.loads(r3.stdout)
    assert out3["decision"] == "INJECT"
    assert out3["packet"] == out1["packet"]
    assert out3["candidate_ids"] == out1["candidate_ids"]


def test_cli_unknown_project_no_injection_not_crash(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    _seed_current(home, "Migration ordering", "apply migrations in numeric order")
    r = _run_cli(
        home,
        "autoinject",
        "shadow",
        "--task",
        "migration ordering",
        "--project",
        "proj-zzz",
        "--session",
        "s1",
        "--agent",
        "a1",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "NO_INJECTION"
    assert out["reason"] in ("WRONG_PROJECT", "NO_RELEVANT_MEMORY")


# ---------------------------------------------------------------------------
# P0-G7 worker-specific packets (Phase 0D, plan §6.10/§17.1): role-scoped
# hard filter over the optional `tags:` frontmatter extension.
# ---------------------------------------------------------------------------


def _tag_memory(home: Path, memory_id: str, tag: str) -> None:
    """Add the optional `tags:` frontmatter extension (documented extension:
    the canonical writer never emits it; the indexer reads it)."""
    path = home / "memory" / "semantic" / f"{memory_id}.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("---\n", "---\ntags: " + tag + "\n", 1)
    path.write_text(text, encoding="utf-8")
    assert semantic.index_memory(home, memory_id)


def test_role_scoped_packets_worker_vs_orchestrator(brain_home) -> None:
    shared = _seed_current(brain_home, "Delegation rules", "delegation rules for everyone")
    worker_mem = _seed_current(
        brain_home, "Worker delegation rules", "worker delegation rules apply"
    )
    orch_mem = _seed_current(
        brain_home, "Orchestrator delegation rules", "orchestrator delegation rules apply"
    )
    _tag_memory(brain_home, worker_mem, "worker")
    _tag_memory(brain_home, orch_mem, "orchestrator")

    # Worker: shared untagged + worker-tagged; NEVER the parent-only memory.
    dw = _inject(brain_home, "delegation rules", role_profile="worker", session_id="sw1")
    assert dw.decision is InjectionDecision.INJECT
    assert shared in dw.selected_ids
    assert worker_mem in dw.selected_ids
    assert orch_mem not in dw.selected_ids

    # Orchestrator: shared untagged + orchestrator-tagged; NEVER worker memory.
    do_ = _inject(brain_home, "delegation rules", role_profile="orchestrator", session_id="so1")
    assert do_.decision is InjectionDecision.INJECT
    assert shared in do_.selected_ids
    assert orch_mem in do_.selected_ids
    assert worker_mem not in do_.selected_ids

    # Parent packet != worker packet for the same task.
    assert autoinject.render_packet(dw) != autoinject.render_packet(do_)


def test_role_filter_only_role_tagged_memory_available(brain_home) -> None:
    orch_mem = _seed_current(
        brain_home, "Orchestrator delegation rules", "orchestrator delegation rules apply"
    )
    _tag_memory(brain_home, orch_mem, "orchestrator")
    d = _inject(brain_home, "delegation rules", role_profile="worker", session_id="sw2")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert orch_mem not in d.selected_ids


# Phase C2 fixes: cwd project resolution and telemetry honesty


def _attempt_records(home: Path) -> list[dict]:
    """brain_retrieval_attempt records for this brain's telemetry dir."""
    import json as _json

    tdir = home / "telemetry" / "agent-performance"
    out = []
    if not tdir.is_dir():
        return out
    for f in tdir.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = _json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == "brain_retrieval_attempt":
                out.append(rec)
    return out


def _packet_delivered_records(home: Path) -> list[dict]:
    """brain_packet_delivered records for this brain's telemetry dir."""
    import json as _json

    tdir = home / "telemetry" / "agent-performance"
    out = []
    if not tdir.is_dir():
        return out
    for f in tdir.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = _json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == "brain_packet_delivered":
                out.append(rec)
    return out


def test_packet_delivered_prepared_not_model_visible(brain_home) -> None:
    """P3 §0A.8/§5.2: the Python event is the PREPARED/delivery-ledger state.

    `delivery_prepared` is always true and `model_visible` stays false —
    Python prepares/selects the packet and cannot observe host insertion;
    the Prime host `autoinject_shadow_decision.model_visible` (mode-aware)
    is the authoritative actual-model-visibility signal.
    """
    _seed_current(brain_home, "Visibility truth", "python prepares, host inserts")
    d = _inject(brain_home, "visibility truth", session_id="s-vis1")
    assert d.decision is InjectionDecision.INJECT
    recs = [
        r for r in _packet_delivered_records(brain_home) if r.get("session") == "s-vis1"
    ]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["model_visible"] is False
    assert rec["delivery_prepared"] is True
    assert rec["packet_id"] == d.packet_ref
    assert isinstance(rec["canonical_packet_hash"], str) and len(rec["canonical_packet_hash"]) == 64


def test_cwd_resolves_project_from_registry(brain_home, tmp_path) -> None:
    from second_brain import registry

    proj_dir = tmp_path / "proj-x"
    proj_dir.mkdir()
    (proj_dir / "marker.txt").write_text("x")
    registry.add_project(brain_home, proj_dir, name="Proj X", project_id="proj-x")
    _seed_current(brain_home, "Project X rule", "project x specific rule", project_id="proj-x")
    # no explicit project: cwd inside the registered root resolves to proj-x
    d = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "project x specific rule", agent_id="a1", session_id="s-cwd1", cwd=str(proj_dir)
    )
    assert d.decision is InjectionDecision.INJECT
    assert d.selected_ids  # matched the proj-x memory (wrong-project filter would block otherwise)


def test_cwd_unregistered_falls_back_to_env_then_default(
    brain_home, tmp_path, monkeypatch
) -> None:
    _seed_current(brain_home, "Env rule", "env project specific rule", project_id="env-proj")
    _seed_current(
        brain_home,
        "Global fallback rule",
        "global fallback policy rule",
        project_id=None,
        scope="global",
    )
    # 1. unregistered cwd + explicit env project -> resolves env-proj
    monkeypatch.setenv("SECOND_BRAIN_PROJECT", "env-proj")
    d = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "env project specific rule",
        agent_id="a1",
        session_id="s-cwd2",
        cwd=str(tmp_path / "elsewhere"),
    )
    assert d.decision is InjectionDecision.INJECT
    assert d.selected_ids

    # 2. no env -> unresolved ("default") -> project-scoped memories blocked, global allowed
    monkeypatch.delenv("SECOND_BRAIN_PROJECT", raising=False)
    d_blocked = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "env project specific rule",
        agent_id="a1",
        session_id="s-cwd3",
        cwd=str(tmp_path / "elsewhere"),
    )
    assert d_blocked.decision is InjectionDecision.NO_INJECTION
    assert d_blocked.reason is NoInjectionReason.WRONG_PROJECT

    d_global = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "global fallback policy rule",
        agent_id="a1",
        session_id="s-cwd4",
        cwd=str(tmp_path / "elsewhere"),
    )
    assert d_global.decision is InjectionDecision.INJECT
    assert d_global.selected_ids


def test_idf_recall_and_query_mode(brain_home) -> None:
    mid = _seed_current(
        brain_home, "Adaptive fan-out", "adaptive fan-out replaces the hard two worker cap"
    )
    decoy = _seed_current(brain_home, "Neapolitan pizza", "pizza has three flavors")
    d = _inject(brain_home, "adaptive fan-out policy", session_id="s-or1")
    assert d.decision is InjectionDecision.INJECT
    assert mid in d.selected_ids
    assert decoy not in d.selected_ids
    modes = [
        r.get("query_mode")
        for r in _attempt_records(brain_home)
        if r.get("session") == "s-or1"
    ]
    assert modes and modes[-1] == "idf"
    d2 = _inject(brain_home, "adaptive fan-out", session_id="s-or2")
    assert d2.decision is InjectionDecision.INJECT
    modes2 = [
        r.get("query_mode")
        for r in _attempt_records(brain_home)
        if r.get("session") == "s-or2"
    ]
    assert modes2 and modes2[-1] == "idf"


def test_no_relevant_only_when_query_empty(brain_home) -> None:
    d = _inject(brain_home, "zzzqqqx unknown gibberish", session_id="s-none1")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.NO_RELEVANT_MEMORY
    modes = [
        r.get("query_mode")
        for r in _attempt_records(brain_home)
        if r.get("session") == "s-none1"
    ]
    assert modes and modes[-1] == "idf"

def test_empty_cwd_falls_back_to_brain_home_project(brain_home) -> None:
    """Phase C3 FIX 2: no --cwd -> registry lookup uses the Brain home path
    itself before env/default."""
    from second_brain import registry

    registry.add_project(
        brain_home, brain_home, name="Self", project_id="self-proj"
    )
    _seed_current(brain_home, "Self rule", "self project rule", project_id="self-proj")
    d = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "self project rule", agent_id="a1", session_id="s-self1", cwd=""
    )
    assert d.decision is InjectionDecision.INJECT
    d2 = autoinject.BrainLifecycle(brain_home).prepare_injection(
        "self project rule", agent_id="a1", session_id="s-self2", cwd=None
    )
    assert d2.decision is InjectionDecision.INJECT

def test_observed_candidate_admitted_as_low_confidence(brain_home) -> None:
    mid = _add(
        brain_home,
        "Observed candidate",
        "candidate observation remains useful context",
        grade="OBSERVED",
    )
    row = semantic._row(brain_home, mid)
    assert row is not None and row["status"] == "candidate"
    intent = autoinject.RetrievalIntent(
        task_text="candidate observation",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="observed-candidate",
        branch_id="main",
    )
    valid = autoinject._valid_candidates(intent, [row])
    assert [r["memory_id"] for r in valid] == [mid]
    item = autoinject._build_items(brain_home, valid)[0]
    assert item.confidence.value == "low"


def test_delivery_records_retrieval_and_is_idempotent(brain_home) -> None:
    mid = _seed_current(brain_home, "Retrieval feedback", "record one retrieval")
    first = _inject(brain_home, "record one retrieval", session_id="feedback-s1")
    assert first.decision is InjectionDecision.INJECT
    second = _inject(brain_home, "record one retrieval", session_id="feedback-s1")
    assert second.reason is NoInjectionReason.ALREADY_DELIVERED
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_retrievals WHERE memory_id = ? AND session_id = ?",
            (mid, "feedback-s1"),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_mention_records_activation_once(brain_home) -> None:
    mid = _seed_current(brain_home, "Activation feedback", "record correct activation")
    lifecycle = autoinject.BrainLifecycle(brain_home)
    decision = lifecycle.prepare_injection(
        "record correct activation",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="feedback-s2",
    )
    assert decision.decision is InjectionDecision.INJECT
    lifecycle.finalize_session(
        tool_call_args=[{"name": "echo", "args": f"used {mid}"}],
        final_message="used the retrieved memory",
    )
    lifecycle.finalize_session(
        tool_call_args=[{"name": "echo", "args": f"used {mid}"}],
        final_message="used the retrieved memory",
    )
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_activations WHERE memory_id = ? AND session_id = ?",
            (mid, "feedback-s2"),
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 1
@pytest.mark.parametrize(
    ("status", "grade"),
    [
        ("superseded", "VERIFIED"),
        ("archived", "VERIFIED"),
        ("current", "INFERRED"),
        ("current", "HISTORICAL"),
        ("current", "REJECTED"),
        ("unknown", "VERIFIED"),
    ],
)
def test_admission_rejects_non_literal_status_and_grade(status, grade) -> None:
    intent = autoinject.RetrievalIntent(
        task_text="policy",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="policy-boundary",
        branch_id="main",
    )
    row = {
        "memory_id": "mem-boundary",
        "status": status,
        "evidence_grade": grade,
        "scope": "project",
        "project_id": "proj-a",
    }
    assert autoinject._valid_candidates(intent, [row]) == []


def test_admission_rejects_missing_metadata() -> None:
    intent = autoinject.RetrievalIntent(
        task_text="policy",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="policy-missing",
        branch_id="main",
    )
    assert autoinject._valid_candidates(
        intent,
        [{"memory_id": "mem-missing", "status": "current", "evidence_grade": "OBSERVED"}],
    ) == []

def test_fit_budget_uses_configured_estimator_target(monkeypatch) -> None:
    item_a = PacketItem(
        memory_id="mem-budget-a",
        version=1,
        status=autoinject.MemoryItemStatus.CURRENT,
        confidence=autoinject.Confidence.HIGH,
        title="A",
        observation="A",
        guidance="",
        evidence="brain://mem-budget-a/1",
    )
    item_b = dataclasses.replace(item_a, memory_id="mem-budget-b")
    estimates: list[int] = []

    def estimate(text: str, *, home=None) -> int:
        del home
        value = 11 if "mem-budget-b" in text else 10
        estimates.append(value)
        return value

    monkeypatch.setattr(autoinject, "token_estimate", estimate)
    fit = autoinject._fit_budget(
        [item_a, item_b],
        "proj-a",
        autoinject.AutoInjectConfig(target_tokens=10, hard_cap_tokens=20),
    )
    assert fit is not None


    assert [item.memory_id for item in fit[0]] == ["mem-budget-a"]
    assert estimates
def test_domain_unknown_project_survives_known_project_prefilter(brain_home) -> None:
    mid = _seed_current(
        brain_home,
        "Domain fallback rule",
        "domain rule with unknown project remains available",
        scope="domain",
        project_id=None,
    )
    decision = _inject(
        brain_home,
        "domain rule with unknown project",
        project_id="proj-a",
        session_id="domain-unknown",
    )
    assert decision.decision is InjectionDecision.INJECT
    assert decision.selected_ids == [mid]


class TestHasSessionStartedMarker:
    """T6.2: `_has_session_started` is an O(1) marker-file check, not a
    full-file JSONL telemetry scan."""

    def test_marker_check_is_idempotent(self, brain_home) -> None:
        host_session_id = "claude-marker-idem-1"
        assert autoinject._has_session_started(brain_home, host_session_id) is False

        autoinject._mark_session_started(brain_home, host_session_id)

        assert autoinject._has_session_started(brain_home, host_session_id) is True

    def test_marker_check_fails_open_on_error(self, brain_home, monkeypatch) -> None:
        def _boom(home, host_session_id):
            raise OSError("simulated corrupt/missing state directory")

        monkeypatch.setattr(autoinject, "_session_started_marker_path", _boom)

        assert autoinject._has_session_started(brain_home, "any-session") is False


class TestSessionStartedMarkerOnlyOnSuccessfulTelemetry:
    """T6.2 review finding 1: the durable session-started marker must only
    be written when the session_started telemetry append it accompanies
    actually succeeds, so a transient telemetry-write failure is retried
    (self-healed) on the next lifecycle call instead of being silently and
    permanently swallowed."""

    def _identity(self, host_session_id: str) -> BrainSessionIdentity:
        return BrainSessionIdentity(
            internal_session_id="is-" + host_session_id,
            host="claude-code",
            host_session_id=host_session_id,
            project_id="proj-a",
            created_at="2026-08-16T01:00:00Z",
            status="active",
            pinned=False,
            schema_version=1,
        )

    def test_marker_not_written_when_telemetry_append_fails(
        self, brain_home, monkeypatch
    ) -> None:
        host_session_id = "claude-marker-telemetry-fail-1"
        monkeypatch.setattr(autoinject, "_append_telemetry", lambda *a, **kw: False)

        lifecycle = autoinject.BrainLifecycle(brain_home)
        lifecycle.start_session(self._identity(host_session_id))

        assert autoinject._has_session_started(brain_home, host_session_id) is False

    def test_marker_written_and_retried_once_telemetry_succeeds(
        self, brain_home, monkeypatch
    ) -> None:
        host_session_id = "claude-marker-telemetry-retry-1"
        calls: list[int] = []

        def flaky(home, session, kind, extra):
            calls.append(1)
            return len(calls) > 1  # first call fails, every later call succeeds

        monkeypatch.setattr(autoinject, "_append_telemetry", flaky)
        lifecycle = autoinject.BrainLifecycle(brain_home)
        identity = self._identity(host_session_id)

        lifecycle.start_session(identity)  # append fails -> marker must not be written
        assert autoinject._has_session_started(brain_home, host_session_id) is False

        lifecycle.start_session(identity)  # retried (no stale marker) -> succeeds -> marker written
        assert autoinject._has_session_started(brain_home, host_session_id) is True
        assert len(calls) == 2  # exactly one retry, not swallowed by a premature marker
