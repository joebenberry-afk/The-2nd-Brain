import subprocess

from second_brain import __version__, build_identity


def _commit(repo, message: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-qm", message],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_describe_reports_package_version_and_schema(brain_home) -> None:
    identity = build_identity.describe(brain_home)

    assert identity["package_version"] == __version__
    assert identity["db_schema_version"] == 21
    assert identity["qualification_baseline_sha"] == build_identity.QUALIFICATION_BASELINE_SHA


def test_describe_reports_none_git_sha_without_commits(brain_home) -> None:
    identity = build_identity.describe(brain_home)

    assert identity["git_sha"] is None
    assert identity["adapter_build_fingerprint"] is None
    assert identity["qualification_baseline_current"] is False


def test_describe_reports_git_sha_and_dirty_state(brain_home) -> None:
    subprocess.run(["git", "add", "-A"], cwd=brain_home, check=True, capture_output=True)
    _commit(brain_home, "initial")

    clean = build_identity.describe(brain_home)
    assert clean["git_sha"]
    assert clean["dirty"] is False

    (brain_home / "VERSION").write_text("changed\n", encoding="utf-8")
    dirty = build_identity.describe(brain_home)
    assert dirty["git_sha"] == clean["git_sha"]
    assert dirty["dirty"] is True


def test_adapter_fingerprint_changes_when_extension_source_changes(brain_home) -> None:
    ext_src = brain_home / "brainstem" / "prime-extension" / "src"
    ext_src.mkdir(parents=True)
    (ext_src / "index.ts").write_text("export default function () {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=brain_home, check=True, capture_output=True)
    _commit(brain_home, "seed extension")

    before = build_identity.describe(brain_home)["adapter_build_fingerprint"]
    assert before is not None

    (ext_src / "index.ts").write_text(
        "export default function () { /* changed */ }\n", encoding="utf-8"
    )
    after = build_identity.describe(brain_home)["adapter_build_fingerprint"]

    assert after != before
