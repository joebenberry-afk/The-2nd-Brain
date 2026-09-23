"""Tests for the Observation Firewall and deterministic reducers (Plan §5)."""

import json
import subprocess
import sys

import pytest

from conftest import clean_python_env
from second_brain import artifacts, firewall
from second_brain.errors import BrainError


class TestIndividualReducers:
    """Unit tests for individual deterministic reducer functions (§5.1)."""

    def test_reduce_pytest_success(self):
        output = (
            "============================= test session starts =============================\n"
            "collecting ... collected 42 items\n\n"
            "tests/test_mod.py ..........................................             [100%]\n\n"
            "============================== 42 passed in 1.23s ==============================\n"
        )
        summary, _sections, errors, warnings = firewall.reduce_pytest(output)
        assert "42 passed" in summary
        assert "0 failed" in summary
        assert errors == 0
        assert warnings == 0

    def test_reduce_pytest_failure_preserves_test_and_location(self):
        output = (
            "============================= test session starts =============================\n"
            "tests/test_mod.py ..F...\n\n"
            "================================== FAILURES ===================================\n"
            "_________________________________ test_feature _________________________________\n"
            "tests/test_mod.py:42: in test_feature\n"
            "    assert result == 100\n"
            "E   AssertionError: assert 99 == 100\n"
            "=========================== short test summary info ===========================\n"
            "FAILED tests/test_mod.py::test_feature - AssertionError: assert 99 == 100\n"
            "========================= 1 failed, 5 passed in 0.50s =========================\n"
        )
        summary, sections, errors, _warnings = firewall.reduce_pytest(output)
        assert "1 failed" in summary
        assert "5 passed" in summary
        assert errors == 1
        # Safety invariant: failing test identity and location must be preserved
        assert any("FAILED tests/test_mod.py::test_feature" in s for s in sections)

    def test_reduce_compiler_pyright(self):
        output = (
            "c:\\repo\\src\\mod.py\n"
            "  c:\\repo\\src\\mod.py:10:15 - error: Type 'int' cannot be assigned to type 'str'\n"
            "  c:\\repo\\src\\mod.py:25:5 - warning: Unused variable 'unused_var'\n"
            "1 error, 1 warning, 0 informations\n"
        )
        summary, sections, errors, warnings = firewall.reduce_compiler(output)
        assert summary == "compiler/typecheck: 1 errors, 1 warnings"
        assert errors == 1
        assert warnings == 1
        assert any("error: Type 'int'" in s for s in sections)
        assert any("warning: Unused variable" in s for s in sections)

    def test_reduce_git_diff(self):
        output = (
            "diff --git a/src/mod.py b/src/mod.py\n"
            "index 1234567..89abcdef 100644\n"
            "--- a/src/mod.py\n"
            "+++ b/src/mod.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+new_line = True\n"
            " 1 file changed, 1 insertion(+)\n"
        )
        summary, sections, _errors, _warnings = firewall.reduce_git(output)
        assert "git diff:" in summary
        assert any("diff --git a/src/mod.py" in s for s in sections)

    def test_reduce_git_status(self):
        output = (
            "On branch brain/v1-token-efficient\n"
            "Changes not staged for commit:\n"
            "\tmodified:   src/mod.py\n"
            "\tmodified:   tests/test_mod.py\n"
            "Untracked files:\n"
            "\tconfig/new.toml\n"
        )
        summary, sections, _errors, _warnings = firewall.reduce_git(output)
        assert "git status:" in summary
        assert any("modified:   src/mod.py" in s for s in sections)

    def test_reduce_search_ripgrep(self):
        output = (
            "src/second_brain/governor.py:25:class SessionTokens:\n"
            "src/second_brain/governor.py:80:def parse_telemetry_session(path):\n"
            "tests/test_governor.py:12:from second_brain import governor\n"
        )
        summary, sections, _errors, _warnings = firewall.reduce_search(output)
        assert "search: 3 matches across 2 files" in summary
        assert len(sections) == 3

    def test_reduce_json_object(self):
        data = {
            "session_id": "sess-123",
            "items": list(range(500)),
            "config": {"nested": True, "values": [1, 2, 3]},
        }
        text = json.dumps(data)
        summary, sections, _errors, _warnings = firewall.reduce_json(text)
        assert "json: object with 3 top-level keys" in summary
        assert any("items: len=500" in s for s in sections)

    def test_reduce_process_logs_python_traceback(self):
        output = (
            "2026-08-18 20:00:00 [INFO] Server started\n"
            "2026-08-18 20:00:05 [ERROR] Uncaught exception:\n"
            "Traceback (most recent call last):\n"
            '  File "app.py", line 15, in handle_request\n'
            "    process_data(data)\n"
            '  File "app.py", line 30, in process_data\n'
            "    raise ValueError('invalid payload')\n"
            "ValueError: invalid payload\n"
            "2026-08-18 20:00:06 [INFO] Worker shutting down\n"
        )
        summary, sections, errors, _warnings = firewall.reduce_process_logs(output)
        assert "process log:" in summary
        assert errors >= 1
        # Invariant: Traceback with exact line and exception must be captured
        assert any("ValueError: invalid payload" in s for s in sections)

    def test_reduce_build_output_npm(self):
        output = (
            "npm ERR! code ENOENT\n"
            "npm ERR! syscall open\n"
            "npm ERR! path /repo/package.json\n"
            "npm ERR! errno -2\n"
            "npm ERR! enoent ENOENT: no such file or directory\n"
        )
        summary, sections, errors, _warnings = firewall.reduce_build_output(output)
        assert "build output:" in summary
        assert errors >= 1
        assert any("npm ERR!" in s for s in sections)

    def test_reduce_doctor(self):
        output = (
            "second_brain doctor\n"
            "  [PASS] layout roots\n"
            "  [PASS] database\n"
            "  [WARN] python env: UV_INTERNAL set\n"
            "  [FAIL] tool:rg not found\n"
        )
        summary, sections, errors, warnings = firewall.reduce_doctor(output)
        assert "doctor:" in summary
        assert errors == 1
        assert warnings == 1
        assert any("[FAIL] tool:rg not found" in s for s in sections)


class TestKindAutoDetection:
    """Tests for kind auto-detection from commands and text heuristics."""

    def test_detect_from_command(self):
        assert firewall.detect_kind("", command="pytest tests/") == "pytest"
        assert firewall.detect_kind("", command="pyright src/") == "compiler"
        assert firewall.detect_kind("", command="git diff HEAD~1") == "git"
        assert firewall.detect_kind("", command="rg -i pattern") == "search"
        assert firewall.detect_kind("", command="npm install") == "build"
        assert firewall.detect_kind("", command="second_brain doctor") == "doctor"

    def test_detect_from_heuristics(self):
        assert firewall.detect_kind('{"key": "value"}') == "json"
        assert firewall.detect_kind("Traceback (most recent call last):\n  File 'a.py'") == "logs"
        assert firewall.detect_kind("12 passed, 2 failed in 0.5s") == "pytest"
        assert firewall.detect_kind("diff --git a/f b/f") == "git"


class TestObservationFirewallEndToEnd:
    """End-to-end integration tests with content-addressed backing store (§5.2)."""

    def test_reduce_and_expand_roundtrip(self, brain_home):
        large_test_output = (
            "pytest output\n"
            + ("tests/test_big.py ..................................\n" * 100)
            + "============================== 3400 passed in 5.20s ==============================\n"
        )

        res = firewall.reduce_observation(
            large_test_output,
            command="pytest",
            home=brain_home,
            session="sess-fw-1",
        )

        assert isinstance(res, firewall.ReducerResult)
        assert "3400 passed" in res.summary
        assert res.reduction_ratio > 0.5  # Significant token reduction
        assert res.lossless_retrieval_handle.startswith("[brain-artifact:sha256:")

        # Verify raw backing store saved exact content
        expanded = firewall.expand_observation(brain_home, res.raw_object_ref)
        assert expanded == large_test_output

        # Verify expansion via handle string
        expanded_handle = firewall.expand_observation(brain_home, res.lossless_retrieval_handle)
        assert expanded_handle == large_test_output

    def test_safety_invariants_never_drops_failures(self, brain_home):
        """Invariant §5.5: failure message and location must always be retained."""
        failing_output = (
            "random log filler\n" * 50
            + "FAILED tests/core/test_crypto.py::test_key_derivation\n"
            + "E   KeyError: 'secret_key' not found in vault\n"
            + "random log filler\n" * 50
            + "1 failed, 99 passed in 2.0s\n"
        )
        res = firewall.reduce_observation(failing_output, command="pytest", home=brain_home)
        assert "1 failed" in res.summary
        assert "FAILED tests/core/test_crypto.py::test_key_derivation" in res.distilled_text

    def test_fail_open_on_corrupt_data(self, brain_home):
        """Fail-open behavior: reducer returns usable fallback on any error."""
        res = firewall.reduce_observation("unparseable text", kind="unknown_kind", home=brain_home)
        assert res.summary.startswith("generic output:") or "generic" in res.distilled_text


class TestFirewallCLI:
    """CLI tests for brainctl firewall subcommands."""

    def test_firewall_kinds_json(self, brain_home):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "firewall",
                "kinds",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env=clean_python_env(),
        )
        assert result.returncode == 0
        kinds = json.loads(result.stdout)
        assert "pytest" in kinds
        assert "compiler" in kinds
        assert "git" in kinds
        assert "search" in kinds
        assert "json" in kinds
        assert "logs" in kinds
        assert "build" in kinds
        assert "doctor" in kinds

    def test_firewall_reduce_json(self, brain_home, tmp_path):
        sample_file = tmp_path / "test_out.txt"
        sample_file.write_text("=== 10 passed, 0 failed in 0.1s ===", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "firewall",
                "reduce",
                str(sample_file),
                "--kind",
                "pytest",
                "--json",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env=clean_python_env(),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "10 passed" in data["summary"]
        assert "lossless_retrieval_handle" in data
        assert "raw_object_ref" in data

    def test_firewall_expand_cli(self, brain_home):
        raw_text = "secret raw test observation output line 1\nline 2\n"
        res = firewall.reduce_observation(raw_text, kind="generic", home=brain_home)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "firewall",
                "expand",
                res.raw_object_ref,
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env=clean_python_env(),
        )
        assert result.returncode == 0
        assert result.stdout == raw_text


@pytest.mark.parametrize("from_stdin", [False, True])
def test_firewall_cli_preserves_original_bytes(brain_home, tmp_path, from_stdin):
    original = b"first\r\ncaf\xc3\xa9\rthird\n"
    args = ["reduce", "--kind", "generic", "--json"]
    if not from_stdin:
        source = tmp_path / "output.txt"
        source.write_bytes(original)
        args.append(str(source))
    env = clean_python_env()
    reduced = subprocess.run(
        [sys.executable, "-m", "second_brain", "firewall", *args, "--home", str(brain_home)],
        input=original if from_stdin else None,
        capture_output=True,
        env=env,
        check=True,
    )
    ref = json.loads(reduced.stdout)["raw_object_ref"]
    assert artifacts.expand(brain_home, ref) == original
    expanded = subprocess.run(
        [
            sys.executable,
            "-m",
            "second_brain",
            "firewall",
            "expand",
            ref,
            "--home",
            str(brain_home),
        ],
        capture_output=True,
        env=env,
        check=True,
    )
    assert expanded.stdout == original


def test_firewall_text_expansion_rejects_invalid_utf8(brain_home):
    stored = artifacts.store_bytes(brain_home, b"invalid \xff text", kind="raw")
    with pytest.raises(BrainError):
        firewall.expand_observation(brain_home, stored["hash"])
