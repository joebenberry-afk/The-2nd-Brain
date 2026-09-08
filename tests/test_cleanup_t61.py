"""Tests for T6.1 Dead Code and State Cleanup.

Verifies:
1. ResidencyState contains only RESIDENT, EVICTED, FAULTED_IN (STORED, SUPERSEDED, PURGED removed).
2. contracts.ToolOutcomeState and contracts.UPGRADERS / ledger.UPGRADERS are removed.
3. read_ledger_header and LedgerStore._check_version raise BrainError on schema version mismatch.
4. Tool-set commands are removed while native tool-surface telemetry is retained.
5. Obsolete configuration is absent from both canonical config and seeded homes.
6. action_cache enforces max_entries with LRU eviction in store_action / put.
"""

from __future__ import annotations

import importlib
import sqlite3
import time
import tomllib
from pathlib import Path

import pytest

from second_brain import contracts, ledger, telemetry
from second_brain.action_cache import (
    ActionCache,
    ActionCacheStore,
    ActionProof,
    ActionType,
    DependencyClass,
)
from second_brain.contracts import LEDGER_SCHEMA_VERSION, LedgerHeader, read_ledger_header
from second_brain.errors import BrainError
from second_brain.ledger import LedgerStore
from second_brain.vmem import ResidencyState


def test_residency_state_members() -> None:
    """ResidencyState must contain only RESIDENT, EVICTED, and FAULTED_IN."""
    expected_members = {"RESIDENT", "EVICTED", "FAULTED_IN"}
    actual_members = {m.name for m in ResidencyState}
    assert actual_members == expected_members
    assert len(ResidencyState) == 3
    for dead_state in ("STORED", "SUPERSEDED", "PURGED"):
        assert not hasattr(ResidencyState, dead_state)


def test_contracts_tool_outcome_state_and_upgraders_removed() -> None:
    """ToolOutcomeState and UPGRADERS must be removed from contracts."""
    assert not hasattr(contracts, "ToolOutcomeState")
    assert not hasattr(contracts, "UPGRADERS")
    assert not hasattr(ledger, "UPGRADERS")


def test_contracts_read_ledger_header_version_check() -> None:
    """read_ledger_header must raise BrainError on version mismatch."""
    base_header = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "brain_version": "0.1.0",
        "adapter_name": "prime",
        "adapter_version": "0.1.0",
        "created_at": "2026-09-03T00:00:00Z",
    }
    # Current version succeeds
    header = read_ledger_header(base_header)
    assert isinstance(header, LedgerHeader)
    assert header.schema_version == LEDGER_SCHEMA_VERSION

    # Older version raises explicit unsupported message
    with pytest.raises(BrainError, match=r"unsupported ledger schema version 0 \(expected 1\)"):
        read_ledger_header({**base_header, "schema_version": 0})

    # Newer version raises explicit unsupported message
    with pytest.raises(BrainError, match=r"unsupported ledger schema version 2 \(expected 1\)"):
        read_ledger_header({**base_header, "schema_version": 2})

    # Non-integer version raises
    with pytest.raises(BrainError, match="ledger header missing integer schema_version"):
        read_ledger_header({**base_header, "schema_version": "1"})


def test_ledger_store_check_version_mismatch(tmp_path: Path) -> None:
    """LedgerStore._check_version must raise BrainError on version mismatch."""
    host = "test-host"
    with LedgerStore(tmp_path, host, host="test").open(create=True):
        pass

    internal = ledger.internal_session_id(host)
    dbfile = tmp_path / "state" / "sessions" / internal / "ledger.sqlite"

    # Mutate to version 0
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(BrainError, match="unsupported"):
        LedgerStore(tmp_path, host).open()

    # Mutate to version 2
    conn = sqlite3.connect(dbfile)
    conn.execute("UPDATE ledger_meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(BrainError, match="unsupported"):
        LedgerStore(tmp_path, host).open()


def test_tool_working_set_deleted() -> None:
    """src/second_brain/tool_working_set.py must be deleted."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("second_brain.tool_working_set")

    # prime_tool_surface telemetry event kind must remain untouched
    assert "prime_tool_surface" in telemetry.KNOWN_KINDS


def test_cli_tool_set_removed() -> None:
    """CLI tool-set command must be removed."""
    from second_brain import cli

    parser = cli._parser()
    with pytest.raises(SystemExit):
        # argparse exits on unrecognized argument
        parser.parse_args(["tool-set", "list"])


def test_config_cleanups() -> None:
    """Verify dead sections and keys removed from config files."""
    worktree = Path(__file__).resolve().parent.parent

    # 1. context.toml: no [governor] bands section
    ctx_data = tomllib.loads((worktree / "config" / "context.toml").read_text(encoding="utf-8"))
    assert "governor" not in ctx_data

    # 2. retrieval.toml: no [lateral_inhibition] or [decay] sections
    ret_data = tomllib.loads((worktree / "config" / "retrieval.toml").read_text(encoding="utf-8"))
    assert "lateral_inhibition" not in ret_data
    assert "decay" not in ret_data

    # 3. governor.toml: tool_working_set removed from [features]
    gov_data = tomllib.loads((worktree / "config" / "governor.toml").read_text(encoding="utf-8"))
    assert "tool_working_set" not in gov_data.get("features", {})

    # 4. seed template copies (src/second_brain/defaults/config/) must be
    #    cleaned identically — cli.py's init/_seed_defaults copies these into
    #    every new Brain home, so dead sections here silently regress even
    #    when the repo-root dev copies above stay clean.
    defaults_dir = worktree / "src" / "second_brain" / "defaults" / "config"
    seed_ctx_data = tomllib.loads((defaults_dir / "context.toml").read_text(encoding="utf-8"))
    assert "governor" not in seed_ctx_data

    seed_ret_data = tomllib.loads((defaults_dir / "retrieval.toml").read_text(encoding="utf-8"))
    assert "lateral_inhibition" not in seed_ret_data
    assert "decay" not in seed_ret_data


def test_action_cache_lru_eviction(tmp_path: Path) -> None:
    """ActionCacheStore must enforce max_entries with LRU eviction."""
    cache = ActionCacheStore(tmp_path, max_entries=3)
    assert cache.max_entries == 3
    assert ActionCache is ActionCacheStore

    proof = ActionProof(
        dependency_class=DependencyClass.PURE_CONSTANT,
        constant_fingerprint={"test": "lru"},
    )

    # Insert 3 entries
    e1 = cache.put(
        action_type=ActionType.GENERIC_PURE,
        target="file1.py",
        content="content 1",
        proof=proof,
        params={"p": 1},
    )
    # Ensure distinct last_accessed_at timestamps if sub-millisecond
    time.sleep(0.01)
    e2 = cache.put(
        action_type=ActionType.GENERIC_PURE,
        target="file2.py",
        content="content 2",
        proof=proof,
        params={"p": 2},
    )
    time.sleep(0.01)
    e3 = cache.put(
        action_type=ActionType.GENERIC_PURE,
        target="file3.py",
        content="content 3",
        proof=proof,
        params={"p": 3},
    )
    assert e1 is not None and e2 is not None and e3 is not None

    stats = cache.get_stats()
    assert stats["total_entries"] == 3

    # Access e1 so e2 becomes the oldest entry
    time.sleep(0.01)
    hit1 = cache.query(e1.action_key)
    assert hit1.hit is True

    # Insert 4th entry -> cache max is 3, so e2 should be evicted
    time.sleep(0.01)
    e4 = cache.put(
        action_type=ActionType.GENERIC_PURE,
        target="file4.py",
        content="content 4",
        proof=proof,
        params={"p": 4},
    )
    assert e4 is not None

    stats = cache.get_stats()
    assert stats["total_entries"] == 3

    # e1, e3, e4 should exist; e2 must be evicted
    assert cache.query(e1.action_key).hit is True
    assert cache.query(e2.action_key).hit is False
    assert cache.query(e3.action_key).hit is True
    assert cache.query(e4.action_key).hit is True


def test_action_cache_lru_method_override(tmp_path: Path) -> None:
    """ActionCacheStore.store_action must respect per-call max_entries override."""
    cache = ActionCache(tmp_path, max_entries=10)
    proof = ActionProof(
        dependency_class=DependencyClass.PURE_CONSTANT,
        constant_fingerprint={"test": "method-override"},
    )

    for i in range(5):
        time.sleep(0.005)
        cache.store_action(
            action_type=ActionType.GENERIC_PURE,
            target=f"file{i}.py",
            content=f"content {i}",
            proof=proof,
            params={"idx": i},
            max_entries=2,  # per-call override
        )

    stats = cache.get_stats()
    assert stats["total_entries"] == 2
