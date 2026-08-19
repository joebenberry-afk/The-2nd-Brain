"""
Live integration tests for Dynamic Tool Working Set & Lean Schemas (Plan §4 R7).

Tests:
1. Initial schema footprint ≤ 500 tokens with Core Resident Tier A tools.
2. Dynamic JIT activation of Tier B domain tools upon matching task intent.
3. Idle pruning deactivates domain tools after N turns of non-use.
4. Schema compression yields ≥40% token reduction vs uncompressed raw JSON schemas.
"""

from second_brain.tool_working_set import (
    ToolTier,
    ToolWorkingSetManager,
    compress_tool_schema,
)


class TestToolWorkingSetLiveIntegration:
    """Proves dynamic tool working set and lean schema compression (§4 R7)."""

    def test_initial_schema_footprint_under_500_tokens(self):
        mgr = ToolWorkingSetManager()
        active = mgr.get_active_tools(compress=True)

        # Only Tier A core resident tools active initially
        assert len(active) == 4

        # Estimate token footprint
        token_est = mgr.estimate_active_tokens()
        assert token_est <= 500  # ≤ 500 tokens requirement proven

    def test_dynamic_jit_activation_and_idle_pruning(self):
        mgr = ToolWorkingSetManager()

        # Register specialized git domain tool
        mgr.register_tool(
            name="git_branch_manager",
            description="Manage git branches and merges.",
            tier=ToolTier.LAZY_DOMAIN,
            domain="git",
            keywords=["git", "branch", "merge", "commit"],
            parameters={"type": "object", "properties": {"action": {"type": "string"}}},
        )

        # Initial state: git tool inactive
        active_names = [t["name"] for t in mgr.get_active_tools()]
        assert "git_branch_manager" not in active_names

        # Turn 1: Task mentions "git branch create" -> JIT activation
        activated = mgr.detect_and_activate("please check the git branch status", turn=1)
        assert "git_branch_manager" in activated
        assert "git_branch_manager" in [t["name"] for t in mgr.get_active_tools()]

        # Turn 2: Tool used
        mgr.mark_tool_used("git_branch_manager", turn=2)
        assert "git_branch_manager" in [t["name"] for t in mgr.get_active_tools()]

        # Turn 3: Unrelated task (tool not used, 1 turn idle)
        pruned_turn3 = mgr.prune_idle_tools(current_turn=3, max_idle_turns=2)
        assert "git_branch_manager" not in pruned_turn3
        assert "git_branch_manager" in [t["name"] for t in mgr.get_active_tools()]

        # Turn 4: Second idle turn (current_turn 4 - last_used 2 = 2) -> pruned
        pruned_turn4 = mgr.prune_idle_tools(current_turn=4, max_idle_turns=2)
        assert "git_branch_manager" in pruned_turn4
        assert "git_branch_manager" not in [t["name"] for t in mgr.get_active_tools()]

    def test_schema_compression_ratio(self):
        raw_schema = {
            "name": "complex_cloud_deployer",
            "description": (
                "Deploy distributed cluster nodes with extensive load balancing "
                "and telemetry logging."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster_name": {
                        "type": "string",
                        "description": (
                            "The unique name of the target Kubernetes cluster in "
                            "the cloud environment."
                        ),
                    },
                    "node_count": {
                        "type": "integer",
                        "description": "Total count of active worker nodes to spin up.",
                    },
                    "enable_redundancy": {
                        "type": "boolean",
                        "description": (
                            "Whether to enable cross-region redundancy with "
                            "automatic failover."
                        ),
                    },
                },
                "required": ["cluster_name", "node_count"],
            },
        }

        compressed = compress_tool_schema(raw_schema)
        import json
        raw_len = len(json.dumps(raw_schema))
        comp_len = len(json.dumps(compressed))

        saving_pct = (raw_len - comp_len) / raw_len
        assert saving_pct >= 0.40  # ≥ 40% compression ratio proven
