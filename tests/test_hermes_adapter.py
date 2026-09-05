"""Hermes adapter integration tests.

These tests exercise the real Brain CLI bridge and canonical Brain storage. The
Hermes plugin itself is loaded from the repository adapter directory with a
small fake PluginContext so the suite does not depend on the installed Hermes
process.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from second_brain import (
    artifacts,
    contracts,
    hermes_adapter,
    ledger,
    semantic,
    vmem,
    worker_protocol,
    working_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HERMES_PLUGIN = REPO_ROOT / "brainstem" / "adapters" / "hermes" / "hermes_plugin.py"


def _run_hook(home: Path, payload: dict[str, Any] | str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), "autoinject", "hermes-hook"],
        input=raw,
        capture_output=True,
        text=True,
        cwd=home,
        env=env,
        timeout=120,
    )


def _current_memory(home: Path, *, project_id: str = "proj-hermes") -> str:
    memory_id = semantic.add_memory(
        home,
        "Hermes integration rule",
        "Hermes retrieves bounded project context through the canonical Brain AutoInject path.",
        project_id=project_id,
        grade="TESTED",
    )
    semantic.curate(home, memory_id, status="current")
    return memory_id


def _router_skill(home: Path) -> None:
    skill_dir = home / "skills" / "shadow" / "sqlite-migration-verifier"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# Positive Triggers\n"
        "- migration verifier\n"
        "# Negative Triggers\n"
        "(none)\n"
        "# Procedure\n"
        "- verify migrations\n",
        encoding="utf-8",
    )
    (home / "config" / "skills.toml").write_text(
        "[router]\nmax_active = 2\n", encoding="utf-8"
    )


def _start_payload(session: str = "hermes-session-1", bot: str = "Brain-Dev") -> dict[str, Any]:
    return {
        "event": "session_start",
        "hermes_session_id": session,
        "bot_name": bot,
        "bot_role": "dev",
        "project_id": "proj-hermes",
        "repo_root": str(REPO_ROOT),
        "provider": "test-provider",
        "model": "test-model",
    }


def _ledger_rows(
    home: Path, host_session_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = ledger.LedgerStore(home, host_session_id).dbfile
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        agents = [dict(row) for row in conn.execute("SELECT * FROM agents")]
        events = [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY seq")]
    return agents, events


def test_binding_is_stable_and_bot_scoped(brain_home: Path) -> None:
    first = hermes_adapter.resolve_binding(brain_home, _start_payload())
    resumed = hermes_adapter.resolve_binding(brain_home, _start_payload())
    other_bot = hermes_adapter.resolve_binding(
        brain_home, _start_payload(bot="Brain-Validator") | {"bot_role": "validator"}
    )

    assert first.host_session_id == "hermes:Brain-Dev:hermes-session-1"
    assert first.brain_session_id == ledger.internal_session_id(first.host_session_id)
    assert first.brain_session_id == resumed.brain_session_id
    assert first.agent_id != other_bot.agent_id
    assert first.brain_session_id != other_bot.brain_session_id
    assert first.project_id == "proj-hermes"


def test_session_start_is_idempotent_and_registers_agent_telemetry_and_ledger(
    brain_home: Path,
) -> None:
    payload = _start_payload()
    first = _run_hook(brain_home, payload)
    second = _run_hook(brain_home, payload)

    assert first.returncode == 0
    assert second.returncode == 0
    first_out = json.loads(first.stdout)
    second_out = json.loads(second.stdout)
    assert first_out["status"] == "registered"
    assert second_out["brain_session_id"] == first_out["brain_session_id"]

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    agents, events = _ledger_rows(brain_home, binding.host_session_id)
    assert len(agents) == 1
    assert agents[0]["host_agent_id"] == "Brain-Dev"
    assert agents[0]["role_profile"] == "dev"
    assert agents[0]["provider"] == "test-provider"
    assert [row["event_type"] for row in events].count("session_started") == 1

    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    records = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["kind"] == "session_started" for record in records)
    assert any(
        record["kind"] == "hermes_session_started"
        and record["bot_name"] == "Brain-Dev"
        and record["hermes_session_id"] == "hermes-session-1"
        for record in records
    )


def test_approved_worker_review_records_approved_in_ledger_and_telemetry(
    brain_home: Path,
) -> None:
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    binding = hermes_adapter.resolve_binding(brain_home, start)
    worker_protocol.register_task(
        brain_home,
        "review-task",
        "b" * 64,
        session_id=binding.host_session_id,
    )
    worker_protocol.record_worker_event(
        brain_home, "review-task", "b" * 64, "accepted", session_id=binding.host_session_id
    )
    result = contracts.WorkerResultPacket(
        "review-task",
        contracts.AgentIdentity(
            agent_id="worker-agent",
            internal_session_id="worker-session",
            host_agent_id="Brain-Dev",
            parent_agent_id=None,
            role_profile="dev",
            model="test-model",
            provider="test-provider",
            created_at="2026-08-22T00:00:00Z",
        ),
        "completed",
        summary="done",
    )
    worker_protocol.record_worker_event(
        brain_home,
        "review-task",
        "b" * 64,
        "completed",
        payload={**json.loads(result.canonical_json()), "result_sha256": result.canonical_hash()},
        session_id=binding.host_session_id,
    )

    review_data = json.loads(result.canonical_json())
    review_data.update(
        {"packet_sha256": "b" * 64, "result_sha256": result.canonical_hash()}
    )
    response = hermes_adapter.review_worker_result(
        brain_home,
        binding,
        review_data,
        approved=True,
        evidence={"tests": [{"name": "pytest", "exit_code": 0}]},
    )

    assert response["status"] == "reviewed"
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    ledger_payload = json.loads(
        next(row for row in events if row["event_type"] == "result_reviewed")["payload_json"]
    )
    assert response["settled"] is True
    assert ledger_payload["approved"] is True
    other_binding = hermes_adapter.resolve_binding(
        brain_home, start | {"hermes_session_id": "reviewer-other"}
    )
    cross_session = hermes_adapter.review_worker_result(
        brain_home,
        other_binding,
        review_data,
        approved=True,
        evidence={"tests": [{"name": "pytest", "exit_code": 0}]},
    )
    assert cross_session["status"] == "failed"
    assert cross_session["failure_code"] == "UNAUTHORIZED_COORDINATOR"
    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    telemetry_payload = next(
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "hermes_worker_result_reviewed"
    )
    assert telemetry_payload["approved"] is True
    assert telemetry_payload["worker_role"] == "dev"

def test_review_rejects_unknown_task_before_ledger(brain_home: Path) -> None:
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    binding = hermes_adapter.resolve_binding(brain_home, start)
    result = contracts.WorkerResultPacket(
        "unknown-review-task",
        contracts.AgentIdentity(
            agent_id="worker-agent",
            internal_session_id="worker-session",
            host_agent_id="Brain-Dev",
            parent_agent_id=None,
            role_profile="dev",
            model="test-model",
            provider="test-provider",
            created_at="2026-08-22T00:00:00Z",
        ),
        "completed",
        summary="synthetic",
    )
    review_data = json.loads(result.canonical_json())
    review_data.update(
        {"packet_sha256": "a" * 64, "result_sha256": result.canonical_hash()}
    )
    response = hermes_adapter.review_worker_result(
        brain_home,
        binding,
        review_data,
        approved=False,
        evidence={"diff_sha256": "b" * 64},
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "ORPHAN_TASK"

def test_approved_worker_review_without_real_evidence_stays_unsettled(
    brain_home: Path,
) -> None:
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    binding = hermes_adapter.resolve_binding(brain_home, start)
    result = contracts.WorkerResultPacket(
        "no-evidence-task",
        contracts.AgentIdentity(
            agent_id="worker-agent",
            internal_session_id="worker-session",
            host_agent_id="Brain-Dev",
            parent_agent_id=None,
            role_profile="dev",
            model="test-model",
            provider="test-provider",
            created_at="2026-08-22T00:00:00Z",
        ),
        "completed",
        summary="done",
    )
    response = hermes_adapter.review_worker_result(
        brain_home, binding, json.loads(result.canonical_json()), approved=True
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "SETTLEMENT_REJECTED"
    coerced = hermes_adapter.review_worker_result(
        brain_home, binding, json.loads(result.canonical_json()), approved=json.loads('"false"')
    )
    assert coerced["status"] == "failed"
    assert coerced["failure_code"] == "PROTOCOL_ERROR"


def test_worker_event_missing_task_id_is_protocol_error(brain_home: Path) -> None:
    binding = hermes_adapter.resolve_binding(brain_home, _start_payload())
    response = hermes_adapter.handle_worker_event(
        brain_home,
        binding,
        {"packet_sha256": "b" * 64, "event": "accepted"},
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "PROTOCOL_ERROR"

def test_approved_worker_review_rejects_unbounded_raw_evidence(
    brain_home: Path,
) -> None:
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    binding = hermes_adapter.resolve_binding(brain_home, start)
    result = contracts.WorkerResultPacket(
        "raw-evidence-task",
        contracts.AgentIdentity(
            agent_id="worker-agent",
            internal_session_id="worker-session",
            host_agent_id="Brain-Dev",
            parent_agent_id=None,
            role_profile="dev",
            model="test-model",
            provider="test-provider",
            created_at="2026-08-22T00:00:00Z",
        ),
        "completed",
        summary="done",
    )
    response = hermes_adapter.review_worker_result(
        brain_home,
        binding,
        json.loads(result.canonical_json()),
        approved=True,
        evidence={"tests": [{"name": "pytest", "exit_code": 0, "raw": "x" * 5000}]},
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "SETTLEMENT_REJECTED"


def test_review_evidence_rejects_bool_exit_and_canonicalizes_diff_alias() -> None:
    assert hermes_adapter._bounded_review_evidence(
        {"tests": [{"name": "pytest", "exit_code": False}]}
    ) is None
    assert hermes_adapter._bounded_review_evidence({"diff_hash": "a" * 64}) == {
        "diff_sha256": "a" * 64
    }
    assert hermes_adapter._bounded_review_evidence(
        {"tests": [{"name": "", "exit_code": 0}]}
    ) is None
    assert hermes_adapter._bounded_review_evidence(
        {"tests": [{"command": "", "exit_code": 0}]}
    ) is None
    assert hermes_adapter._bounded_review_evidence(
        {"diff_sha256": "invalid", "diff_hash": "a" * 64}
    ) is None
    assert hermes_adapter._bounded_review_evidence(
        {"diff_sha256": None, "diff_hash": "a" * 64}
    ) is None
    assert hermes_adapter._bounded_review_evidence([]) is None
    assert hermes_adapter._bounded_review_evidence(
        {"tests": [{"name": 7, "command": "pytest", "exit_code": 0}]}
    ) is None

def test_handoff_create_preserves_machine_readable_error_code(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    _run_hook(brain_home, start)
    binding = hermes_adapter.resolve_binding(brain_home, start)

    def raise_handoff_error(*args: Any, **kwargs: Any) -> Any:
        raise contracts.HandoffError("HANDOFF_MALFORMED", "bad envelope")

    monkeypatch.setattr(
        hermes_adapter.handoff, "create_handoff_envelope", raise_handoff_error
    )
    response = hermes_adapter._handle_handoff_create(
        brain_home,
        binding,
        {"target_harness": "hermes", "target_role": "dev", "task_id": "handoff-task"},
    )
    assert response["failure_code"] == "HANDOFF_MALFORMED"

def test_pre_llm_uses_real_bounded_brain_packet_when_mode_is_active(brain_home: Path) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(),
        "event": "pre_llm_call",
        "task": "How does Hermes retrieve bounded project context?",
        "turn_id": "turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    assert out["model_visible"] is True
    assert out["packet_tokens"] is not None
    assert "Hermes integration rule" in out["packet"]
    assert "How does Hermes" not in out["packet"]

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    assert any(row["event_type"] == "brain_packet_delivered" for row in events)
    assert all("How does Hermes" not in str(row["payload_json"]) for row in events)


def test_pre_llm_routes_existing_skill_and_preserves_bounded_injection(
    brain_home: Path,
) -> None:
    _current_memory(brain_home)
    _router_skill(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="router-runtime", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "run the migration verifier on the patch; retrieve Hermes bounded project context",
        "turn_id": "router-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    assert out["model_visible"] is True
    assert out["packet_tokens"] is not None
    assert out["packet_tokens"] <= 2000
    assert out["selected_routes"] == ["sqlite-migration-verifier"]
    assert out["routing_error"] is False
    assert "Hermes integration rule" in out["packet"]
    assert "run the migration verifier" not in out["packet"]
    assert out["bot_name"] == "Brain-Dev"
    assert out["bot_role"] == "dev"

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    delivery = next(row for row in events if row["event_type"] == "brain_packet_delivered")
    delivery_payload = json.loads(delivery["payload_json"])
    assert delivery_payload["selected_routes"] == ["sqlite-migration-verifier"]
    assert delivery_payload["routing_error"] is False
    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    telemetry = [
        json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    record = next(item for item in telemetry if item["kind"] == "hermes_pre_llm_call")
    assert record["selected_routes"] == ["sqlite-migration-verifier"]
    assert record["routing_error"] is False
    assert record["bot_name"] == "Brain-Dev"
    assert record["bot_role"] == "dev"


def _visibility_skill(home: Path, name: str = "demo-visibility-skill") -> None:
    skill_dir = home / "skills" / "shadow" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"# {title}\n\n- {name} content"
        for title in (
            "Purpose",
            "Positive Triggers",
            "Negative Triggers",
            "Inputs",
            "Procedure",
            "Tools",
            "Safety",
            "Verification",
            "Output",
            "References",
        )
    )
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nstatus: shadow\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )


def test_pre_llm_shadow_mode_never_injects_hydrated_skill(brain_home: Path) -> None:
    _current_memory(brain_home)
    _visibility_skill(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-shadow", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": (
            "How does Hermes retrieve bounded project context for demo-visibility-skill content?"
        ),
        "turn_id": "visibility-shadow-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is not None
    assert out["visibility_plan"]["mode"] == "shadow"
    assert out["visibility_plan"]["hydrated_skill_ids"] == ["demo-visibility-skill"]
    assert out["packet"] is not None
    assert "demo-visibility-skill content" not in out["packet"]


def test_pre_llm_enforced_mode_injects_hydrated_skill(brain_home: Path) -> None:
    _current_memory(brain_home)
    _visibility_skill(brain_home, name="enforced-visibility-skill")
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "enforced"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-enforced", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "enforced-visibility-skill content trigger",
        "turn_id": "visibility-enforced-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is not None
    assert out["visibility_plan"]["mode"] == "enforced"
    assert "enforced-visibility-skill content" in out["packet"]


def test_pre_llm_enforced_mode_rejects_oversized_hydrated_skill(brain_home: Path) -> None:
    _current_memory(brain_home)
    _visibility_skill(brain_home, name="oversized-visibility-skill")
    skill_path = (
        brain_home / "skills" / "shadow" / "oversized-visibility-skill" / "SKILL.md"
    )
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8") + ("x" * 5000),
        encoding="utf-8",
    )
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    (brain_home / "config" / "skills.toml").write_text(
        '[visibility]\nmode = "enforced"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-oversized", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": (
            "How does Hermes retrieve bounded project context for "
            "oversized-visibility-skill content?"
        ),
        "turn_id": "visibility-oversized-turn-1",
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is not None
    assert out["visibility_plan"]["mode"] == "enforced"
    assert out["visibility_plan"]["hydrated_skill_ids"] == []
    assert (
        out["visibility_plan"]["unavailable_skill_ids"]["oversized-visibility-skill"]
        == "body_too_large"
    )
    assert "x" * 5000 not in out["packet"]
    assert "Hermes integration rule" in out["packet"]


def test_pre_llm_visibility_failure_does_not_break_existing_autoinject_path(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    payload = {
        **_start_payload(session="visibility-failure", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "How does Hermes retrieve bounded project context?",
        "turn_id": "visibility-failure-turn-1",
    }
    # Break skills.build_plan via invalid UTF-8 bytes in config/skills.toml.
    # resolve_visibility_mode only catches (OSError, tomllib.TOMLDecodeError);
    # `.read_text(encoding="utf-8")` on invalid UTF-8 raises UnicodeDecodeError
    # (a ValueError, not caught there), so this is a real, reachable failure
    # that propagates out of skills.build_plan -- unlike malformed-but-valid-
    # UTF-8 TOML text, which resolve_visibility_mode already fails safe on
    # (falling back to "shadow" without raising). Exercised through the
    # actual subprocess rather than a monkeypatch that a fresh subprocess
    # would not see.
    with open(brain_home / "config" / "skills.toml", "wb") as f:
        f.write(b'[visibility]\nmode = "shad\xffow"\n')

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["visibility_plan"] is None
    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    assert "Hermes integration rule" in out["packet"]


def test_pre_llm_records_bounded_model_decision_with_identity_correlation(
    brain_home: Path,
) -> None:
    task = "summarize the routine migration status"
    payload = {
        **_start_payload(session="routing-response", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": task,
        "task_id": "task-routing-1",
        "turn_id": "routing-turn-1",
        "provider": "host-provider",
        "model": "host-model",
        "candidates": [
            {
                "provider": "fast-provider",
                "model": "fast-model",
                "tier": "efficient",
                "cost_class": "low",
                "capabilities": ["summarization"],
            },
            {
                "provider": "deep-provider",
                "model": "deep-model",
                "tier": "premium",
                "cost_class": "high",
                "capabilities": ["summarization"],
            },
        ],
    }

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["turn_id"] == "routing-turn-1"
    assert out["selected_provider"] == "fast-provider"
    assert out["selected_model"] == "fast-model"
    assert out["selected_tier"] == "efficient"
    assert out["reason_code"] == "LOWEST_COST_ELIGIBLE"
    model_decision = out["model_decision"]
    assert model_decision["task_hash"] == hermes_adapter._sha256(task)[:16]
    assert task not in json.dumps(model_decision)
    assert len(json.dumps(model_decision)) < 32_000

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    routing_event = next(row for row in events if row["event_type"] == "decision")
    routing_payload = json.loads(routing_event["payload_json"])
    assert routing_payload["routing_event"] == "model_decision"
    assert routing_payload["decision_id"] == model_decision["decision_id"]
    assert routing_payload["selected_identity"] == {
        "provider": "fast-provider",
        "model": "fast-model",
        "tier": "efficient",
    }
    assert routing_payload["session_id"] == binding.host_session_id
    assert routing_payload["project_id"] == binding.project_id
    assert task not in json.dumps(routing_payload)

    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    telemetry = [
        json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    telemetry_decision = next(item for item in telemetry if item["kind"] == "hermes_model_decision")
    assert telemetry_decision["decision_id"] == model_decision["decision_id"]
    assert telemetry_decision["task_hash"] == model_decision["task_hash"]


# ---------------------------------------------------------------------------
# T3.1 hard/soft budget caps
# ---------------------------------------------------------------------------


def _write_budget_telemetry(home: Path, host_session_id: str, total_tokens: int) -> None:
    tdir = home / "telemetry" / "agent-performance"
    tdir.mkdir(parents=True, exist_ok=True)
    stem = hermes_adapter.telemetry_stem(host_session_id)
    rec = {
        "v": 2,
        "ts": "2026-08-18T10:00:00.000Z",
        "kind": "assistant_usage",
        "session": host_session_id,
        "total_tokens": total_tokens,
    }
    (tdir / f"{stem}.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")


def test_hard_cap_blocks_worker_dispatch_with_budget_exceeded(brain_home: Path) -> None:
    """T3.1 §4: HARD parent budget fails worker dispatch before it starts,
    same status="failed"/failure_code shape as UNAUTHORIZED_COORDINATOR."""
    start = _start_payload(session="budget-hard-dispatch", bot="Brain-Integrator") | {
        "bot_role": "integrator"
    }
    binding = hermes_adapter.resolve_binding(brain_home, start)
    # session_tokens cap defaults to 400000 for a non-worker role.
    _write_budget_telemetry(brain_home, binding.host_session_id, 500000)

    packet = contracts.WorkerTaskPacket(
        task_id="budget-hard-task",
        parent_session_id=binding.host_session_id,
        driver_identity=contracts.AgentIdentity(
            agent_id=binding.agent_id,
            internal_session_id=binding.brain_session_id,
            host_agent_id=binding.bot_name,
            parent_agent_id=None,
            role_profile=binding.bot_role,
            model=binding.model,
            provider=binding.provider,
            created_at="2026-08-18T10:00:00Z",
        ),
        requested_role="dev",
        objective="do work under a HARD budget",
        scope="repository",
        constraints=[],
        evidence_requirements=[],
        completion_condition="return evidence",
        context_refs=[],
        project_id=binding.project_id,
        repo_root=binding.repo_root,
        access_intent="read_only",
    ).validate()

    response = hermes_adapter.request_worker_task(
        brain_home, binding, json.loads(packet.canonical_json())
    )
    assert response["status"] == "failed"
    assert response["failure_code"] == "BUDGET_EXCEEDED"


def test_below_hard_cap_worker_dispatch_proceeds(brain_home: Path) -> None:
    """No BUDGET_EXCEEDED short-circuit when usage is below the cap."""
    start = _start_payload(session="budget-ok-dispatch", bot="Brain-Integrator") | {
        "bot_role": "integrator"
    }
    binding = hermes_adapter.resolve_binding(brain_home, start)
    _write_budget_telemetry(brain_home, binding.host_session_id, 100)

    packet = contracts.WorkerTaskPacket(
        task_id="budget-ok-task",
        parent_session_id=binding.host_session_id,
        driver_identity=contracts.AgentIdentity(
            agent_id=binding.agent_id,
            internal_session_id=binding.brain_session_id,
            host_agent_id=binding.bot_name,
            parent_agent_id=None,
            role_profile=binding.bot_role,
            model=binding.model,
            provider=binding.provider,
            created_at="2026-08-18T10:00:00Z",
        ),
        requested_role="dev",
        objective="do work under an OK budget",
        scope="repository",
        constraints=[],
        evidence_requirements=[],
        completion_condition="return evidence",
        context_refs=[],
        project_id=binding.project_id,
        repo_root=binding.repo_root,
        access_intent="read_only",
    ).validate()

    response = hermes_adapter.request_worker_task(
        brain_home, binding, json.loads(packet.canonical_json())
    )
    assert response.get("failure_code") != "BUDGET_EXCEEDED"


def test_pre_llm_hard_cap_injects_exact_budget_warning_tail(brain_home: Path) -> None:
    """T3.1 §4 Hermes fallback: no pre_tool_call blocking primitive exists
    (verified against hermes_plugin.py's host contract), so the exact
    `[SECOND_BRAIN_BUDGET]` line must appear in the rendered TAIL instead,
    and a decisions(kind="budget", state="HARD") row is recorded once."""
    payload = {
        **_start_payload(session="budget-hard-tail", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "keep working past the hard cap",
        "turn_id": "budget-hard-turn",
    }
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    # role "dev" is not "worker" -> session_tokens cap (400000 default).
    _write_budget_telemetry(brain_home, binding.host_session_id, 500000)

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["budget_state"] == "HARD"
    assert "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED" in out["tail"]

    conn = sqlite3.connect(brain_home / "db" / "brain.sqlite")
    try:
        row = conn.execute(
            "SELECT kind, chosen_json FROM decisions WHERE session_id = ? AND kind = 'budget'",
            (binding.host_session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    chosen = json.loads(row[1])
    assert chosen == {"decision": "BLOCK", "state": "HARD"}


def test_pre_llm_soft_cap_never_writes_hard_budget_tail(brain_home: Path) -> None:
    """Usage below HARD (even if SOFT) never adds the hard-cap warning line."""
    payload = {
        **_start_payload(session="budget-soft-tail", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "keep working under a soft cap",
        "turn_id": "budget-soft-turn",
    }
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    # 96000 = 400000 * 0.8 (SOFT threshold for a non-worker role), below cap.
    _write_budget_telemetry(brain_home, binding.host_session_id, 350000)

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["budget_state"] == "SOFT"
    assert "[SECOND_BRAIN_BUDGET]" not in (out["tail"] or "")


def test_pre_tool_call_unaffected_by_hard_budget(brain_home: Path) -> None:
    """Documented limitation: Hermes' pre_tool_call host contract only
    understands {"replacement": str} (no deny/block field exists), so a HARD
    budget state never changes pre_tool_call's read/cat/grep behavior."""
    start_payload = _start_payload(session="budget-hard-tool", bot="Brain-Dev")
    binding = hermes_adapter.resolve_binding(brain_home, start_payload)
    _write_budget_telemetry(brain_home, binding.host_session_id, 500000)
    target = brain_home / "stable.txt"
    target.write_text("stable content", encoding="utf-8")

    result = hermes_adapter.handle_request(
        brain_home,
        start_payload | {"event": "pre_tool_call", "tool_name": "read", "path": str(target)},
    )
    assert result["status"] == "ok"
    assert "block" not in result



def test_pre_llm_model_decision_records_unavailable_fallback(brain_home: Path) -> None:
    payload = {
        **_start_payload(session="routing-fallback", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "security architecture review",
        "turn_id": "routing-fallback-turn",
        "premium_justification": ["security"],
        "candidates": [
            {
                "provider": "premium-provider",
                "model": "premium-model",
                "tier": "premium",
                "cost_class": "low",
                "capabilities": ["security", "architecture"],
                "available": False,
            },
            {
                "provider": "balanced-provider",
                "model": "balanced-model",
                "tier": "balanced",
                "cost_class": "medium",
                "capabilities": ["security", "architecture"],
            },
        ],
    }

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["selected_provider"] == "balanced-provider"
    assert out["selected_model"] == "balanced-model"
    assert out["fallback_used"] is True
    assert out["fallback_provider"] == "balanced-provider"
    assert out["fallback_reason"] == "MODEL_UNAVAILABLE"
    assert out["original_selected_provider"] == "premium-provider"
    assert out["reason_code"] == "MODEL_UNAVAILABLE_FALLBACK"


def test_pre_llm_model_decision_exposes_explicit_premium_reason(brain_home: Path) -> None:
    payload = {
        **_start_payload(session="routing-premium", bot="Brain-Integrator"),
        "event": "pre_llm_call",
        "task": "security architecture review",
        "turn_id": "routing-premium-turn",
        "premium_justification": ["security"],
        "candidates": [
            {
                "provider": "premium-provider",
                "model": "premium-model",
                "tier": "premium",
                "cost_class": "high",
                "capabilities": ["security", "architecture"],
            }
        ],
    }

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["selected_provider"] == "premium-provider"
    assert out["selected_tier"] == "premium"
    assert out["reason_code"] == "PREMIUM_ESCALATION_JUSTIFIED"
    assert out["fallback_used"] is False


def test_pre_llm_attribution_is_byte_identical_across_response_ledger_and_telemetry(
    brain_home: Path,
) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    task = "How does Hermes retrieve bounded project context?"
    payload = {
        **_start_payload(session="attribution-inject"),
        "event": "pre_llm_call",
        "task": task,
        "turn_id": "attribution-turn-1",
    }

    out = hermes_adapter.handle_request(brain_home, payload)
    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    attribution = out["attribution"]
    assert attribution["decision_source"] == "autoinject"
    assert attribution["decision"] == out["decision"]
    assert attribution["profile"] == "dev"
    assert len(attribution["injection_decision_id"]) <= 64
    assert task not in json.dumps(attribution)

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    ledger_event = next(
        row
        for row in reversed(events)
        if row["event_type"] in {"brain_packet_delivered", "brain_no_injection"}
        and json.loads(row["payload_json"]).get("attribution") is not None
    )
    ledger_payload = json.loads(ledger_event["payload_json"])
    assert ledger_payload["project_id"] == binding.project_id
    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    telemetry_record = next(
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("kind") == "hermes_pre_llm_call"
        and json.loads(line).get("attribution") is not None
    )
    assert json.dumps(attribution, sort_keys=True, separators=(",", ":")) == json.dumps(
        ledger_payload["attribution"], sort_keys=True, separators=(",", ":")
    )
    assert json.dumps(attribution, sort_keys=True, separators=(",", ":")) == json.dumps(
        telemetry_record["attribution"], sort_keys=True, separators=(",", ":")
    )
    assert ledger_payload["attribution"]["injection_decision_id"] == attribution[
        "injection_decision_id"
    ]


def test_pre_llm_no_injection_attribution_is_actual_and_bounded(brain_home: Path) -> None:
    payload = {
        **_start_payload(session="attribution-none"),
        "bot_role": "role-" + ("x" * 200),
        "event": "pre_llm_call",
        "task": "unique task with no matching canonical memory",
        "turn_id": "attribution-none-turn",
    }

    first = hermes_adapter.handle_request(brain_home, payload)
    second = hermes_adapter.handle_request(brain_home, payload)
    assert first["status"] == second["status"] == "ok"
    assert first["decision"] == second["decision"] == "NO_INJECTION"
    assert first["attribution"] == second["attribution"]
    assert first["attribution"]["decision"] == "NO_INJECTION"
    assert first["attribution"]["decision_source"] == "autoinject"
    assert first["attribution"]["reason_code"]
    assert len(first["attribution"]["profile"]) <= 64
    assert first["bot_role"] == payload["bot_role"]


def test_pre_llm_authority_failure_fails_open_without_false_success(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_prepare(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("AutoInject unavailable")

    monkeypatch.setattr(hermes_adapter.autoinject.BrainLifecycle, "prepare_injection", fail_prepare)
    response = hermes_adapter.handle_request(
        brain_home,
        {
            **_start_payload(session="attribution-failure"),
            "event": "pre_llm_call",
            "task": "must not report a successful injection",
            "turn_id": "attribution-failure-turn",
        },
    )
    assert response["status"] == "fail_open"
    assert response["event"] == "pre_llm_call"
    assert "attribution" not in response
    assert response.get("decision") is None


def test_router_failure_fails_open_without_regressing_autoinject(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )

    def fail_route(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(hermes_adapter.router, "route", fail_route)
    payload = {
        **_start_payload(session="router-failure", bot="Brain-Dev"),
        "event": "pre_llm_call",
        "task": "How does Hermes retrieve bounded project context?",
        "turn_id": "router-failure-turn",
    }

    out = hermes_adapter.handle_request(brain_home, payload)

    assert out["status"] == "ok"
    assert out["decision"] == "INJECT"
    assert out["model_visible"] is True
    assert out["selected_routes"] == []
    assert out["routing_error"] is True
    assert out["bot_name"] == "Brain-Dev"
    assert out["bot_role"] == "dev"
    assert out["brain_session_id"] == hermes_adapter.resolve_binding(
        brain_home, payload
    ).brain_session_id


def test_writeback_uses_existing_candidate_memory_with_provenance(brain_home: Path) -> None:
    payload = {
        **_start_payload(),
        "event": "writeback",
        "title": "Hermes bridge proof",
        "observation": "A separate Hermes session can retrieve a controlled Brain event.",
        "guidance": "Keep the proof bounded and provenance-backed.",
        "evidence": [{"ref": "test:hermes-adapter", "kind": "test"}],
    }

    result = _run_hook(brain_home, payload)

    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["status"] == "candidate"
    memory = semantic.show_memory(brain_home, out["memory_id"])
    assert memory["row"]["status"] == "candidate"
    sources = semantic._sources(brain_home, out["memory_id"])
    assert {source["ref"] for source in sources} >= {
        "session:hermes:Brain-Dev:hermes-session-1",
        "test:hermes-adapter",
    }
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    assert any(row["event_type"] == "finding" for row in events)


def test_cross_bot_adapter_path_retrieves_integrator_event_in_dev_and_validator_sessions(
    brain_home: Path,
) -> None:
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    write_payload = {
        **_start_payload(session="integrator-cross-bot", bot="Brain-Integrator"),
        "bot_role": "integrator",
        "event": "writeback",
        "title": "Cross-bot Brain checkpoint",
        "observation": "Integrator recorded a durable event through the Hermes adapter.",
        "evidence": [{"ref": "test:cross-bot", "kind": "test"}],
    }
    write_result = _run_hook(brain_home, write_payload)
    write_out = json.loads(write_result.stdout)
    assert "memory_id" in write_out, write_out
    semantic.curate(brain_home, write_out["memory_id"], grade="TESTED", status="current")

    retrieved: dict[str, dict[str, Any]] = {}
    for bot_name, bot_role, session in (
        ("Brain-Dev", "dev", "dev-cross-bot"),
        ("Brain-Validator", "validator", "validator-cross-bot"),
    ):
        result = _run_hook(
            brain_home,
            {
                **_start_payload(session=session, bot=bot_name),
                "bot_role": bot_role,
                "event": "pre_llm_call",
                "task": "Retrieve the Cross-bot Brain checkpoint from the Integrator.",
                "turn_id": f"{bot_role}-cross-bot-turn",
            },
        )
        retrieved[bot_role] = json.loads(result.stdout)

    assert retrieved["dev"]["model_visible"] is True
    assert retrieved["validator"]["model_visible"] is True
    assert "Cross-bot Brain checkpoint" in retrieved["dev"]["packet"]
    assert "Cross-bot Brain checkpoint" in retrieved["validator"]["packet"]
    assert retrieved["dev"]["brain_session_id"] != retrieved["validator"]["brain_session_id"]
    sources = semantic._sources(brain_home, write_out["memory_id"])
    assert "session:hermes:Brain-Integrator:integrator-cross-bot" in {
        source["ref"] for source in sources
    }


def test_malformed_hook_fails_open_with_json(brain_home: Path) -> None:
    result = _run_hook(brain_home, "not json")

    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["status"] == "fail_open"
    assert out["event"] == "unknown"


class _FakeContext:
    profile_name = "Brain-Dev"

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.hooks: dict[str, Any] = {}
        self.middleware: dict[str, Any] = {}
        self.tools: dict[str, dict[str, Any]] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks[name] = callback

    def register_middleware(self, name: str, callback: Any) -> None:
        self.middleware[name] = callback

    def register_tool(self, **kwargs: Any) -> None:
        self.tools[kwargs["name"]] = kwargs

def _load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location("second_brain_hermes_plugin", HERMES_PLUGIN)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {HERMES_PLUGIN}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_hermes_plugin_registers_hooks_and_real_context_callback(brain_home: Path) -> None:
    _current_memory(brain_home)
    (brain_home / "config" / "autoinject.toml").write_text(
        '[autoinject]\nmode = "active"\n', encoding="utf-8"
    )
    plugin = _load_plugin()
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Dev",
            "bot_role": "dev",
            "project_id": "proj-hermes",
            "repo_root": str(REPO_ROOT),
        }
    )

    plugin.register(ctx)
    callback = ctx.hooks["pre_llm_call"]
    result = callback(
        session_id="hermes-plugin-session",
        user_message="How does Hermes retrieve bounded project context?",
        model="test-model",
        provider="test-provider",
        platform="cli",
        turn_id="plugin-turn-1",
    )

    assert set(ctx.hooks) >= {
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_api_request",
        "api_request_error",
        "on_session_finalize",
    }
    assert "llm_request" in ctx.middleware
    assert "second_brain_writeback" in ctx.tools
    assert "second_brain_delegate" in ctx.tools
    assert "second_brain_review_worker_result" in ctx.tools
    assert "second_brain_correct_worker_result" in ctx.tools
    assert isinstance(result, dict)
    assert "Hermes integration rule" in result["context"]


def test_handle_request_preserves_raw_correction_attempt(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[Any] = []

    def capture(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        attempts.append(args[-1])
        return {"status": "captured"}

    monkeypatch.setattr(hermes_adapter, "request_worker_correction", capture)
    start = _start_payload(bot="Brain-Integrator") | {"bot_role": "integrator"}
    for value in (1.5, True):
        output = hermes_adapter.handle_request(
            brain_home,
            start
            | {
                "event": "worker_result_correction",
                "packet": {},
                "result": {},
                "correction_attempt": value,
            },
        )
        assert output["status"] == "captured"
    assert attempts == [1.5, True]

def test_hermes_plugin_forwards_review_evidence(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"status": "reviewed"}

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "project_id": "proj-hermes",
            "repo_root": str(REPO_ROOT),
        }
    )
    plugin.register(ctx)
    ctx.tools["second_brain_review_worker_result"]["handler"](
        {
            "result": {"task_id": "plugin-review-task"},
            "approved": True,
            "evidence": {"diff_hash": "a" * 64},
        },
        session_id="hermes-plugin-review",
    )
    assert calls[-1]["event"] == "worker_result_review"
    assert calls[-1]["evidence"] == {"diff_hash": "a" * 64}
    ctx.tools["second_brain_review_worker_result"]["handler"](
        {
            "result": {"task_id": "plugin-review-task"},
            "approved": "false",
        },
        session_id="hermes-plugin-review",
    )
    assert calls[-1]["approved"] == "false"


def test_hermes_plugin_terminal_delegate_does_not_invoke_worker(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {
            "status": "prepared",
            "duplicate": True,
            "terminal_noop": True,
            "state": "completed",
        }

    def fail_worker(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("terminal retry must not invoke worker")

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    monkeypatch.setattr(plugin, "_invoke_persistent_worker", fail_worker)
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "project_id": "proj-hermes",
            "repo_root": str(REPO_ROOT),
        }
    )
    plugin.register(ctx)
    output = ctx.tools["second_brain_delegate"]["handler"](
        {"packet": {"task_id": "terminal-retry"}},
        session_id="hermes-terminal-retry",
    )
    assert json.loads(output)["terminal_noop"] is True
    assert len(calls) == 1
def test_hermes_plugin_forwards_pre_tool_call_to_brain(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"replacement": "[SECOND_BRAIN_UNCHANGED marker]"}

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Dev",
            "bot_role": "dev",
        }
    )
    plugin.register(ctx)
    result = ctx.hooks["pre_tool_call"](
        session_id="plugin-reread",
        tool_name="read",
        args={"path": "file.txt"},
        tool_call_id="call-1",
    )
    assert result == {"replacement": "[SECOND_BRAIN_UNCHANGED marker]"}
    assert calls[-1]["event"] == "pre_tool_call"
    assert calls[-1]["tool_name"] == "read"

def test_hermes_plugin_brain_decision_drives_safe_middleware_handoff(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        if payload["event"] == "pre_llm_call":
            return {
                "packet": None,
                "model_decision": {
                    "decision_id": "decision-1",
                    "selected_provider": "selected-provider",
                    "selected_model": "selected-model",
                    "selected_tier": "standard",
                },
            }
        return {"status": "ok"}

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Dev",
            "bot_role": "dev",
            "model_candidates": [
                {
                    "provider": "selected-provider",
                    "model": "selected-model",
                    "tier": "standard",
                    "capabilities": ["reasoning"],
                    "cost": "medium",
                    "availability": True,
                }
            ],
        }
    )
    plugin.register(ctx)
    context = ctx.hooks["pre_llm_call"](
        session_id="s1",
        user_message="route this",
        model="host-model",
        provider="host-provider",
        turn_id="t1",
    )
    assert context is None
    assert calls[0]["model_candidates"][0]["provider"] == "selected-provider"

    middleware = ctx.middleware["llm_request"]
    rewritten = middleware(
        request={"model": "host-model", "provider": "host-provider"},
        original_request={"model": "host-model", "provider": "host-provider"},
        session_id="s1",
        turn_id="t1",
        api_request_id="api-1",
    )
    assert rewritten["request"]["model"] == "selected-model"
    assert rewritten["request"]["provider"] == "selected-provider"
    assert rewritten["trace_marker"]["decision_id"] == "decision-1"

    failed = middleware(
        request={"model": "host-model"},
        original_request={"model": "host-model"},
        session_id="s1",
        turn_id="t1",
        api_request_id="api-2",
    )
    assert failed["request"] == {"model": "host-model"}
    assert failed["trace_marker"]["status"] == "handoff_failed"
    assert any(
        call["event"] == "api_request_error"
        and call["failure_code"] == "MODEL_PROVIDER_HANDOFF_UNREPRESENTABLE"
        for call in calls
    )

def test_hermes_plugin_observer_uses_effective_middleware_model(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        if payload["event"] == "pre_llm_call":
            return {
                "model_decision": {
                    "decision_id": "decision-effective",
                    "selected_provider": "selected-provider",
                    "selected_model": "selected-model",
                    "selected_tier": "balanced",
                }
            }
        return {"status": "ok"}

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    ctx = _FakeContext({"brain_home": str(brain_home), "brain_python": sys.executable})
    plugin.register(ctx)
    ctx.hooks["pre_llm_call"](
        session_id="s-effective",
        user_message="route this",
        model="host-model",
        provider="host-provider",
        turn_id="t-effective",
    )
    ctx.middleware["llm_request"](
        request={"model": "host-model", "provider": "host-provider"},
        original_request={"model": "host-model", "provider": "host-provider"},
        session_id="s-effective",
        turn_id="t-effective",
        api_request_id="api-effective",
    )
    ctx.hooks["post_api_request"](
        session_id="s-effective",
        turn_id="t-effective",
        api_request_id="api-effective",
        model="host-model",
        provider="host-provider",
        response_model="selected-model",
    )
    assert calls[-1]["event"] == "post_api_request"
    assert calls[-1]["model"] == "selected-model"
    assert calls[-1]["provider"] == "selected-provider"



def test_hermes_plugin_observers_emit_correlated_bounded_lifecycle(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {
            "model_decision": {
                "decision_id": "decision-2",
                "selected_provider": "provider",
                "selected_model": "model",
                "selected_tier": "standard",
            }
        }

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    ctx = _FakeContext({"brain_home": str(brain_home), "brain_python": sys.executable})
    plugin.register(ctx)
    ctx.hooks["pre_llm_call"](
        session_id="s2",
        user_message="route",
        model="model",
        provider="provider",
        turn_id="t2",
    )
    ctx.hooks["post_api_request"](
        session_id="s2",
        turn_id="t2",
        api_request_id="api-2",
        model="model",
        provider="provider",
        response_model="model-response",
        usage={"total_tokens": 12, "raw_response": "must not pass"},
        cost={"amount": 0.02, "currency": "USD"},
    )
    assert calls[-1]["event"] == "post_api_request"
    assert calls[-1]["decision_id"] == "decision-2"
    assert calls[-1]["response_model"] == "model-response"
    assert calls[-1]["usage"] == {"total_tokens": 12}
    assert "raw_response" not in json.dumps(calls[-1])


def test_brain_lifecycle_events_correlate_identity_and_bound_metrics(
    brain_home: Path,
) -> None:
    payload = {
        **_start_payload(session="invocation-lifecycle"),
        "event": "post_api_request",
        "turn_id": "turn-lifecycle",
        "api_request_id": "api-lifecycle",
        "decision_id": "decision-lifecycle",
        "selected_identity": {
            "provider": "selected-provider",
            "model": "selected-model",
            "tier": "standard",
        },
        "actual_identity": {
            "provider": "actual-provider",
            "model": "actual-model",
        },
        "response_model": "response-model",
        "usage": {"total_tokens": 9, "raw_response": "not retained"},
        "cost": {"amount": 0.01, "currency": "USD"},
        "status": "completed",
    }
    result = hermes_adapter.handle_request(brain_home, payload)
    assert result["status"] == "completed"
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    _, events = _ledger_rows(brain_home, binding.host_session_id)
    lifecycle = next(
        json.loads(row["payload_json"])
        for row in reversed(events)
        if row["event_type"] == "decision"
        and json.loads(row["payload_json"]).get("lifecycle_event") == "post_api_request"
    )
    assert lifecycle["decision_id"] == "decision-lifecycle"
    assert lifecycle["actual_identity"]["model"] == "actual-model"
    assert lifecycle["usage"] == {"total_tokens": 9}
    assert "raw_response" not in json.dumps(lifecycle)

def test_real_post_tool_hook_stores_bounded_vmem_evicts_and_faults_in(brain_home: Path) -> None:
    first_payload = {
        **_start_payload(session="vmem-runtime"),
        "event": "post_tool_call",
        "tool_name": "shell",
        "args": {"command": "first"},
        "result": "FIRST-OBSERVATION " + ("x" * 2200),
        "tool_call_id": "tool-1",
        "turn_id": "turn-1",
        "status": "completed",
    }
    second_payload = first_payload | {
        "args": {"command": "second"},
        "result": "SECOND-OBSERVATION " + ("y" * 2200),
        "tool_call_id": "tool-2",
        "turn_id": "turn-2",
    }
    first = hermes_adapter.handle_request(brain_home, first_payload)
    second = hermes_adapter.handle_request(brain_home, second_payload)
    assert first["status"] == second["status"] == "ok"

    binding = hermes_adapter.resolve_binding(brain_home, first_payload)
    store = vmem.VMemStore(brain_home, binding.host_session_id)
    objects = store.list_objects(kind=vmem.SessionObjectKind.TOOL_OBSERVATION)
    assert len(objects) == 2
    # T2.3: post_tool_call does not evict. Eviction occurs at cache break-points in _vmem_context.
    initial = hermes_adapter.handle_request(
        brain_home,
        first_payload | {"event": "pre_llm_call", "task": "Initial render"},
    )
    assert initial["status"] == "ok"
    objects_after_break = store.list_objects(kind=vmem.SessionObjectKind.TOOL_OBSERVATION)
    cold = next(
        obj
        for obj in objects_after_break
        if obj.residency_state == vmem.ResidencyState.EVICTED
    )
    assert cold.residency_state == vmem.ResidencyState.EVICTED
    assert cold.metadata["tool_call_id"] in {"tool-1", "tool-2"}

    readback = hermes_adapter.handle_request(
        brain_home,
        first_payload
        | {
            "event": "pre_llm_call",
            "task": f"Please inspect {cold.title} ({cold.obj_id})",
            "turn_id": "turn-readback",
            "cache_read_tokens": 0,
        },
    )
    assert readback["status"] == "ok"
    assert len(readback["vmem_context"]["rendered_text"]) <= 6000
    assert cold.title in readback["vmem_context"]["rendered_text"]
    assert "[SECOND_BRAIN_FAULTED_IN]" in readback["vmem_context"]["rendered_text"]
    expected_marker = (
        "FIRST-OBSERVATION" if cold.metadata["tool_call_id"] == "tool-1" else "SECOND-OBSERVATION"
    )
    assert expected_marker in readback["vmem_context"]["rendered_text"]
    assert readback["vmem_context_changed"] is True
    assert readback["vmem_faulted_in_ids"] == [cold.obj_id]
    faulted_cold = store.get_object(cold.obj_id)
    assert faulted_cold is not None
    assert faulted_cold.residency_state == vmem.ResidencyState.FAULTED_IN

    _, events = _ledger_rows(brain_home, binding.host_session_id)
    delivery_event = next(
        row
        for row in reversed(events)
        if row["event_type"] in {"brain_packet_delivered", "brain_no_injection"}
    )
    delivery_payload = json.loads(delivery_event["payload_json"])
    assert delivery_payload["vmem_context_changed"] is True
    assert delivery_payload["vmem_faulted_in_ids"] == [cold.obj_id]
    tool_event = next(
        row
        for row in events
        if row["event_type"] == "tool_completed"
        and json.loads(row["payload_json"])["tool_call_id"] == cold.metadata["tool_call_id"]
    )
    tool_payload = json.loads(tool_event["payload_json"])
    assert tool_payload["tool_call_id"] == cold.metadata["tool_call_id"]
    assert tool_payload["bot_name"] == "Brain-Dev"
    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    records = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
    observed = next(
        item
        for item in records
        if item["kind"] == "hermes_post_tool_call"
        and item["tool_call_id"] == cold.metadata["tool_call_id"]
    )
    assert observed["bot_role"] == "dev"
    assert observed["residency_state"] == "RESIDENT"
    assert observed["evicted_count"] == 0
    assert expected_marker not in json.dumps(observed)


def test_oversized_raw_result_preserves_artifact_reduces_and_faults_in(
    brain_home: Path,
) -> None:
    raw_output = "\n".join(
        [f"PASSED tests/test_{index}.py::test_case" for index in range(400)]
    ) + "\n400 passed in 1.0s\n"
    payload = {
        **_start_payload(session="vmem-oversized-lossless"),
        "event": "post_tool_call",
        "tool_name": "bash",
        "args": {"command": "pytest -q tests/"},
        "result": raw_output[:4000],
        "raw_result": raw_output,
        "tool_call_id": "oversized-tool-1",
        "turn_id": "oversized-turn-1",
        "status": "completed",
    }

    post = hermes_adapter.handle_request(brain_home, payload)
    assert post["status"] == "ok"
    assert post["original_result_bytes"] == len(raw_output.encode("utf-8"))
    assert post["original_result_sha256"] == hashlib.sha256(raw_output.encode()).hexdigest()
    assert post["artifact_ref"] == post["original_result_sha256"]
    assert post["reduction_ratio"] > 0.80

    binding = hermes_adapter.resolve_binding(brain_home, payload)
    store = vmem.VMemStore(brain_home, binding.host_session_id)
    obj = store.get_object(post["obj_id"])
    assert obj is not None
    assert obj.content_sha256 == post["original_result_sha256"]
    recovered_artifact = artifacts.expand(brain_home, obj.content_sha256)
    assert recovered_artifact == raw_output.encode("utf-8")
    assert obj.metadata["recovery_handle"] == post["recovery_handle"]
    assert obj.metadata["original_result_bytes"] == len(recovered_artifact)

    store.evict_to_budget(0)
    cold = store.get_object(obj.obj_id)
    assert cold is not None and cold.residency_state == vmem.ResidencyState.EVICTED
    readback = hermes_adapter.handle_request(
        brain_home,
        payload
        | {
            "event": "pre_llm_call",
            "task": f"inspect {obj.title} ({obj.obj_id})",
            "turn_id": "oversized-readback",
        },
    )
    assert readback["status"] == "ok"
    assert readback["vmem_faulted_in_ids"] == [obj.obj_id]
    assert readback["vmem_context_changed"] is True
    assert readback["vmem_context_chars"] <= 4096
    assert "[SECOND_BRAIN_FAULTED_IN]" in readback["vmem_context"]["rendered_text"]
    obj_after_fault = store.get_object(obj.obj_id)
    assert obj_after_fault is not None
    assert obj_after_fault.residency_state == vmem.ResidencyState.FAULTED_IN
    assert artifacts.expand(brain_home, obj.content_sha256) == raw_output.encode("utf-8")

    _, events = _ledger_rows(brain_home, binding.host_session_id)
    tool_payload = json.loads(
        next(row for row in events if row["event_type"] == "tool_completed")["payload_json"]
    )
    assert tool_payload["original_result_bytes"] == len(raw_output.encode("utf-8"))
    assert tool_payload["original_result_sha256"] == post["original_result_sha256"]
    assert tool_payload["artifact_ref"] == post["artifact_ref"]
    assert tool_payload["visible_result_bytes"] < len(raw_output.encode("utf-8")) * 0.20

    telemetry_path = (
        brain_home
        / "telemetry"
        / "agent-performance"
        / f"{hermes_adapter.telemetry_stem(binding.host_session_id)}.jsonl"
    )
    records = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
    observed = next(record for record in records if record["kind"] == "hermes_post_tool_call")
    assert observed["original_result_bytes"] == len(raw_output.encode("utf-8"))
    assert observed["original_result_sha256"] == post["original_result_sha256"]
    assert observed["recovery_handle"] == post["recovery_handle"]
    assert observed["reduction_ratio"] > 0.80
    assert '"raw_result"' not in json.dumps(observed)


def test_post_tool_and_vmem_fail_open(brain_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _start_payload(session="vmem-fail-open") | {
        "event": "post_tool_call",
        "tool_name": "broken",
        "result": "ignored",
    }
    def fail_store(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("down")

    monkeypatch.setattr(vmem.VMemStore, "store_object", fail_store)
    response = hermes_adapter.handle_request(brain_home, payload)
    assert response["status"] == "fail_open"
    assert response["event"] == "post_tool_call"


@pytest.mark.parametrize(
    "event", ["session_start", "pre_llm_call", "post_tool_call", "writeback", "session_end"]
)
def test_supported_events_are_explicit(brain_home: Path, event: str) -> None:
    payload = _start_payload() | {"event": event}
    if event == "pre_llm_call":
        payload["task"] = "bounded context"
    elif event == "post_tool_call":
        payload.update(
            {
                "tool_name": "shell",
                "args": {"command": "printf bounded"},
                "result": "bounded tool result",
                "tool_call_id": "event-tool-1",
                "turn_id": "event-turn-1",
                "status": "completed",
            }
        )
    elif event == "writeback":
        payload.update(
            {
                "title": "event test",
                "observation": "event handler remains explicit",
                "evidence": [],
            }
        )
    response = hermes_adapter.handle_request(brain_home, payload)
    assert response["event"] == event

    assert response["status"] in {"registered", "ok", "candidate", "finalized"}

def test_session_end_records_activation_from_tool_args(brain_home: Path) -> None:
    mid = _current_memory(brain_home)
    start = _start_payload() | {
        "event": "pre_llm_call",
        "task": "Hermes retrieves bounded project context",
        "turn_id": "turn-feedback",
    }
    prepared = hermes_adapter.handle_request(brain_home, start)
    assert mid in prepared["selected_ids"]
    end = _start_payload() | {
        "event": "session_end",
        "tool_call_args": [{"input": {"command": f"echo {mid}"}}],
        "final_message": "Used the retrieved context.",
    }
    hermes_adapter.handle_request(brain_home, end)
    hermes_adapter.handle_request(brain_home, end)
    import sqlite3

    with sqlite3.connect(brain_home / "db" / "brain.sqlite") as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_activations WHERE memory_id = ? AND session_id = ?",
            (mid, "hermes:Brain-Dev:hermes-session-1"),
        ).fetchone()[0] == 1


def test_pre_tool_call_active_replaces_only_unchanged_read(brain_home: Path) -> None:
    payload = _start_payload(session="reread-active")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    target = brain_home / "stable.txt"
    target.write_text("stable", encoding="utf-8")
    working_set.record_read(
        brain_home,
        binding.brain_session_id,
        str(target),
        "read",
        turn=4,
        distilled_ref="sha256:distilled",
    )
    (brain_home / "config" / "context.toml").write_text(
        '[rollout]\nreread_avoidance = "ACTIVE"\n', encoding="utf-8"
    )
    result = hermes_adapter.handle_request(
        brain_home,
        payload | {"event": "pre_tool_call", "tool_name": "read", "path": str(target)},
    )
    assert result["replacement"].startswith("[SECOND_BRAIN_UNCHANGED ")
    assert "sha256:distilled" in result["replacement"]


def test_pre_tool_call_active_does_not_replace_selected_read(brain_home: Path) -> None:
    payload = _start_payload(session="reread-range")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    target = brain_home / "stable.txt"
    target.write_text("stable", encoding="utf-8")
    working_set.record_read(
        brain_home,
        binding.brain_session_id,
        str(target),
        "read",
        turn=4,
        distilled_ref="sha256:distilled",
    )
    (brain_home / "config" / "context.toml").write_text(
        '[rollout]\nreread_avoidance = "ACTIVE"\n', encoding="utf-8"
    )
    result = hermes_adapter.handle_request(
        brain_home,
        payload
        | {"event": "pre_tool_call", "tool_name": "read", "path": str(target), "range": "1-2"},
    )
    assert result["replacement"] is None


def test_pre_tool_call_shadow_retains_read_and_records_decision(brain_home: Path) -> None:
    payload = _start_payload(session="reread-shadow")
    binding = hermes_adapter.resolve_binding(brain_home, payload)
    target = brain_home / "stable.txt"
    target.write_text("stable", encoding="utf-8")
    working_set.record_read(brain_home, binding.brain_session_id, str(target), "read", turn=4)
    (brain_home / "config" / "context.toml").write_text(
        '[rollout]\nreread_avoidance = "SHADOW"\n', encoding="utf-8"
    )
    result = hermes_adapter.handle_request(
        brain_home,
        payload | {"event": "pre_tool_call", "tool_name": "cat", "path": str(target)},
    )
    assert result["replacement"] is None
    with sqlite3.connect(brain_home / "db" / "brain.sqlite") as conn:
        row = conn.execute(
            "SELECT kind, propensity FROM decisions "
            "WHERE kind = 'reread' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row == ("reread", 1.0)

def test_pre_tool_call_off_skips_lookup_and_telemetry(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _start_payload(session="reread-off")
    target = brain_home / "stable.txt"
    target.write_text("stable", encoding="utf-8")
    (brain_home / "config" / "context.toml").write_text(
        '[rollout]\nreread_avoidance = "OFF"\n', encoding="utf-8"
    )
    telemetry: list[str] = []

    def capture(*args: Any, **kwargs: Any) -> None:
        del kwargs
        telemetry.append(str(args[2]) if len(args) > 2 else "")

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("OFF mode performed reread lookup")

    monkeypatch.setattr(working_set, "reread_hint", unexpected)
    monkeypatch.setattr(hermes_adapter.autoinject, "_append_telemetry", capture)
    monkeypatch.setattr(hermes_adapter.decisions, "record", unexpected)
    result = hermes_adapter.handle_request(
        brain_home,
        payload | {"event": "pre_tool_call", "tool_name": "read", "path": str(target)},
    )
    assert result["status"] == "ok"
    assert "replacement" not in result
    assert "reread_avoidable" not in telemetry

def test_hermes_plugin_correction_cache_preserves_result_identity(
    brain_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _load_plugin()
    calls: list[dict[str, Any]] = []
    packet_sha = "p" * 64
    result_sha = "r" * 64
    correction = {"task_id": "plugin-correction", "correction_attempt": 1}
    corrected = {"task_id": "plugin-correction", "summary": "corrected"}

    def fake_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        del self
        calls.append(payload)
        if payload["event"] == "worker_task_prepare":
            return {"status": "prepared", "context_handoff": {}}
        if payload["event"] == "worker_result_correction":
            return {"status": "correction_requested", "correction": correction}
        if payload["event"] == "worker_result_corrected":
            return {
                "status": "completed",
                "task_id": corrected["task_id"],
                "packet_sha256": packet_sha,
                "result_sha256": result_sha,
                "result": corrected,
            }
        if payload["event"] == "worker_result_review":
            return {"status": "reviewed"}
        raise AssertionError(payload)

    monkeypatch.setattr(plugin._BrainClient, "request", fake_request)
    monkeypatch.setattr(plugin, "_invoke_persistent_worker", lambda *args: dict(corrected))
    ctx = _FakeContext(
        {
            "brain_home": str(brain_home),
            "brain_python": sys.executable,
            "bot_name": "Brain-Integrator",
            "bot_role": "integrator",
            "project_id": "proj-hermes",
            "repo_root": str(REPO_ROOT),
        }
    )
    plugin.register(ctx)
    correct = ctx.tools["second_brain_correct_worker_result"]["handler"]
    review = ctx.tools["second_brain_review_worker_result"]["handler"]

    output = json.loads(
        correct(
            {
                "packet": {"task_id": corrected["task_id"]},
                "result": {"task_id": corrected["task_id"]},
                "reason": "fix",
                "requested_changes": ["summary"],
            },
            session_id="plugin-correction-session",
        )
    )
    assert output["status"] == "completed"
    assert output["packet_sha256"] == packet_sha
    assert output["result_sha256"] == result_sha

    review_output = json.loads(
        review(
            {"result": corrected, "approved": False},
            session_id="plugin-correction-session",
        )
    )
    assert review_output == {"status": "reviewed"}
    review_request = next(call for call in calls if call["event"] == "worker_result_review")
    assert review_request["result"]["packet_sha256"] == packet_sha
    assert review_request["result"]["result_sha256"] == result_sha
