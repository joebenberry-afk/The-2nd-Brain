import json

from second_brain import db, doctor, semantic


def _statuses(result):
    return {c.name: c.status for c in result.checks}


def test_doctor_passes_on_fresh_brain(brain_home, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(brain_home))
    result = doctor.run_doctor(brain_home)
    assert not result.failed
    assert _statuses(result)["database"] == "ok"
    assert _statuses(result)["migrations"] == "ok"
    assert _statuses(result)["layout"] == "ok"


def test_doctor_detects_missing_canonical_memory(brain_home):
    memory_id = semantic.add_memory(brain_home, "Durable fact", "Canonical source.", scope="global")
    relative = semantic.show_memory(brain_home, memory_id)["row"]["body_path"]
    (brain_home / relative).unlink()
    checks = []

    doctor.check_db(brain_home, checks)

    assert any(check.status == doctor.STATUS_FAIL for check in checks)


def test_doctor_fails_on_missing_home(tmp_path, monkeypatch):
    result = doctor.run_doctor(tmp_path / "nope")
    assert result.failed
    assert _statuses(result)["brain home"] == "fail"


def test_doctor_fails_on_missing_layout_dir(brain_home):
    import shutil

    shutil.rmtree(brain_home / "constitution")
    result = doctor.run_doctor(brain_home)
    assert _statuses(result)["layout"] == "fail"


def test_doctor_fails_on_missing_config(brain_home):
    (brain_home / "config" / "brain.toml").unlink()
    result = doctor.run_doctor(brain_home)
    assert _statuses(result)["config"] == "fail"


def test_doctor_fails_on_missing_db(brain_home):
    db.db_path(brain_home).unlink()
    result = doctor.run_doctor(brain_home)
    assert _statuses(result)["database"] == "fail"


def test_doctor_fails_on_pending_migration(brain_home):
    conn = db.connect(db.db_path(brain_home))
    try:
        conn.execute("DELETE FROM schema_version")
        conn.commit()
    finally:
        conn.close()
    result = doctor.run_doctor(brain_home)
    assert _statuses(result)["migrations"] == "fail"


def test_doctor_warns_on_python_env_pollution(brain_home, monkeypatch):
    monkeypatch.setenv("PYTHONHOME", "C:/fake")
    result = doctor.run_doctor(brain_home)
    assert _statuses(result)["python env"] == "warn"
    assert not result.failed


def test_doctor_fails_when_explicit_and_environment_homes_differ(brain_home, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(brain_home.parent / "other-brain"))

    result = doctor.run_doctor(brain_home)

    assert _statuses(result)["identity coherence"] == "fail"


def test_doctor_fails_when_runtime_root_disagrees(brain_home, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(brain_home))
    monkeypatch.setenv("SECOND_BRAIN_RUNTIME_ROOT", str(brain_home / "other-runtime"))

    result = doctor.run_doctor(brain_home)

    assert _statuses(result)["identity coherence"] == "fail"


def test_format_result(brain_home):
    text = doctor.format_result(doctor.run_doctor(brain_home))
    assert "PASS" in text
    assert "Brain home" in text


def test_doctor_reports_environment_steward_state(brain_home, repo):
    result = doctor.run_doctor(brain_home, repo=repo, session_id="doctor-session")
    env_check = next(check for check in result.checks if check.name == "environment steward")
    assert env_check.status == "ok"
    assert "doctor-session" in env_check.detail
    persisted = brain_home / "state" / "sessions" / "doctor-session" / "environment-evidence.json"
    assert persisted.is_file()
    payload = json.loads(persisted.read_text())
    assert payload["doctor_check_state"] == "passed"
