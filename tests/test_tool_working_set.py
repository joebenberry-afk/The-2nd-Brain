"""Tests for Dynamic Tool Working Set & Lazy Loading (Plan §10)."""

import json
import os
import subprocess
import sys

from second_brain.tool_working_set import (
    ToolWorkingSetManager,
    compress_tool_schema,
)


class TestToolWorkingSetLifecycle:
    """Tests for dynamic tool activation, pruning, and compression (§10.1 - §10.3)."""

    def test_initial_state_core_tools_only(self):
        mgr = ToolWorkingSetManager()
        active = mgr.get_active_tools(compress=True)
        active_names = [t["name"] for t in active]

        assert "view_file" in active_names
        assert "run_command" in active_names
        assert "replace_file_content" in active_names
        assert "write_to_file" in active_names
        assert "git_commit_and_sync" not in active_names
        assert "database_migrate_query" not in active_names

    def test_schema_compression_savings(self):
        verbose_schema = {
            "name": "super_verbose_tool_name",
            "description": (
                "This is an extraordinarily long, verbose, and repetitive description "
                "explaining every minor edge case of this tool for human readers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Very long parameter explanation with examples and history.",
                    },
                    "param2": {
                        "type": "integer",
                        "description": "Another long paragraph about integers and defaults.",
                    },
                },
                "required": ["param1"],
            },
        }

        compressed = compress_tool_schema(verbose_schema)
        raw_len = len(json.dumps(verbose_schema))
        comp_len = len(json.dumps(compressed))

        assert comp_len < raw_len * 0.60  # At least 40% reduction
        assert compressed["name"] == "super_verbose_tool_name"
        assert compressed["parameters"]["required"] == ["param1"]
        assert "param1" in compressed["parameters"]["properties"]

    def test_detect_and_activate_domain_tools(self):
        mgr = ToolWorkingSetManager()
        # Initial turn: domain tools inactive
        assert "git_commit_and_sync" not in [t["name"] for t in mgr.get_active_tools()]

        # Turn 1: Developer asks to commit and push
        activated = mgr.detect_and_activate("Please commit and push these changes to git", turn=1)
        assert "git_commit_and_sync" in activated
        assert "git_commit_and_sync" in [t["name"] for t in mgr.get_active_tools()]

    def test_idle_tool_pruning(self):
        mgr = ToolWorkingSetManager()
        # Activate git tool at turn 1
        mgr.activate_tool("git_commit_and_sync", turn=1)
        assert "git_commit_and_sync" in [t["name"] for t in mgr.get_active_tools()]

        # Turn 2: Still within 3 idle turns
        pruned_t2 = mgr.prune_idle_tools(current_turn=2, max_idle_turns=3)
        assert "git_commit_and_sync" not in pruned_t2
        assert "git_commit_and_sync" in [t["name"] for t in mgr.get_active_tools()]

        # Turn 5: 4 turns elapsed without usage -> pruned!
        pruned_t5 = mgr.prune_idle_tools(current_turn=5, max_idle_turns=3)
        assert "git_commit_and_sync" in pruned_t5
        assert "git_commit_and_sync" not in [t["name"] for t in mgr.get_active_tools()]

        # Core tools must never be pruned
        assert "view_file" in [t["name"] for t in mgr.get_active_tools()]


class TestPhase7GateBenchmark:
    """Phase 7 Gate: Prove initial turn tool definitions consume <=500 tokens."""

    def test_initial_toolset_token_budget_gate(self):
        mgr = ToolWorkingSetManager()
        token_estimate = mgr.estimate_active_tokens()

        # Gate Requirement: Initial turn tool definitions consume <= 500 tokens
        assert token_estimate <= 500
        # Eager toolset with all tools uncompressed would be > 1500 tokens
        all_uncompressed = json.dumps([t.to_dict() for t in mgr._tools.values()])
        eager_tokens = len(all_uncompressed) // 4
        assert token_estimate < eager_tokens * 0.40  # Massive >60% savings!


class TestToolSetCLI:
    """CLI tests for brainctl tool-set subcommands."""

    def test_cli_list_and_activate(self):
        # 1. List active tools
        res_list = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "tool-set",
                "list",
                "--active",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert res_list.returncode == 0
        data = json.loads(res_list.stdout)
        assert data["token_estimate"] <= 500
        assert len(data["active_tools"]) == 4

        # 2. Detect
        res_det = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "tool-set",
                "detect",
                "run sqlite database migration",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert res_det.returncode == 0
        det_data = json.loads(res_det.stdout)
        assert "database_migrate_query" in det_data["activated"]
