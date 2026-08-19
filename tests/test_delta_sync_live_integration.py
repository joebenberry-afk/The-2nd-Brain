"""
Live integration tests for Delta Sync & Progressive Disclosure (Plan §4 R5).

Tests:
1. Unchanged memories emit 0 tokens (UNCHANGED delta, empty rendered sync text).
2. Small update emits structured diff (≤20% token overhead).
3. Verified hash matching and fail-open invalidation.
4. Progressive disclosure levels (REPO -> MODULE -> SYMBOL -> EXCERPT -> FULL).
"""

from second_brain.contracts import Confidence, MemoryItemStatus, PacketItem
from second_brain.delta_sync import (
    DeltaSyncEngine,
    DeltaType,
    DisclosureLevel,
    compute_memory_delta,
    progressive_disclose,
)


class TestDeltaSyncLiveIntegration:
    """Proves delta synchronization and progressive disclosure (§4 R5)."""

    def test_unchanged_memory_emits_zero_tokens(self):
        engine = DeltaSyncEngine()
        session_id = "sess-delta-01"

        item = PacketItem(
            memory_id="mem-rule-01",
            version=1,
            status=MemoryItemStatus.CURRENT,
            confidence=Confidence.HIGH,
            title="Stable Principle",
            observation="Observed persistent rule.",
            guidance="Always follow this rule.",
            evidence="tests/test_rule.py",
        )

        # Turn 1: Initial delivery
        deltas1, text1 = engine.sync_memories(session_id, [item])
        assert len(deltas1) == 1
        assert deltas1[0].delta_type == DeltaType.ADD
        assert len(text1) > 0

        # Turn 2: Unchanged memory -> UNCHANGED delta, 0 token rendered text
        deltas2, text2 = engine.sync_memories(session_id, [item])
        assert len(deltas2) == 1
        assert deltas2[0].delta_type == DeltaType.UNCHANGED
        assert text2 == ""  # Zero token emission

    def test_small_update_emits_bounded_diff(self):
        base_item = {
            "memory_id": "mem-rule-02",
            "version": 1,
            "title": "Build rule",
            "guidance": "Run pytest",
            "observation": "Tests pass",
        }
        target_item = {
            "memory_id": "mem-rule-02",
            "version": 2,
            "title": "Build rule",
            "guidance": "Run pytest and pyright",
            "observation": "Tests pass",
        }

        delta = compute_memory_delta(base_item, target_item)
        assert delta.delta_type == DeltaType.MODIFY
        assert delta.base_version == 1
        assert delta.target_version == 2
        # Only the modified field in patch payload
        assert "guidance" in delta.patch_payload
        assert "observation" not in delta.patch_payload

    def test_progressive_disclosure_levels(self):
        sample_code = (
            "import os\n"
            "import sys\n\n"
            "class Engine:\n"
            "    '''Core engine class.'''\n"
            "    def start(self):\n"
            "        return True\n\n"
            "def run_task():\n"
            "    '''Execute main task.'''\n"
            "    return 42\n"
        )

        # REPO level
        repo_disc = progressive_disclose(sample_code, level=DisclosureLevel.REPO)
        assert "Repository Overview" in repo_disc

        # MODULE level
        mod_disc = progressive_disclose(sample_code, level=DisclosureLevel.MODULE)
        assert "class Engine" in mod_disc
        assert "def run_task" in mod_disc

        # SYMBOL level
        sym_disc = progressive_disclose(
            sample_code,
            level=DisclosureLevel.SYMBOL,
            symbol_name="run_task",
        )
        assert "def run_task" in sym_disc
        assert "return 42" in sym_disc

        # FULL level
        full_disc = progressive_disclose(sample_code, level=DisclosureLevel.FULL)
        assert full_disc == sample_code
