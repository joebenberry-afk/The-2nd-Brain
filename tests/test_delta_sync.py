"""Tests for Delta Sync & Compact Invalidation (Plan §8)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain.delta_sync import (
    DeltaSyncEngine,
    DeltaType,
    apply_delta,
    compute_canonical_hash,
    compute_memory_delta,
)
from second_brain.errors import BrainError


class TestDeltaComputation:
    """Tests for computing structured deltas between base and target memories (§8.2, §8.3)."""

    def test_compute_delta_add_new_memory(self):
        target = {
            "memory_id": "mem-101",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Use SQLite WAL",
            "observation": "WAL mode enables concurrent reads without lock errors",
            "guidance": "Always PRAGMA journal_mode=WAL on connection open",
            "evidence": "tests/test_ledger.py",
        }
        delta = compute_memory_delta(None, target)
        assert delta.delta_type == DeltaType.ADD
        assert delta.base_version == 0
        assert delta.target_version == 1
        assert delta.target_memory_id == "mem-101"
        assert delta.target_canonical_hash == compute_canonical_hash(target)

    def test_compute_delta_unchanged_zero_tokens(self):
        item = {
            "memory_id": "mem-102",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Unchanged Memory",
            "observation": "Obs text",
            "guidance": "Guidance text",
            "evidence": "Evidence text",
        }
        delta = compute_memory_delta(item, item)
        assert delta.delta_type == DeltaType.UNCHANGED
        assert delta.token_size_estimate == 0
        assert delta.patch_payload == {}

    def test_compute_delta_modify_small_token_overhead(self):
        """Phase 5 Gate: updating existing memory produces delta <= 20% of full token size."""
        base = {
            "memory_id": "mem-103",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Large Memory Item Title with Extensive Explanations",
            "observation": (
                "Detailed multi-paragraph observation about system architecture: "
                + "the database schema enforces foreign keys, busy timeout handles, "
                + "and WAL journal modes for reliable lock-free concurrency in Python."
            ),
            "guidance": "Initial guidance that needs updating.",
            "evidence": "Evidence path with commit refs and telemetry benchmarks.",
        }

        target = dict(base)
        target["version"] = 2
        target["guidance"] = "Updated guidance text with specific advice."

        delta = compute_memory_delta(base, target)
        assert delta.delta_type == DeltaType.MODIFY
        assert delta.base_version == 1
        assert delta.target_version == 2
        assert "guidance" in delta.patch_payload
        assert "observation" not in delta.patch_payload  # Untouched large field omitted!

        full_token_size = len(json.dumps(target)) // 4
        delta_token_size = delta.token_size_estimate

        # Invariant: delta size <= 20% of full token size
        assert delta_token_size <= full_token_size * 0.20

    def test_compute_delta_tombstone(self):
        base = {
            "memory_id": "mem-104",
            "version": 1,
            "status": "current",
            "title": "Deprecate Me",
        }
        delta = compute_memory_delta(base, None)
        assert delta.delta_type == DeltaType.TOMBSTONE
        assert delta.target_memory_id == "mem-104"


class TestDeltaApplication:
    """Tests for applying deltas and verifying resulting hashes (§8.5)."""

    def test_apply_modify_delta_success(self):
        base = {
            "memory_id": "mem-105",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Base Title",
            "observation": "Base obs",
            "guidance": "Old guidance",
            "evidence": "ev",
        }
        target = dict(base)
        target["version"] = 2
        target["guidance"] = "New guidance"

        delta = compute_memory_delta(base, target)
        updated = apply_delta(base, delta, verify_hash=True)

        assert updated["version"] == 2
        assert updated["guidance"] == "New guidance"
        assert updated["observation"] == "Base obs"
        assert compute_canonical_hash(updated) == delta.target_canonical_hash

    def test_apply_delta_hash_mismatch_raises_brain_error(self):
        base = {
            "memory_id": "mem-106",
            "version": 1,
            "status": "current",
            "title": "Base",
            "guidance": "g1",
        }
        target = dict(base)
        target["guidance"] = "g2"
        delta = compute_memory_delta(base, target)

        # Corrupt target hash
        delta.target_canonical_hash = "corrupted_fake_hash_123"

        with pytest.raises(BrainError, match="Delta hash mismatch"):
            apply_delta(base, delta, verify_hash=True)


class TestDeltaSyncEngine:
    """Tests for multi-turn session recipient delta sync (§8.4)."""

    def test_engine_eliminates_redundant_resends(self):
        engine = DeltaSyncEngine()
        mem1 = {
            "memory_id": "mem-201",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Kernel Memory",
            "observation": "Obs",
            "guidance": "Guidance",
            "evidence": "Ev",
        }

        # Turn 1: Initial delivery -> ADD
        deltas_t1, rendered_t1 = engine.sync_memories("sess-1", [mem1], recipient="driver")
        assert len(deltas_t1) == 1
        assert deltas_t1[0].delta_type == DeltaType.ADD
        assert "[ADD] mem-201" in rendered_t1

        # Turn 2: Same memory -> UNCHANGED (rendered text is empty, 0 tokens emitted!)
        deltas_t2, rendered_t2 = engine.sync_memories("sess-1", [mem1], recipient="driver")
        assert len(deltas_t2) == 1
        assert deltas_t2[0].delta_type == DeltaType.UNCHANGED
        assert rendered_t2 == ""

        # Turn 3: Update guidance -> MODIFY
        mem1_v2 = dict(mem1)
        mem1_v2["version"] = 2
        mem1_v2["guidance"] = "Updated advice"
        deltas_t3, rendered_t3 = engine.sync_memories("sess-1", [mem1_v2], recipient="driver")
        assert len(deltas_t3) == 1
        assert deltas_t3[0].delta_type == DeltaType.MODIFY
        assert "[MODIFY] mem-201 (v1 -> v2)" in rendered_t3

    def test_delta_sync_state_survives_process(self, tmp_path):
        home = tmp_path / "brain"
        first = DeltaSyncEngine(home=home, session_id="sess-persist")
        item = {
            "memory_id": "mem-persist",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Persisted",
            "observation": "Obs",
            "guidance": "Guidance",
            "evidence": "Ev",
        }
        first.sync_memories("sess-persist", [item])
        second = DeltaSyncEngine(home=home, session_id="sess-persist")
        deltas, rendered = second.sync_memories("sess-persist", [item])
        assert deltas[0].delta_type == DeltaType.UNCHANGED
        assert rendered == ""
        assert (home / "state" / "sessions" / "sess-persist" / "delta-sync.json").is_file()

    def test_engine_without_constructor_session_persists_per_sync_session(self, tmp_path):
        home = tmp_path / "brain"
        item = {
            "memory_id": "mem-persist-default",
            "version": 1,
            "status": "current",
            "title": "Persisted",
        }
        first = DeltaSyncEngine(home=home)
        first.sync_memories("sess-default", [item])
        second = DeltaSyncEngine(home=home)
        deltas, rendered = second.sync_memories("sess-default", [item])
        assert deltas[0].delta_type == DeltaType.UNCHANGED
        assert rendered == ""

    def test_delta_sync_rejects_dot_session_without_escape(self, tmp_path):
        home = tmp_path / "brain"
        with pytest.raises(BrainError, match="Invalid session id"):
            DeltaSyncEngine(home=home).sync_memories(
                "..",
                [{"memory_id": "m", "version": 1, "status": "current", "title": "x"}],
            )
        assert not (home.parent / "state" / "sessions" / "delta-sync.json").exists()

    def test_malformed_delta_sync_state_fails_open_without_overwrite(self, tmp_path):
        home = tmp_path / "brain"
        state = home / "state" / "sessions" / "sess-malformed" / "delta-sync.json"
        state.parent.mkdir(parents=True)
        state.write_text("{not-json", encoding="utf-8")
        engine = DeltaSyncEngine(home=home, session_id="sess-malformed")
        assert engine._delivered == {}
        engine.sync_memories(
            "sess-malformed",
            [{"memory_id": "m", "version": 1, "status": "current", "title": "x"}],
        )
        assert state.read_text(encoding="utf-8") == "{not-json"


class TestDeltaSyncCLI:
    """CLI tests for brainctl delta-sync subcommands."""

    def test_cli_diff_and_apply(self, tmp_path):
        base_file = tmp_path / "base.json"
        target_file = tmp_path / "target.json"
        delta_file = tmp_path / "delta.json"

        base_mem = {
            "memory_id": "mem-cli-1",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "CLI Test",
            "observation": "Obs",
            "guidance": "Old advice",
            "evidence": "Ev",
        }
        target_mem = dict(base_mem)
        target_mem["version"] = 2
        target_mem["guidance"] = "New advice"

        base_file.write_text(json.dumps(base_mem), encoding="utf-8")
        target_file.write_text(json.dumps(target_mem), encoding="utf-8")

        # 1. Diff
        diff_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "delta-sync",
                "diff",
                str(base_file),
                str(target_file),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert diff_res.returncode == 0
        delta_data = json.loads(diff_res.stdout)
        assert delta_data["delta_type"] == "MODIFY"
        delta_file.write_text(diff_res.stdout, encoding="utf-8")

        # 2. Apply
        apply_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "delta-sync",
                "apply",
                str(base_file),
                str(delta_file),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert apply_res.returncode == 0
        updated_data = json.loads(apply_res.stdout)
        assert updated_data["version"] == 2
        assert updated_data["guidance"] == "New advice"

    def test_cli_sync_uses_custom_home_calibration(self, tmp_path):
        calibration = tmp_path / "state" / "calibration"
        calibration.mkdir(parents=True)
        (calibration / "tokens.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "default",
                    "default_chars_per_token": 8.0,
                    "models": {},
                }
            ),
            encoding="utf-8",
        )
        target = {
            "memory_id": "mem-sync-home",
            "version": 1,
            "status": "current",
            "confidence": "high",
            "title": "Custom home",
            "observation": "Observed",
            "guidance": "Guidance",
            "evidence": "Evidence",
        }
        target_file = tmp_path / "target.json"
        target_file.write_text(json.dumps([target]), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "--home",
                str(tmp_path),
                "delta-sync",
                "sync",
                "session-home",
                str(target_file),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": str(Path("src").resolve())},
        )
        data = json.loads(result.stdout)
        expected = compute_memory_delta(None, target, home=tmp_path)
        assert data[0]["token_size_estimate"] == expected.token_size_estimate
        second = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "--home",
                str(tmp_path),
                "delta-sync",
                "sync",
                "session-home",
                str(target_file),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": str(Path("src").resolve())},
        )
        assert second.returncode == 0
        assert json.loads(second.stdout)[0]["delta_type"] == "UNCHANGED"
