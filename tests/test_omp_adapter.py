from __future__ import annotations

from second_brain import omp_adapter


def test_omp_adapter_prepares_bounded_worker_context_handoff(tmp_path) -> None:
    from second_brain import semantic, working_set

    session = "omp-parent"
    working_set.init_capsule(tmp_path, session, "Parent task")
    memory_id = semantic.add_memory(
        tmp_path,
        "OMP worker context",
        "Brain-owned context for the child worker.",
        project_id="omp-project",
        grade="TESTED",
    )
    semantic.curate(tmp_path, memory_id, status="current")
    working_set.update_capsule(tmp_path, session, brain_refs=[f"memory:{memory_id}"])

    response = omp_adapter.handle_request(
        tmp_path,
        {
            "operation": "worker_context",
            "host_session_id": session,
            "task_id": "omp-task-1",
            "task": "Inspect the bounded worker seam",
            "scope": "repository",
            "completion_condition": "Return evidence",
            "project_id": "omp-project",
            "cwd": str(tmp_path),
            "role": "driver",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "worker_role": "worker",
        },
    )

    assert response["status"] == "prepared"
    assert response["context_metadata"]["mode"] == "full"
    assert response["context_metadata"]["resolved_count"] == 1
    assert (
        "Brain-owned context for the child worker."
        in (response["context_handoff"]["resolved_context"][0]["content"])
    )
    assert response["context_handoff"]["context_handoff_bytes"] <= 16_384


def _worker_context_payload(session: str, task_id: str, **extra: object) -> dict[str, object]:
    return {
        "operation": "worker_context",
        "host_session_id": session,
        "task_id": task_id,
        "task": "Inspect the bounded worker seam",
        "scope": "repository",
        "completion_condition": "Return evidence",
        "project_id": "omp-project",
        "cwd": "C:/repo",
        "role": "driver",
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "worker_role": "worker",
        **extra,
    }


def test_omp_adapter_reuses_and_deltas_worker_context(tmp_path) -> None:
    from second_brain import semantic, working_set

    session = "omp-modes"
    working_set.init_capsule(tmp_path, session, "Parent task")
    memory_id = semantic.add_memory(
        tmp_path,
        "OMP mode fixture",
        "Initial context.",
        project_id="omp-project",
        grade="TESTED",
    )
    semantic.curate(tmp_path, memory_id, status="current")
    working_set.update_capsule(tmp_path, session, brain_refs=[f"memory:{memory_id}"])

    first = omp_adapter.handle_request(tmp_path, _worker_context_payload(session, "task-modes"))
    unchanged = omp_adapter.handle_request(tmp_path, _worker_context_payload(session, "task-modes"))
    semantic.supersede(tmp_path, memory_id, new_body="Changed context.", change_note="mode delta")
    changed = omp_adapter.handle_request(tmp_path, _worker_context_payload(session, "task-modes"))

    assert first["context_metadata"]["mode"] == "full"
    assert unchanged["context_metadata"]["mode"] == "unchanged"
    assert unchanged["context_metadata"]["cache_hit"] is True
    assert unchanged["context_handoff"]["resolved_context"] == []
    assert changed["context_metadata"]["mode"] == "delta"
    assert changed["context_handoff"]["resolved_context"] == []
    assert changed["context_handoff"]["context_delta"]["changed_refs"]

    assert (
        unchanged["context_metadata"]["context_handoff_bytes"]
        < first["context_metadata"]["context_handoff_bytes"]
    )


def test_omp_adapter_rejects_invalid_and_unresolved_context_refs(tmp_path) -> None:
    invalid = omp_adapter.handle_request(
        tmp_path,
        _worker_context_payload("omp-invalid", "task-invalid", context_refs=["unsupported:ref"]),
    )
    missing = omp_adapter.handle_request(
        tmp_path,
        _worker_context_payload("omp-missing", "task-missing", context_refs=["memory:mem-missing"]),
    )
    worker_parent = omp_adapter.handle_request(
        tmp_path,
        _worker_context_payload("omp-worker", "task-worker", role="worker"),
    )

    assert invalid["status"] == "failed"
    assert invalid["failure_code"] == "CONTEXT_REF_UNRESOLVED"
    assert missing["status"] == "failed"
    assert missing["failure_code"] == "CONTEXT_REF_UNRESOLVED"
    assert worker_parent["status"] == "failed"
    assert worker_parent["failure_code"] == "UNAUTHORIZED_COORDINATOR"


def test_omp_adapter_delegates_selection_to_brain_and_keeps_task_out_of_response(tmp_path) -> None:
    response = omp_adapter.handle_request(
        tmp_path,
        {
            "task": "private task text must not be returned",
            "host_session_id": "omp-session",
            "project_id": "omp-project",
            "role": "worker",
            "provider": "provider-a",
            "model": "model-a",
            "candidates": [
                {
                    "provider": "provider-a",
                    "model": "model-a",
                    "tier": "efficient",
                    "cost_class": "low",
                },
                {
                    "provider": "provider-b",
                    "model": "model-b",
                    "tier": "balanced",
                    "cost_class": "medium",
                },
            ],
        },
    )
    decision = response["decision"]
    assert decision is not None
    assert decision["selected_provider"] == "provider-a"
    assert decision["selected_model"] == "model-a"
    assert "private task text" not in str(response)


def test_omp_adapter_bounds_invalid_request(tmp_path) -> None:
    assert omp_adapter.handle_request(tmp_path, None)["error"] == "MALFORMED_ROUTING_INPUT"
    assert omp_adapter.handle_request(tmp_path, {"task": ""})["error"] == "NO_TASK"


def test_empty_candidate_metadata_defaults_to_host_identity(tmp_path) -> None:
    response = omp_adapter.handle_request(
        tmp_path,
        {
            "task": "host candidate fallback",
            "host_session_id": "omp-session",
            "role": "worker",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "candidates": [],
        },
    )
    assert response["decision"]["selected_provider"] == "openai-codex"
    assert response["decision"]["selected_model"] == "gpt-5.6-luna"


def test_driver_host_candidate_meets_driver_minimum_tier(tmp_path) -> None:
    response = omp_adapter.handle_request(
        tmp_path,
        {
            "task": "driver coordination task",
            "host_session_id": "omp-driver",
            "role": "driver",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "candidates": [],
        },
    )
    assert response["decision"]["status"] == "selected"
    assert response["decision"]["selected_tier"] == "balanced"


def test_omp_adapter_skill_visibility_returns_bounded_plan(tmp_path):
    from second_brain import paths

    directory = tmp_path / paths.SKILL_LEVEL_DIRS["shadow"] / "demo-skill"
    directory.mkdir(parents=True)
    sections = "\n\n".join(
        f"# {title}\n\n- content"
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
    (directory / "SKILL.md").write_text(
        f"---\nname: demo-skill\nstatus: shadow\nversion: 1\n---\n\n{sections}\n",
        encoding="utf-8",
    )
    response = omp_adapter.handle_request(
        tmp_path,
        {
            "operation": "skill_visibility",
            "task": "demo-skill trigger phrase",
            "host_session_id": "omp-session-1",
            "project_id": "proj",
        },
    )
    assert response["visibility_plan"] is not None
    assert response["visibility_plan"]["mode"] == "shadow"
    # task_hash (privacy-preserving digest) is expected; the raw task text is not.
    assert "demo-skill trigger phrase" not in str(response["visibility_plan"])
    assert isinstance(response["hydrated_instructions"], dict)


def test_omp_adapter_skill_visibility_fails_open_on_error(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr("second_brain.skills.build_plan", _boom)
    response = omp_adapter.handle_request(
        tmp_path,
        {"operation": "skill_visibility", "task": "x", "host_session_id": "s", "project_id": "p"},
    )
    assert response["visibility_plan"] is None
    assert response["error"] == "VISIBILITY_UNAVAILABLE"


def test_omp_adapter_skill_visibility_requires_task(tmp_path):
    response = omp_adapter.handle_request(
        tmp_path,
        {"operation": "skill_visibility", "host_session_id": "s", "project_id": "p"},
    )
    assert response["visibility_plan"] is None
    assert response["error"] == "NO_TASK"
