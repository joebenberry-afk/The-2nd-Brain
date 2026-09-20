"""Refresh the qualification identity artifacts reproducibly.

Writes, from the live executed files:
- docs/integrations/omp-host-patch-2026-09-19/HASHES.txt (loaded host identity)
- docs/integrations/omp-host-patch-2026-09-19/RUN-IDENTITIES.json (the full
  run identity inventory consumed by the launcher's binding gate)
- tracked host/test snapshots under the same directory

Run after any change to a bound file: the launcher refuses to start when a
listed identity is null or mismatched, and the campaign tests validate the
inventory against the live files.

Usage: python refresh_identities.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
CANARY = Path(r"C:\Users\assas\.bun\install\global\node_modules\@oh-my-pi\pi-coding-agent-canary")
DOCS = WORKTREE / "docs" / "integrations" / "omp-host-patch-2026-09-19"
PYTHON = Path(r"C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    snapshots = {
        CANARY / "src/async/job-manager.ts": DOCS / "host/job-manager.ts",
        CANARY / "src/session/agent-session.ts": DOCS / "host/agent-session.ts",
        CANARY / "src/task/isolation-runner.ts": DOCS / "host/isolation-runner.ts",
        CANARY / "src/task/worktree.ts": DOCS / "host/worktree.ts",
        CANARY / "src/main.ts": DOCS / "host/main.ts",
        CANARY / "tests/host-patch/trace-safety.test.ts": DOCS / "tests/trace-safety.test.ts",
    }
    for source, target in snapshots.items():
        target.write_bytes(source.read_bytes())

    hash_entries = [
        CANARY / "src/async/job-manager.ts",
        CANARY / "src/session/agent-session.ts",
        CANARY / "src/task/isolation-runner.ts",
        CANARY / "src/task/cleanup-barrier.ts",
        CANARY / "src/task/worktree.ts",
        CANARY / "src/main.ts",
        WORKTREE / "brainstem/prime-extension/src/index.ts",
        WORKTREE / "brainstem/prime-extension/src/worker-lifecycle-bridge.ts",
    ]
    (DOCS / "HASHES.txt").write_text(
        "\n".join(f"{sha(path)} {path}" for path in hash_entries) + "\n", encoding="utf-8"
    )

    identities = [
        # executable / runtime
        {"role": "executable-bun", "path": r"C:\Users\assas\.bun\bin\bun.exe"},
        {"role": "executable-cli-entry", "path": str(CANARY / "src/cli.ts")},
        {"role": "runtime-python", "path": str(PYTHON)},
        # configuration / package
        {"role": "configuration-canary-package", "path": str(CANARY / "package.json")},
        # host cleanup + observer/settlement types
        {"role": "host-job-manager", "path": str(CANARY / "src/async/job-manager.ts")},
        {"role": "host-agent-session", "path": str(CANARY / "src/session/agent-session.ts")},
        {"role": "host-isolation-runner", "path": str(CANARY / "src/task/isolation-runner.ts")},
        {"role": "host-cleanup-barrier", "path": str(CANARY / "src/task/cleanup-barrier.ts")},
        {"role": "host-worktree", "path": str(CANARY / "src/task/worktree.ts")},
        {"role": "host-main", "path": str(CANARY / "src/main.ts")},
        {
            "role": "observer-settlement-registry",
            "path": str(CANARY / "src/task/attempt-settlement.ts"),
        },
        {
            "role": "observer-settlement-subagent",
            "path": str(CANARY / "src/task/structured-subagent.ts"),
        },
        {
            "role": "observer-settlement-runner",
            "path": str(CANARY / "src/extensibility/extensions/runner.ts"),
        },
        {
            "role": "observer-settlement-types",
            "path": str(CANARY / "src/extensibility/extensions/types.ts"),
        },
        # adapter
        {"role": "adapter-index", "path": str(WORKTREE / "brainstem/prime-extension/src/index.ts")},
        {
            "role": "adapter-bridge",
            "path": str(WORKTREE / "brainstem/prime-extension/src/worker-lifecycle-bridge.ts"),
        },
        {
            "role": "adapter-types",
            "path": str(WORKTREE / "brainstem/prime-extension/types/prime.d.ts"),
        },
        # Brain code
        {
            "role": "brain-worker-protocol",
            "path": str(WORKTREE / "src/second_brain/worker_protocol.py"),
        },
        {
            "role": "brain-worker-recovery",
            "path": str(WORKTREE / "src/second_brain/worker_recovery.py"),
        },
        {"role": "brain-db", "path": str(WORKTREE / "src/second_brain/db.py")},
        {"role": "brain-cli", "path": str(WORKTREE / "src/second_brain/cli.py")},
        # launcher / watcher
        {"role": "launcher", "path": str(WORKTREE / "scripts/omp-canary/launch_run.py")},
        {"role": "watcher", "path": str(WORKTREE / "scripts/omp-canary/db_watch.py")},
        {"role": "preflight", "path": str(WORKTREE / "scripts/omp-canary/preflight_run.py")},
        {
            "role": "post-exit-check",
            "path": str(WORKTREE / "scripts/omp-canary/post_exit_check.py"),
        },
    ]
    user_config = Path(r"C:\Users\assas\.omp\agent\config.yml")
    profile_dir = Path(r"C:\Users\assas\.omp\profiles\canary-settlement")
    profile_agent_dir = profile_dir / "agent"
    if user_config.exists():
        identities.append({"role": "configuration-default-profile-user", "path": str(user_config)})
    inventory = {
        "schema": "second-brain.omp-run-identities.v1",
        "generated_at": "2026-09-19",
        "note": (
            "Required identity inventory for the evidence-complete qualification rerun. "
            "The launcher validates every entry and every required role at the last "
            "setup boundary before spawn; the executed bun/CLI/extension/launcher/"
            "watcher/python paths must resolve to the bound files, and schema, "
            "preflight and fixture identities are validated from the run spec. The "
            "configuration_contract binds the intended profile, its resolved agent "
            "directory and main-config files (enforced absent until deliberately "
            "bound), the default-profile user config by hash, and forbids every "
            "documented configuration-root/profile override (PI_CONFIG_DIR, "
            "PI_CONFIG_FILES, PI_CODING_AGENT_DIR, PI_PACKAGE_DIR, OMP_PROFILE, "
            "PI_PROFILE, --config, project-local settings). Regenerate after any "
            "change to a bound file (scripts/omp-canary/refresh_identities.py); the "
            "campaign test suite validates this inventory against the live files."
        ),
        "required_roles": [entry["role"] for entry in identities],
        "configuration_contract": {
            "profile": "canary-settlement",
            "home_dir": str(Path.home()),
            "config_dir_name": ".omp",
            "profile_dir": str(profile_dir),
            "profile_agent_dir": str(profile_agent_dir),
            "profile_config_files": [
                {"name": "config.yml", "expects": "absent"},
                {"name": "config.yaml", "expects": "absent"},
                {"name": "settings.json", "expects": "absent"},
                {"name": ".env", "expects": "absent"},
            ],
            "env_files_must_be_absent": [
                str(Path.home() / ".env"),
                str(Path.home() / ".omp" / ".env"),
            ],
            "default_profile_user_config": str(user_config) if user_config.exists() else None,
            "forbidden_env": [
                "PI_CONFIG_DIR",
                "PI_CONFIG_FILES",
                "PI_CODING_AGENT_DIR",
                "PI_PACKAGE_DIR",
                "OMP_PROFILE",
                "PI_PROFILE",
            ],
            "forbidden_argv_flags": ["--config"],
            "forbidden_project_overlays": [
                ".omp/config.yml",
                ".omp/settings.json",
                ".claude/settings.yml",
                ".claude/settings.json",
                ".env",
                ".env.local",
                ".env.development",
                ".env.production",
                ".env.test",
            ],
        },
        "identities": [
            {"role": entry["role"], "path": entry["path"], "sha256": sha(Path(entry["path"]))}
            for entry in identities
        ],
    }
    (DOCS / "RUN-IDENTITIES.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "hashes": len(hash_entries),
                "identities": len(inventory["identities"]),
                "required_roles": len(inventory["required_roles"]),
                "docs": str(DOCS),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
