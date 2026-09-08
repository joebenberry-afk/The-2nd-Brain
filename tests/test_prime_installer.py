from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-prime-extension.ps1"
UNINSTALLER = ROOT / "scripts" / "uninstall-prime-extension.ps1"


def run_script(
    script: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_installer_uses_source_root_and_rollback_is_byte_exact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "brainstem/prime-extension/src").mkdir(parents=True)
    (source / "brainstem/prime-extension/types").mkdir(parents=True)
    (source / "brainstem/prime-extension/src/index.ts").write_bytes(b"new source\n")
    (source / "brainstem/prime-extension/types/prime.d.ts").write_bytes(b"new types\n")
    extensions = tmp_path / "extensions"
    target = extensions / "second-brain"
    target.mkdir(parents=True)
    (target / "index.ts").write_bytes(b"old installed bytes\r\n")
    env = {**os.environ, "SECOND_BRAIN_HOME": str(tmp_path / "legacy-state")}

    installed = run_script(
        INSTALLER,
        "-SourceRoot",
        str(source),
        "-ExtensionsDir",
        str(extensions),
        env=env,
    )

    assert installed.returncode == 0, installed.stderr
    assert (target / "index.ts").read_bytes() == b"new source\n"
    assert "Source repository:" in installed.stdout
    assert "Manifest SHA-256:" in installed.stdout
    backups = list((source / "backups").glob("*-prime-extension-pre-install"))
    assert len(backups) == 1

    restored = run_script(
        UNINSTALLER,
        "-SourceRoot",
        str(source),
        "-ExtensionsDir",
        str(extensions),
        "-BackupDir",
        str(backups[0]),
        env=env,
    )

    assert restored.returncode == 0, restored.stderr
    assert (target / "index.ts").read_bytes() == b"old installed bytes\r\n"


def test_missing_source_does_not_delete_installed_extension(tmp_path: Path) -> None:
    extensions = tmp_path / "extensions"
    target = extensions / "second-brain"
    target.mkdir(parents=True)
    installed = target / "index.ts"
    installed.write_bytes(b"keep me")

    result = run_script(
        INSTALLER,
        "-SourceRoot",
        str(tmp_path / "missing"),
        "-ExtensionsDir",
        str(extensions),
    )

    assert result.returncode != 0
    assert installed.read_bytes() == b"keep me"
