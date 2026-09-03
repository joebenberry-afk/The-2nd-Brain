"""Tests for the working set: active-state capsule, requirement and read ledgers."""

import hashlib
import json
import string
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import working_set as ws
from second_brain.errors import BrainError


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _nonempty_text(max_size=40):
    return st.text(alphabet=string.ascii_letters + string.digits + " _-", min_size=1)


# ---------------------------------------------------------------------------
# Capsule
# ---------------------------------------------------------------------------


def test_init_creates_capsule_with_defaults(brain_home):
    path = ws.init_capsule(brain_home, "s1", "Build the thing")
    assert path == brain_home / "state" / "sessions" / "s1" / "active-state.json"
    assert path.is_file()
    capsule = ws.show_capsule(brain_home, "s1")
    assert capsule["objective"] == "Build the thing"
    assert capsule["task_mode"] == "STANDARD"
    assert capsule["risk"] == "MEDIUM"
    assert capsule["constraints"] == []
    assert capsule["verification"] == {}
    assert capsule["next_action"] == ""
    assert capsule["updated_at"]
    for field in ws.CAPSULE_LIST_FIELDS:
        assert capsule[field] == []
    assert set(capsule) == set(ws.CAPSULE_FIELDS)


def test_update_merges_and_refreshes_updated_at(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    first = ws.show_capsule(brain_home, "s1")["updated_at"]
    ws.update_capsule(
        brain_home,
        "s1",
        objective="New objective",
        task_mode="DEEP",
        constraints=["one", "two"],
        verification={"ran": "true"},
    )
    capsule = ws.show_capsule(brain_home, "s1")
    assert capsule["objective"] == "New objective"
    assert capsule["task_mode"] == "DEEP"
    assert capsule["risk"] == "MEDIUM"  # untouched
    assert capsule["constraints"] == ["one", "two"]
    assert capsule["verification"] == {"ran": "true"}
    assert capsule["confirmed_facts"] == []  # untouched
    assert capsule["updated_at"] >= first


def test_update_unknown_field_rejected(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    with pytest.raises(BrainError, match="Unknown capsule field"):
        ws.update_capsule(brain_home, "s1", not_a_field=["x"])


def test_update_invalid_enums_rejected(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    with pytest.raises(BrainError, match="task_mode"):
        ws.update_capsule(brain_home, "s1", task_mode="BOGUS")
    with pytest.raises(BrainError, match="risk"):
        ws.update_capsule(brain_home, "s1", risk="EXTREME")


def test_update_type_checks(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    with pytest.raises(BrainError, match="constraints"):
        ws.update_capsule(brain_home, "s1", constraints="nope")
    with pytest.raises(BrainError, match="constraints"):
        ws.update_capsule(brain_home, "s1", constraints=["ok", 5])
    with pytest.raises(BrainError, match="verification"):
        ws.update_capsule(brain_home, "s1", verification="nope")
    with pytest.raises(BrainError, match="verification"):
        ws.update_capsule(brain_home, "s1", verification={"k": ["nested"]})
    with pytest.raises(BrainError, match="objective"):
        ws.update_capsule(brain_home, "s1", objective="   ")
    with pytest.raises(BrainError, match="updated_at"):
        ws.update_capsule(brain_home, "s1", updated_at="2000-01-01")


def test_double_init_fails(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    with pytest.raises(BrainError, match="already exists"):
        ws.init_capsule(brain_home, "s1", "Objective again")


def test_init_validates_arguments(brain_home):
    with pytest.raises(BrainError, match="objective"):
        ws.init_capsule(brain_home, "s1", "   ")
    with pytest.raises(BrainError, match="task_mode"):
        ws.init_capsule(brain_home, "s1", "Objective", task_mode="FAST")
    with pytest.raises(BrainError, match="risk"):
        ws.init_capsule(brain_home, "s1", "Objective", risk="LOWISH")
    with pytest.raises(BrainError, match="constraints"):
        ws.init_capsule(brain_home, "s1", "Objective", constraints=["ok", 1])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    ["..", ".", "a/b", "a\\b", "", "x" * 65, "has space", "semi;colon"],
)
def test_session_id_rejects_unsafe_ids(brain_home, bad):
    with pytest.raises(BrainError):
        ws.session_dir(brain_home, bad)
    with pytest.raises(BrainError):
        ws.init_capsule(brain_home, bad, "Objective")


def test_session_id_valid_ids_roundtrip(brain_home):
    for sid in ["abc", "session-1", "a.b_c", "x" * 64, "A1.-_z"]:
        ws.init_capsule(brain_home, sid, "Objective")
        assert ws.show_capsule(brain_home, sid)["objective"] == "Objective"

def test_session_dir_reuses_ledger_internal_identity_when_present(brain_home):
    from second_brain.ledger import internal_session_id

    host_session = "2026-08-24T05-12-05-023Z_01a0322e-d49f-74a1-9084-5e7129e7457d"
    internal = internal_session_id(host_session)
    hashed = brain_home / "state" / "sessions" / internal
    hashed.mkdir(parents=True)

    assert ws.session_dir(brain_home, host_session) == hashed


# ---------------------------------------------------------------------------
# Requirement ledger
# ---------------------------------------------------------------------------


def test_requirement_auto_ids(brain_home):
    a = ws.add_requirement(brain_home, "s1", "First")
    b = ws.add_requirement(brain_home, "s1", "Second")
    c = ws.add_requirement(brain_home, "s1", "Third")
    assert [e["id"] for e in (a, b, c)] == ["REQ-001", "REQ-002", "REQ-003"]
    assert all(e["evidence"] == [] and e["status"] == "unverified" for e in (a, b, c))
    assert a["importance"] == "normal"


def test_requirement_custom_id_and_gap_free_auto(brain_home):
    ws.add_requirement(brain_home, "s1", "First", req_id="REQ-010")
    assert ws.add_requirement(brain_home, "s1", "Second")["id"] == "REQ-011"
    with pytest.raises(BrainError, match="already exists"):
        ws.add_requirement(brain_home, "s1", "Third", req_id="REQ-010")
    with pytest.raises(BrainError, match="Invalid requirement id"):
        ws.add_requirement(brain_home, "s1", "Third", req_id="REQ-x")


def test_requirement_duplicate_text_rejected(brain_home):
    ws.add_requirement(brain_home, "s1", "Do the thing")
    with pytest.raises(BrainError, match="Duplicate requirement"):
        ws.add_requirement(brain_home, "s1", "Do the thing")
    with pytest.raises(BrainError, match="importance"):
        ws.add_requirement(brain_home, "s1", "Another", importance="urgent")


def test_evidence_append_and_unknown_req(brain_home):
    ws.add_requirement(brain_home, "s1", "Req A", importance="critical")
    ws.add_evidence(brain_home, "s1", "REQ-001", "evidence one")
    ws.add_evidence(brain_home, "s1", "REQ-001", "evidence two")
    entry = ws.show_requirements(brain_home, "s1")[0]
    assert entry["evidence"] == ["evidence one", "evidence two"]
    with pytest.raises(BrainError, match="Unknown requirement id"):
        ws.add_evidence(brain_home, "s1", "REQ-999", "nope")
    with pytest.raises(BrainError, match="evidence"):
        ws.add_evidence(brain_home, "s1", "REQ-001", "   ")


def test_status_transitions(brain_home):
    ws.add_requirement(brain_home, "s1", "Req A")
    for status in ws.REQUIREMENT_STATUSES:
        entry = ws.set_requirement_status(brain_home, "s1", "REQ-001", status)
        assert entry["status"] == status
    with pytest.raises(BrainError, match="status"):
        ws.set_requirement_status(brain_home, "s1", "REQ-001", "done")
    with pytest.raises(BrainError, match="Unknown requirement id"):
        ws.set_requirement_status(brain_home, "s1", "REQ-002", "verified")


def test_check_requirements_material_counting(brain_home):
    ws.add_requirement(brain_home, "s1", "Critical unverified", importance="critical")
    ws.add_requirement(brain_home, "s1", "Normal unverified", importance="normal")
    ws.add_requirement(brain_home, "s1", "Critical verified", importance="critical")
    ws.set_requirement_status(brain_home, "s1", "REQ-003", "verified")
    ws.add_requirement(brain_home, "s1", "High partial", importance="high")
    ws.set_requirement_status(brain_home, "s1", "REQ-004", "partially_verified")
    ws.add_requirement(brain_home, "s1", "Critical n/a", importance="critical")
    ws.set_requirement_status(brain_home, "s1", "REQ-005", "not_applicable")

    check = ws.check_requirements(brain_home, "s1")
    assert check["material_total"] == 4
    assert check["material_unverified"] == 2
    ids = [e["id"] for e in check["entries"]]
    assert ids == ["REQ-001", "REQ-004"]
    assert check["entries"][0]["importance"] == "critical"


def test_show_requirements_empty_and_order(brain_home):
    assert ws.show_requirements(brain_home, "s1") == []
    for i in range(3):
        ws.add_requirement(brain_home, "s1", f"Req {i}")
    assert [e["requirement"] for e in ws.show_requirements(brain_home, "s1")] == [
        "Req 0",
        "Req 1",
        "Req 2",
    ]


# ---------------------------------------------------------------------------
# Read ledger
# ---------------------------------------------------------------------------


def test_record_read_hash_matches_content(brain_home, tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("hello world", encoding="utf-8")
    ws.record_read(brain_home, "s1", str(target), "understand")
    entry = ws.show_reads(brain_home, "s1")[0]
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    assert entry["hash"] == expected
    assert entry["blob_sha"] == expected
    assert entry["path"] == str(target)
    assert entry["purpose"] == "understand"


def test_record_read_missing_file_null_hash(brain_home, tmp_path):
    missing = tmp_path / "gone.txt"
    ws.record_read(brain_home, "s1", str(missing), "probe", turn=2)
    entry = ws.show_reads(brain_home, "s1")[0]
    assert entry["hash"] is None
    assert entry["blob_sha"] is None
    assert entry["turn"] == 2


def test_record_read_append_only_order(brain_home, tmp_path):
    paths = []
    for i in range(4):
        p = tmp_path / f"f{i}.txt"
        p.write_text(f"content {i}", encoding="utf-8")
        paths.append(str(p))
        ws.record_read(brain_home, "s1", str(p), f"purpose {i}", range_text=f"{i}-{i}")
    entries = ws.show_reads(brain_home, "s1")
    assert [e["path"] for e in entries] == paths
    assert [e["range"] for e in entries] == ["0-0", "1-1", "2-2", "3-3"]
    assert all(e["ts"] for e in entries)
    assert entries[0]["ts"] <= entries[-1]["ts"]


def test_record_read_artifact(brain_home, tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x", encoding="utf-8")
    ws.record_read(brain_home, "s1", str(p), "scan", artifact="tool-result-3")
    entry = ws.show_reads(brain_home, "s1")[0]
    assert entry["artifact"] == "tool-result-3"
    assert entry["distilled_ref"] == "tool-result-3"


def test_reread_hint_on_unchanged_blob(brain_home, tmp_path):
    target = tmp_path / "stable.txt"
    target.write_text("same", encoding="utf-8")
    ws.record_read(brain_home, "s1", str(target), "inspect", turn=7, artifact="sha256:abc")
    assert ws.reread_hint(brain_home, "s1", str(target)) == {
        "unchanged": True,
        "prior_artifact": "sha256:abc",
        "prior_turn": 7,
    }


def test_reread_hint_changed_missing_and_traversal(brain_home, tmp_path):
    target = tmp_path / "mutable.txt"
    target.write_text("before", encoding="utf-8")
    ws.record_read(brain_home, "s1", str(target), "inspect", turn=1, artifact="ref")
    target.write_text("after", encoding="utf-8")
    assert ws.reread_hint(brain_home, "s1", str(target)) is None
    target.unlink()
    assert ws.reread_hint(brain_home, "s1", str(target)) is None
    with pytest.raises(BrainError, match="Invalid session id"):
        ws.reread_hint(brain_home, "../escape", str(target))

def test_reread_hint_rejects_prior_selected_read(brain_home, tmp_path):
    target = tmp_path / "selected.txt"
    target.write_text("same", encoding="utf-8")
    ws.record_read(
        brain_home,
        "s1",
        str(target),
        "inspect",
        turn=2,
        range_text="1-2",
        artifact="partial-ref",
    )
    assert ws.reread_hint(brain_home, "s1", str(target)) is None


def test_record_read_validates(brain_home):
    with pytest.raises(BrainError, match="path"):
        ws.record_read(brain_home, "s1", "  ", "purpose")
    with pytest.raises(BrainError, match="purpose"):
        ws.record_read(brain_home, "s1", "some/path", "   ")
    with pytest.raises(BrainError, match="turn"):
        ws.record_read(brain_home, "s1", "some/path", "purpose", turn="3")  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="artifact"):
        ws.record_read(brain_home, "s1", "some/path", "purpose", artifact=5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Corrupt files
# ---------------------------------------------------------------------------


def test_corrupt_capsule_json_raises_with_path(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    path = brain_home / "state" / "sessions" / "s1" / "active-state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        ws.show_capsule(brain_home, "s1")
    assert str(path) in str(exc.value)


def test_corrupt_capsule_shape_raises(brain_home):
    ws.init_capsule(brain_home, "s1", "Objective")
    path = brain_home / "state" / "sessions" / "s1" / "active-state.json"
    data = _read_json(path)
    del data["constraints"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        ws.show_capsule(brain_home, "s1")
    assert str(path) in str(exc.value)

    data["constraints"] = ["fine", 42]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        ws.show_capsule(brain_home, "s1")
    assert str(path) in str(exc.value)


def test_corrupt_requirements_and_reads_raise(brain_home):
    req = brain_home / "state" / "sessions" / "s1" / "requirements.json"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        ws.show_requirements(brain_home, "s1")
    assert str(req) in str(exc.value)

    reads = brain_home / "state" / "sessions" / "s1" / "read-ledger.json"
    reads.write_text("[{}]", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        ws.show_reads(brain_home, "s1")
    assert str(reads) in str(exc.value)


def test_missing_capsule_raises(brain_home):
    with pytest.raises(BrainError, match="Missing state file"):
        ws.show_capsule(brain_home, "nosession")


# ---------------------------------------------------------------------------
# Hypothesis: randomized invariants
# ---------------------------------------------------------------------------

_FIELD_STRATEGIES = {
    "objective": st.text(alphabet=string.ascii_letters + string.digits, min_size=1),
    "task_mode": st.sampled_from(ws.TASK_MODES),
    "risk": st.sampled_from(ws.RISK_LEVELS),
    "constraints": st.lists(st.text(max_size=20), max_size=5),
    "confirmed_facts": st.lists(st.text(max_size=20), max_size=5),
    "current_hypotheses": st.lists(st.text(max_size=20), max_size=5),
    "decisions_this_session": st.lists(st.text(max_size=20), max_size=5),
    "files_touched": st.lists(st.text(max_size=20), max_size=5),
    "open_questions": st.lists(st.text(max_size=20), max_size=5),
    "verification": st.dictionaries(
        st.text(max_size=20),
        st.one_of(st.text(max_size=20), st.integers(), st.booleans()),
        max_size=5,
    ),
    "next_action": st.text(max_size=40),
    "brain_refs": st.lists(st.text(max_size=20), max_size=5),
    "artifact_refs": st.lists(st.text(max_size=20), max_size=5),
}
_PARTIAL_UPDATE = st.fixed_dictionaries(
    {key: st.one_of(st.none(), value) for key, value in _FIELD_STRATEGIES.items()}
)


def _clean_update(update):
    return {key: value for key, value in update.items() if value is not None}


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(_PARTIAL_UPDATE, max_size=8))
def test_random_update_sequences_roundtrip(brain_home, updates):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    ws.init_capsule(home, "sid", "Initial objective")
    expected = ws.show_capsule(home, "sid")
    for update in updates:
        ws.update_capsule(home, "sid", **_clean_update(update))
        expected.update(_clean_update(update))
        actual = ws.show_capsule(home, "sid")
        assert {k: v for k, v in actual.items() if k != "updated_at"} == {
            k: v for k, v in expected.items() if k != "updated_at"
        }


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(st.sampled_from(("add", "evidence", "status")), min_size=1, max_size=40),
    st.lists(
        st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=30),
        min_size=1,
        max_size=12,
    ),
)
def test_random_requirement_sequences_keep_invariants(brain_home, ops, texts):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    expected = []
    used_texts = set()
    for op in ops:
        if op == "add":
            text = texts[len(used_texts) % len(texts)]
            if text in used_texts:
                with pytest.raises(BrainError, match="Duplicate requirement"):
                    ws.add_requirement(home, "sid", text)
                continue
            used_texts.add(text)
            entry = ws.add_requirement(home, "sid", text)
            expected.append(entry)
        else:
            if not expected:
                continue
            entry = expected[0]
            if op == "evidence":
                ws.add_evidence(home, "sid", entry["id"], f"evidence-{len(entry['evidence'])}")
                expected[0] = ws.show_requirements(home, "sid")[0]
            else:
                status = ws.REQUIREMENT_STATUSES[len(expected) % len(ws.REQUIREMENT_STATUSES)]
                ws.set_requirement_status(home, "sid", entry["id"], status)
                expected[0] = ws.show_requirements(home, "sid")[0]
    entries = ws.show_requirements(home, "sid")
    assert len({e["id"] for e in entries}) == len(entries)  # ids unique
    assert [e["id"] for e in entries] == [e["id"] for e in expected]  # order stable
    assert [e["evidence"] for e in entries] == [e["evidence"] for e in expected]


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text(max_size=80))
def test_session_id_accept_or_raise_property(brain_home, sid):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    try:
        path = ws.init_capsule(home, sid, "Objective")
    except BrainError:
        return
    # Accepted ids must round-trip and live under state/sessions/.
    assert path.parent == home / "state" / "sessions" / sid
    assert ws.show_capsule(home, sid)["objective"] == "Objective"


def test_material_gate_config_wiring(brain_home):
    """Scout finding: verification.toml gate knob must be honored."""
    ws.add_requirement(brain_home, "s1", "critical thing", importance="critical")
    result = ws.check_requirements(brain_home, "s1")
    assert result["gate"] is True and result["blocks"] is True  # default config gate on

    (brain_home / "config" / "verification.toml").write_text(
        "[requirement_ledger]\nmaterial_unverified_blocks_completion = false\n",
        encoding="utf-8",
    )
    result = ws.check_requirements(brain_home, "s1")
    assert result["gate"] is False and result["blocks"] is False
    assert result["material_unverified"] == 1

    (brain_home / "config" / "verification.toml").unlink()
    result = ws.check_requirements(brain_home, "s1")
    assert result["gate"] is True  # fail-safe default

# ---------------------------------------------------------------------------
# P3-H: STOP / Requirement-Ledger dogfood (plan §15 + §24.7)
# ---------------------------------------------------------------------------


def test_material_unverified_remains_completion_gate(brain_home):
    """A material (critical/high) requirement left unverified BLOCKS."""
    ws.add_requirement(brain_home, "s1", "fix the parser", importance="high")
    ws.add_requirement(brain_home, "s1", "keep config intact", importance="normal")
    result = ws.check_requirements(brain_home, "s1")
    assert result["material_total"] == 1
    assert result["material_unverified"] == 1
    assert result["gate"] is True
    assert result["blocks"] is True  # completion gate closed
    # the CLI exit code is the gate signal
    assert len(result["entries"]) == 1 and result["entries"][0]["id"] == "REQ-001"


def test_all_material_verified_or_na_permits_stop(brain_home):
    ws.add_requirement(brain_home, "s1", "fix the parser", importance="high")
    ws.add_requirement(brain_home, "s1", "schema stays v1", importance="critical")
    assert ws.check_requirements(brain_home, "s1")["blocks"] is True
    ws.set_requirement_status(brain_home, "s1", "REQ-001", "verified")
    ws.set_requirement_status(brain_home, "s1", "REQ-002", "not_applicable")
    result = ws.check_requirements(brain_home, "s1")
    assert result["material_unverified"] == 0
    assert result["blocks"] is False  # stop permitted
    assert result["entries"] == []


def test_cli_requirements_check_blocks_and_permits(brain_home):
    """End-to-end: `brainctl requirements check` exit 1 while a material
    requirement is unverified, exit 0 once all material are verified/N-A."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)

    ws.init_capsule(brain_home, "dogfood-s1", "Complete the change")
    ws.add_requirement(brain_home, "dogfood-s1", "behavior works", importance="high")
    legacy = "no regression on legacy input"
    ws.add_requirement(brain_home, "dogfood-s1", legacy, importance="critical")

    def check():
        return subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(brain_home),
             "requirements", "check", "dogfood-s1"],
            capture_output=True, text=True, env=env, cwd=brain_home, timeout=120,
        )

    blocked = check()
    assert blocked.returncode == 1, blocked.stdout
    assert "2/2 material requirements unverified (gate on)" in blocked.stdout
    ws.set_requirement_status(brain_home, "dogfood-s1", "REQ-001", "verified")
    assert check().returncode == 1  # still blocked by REQ-002
    ws.set_requirement_status(brain_home, "dogfood-s1", "REQ-002", "verified")
    permitted = check()
    assert permitted.returncode == 0, permitted.stdout
    assert "0/2 material requirements unverified (gate on)" in permitted.stdout


def test_no_lean_path_bypasses_requirement_ledger():
    """Structural: the Lean candidate skill instructs requirement
    verification and contains NO bypass instruction; the Lean runtime
    adapter has no requirement-ledger code path (never touches it)."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    skill = (repo_root / "skills" / "candidates" / "lean-code" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    # positive: the canonical skill mandates the requirement check before stop
    assert "material requirements are verified before stopping" in skill
    assert "Requirement Ledger" in skill
    # negative: no bypass language
    for bypass in (
        "skip the requirement",
        "ignore the requirement",
        "without verifying",
        "bypass",
        "do not run the ledger",
    ):
        assert bypass not in skill.lower(), f"lean skill contains bypass language: {bypass}"

    adapter = (repo_root / "brainstem" / "prime-extension" / "src" / "lean-code.ts").read_text(
        encoding="utf-8"
    ).lower()
    # the adapter's scope is the runtime kernel only: no requirements surface
    for token in ("requirement", "requirements.json", "material_unverified"):
        assert token not in adapter, f"lean-code.ts references {token!r}"


def test_all_material_verified_triggers_no_continuation(brain_home):
    """A completed task (all material verified) leaves the gate open for
    stop: check_requirements reports blocks=False — the STOP mechanism has
    no continuation step of its own."""
    ws.add_requirement(brain_home, "s1", "done thing", importance="high")
    ws.set_requirement_status(brain_home, "s1", "REQ-001", "verified")
    result = ws.check_requirements(brain_home, "s1")
    assert result["blocks"] is False
    assert result["material_unverified"] == 0
    assert result["entries"] == []  # nothing left that would trigger more work
