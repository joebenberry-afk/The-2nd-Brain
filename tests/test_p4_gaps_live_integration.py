"""
Live integration tests for P4 Gaps (Plan §4 R10: P4.1, P4.2, P4.4, P4.5).

Tests:
1. P4.1 Long-Running Goals: goal lifecycle, milestones, completion tracking, persistence.
2. P4.2 Zero-Token Local Heartbeat: local DB integrity and cache maintenance without model tokens.
3. P4.4 Structural Bottleneck Fingerprinting: records, aggregates, and ranks systemic bottlenecks.
"""

from second_brain import db
from second_brain.fingerprints import BottleneckCategory, BottleneckFingerprintStore
from second_brain.goals import GoalStatus, GoalStore
from second_brain.heartbeat import LocalHeartbeatEngine


class TestP4GapsLiveIntegration:
    """Proves P4 gap closures on the frozen roadmap (§4 R10)."""

    def test_long_running_goal_lifecycle_and_milestones(self, brain_home):
        assert db.db_path(brain_home).is_file()
        store = GoalStore(brain_home)

        # Create goal with 3 milestones
        goal = store.create_goal(
            title="Migrate to Microservices",
            description="Extract auth and payment services into dedicated modules.",
            milestone_titles=[
                "Extract auth module",
                "Extract payment module",
                "Implement gateway router",
            ],
        )

        assert goal.status == GoalStatus.ACTIVE
        assert len(goal.milestones) == 3
        assert goal.progress_pct() == 0.0

        # Complete milestone 1
        g1 = store.complete_milestone(goal.goal_id, "m-1", evidence_ref="test-auth-pass")
        assert g1.milestones[0].completed is True
        assert g1.progress_pct() == 33.3
        assert g1.status == GoalStatus.ACTIVE

        # Complete milestone 2
        g2 = store.complete_milestone(goal.goal_id, "m-2", evidence_ref="test-payment-pass")
        assert g2.progress_pct() == 66.7
        assert g2.status == GoalStatus.ACTIVE

        # Complete final milestone -> Auto-completes goal
        g3 = store.complete_milestone(goal.goal_id, "m-3", evidence_ref="test-gateway-pass")
        assert g3.progress_pct() == 100.0
        assert g3.status == GoalStatus.COMPLETED
        assert g3.completed_at is not None

        history = store.list_goal_events(goal.goal_id)
        assert [event["event_type"] for event in history] == [
            "MILESTONE_COMPLETED",
            "MILESTONE_COMPLETED",
            "MILESTONE_COMPLETED",
        ]

        # Verify active goals list excludes completed goal
        active_goals = store.list_active_goals()
        assert goal.goal_id not in [g.goal_id for g in active_goals]

    def test_zero_token_local_heartbeat(self, brain_home):
        engine = LocalHeartbeatEngine(brain_home)

        # Execute pulse
        status = engine.pulse()

        assert status.healthy is True
        assert status.db_ok is True
        assert status.model_tokens_used == 0  # Invariant: 0 model tokens consumed

        # Check dictionary representation
        d = status.to_dict()
        assert d["model_tokens_used"] == 0
        assert d["healthy"] is True

    def test_bottleneck_fingerprint_ranking(self, brain_home):
        store = BottleneckFingerprintStore(brain_home)

        # Record prompt bloat bottleneck (occurs 3 times)
        for _ in range(3):
            store.record_bottleneck(
                category=BottleneckCategory.PROMPT_BLOAT,
                description="System prompt bloated with unused tool schemas",
                mitigation="Use Dynamic Tool Working Set (Tier A/B/C)",
                impact_score=8.5,
            )

        # Record minor tool error
        store.record_bottleneck(
            category=BottleneckCategory.TOOL_CHAIN_THRASH,
            description="Grep called 5 times with identical arguments",
            mitigation="Use Action Cache to replay identical searches",
            impact_score=3.0,
        )

        top = store.list_top_bottlenecks()
        assert len(top) == 2

        # Prompt bloat should rank highest due to higher impact * occurrences
        assert top[0].category == BottleneckCategory.PROMPT_BLOAT
        assert top[0].occurrence_count == 3
        assert top[0].impact_score == 8.5
