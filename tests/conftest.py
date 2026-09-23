import os
import shutil
import subprocess
from pathlib import Path

import pytest

from second_brain import db, paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def clean_python_env() -> dict[str, str]:
    """Bind CLI children to this candidate without inherited interpreter state."""
    if not Path(db.__file__).resolve().is_relative_to(REPO_ROOT / "src"):
        raise RuntimeError("test runner imported Brain outside the candidate")
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    env.pop("SECOND_BRAIN_HOME", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return env


def make_brain(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a complete, minimal Brain installation under `home`."""
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home))
    paths.ensure_layout(home)
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    cfg = home / "config"
    for name in paths.REQUIRED_CONFIG_FILES:
        (cfg / name).write_text("schema_version = 1\n", encoding="utf-8")
    shutil.copytree(REPO_ROOT / "templates", home / "templates", dirs_exist_ok=True)
    db.migrate(db.db_path(home))
    subprocess.run(["git", "init", "-q"], cwd=home, check=True, capture_output=True)
    return home


@pytest.fixture
def brain_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_brain(tmp_path / "brain", monkeypatch)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fake external repository for registry tests."""
    r = tmp_path / "some-repo"
    r.mkdir(parents=True)
    (r / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=r, check=True, capture_output=True)
    return r
