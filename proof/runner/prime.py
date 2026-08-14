"""Minimal Prime Agent subprocess adapter for C0/C1 evidence."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .condition import Condition, parse_condition
from .sanitize import sanitize_text


@dataclass(frozen=True)
class PrimeResult:
    exit_code: int | None
    stdout: str
    stderr: str
    wall_seconds: float
    timed_out: bool


def _launcher(launcher: Path) -> list[str]:
    if launcher.suffix.lower() == ".sh":
        bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        return [str(bash if bash.exists() else "bash"), str(launcher)]
    return [str(launcher)]


def run_prime(
    *,
    condition: str | Condition,
    prompt: str,
    cwd: Path,
    brain_home: Path,
    launcher: Path,
    model: str,
    thinking: str = "minimal",
    extension: Path | None = None,
    session_dir: Path | None = None,
    timeout_s: float = 300.0,
    offline: bool = False,
) -> PrimeResult:
    """Run one fresh Prime process with condition-specific flags."""
    selected = parse_condition(condition)
    if selected not in (Condition.C0_OFF, Condition.C1_OBSERVABILITY):
        raise RuntimeError(
            f"{selected.value} refused: official automatic Brain integration is not verified"
        )
    if selected is Condition.C1_OBSERVABILITY and extension is None:
        raise ValueError("C1 requires the explicit observability extension path")
    args = [*_launcher(launcher), "-p", "--cwd", str(cwd), "--model", model, "--thinking", thinking]
    if session_dir is not None:
        args.extend(["--session-dir", str(session_dir)])
    if offline:
        args.append("--offline")
    if selected is Condition.C0_OFF:
        args.append("--no-extensions")
    else:
        args.extend(["--extension", str(extension)])
    args.append(prompt)

    environment = os.environ.copy()
    environment["SECOND_BRAIN_HOME"] = str(brain_home)
    environment["SECOND_BRAIN_OBSERVABILITY"] = "off" if selected is Condition.C0_OFF else "on"
    for key in list(environment):
        if key.startswith("PRIME_AGENT_INTERNAL_"):
            environment.pop(key, None)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        return PrimeResult(
            exit_code=None,
            stdout=sanitize_text(str(exc.stdout or ""))[-4000:],
            stderr=sanitize_text(str(exc.stderr or ""))[-4000:],
            wall_seconds=elapsed,
            timed_out=True,
        )
    elapsed = time.perf_counter() - started
    return PrimeResult(
        exit_code=completed.returncode,
        stdout=sanitize_text(completed.stdout)[-4000:],
        stderr=sanitize_text(completed.stderr)[-4000:],
        wall_seconds=elapsed,
        timed_out=False,
    )
