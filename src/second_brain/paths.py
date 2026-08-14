"""Canonical path resolution for The Second Brain.

Rule (plan §1): resolve the Brain root from, in order:
1. the SECOND_BRAIN_HOME environment variable, if set;
2. otherwise %USERPROFILE%\\Documents\\The-Second-Brain.

Source code never hardcodes the absolute path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DISPLAY_NAME = "The Second Brain"

# Major roots created on init (plan §6). Deeper folders are created on demand.
MAJOR_DIRS: tuple[str, ...] = (
    "constitution",
    "config",
    "brainstem/prime-extension",
    "brainstem/adapters",
    "brainstem/policies",
    "brainstem/telemetry",
    "brainstem/tests",
    "memory/episodic",
    "memory/semantic",
    "memory/procedural",
    "memory/meta",
    "memory/archive",
    "projects",
    "experiences/successes",
    "experiences/failures",
    "experiences/incidents",
    "experiences/experiments",
    "decisions/global",
    "decisions/projects",
    "skills/candidates",
    "skills/shadow",
    "skills/staged",
    "skills/approved/global",
    "skills/approved/domain",
    "skills/approved/project",
    "skills/approved/model",
    "skills/evals",
    "skills/quarantine",
    "skills/retired",
    "skills/principles",
    "engrams/candidates",
    "engrams/shadow",
    "engrams/active",
    "engrams/retired",
    "plasticity/prediction-errors",
    "plasticity/rewards",
    "plasticity/credit",
    "plasticity/routing",
    "plasticity/hindsight",
    "sleep/replay-queue",
    "sleep/consolidation",
    "sleep/dreaming",
    "sleep/reconsolidation",
    "sleep/reports",
    "frontier/projects",
    "lexicon/projects",
    "immune/quarantine",
    "immune/fingerprints",
    "immune/trust",
    "immune/baselines",
    "immune/reports",
    "outputs/context-capsules",
    "outputs/evidence-maps",
    "outputs/handoffs",
    "outputs/plans",
    "outputs/audits",
    "outputs/reports",
    "state/sessions",
    "state/artifacts",
    "state/ownership",
    "state/locks",
    "state/projections",
    "state/cache",
    "telemetry/agent-performance",
    "db",
    "templates",
    "scripts",
    "src/second_brain",
    "tests",
)

REQUIRED_CONFIG_FILES: tuple[str, ...] = (
    "brain.toml",
    "context.toml",
    "learning.toml",
    "retrieval.toml",
    "verification.toml",
    "environment.toml",
    "skills.toml",
    "sleep.toml",
)


def default_home() -> Path:
    """The default Brain root when SECOND_BRAIN_HOME is unset."""
    return Path.home() / "Documents" / "The-Second-Brain"


def resolve_home(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the canonical Brain root (plan §1)."""
    environ = env if env is not None else os.environ
    raw = environ.get("SECOND_BRAIN_HOME")
    if raw:
        return Path(raw).expanduser()
    return default_home()


def ensure_layout(home: Path) -> None:
    """Create major roots (idempotent). Deeper folders are created on demand."""
    for rel in MAJOR_DIRS:
        (home / rel).mkdir(parents=True, exist_ok=True)


def db_path(home: Path) -> Path:
    return home / "db" / "brain.sqlite"


def backups_dir(home: Path) -> Path:
    return home / "backups"
