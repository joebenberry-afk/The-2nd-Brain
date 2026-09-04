"""brainctl doctor — health checks for a Brain installation.

Checks are deterministic and evidence-based. Warnings do not fail the doctor;
failures do. Exit code 0 only when every check passes.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, build_identity, db, envsteward, paths

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class DoctorResult:
    home: Path
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(c.status == STATUS_FAIL for c in self.checks)

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == STATUS_WARN]


def _run(cmd: list[str], timeout: float = 15) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "").strip().splitlines()
        return r.returncode == 0, (out[0] if out else "(no output)")
    except FileNotFoundError:
        return False, "not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "timed out"


def check_home(home: Path, checks: list[Check]) -> None:
    if home.exists():
        checks.append(Check("brain home", STATUS_OK, str(home)))
    else:
        checks.append(
            Check("brain home", STATUS_FAIL, f"{home} does not exist; run `brainctl init`")
        )
        return
    # refuse non-empty dirs that are clearly not a Brain
    marker = (home / "VERSION").exists() or (home / "config" / "brain.toml").exists()
    if not marker:
        checks.append(Check("brain marker", STATUS_FAIL, "no VERSION or config/brain.toml"))
    else:
        checks.append(Check("brain marker", STATUS_OK))


def check_layout(home: Path, checks: list[Check]) -> None:
    missing = [d for d in paths.MAJOR_DIRS if not (home / d).is_dir()]
    if missing:
        checks.append(
            Check("layout", STATUS_FAIL, f"missing {len(missing)} dirs: {', '.join(missing[:5])}")
        )
    else:
        checks.append(Check("layout", STATUS_OK, f"{len(paths.MAJOR_DIRS)} major roots present"))


def check_config(home: Path, checks: list[Check]) -> None:
    bad = []
    for name in paths.REQUIRED_CONFIG_FILES:
        p = home / "config" / name
        if not p.exists():
            bad.append(f"{name}: missing")
            continue
        try:
            with open(p, "rb") as f:
                tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            bad.append(f"{name}: {exc}")
    if bad:
        checks.append(Check("config", STATUS_FAIL, "; ".join(bad)))
    else:
        checks.append(Check("config", STATUS_OK, "all config files parse as TOML"))


def check_env(checks: list[Check]) -> None:
    home_env = os.environ.get("SECOND_BRAIN_HOME")
    if home_env is None:
        checks.append(
            Check(
                "SECOND_BRAIN_HOME",
                STATUS_WARN,
                r"unset; defaulting to %USERPROFILE%\Documents\The-Second-Brain",
            )
        )
    else:
        checks.append(Check("SECOND_BRAIN_HOME", STATUS_OK, home_env))
    polluted = [
        k for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME") if os.environ.get(k)
    ]
    if polluted:
        checks.append(
            Check(
                "python env",
                STATUS_WARN,
                f"{', '.join(polluted)} set; this machine's PYTHONHOME is known to break "
                "python launches (SRE module mismatch). Run via brainctl.cmd / bootstrap.ps1 "
                "which sanitize the environment.",
            )
        )
    else:
        checks.append(Check("python env", STATUS_OK, "no PYTHONHOME/PYTHONPATH pollution"))


def check_python(checks: list[Check]) -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(Check("python", STATUS_OK, f"{version} at {sys.executable}"))
    checks.append(Check("sqlite3", STATUS_OK, f"SQLite {sqlite3.sqlite_version}"))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def check_identity(home: Path, checks: list[Check]) -> None:
    env_home = os.environ.get("SECOND_BRAIN_HOME")
    if env_home and not _same_path(home, Path(env_home)):
        checks.append(
            Check(
                "identity coherence",
                STATUS_FAIL,
                f"requested home={home.resolve()}, environment home={Path(env_home).resolve()}",
            )
        )
        return

    package_root = Path(__file__).resolve().parents[2]
    configured_runtime = os.environ.get("SECOND_BRAIN_RUNTIME_ROOT")
    if configured_runtime and not _same_path(package_root, Path(configured_runtime)):
        checks.append(
            Check(
                "identity coherence",
                STATUS_FAIL,
                (
                    f"runtime package={package_root}, "
                    f"configured runtime root={Path(configured_runtime).resolve()}"
                ),
            )
        )
        return

    checks.append(
        Check(
            "identity coherence",
            STATUS_OK,
            (
                f"state={home.resolve()}, runtime={package_root}, "
                f"python={Path(sys.executable).resolve()}"
            ),
        )
    )


def check_git(home: Path, checks: list[Check]) -> None:
    ok, out = _run(["git", "--version"])
    if not ok:
        checks.append(Check("git", STATUS_FAIL, out))
        return
    if not (home / ".git").exists():
        checks.append(Check("git repo", STATUS_FAIL, f"{home} is not a Git repository"))
    else:
        checks.append(Check("git repo", STATUS_OK, out))


def check_build_identity(home: Path, checks: list[Check]) -> None:
    identity = build_identity.describe(home)
    sha = identity["git_sha"] or "unknown"
    dirty = "dirty" if identity["dirty"] else "clean" if identity["dirty"] is False else "unknown"
    fingerprint = identity["adapter_build_fingerprint"]
    detail = (
        f"version={identity['package_version']} sha={sha[:12]} ({dirty}) "
        f"schema={identity['db_schema_version']} "
        f"adapter={fingerprint[:12] if fingerprint else 'unavailable'} "
        f"qualified_baseline={identity['qualification_baseline_sha'][:12]}"
    )
    checks.append(Check("build identity", STATUS_OK, detail))


def check_db(home: Path, checks: list[Check]) -> None:
    dbf = db.db_path(home)
    if not dbf.exists():
        checks.append(Check("database", STATUS_FAIL, f"{dbf} missing; run `brainctl init`"))
        return
    try:
        conn = db.connect(dbf)
    except sqlite3.Error as exc:
        checks.append(Check("database", STATUS_FAIL, f"cannot open: {exc}"))
        return
    try:
        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        checks.append(Check("database", STATUS_OK, f"journal_mode={wal}, foreign_keys={fk}"))
        pending = db.pending_migrations(dbf)
        if pending:
            checks.append(
                Check("migrations", STATUS_FAIL, f"pending: {pending}; run `brainctl init`")
            )
        else:
            v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
            checks.append(Check("migrations", STATUS_OK, f"current at version {v}"))
    finally:
        conn.close()


def check_tools(checks: list[Check]) -> None:
    """Optional-but-expected implementation tools (plan §5.4)."""
    for name in ("rg", "ast-grep", "repowise", "uv"):
        ok, out = _run([name, "--version"])
        if ok:
            checks.append(Check(f"tool:{name}", STATUS_OK, out))
        else:
            checks.append(Check(f"tool:{name}", STATUS_WARN, out))


def check_version_file(home: Path, checks: list[Check]) -> None:
    vf = home / "VERSION"
    if vf.exists():
        file_v = vf.read_text(encoding="utf-8").strip()
        if file_v == __version__:
            checks.append(Check("version", STATUS_OK, file_v))
        else:
            checks.append(Check("version", STATUS_WARN, f"VERSION={file_v}, package={__version__}"))
    else:
        checks.append(Check("version", STATUS_FAIL, "VERSION file missing"))


def check_environment(
    home: Path,
    repo: Path | None,
    session_id: str | None,
    checks: list[Check],
) -> dict | None:
    root = Path(repo) if repo is not None else Path.cwd()
    try:
        evidence = (
            envsteward.assess(
                home,
                root,
                session_id=session_id,
                phase="doctor",
                doctor_check_state="passed",
            )
            if session_id is not None
            else envsteward.snapshot(home, root)
        )
    except Exception as exc:
        checks.append(Check("environment steward", STATUS_FAIL, f"assessment failed: {exc}"))
        return None
    if evidence.get("completion_eligible") is False:
        checks.append(
            Check(
                "environment steward",
                STATUS_FAIL,
                (
                    f"{evidence.get('environment_steward_id')} "
                    f"mutation={evidence.get('mutation_classification')}"
                ),
            )
        )
    else:
        checks.append(
            Check(
                "environment steward",
                STATUS_OK,
                f"{evidence.get('environment_steward_id')} session={session_id or 'unpersisted'}",
            )
        )
    return evidence


def run_doctor(
    home: Path | None = None,
    *,
    repo: Path | None = None,
    session_id: str | None = None,
) -> DoctorResult:
    home = Path(home) if home else paths.resolve_home()
    checks: list[Check] = []
    check_home(home, checks)
    if not any(c.status == STATUS_FAIL for c in checks):
        check_layout(home, checks)
        check_config(home, checks)
        check_version_file(home, checks)
        check_env(checks)
        check_python(checks)
        check_identity(home, checks)
        check_git(home, checks)
        check_db(home, checks)
        check_build_identity(home, checks)
        check_tools(checks)
        check_environment(home, repo, session_id, checks)
    return DoctorResult(home=home, checks=checks)


def format_result(result: DoctorResult) -> str:
    lines = [f"Brain home: {result.home}"]
    for c in result.checks:
        mark = {"ok": "PASS", "warn": "WARN", "fail": "FAIL"}[c.status]
        detail = f" — {c.detail}" if c.detail else ""
        lines.append(f"[{mark}] {c.name}{detail}")
    n_fail = sum(1 for c in result.checks if c.status == STATUS_FAIL)
    n_warn = sum(1 for c in result.checks if c.status == STATUS_WARN)
    lines.append(f"{len(result.checks)} checks: {n_fail} failed, {n_warn} warnings")
    return "\n".join(lines)
