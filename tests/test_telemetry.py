import json

from second_brain import telemetry


def _write_session(home, name, lines):
    f = telemetry.telemetry_dir(home) / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _rec(kind, **kw):
    rec = {"v": 2, "ts": "2026-08-14T10:00:00.000Z", "kind": kind, "session": "s1"}
    rec.update(kw)
    return rec


def test_validate_empty(brain_home):
    r = telemetry.validate(brain_home)
    assert r == {"files": 0, "records": 0, "issues": []}


def test_validate_clean(brain_home):
    _write_session(
        brain_home,
        "s1.jsonl",
        [_rec("session_start"), _rec("turn_start", turn=0), _rec("session_shutdown")],
    )
    r = telemetry.validate(brain_home)
    assert r["records"] == 3
    assert r["issues"] == []


def test_validate_flags_problems(brain_home):
    _write_session(
        brain_home,
        "bad.jsonl",
        [
            {"v": 2, "kind": "mystery", "session": "s1"},  # unknown kind, no ts
            {"v": 3, "ts": "x", "kind": "turn_start", "session": "s1"},  # old schema
            "not-json",
        ],
    )
    r = telemetry.validate(brain_home)
    assert len(r["issues"]) == 4  # unknown kind + ts not a string + schema v + not an object
    assert any("not a JSON object" in i for i in r["issues"])


def test_report_aggregates(brain_home):
    _write_session(
        brain_home,
        "s1.jsonl",
        [
            _rec("session_start", cwd="C:/proj", model="m1"),
            _rec("tool_call", tool="bash", command="pytest -q", input_bytes=10),
            _rec("tool_result", tool="bash", is_error=False, output_bytes=500),
            _rec("tool_call", tool="bash", command="git status", input_bytes=10),
            _rec("tool_result", tool="bash", is_error=True, output_bytes=80),
            _rec("turn_end", turn=0, context_usage={"percent": 42.5}),
            _rec("turn_end", turn=1, context_usage={"percent": 91.0}),
            _rec("session_compact", from_extension=False),
            _rec("session_shutdown"),
        ],
    )
    rep = telemetry.report(brain_home)
    assert rep["sessions"] == 1
    assert rep["records"] == 9
    assert rep["bash_calls"] == 2
    assert rep["tool_results_with_error"] == 1
    assert rep["compactions"] == 1
    assert rep["max_context_percent"] == 91.0
    assert rep["total_result_bytes"] == 580
    assert rep["kinds"]["tool_call"] == 2
    assert rep["tools"]["bash"] == 4
    assert rep["models"] == {"m1": 1}


def test_report_since_filter(brain_home):
    _write_session(
        brain_home,
        "s1.jsonl",
        [
            _rec("session_start", ts="2026-08-13T00:00:00.000Z"),
            _rec("session_shutdown", ts="2026-08-15T00:00:00.000Z"),
        ],
    )
    rep = telemetry.report(brain_home, since="2026-08-14T00:00:00.000Z")
    assert rep["records"] == 1
    assert rep["kinds"] == {"session_shutdown": 1}


def test_report_no_dir(brain_home):
    rep = telemetry.report(brain_home)
    assert rep["sessions"] == 0 and rep["records"] == 0


def test_format_report(brain_home):
    text = telemetry.format_report(telemetry.report(brain_home))
    assert "Sessions:" in text


def test_validate_accepts_orchestrator_policy_violation(brain_home):
    _write_session(
        brain_home,
        "viol.jsonl",
        [
            _rec(
                "orchestrator_policy_violation",
                violation="direct_execution",
                model="openai/gpt-5.6-sol",
                detected_by="manual",
                blocked=False,
            )
        ],
    )
    r = telemetry.validate(brain_home)
    assert r["issues"] == []


def test_report_counts_orchestrator_violations(brain_home):
    _write_session(
        brain_home,
        "s1.jsonl",
        [
            _rec(
                "orchestrator_policy_violation",
                violation="wrong_tier",
                model="m1",
                detected_by="telemetry_audit",
                blocked=False,
            ),
            _rec(
                "orchestrator_policy_violation",
                violation="wrong_tier",
                model="m1",
                detected_by="runtime_guard",
                blocked=True,
            ),
            _rec(
                "orchestrator_policy_violation",
                violation="direct_execution",
                model="m2",
                detected_by="manual",
                blocked=False,
            ),
            _rec("session_shutdown"),
        ],
    )
    rep = telemetry.report(brain_home)
    assert rep["orchestrator_violations"] == 3
    assert rep["violation_codes"] == {"direct_execution": 1, "wrong_tier": 2}
    assert "Orchestrator viol.:" in telemetry.format_report(rep)


def test_validate_accepts_rtd_shadow(brain_home):
    _write_session(
        brain_home,
        "rtd.jsonl",
        [
            _rec(
                "rtd_shadow",
                tool="bash",
                id="tc1",
                size=12000,
                threshold=8000,
                would_trigger=True,
                reason="size",
            )
        ],
    )
    r = telemetry.validate(brain_home)
    assert r["issues"] == []


def test_current_omp_v3_records_validate(brain_home):
    _write_session(
        brain_home,
        "session.jsonl",
        [
            {
                "v": 3,
                "kind": "omp_routing_invocation",
                "session": "s",
                "ts": "2026-08-29T00:00:00Z",
            },
            {
                "v": 2,
                "kind": "heartbeat_pulse",
                "session": "s",
                "ts": "2026-08-29T00:00:01Z",
                "mode": "shadow",
                "event": "session_start",
                "due": True,
                "ran": True,
                "healthy": True,
                "db_ok": True,
                "cache_pruned_count": 0,
                "git_dirty": False,
                "issue_codes": [],
                "latency_ms": 0,
                "model_tokens_used": 0,
                "artifacts_gc_count": 0,
            },
        ],
    )
    assert telemetry.validate(brain_home)["issues"] == []


def test_operational_report_preserves_missing_provider_counters(brain_home):
    _write_session(
        brain_home,
        "session.jsonl",
        [
            _rec("session_start", model="local", cwd="/repo"),
            _rec("tool_call", tool="read", input_bytes=10, target_sha256="a" * 64),
            _rec(
                "heartbeat_pulse",
                mode="shadow",
                event="turn_start",
                due=True,
                ran=True,
                healthy=True,
                db_ok=True,
                cache_pruned_count=0,
                git_dirty=False,
                issue_codes=[],
                latency_ms=0,
                model_tokens_used=0,
            ),
        ],
    )
    result = telemetry.report(brain_home)["operational"]
    assert result["provider_tokens"]["input"] is None
    assert result["tool_calls"] == 1
    assert result["heartbeat_runs"] == 1


def test_known_kinds_cover_live_records(brain_home):
    path = telemetry.telemetry_dir(brain_home) / "live.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(_rec("model_invocation_completed", usage={})),
                '{"v": 2, "session": "s1"}',
                "not-json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    checked = 0
    for _, _, record in telemetry.iter_records(brain_home):
        if not isinstance(record, dict) or "__parse_error__" in record:
            continue
        kind = record.get("kind")
        if kind is None:
            continue
        checked += 1
        assert kind in telemetry.KNOWN_KINDS
    assert checked > 0


def test_session_usage_reads_hermes_model_invocation_completed(brain_home):
    _write_session(
        brain_home,
        "s1.jsonl",
        [
            _rec(
                "model_invocation_completed",
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_tokens": 3,
                    "cache_write_tokens": None,
                },
            )
        ],
    )

    usage = telemetry.session_usage(brain_home, "s1")

    assert usage["input"] == 10
    assert usage["output"] == 5
    assert usage["cache_read"] == 3
    assert usage["cache_write"] is None
    assert usage["total"] is None
    assert usage["message_count"] == 1
    assert usage["source_kind"] == "model_invocation_completed"


def test_telemetry_schema_has_no_reasoning_fields():
    """Cheap guard: assert SCHEMA.md doesn't declare reasoning/thinking fields."""
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "brainstem" / "telemetry" / "SCHEMA.md"
    if schema_path.exists():
        schema_content = schema_path.read_text(encoding="utf-8", errors="ignore")

        forbidden = ["thinking", "reasoning", "chain_of_thought", "cot", "internal_monologue"]
        for word in forbidden:
            assert word.lower() not in schema_content.lower(), (
                f"SCHEMA.md contains forbidden field: {word}"
            )
