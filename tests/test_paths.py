from pathlib import Path

from second_brain import paths


def test_default_home_is_documents():
    assert paths.default_home() == Path.home() / "Documents" / "The-Second-Brain"


def test_resolve_home_env_wins(monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_HOME", "C:/tmp/my-brain")
    assert paths.resolve_home() == Path("C:/tmp/my-brain")


def test_resolve_home_default_when_unset(monkeypatch):
    monkeypatch.delenv("SECOND_BRAIN_HOME", raising=False)
    assert paths.resolve_home() == paths.default_home()


def test_ensure_layout_idempotent(tmp_path):
    home = tmp_path / "b"
    paths.ensure_layout(home)
    first = {p for p in home.rglob("*")}
    paths.ensure_layout(home)
    second = {p for p in home.rglob("*")}
    assert first == second
    assert all((home / d).is_dir() for d in paths.MAJOR_DIRS)
