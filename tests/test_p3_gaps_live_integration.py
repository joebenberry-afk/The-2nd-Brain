"""
Live integration tests for P3 Gaps (Plan §4 R9: P3.8, P3.10, P3.14, P3.15, P3.17).

Tests:
1. P3.10 Improvement Radar: detects repeated reads, tool error loops, and search thrash.
2. P3.14 & P3.15 Skill ROI & Skill Gardener: computes net tokens and audits degraded/healthy skills.
3. P3.17 Brain Handoff: generates structured, lossless cross-agent handoff artifact.
4. P3.8 Verifier Brief: generates fresh verifier brief from requirements ledger.
"""

from second_brain.gardener import SkillGardener, SkillHealth, SkillROILedger
from second_brain.handoff import create_handoff
from second_brain.radar import ImprovementRadar, InefficiencyPattern
from second_brain.verify import build_verifier_brief
from second_brain.working_set import init_capsule


class TestP3GapsLiveIntegration:
    """Proves P3 gap closures on the frozen roadmap (§4 R9)."""

    def test_improvement_radar_detects_inefficiencies(self, brain_home):
        radar = ImprovementRadar(brain_home)

        # Synthetic session events with repeated reads and error loop
        events = [
            {"kind": "tool_call", "tool": "view_file", "input": {"AbsolutePath": "src/core.py"}},
            {"kind": "tool_call", "tool": "view_file", "input": {"AbsolutePath": "src/core.py"}},
            {"kind": "tool_call", "tool": "view_file", "input": {"AbsolutePath": "src/core.py"}},
            {
                "kind": "tool_result",
                "toolName": "bash",
                "is_error": True,
                "content": "Exit 1: SyntaxError",
            },
            {
                "kind": "tool_result",
                "toolName": "bash",
                "is_error": True,
                "content": "Exit 1: SyntaxError",
            },
            {"kind": "brain_retrieval_attempt", "candidate_count": 0},
            {"kind": "brain_retrieval_attempt", "candidate_count": 0},
            {"kind": "brain_retrieval_attempt", "candidate_count": 0},
        ]

        alerts = radar.analyze_events(events)
        patterns = [a.pattern for a in alerts]

        assert InefficiencyPattern.REPEATED_READ in patterns
        assert InefficiencyPattern.TOOL_ERROR_LOOP in patterns
        assert InefficiencyPattern.SEARCH_THRASH in patterns

        # Check alert content
        read_alert = next(a for a in alerts if a.pattern == InefficiencyPattern.REPEATED_READ)
        assert "core.py" in read_alert.summary
        assert read_alert.tokens_wasted_estimate > 0

    def test_skill_roi_ledger_and_gardener_audit(self, brain_home):
        ledger = SkillROILedger(brain_home)

        # Record high-value skill usage
        ledger.record_usage(
            skill_name="fast_test_runner",
            session_id="sess-01",
            tokens_invested=100,
            tokens_saved=500,
            success=True,
        )
        ledger.record_usage(
            skill_name="fast_test_runner",
            session_id="sess-02",
            tokens_invested=100,
            tokens_saved=600,
            success=True,
        )

        # Record degraded skill usage
        ledger.record_usage(
            skill_name="broken_generator",
            session_id="sess-01",
            tokens_invested=800,
            tokens_saved=100,
            success=False,
        )

        gardener = SkillGardener(brain_home)
        audit = gardener.audit_portfolio()

        assert audit["total_skills_tracked"] == 2
        assert audit["healthy_count"] == 1
        assert audit["degraded_count"] == 1

        degraded = audit["degraded_skills"][0]
        assert degraded["skill_name"] == "broken_generator"
        assert degraded["health"] == SkillHealth.DEGRADED.value

        healthy = audit["healthy_skills"][0]
        assert healthy["skill_name"] == "fast_test_runner"
        assert healthy["net_tokens_saved"] == 900
        assert healthy["health"] == SkillHealth.HEALTHY.value

    def test_brain_handoff_artifact_generation(self, brain_home):
        session_id = "sess-handoff-01"
        init_capsule(
            brain_home,
            session_id,
            objective="Implement R9 closure",
            constraints=["Close P3 gaps", "Pass all tests"],
        )

        artifact = create_handoff(
            brain_home,
            session_id,
            target_agent="incoming-qualification-agent",
            objective="Complete RC2 qualification",
            completed_steps=["R0-R8 completed", "R9 implemented"],
            key_decisions=["Use deterministic reducers", "Harden proof validation"],
            pending_blockers=["Run paired token benchmark"],
            relevant_files=["src/second_brain/radar.py", "src/second_brain/gardener.py"],
            next_actions=["Proceed to R10"],
        )

        assert "sess-handoff-01" in artifact.session_id
        assert "Complete RC2 qualification" in artifact.objective
        assert len(artifact.completed_steps) == 2

        # Check saved markdown file
        saved_path = brain_home / "outputs" / "handoffs" / "handoff-sess-handoff-01.md"
        assert saved_path.exists()
        md = saved_path.read_text(encoding="utf-8")
        assert "# Brain Handoff Artifact" in md
        assert "incoming-qualification-agent" in md
        assert "Key Architectural Decisions" in md

    def test_verifier_brief_generation(self, brain_home, tmp_path):
        session_id = "sess-verifier-01"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        init_capsule(
            brain_home,
            session_id,
            objective="Add security hardening",
            constraints=["Validate inputs", "Log security telemetry"],
        )

        brief_path = build_verifier_brief(brain_home, session_id, repo_dir)
        assert brief_path.exists()
        text = brief_path.read_text(encoding="utf-8")
        assert "Intent Verifier Brief" in text
        assert "Backward Reconstruction" in text
        assert "Requirements" in text
