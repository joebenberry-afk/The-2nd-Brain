"""Focused T7.4 Brainstem attention/intervention coordinator tests."""

from __future__ import annotations

from pathlib import Path

from second_brain import brainstem, decisions


def test_brainstem_missing_signal_uses_conservative_default(brain_home: Path) -> None:
    """Missing signals produce conservative, non-escalated defaults."""
    empty_signals = brainstem.BrainstemSignals()
    decision = brainstem.decide(brain_home, empty_signals)

    assert decision.retrieve is False
    assert decision.inject_budget == 500
    assert decision.route_floor == "T0"
    assert decision.evict is False
    assert decision.verify_level == "targeted"
    assert decision.scout_allowed is False
    assert "CONSERVATIVE_DEFAULTS_APPLIED" in decision.reason_codes


def test_brainstem_decision_is_deterministic(brain_home: Path) -> None:
    """Identical signals produce identical decisions and reason codes."""
    signals = brainstem.BrainstemSignals(
        budget_tokens_used=1200,
        budget_tokens_cap=2500,
        budget_hard_cap=4000,
        resident_tokens=7000,
        context_token_limit=8000,
        task_class="debugging",
        risk_class="HIGH",
    )

    dec1 = brainstem.decide(brain_home, signals)
    dec2 = brainstem.decide(brain_home, signals)

    assert dec1.retrieve == dec2.retrieve
    assert dec1.inject_budget == dec2.inject_budget
    assert dec1.route_floor == dec2.route_floor
    assert dec1.evict == dec2.evict
    assert dec1.verify_level == dec2.verify_level
    assert dec1.scout_allowed == dec2.scout_allowed
    assert dec1.reason_codes == dec2.reason_codes


def test_brainstem_records_decision(brain_home: Path) -> None:
    """Every brainstem decision is recorded in the decisions ledger with kind='brainstem'."""
    signals = brainstem.BrainstemSignals(
        task_class="implementation",
        risk_class="LOW",
        budget_tokens_cap=1500,
    )
    decision = brainstem.decide(brain_home, signals)

    assert decision.decision_ref is not None
    rows = decisions.list_decisions(brain_home, kind="brainstem")
    assert len(rows) >= 1
    logged = rows[-1]
    assert logged["decision_id"] == decision.decision_ref
    assert logged["kind"] == "brainstem"
    assert logged["chosen"]["route_floor"] == decision.route_floor
    assert logged["chosen"]["verify_level"] == decision.verify_level
    assert logged["inputs"]["task_class"] == "implementation"


def test_learned_override_cannot_bypass_hard_budget_or_authority(brain_home: Path) -> None:
    """Learned overrides in SHADOW cannot exceed hard budget caps or downgrade verification floors."""
    signals = brainstem.BrainstemSignals(
        budget_tokens_used=500,
        budget_tokens_cap=2000,
        budget_hard_cap=2500,  # Hard cap
        risk_class="HIGH",      # Requires full verification floor
        task_class="implementation",
    )

    # Attempt to bypass hard budget (request 50000) and downgrade verification to none
    override = {
        "inject_budget": 50000,
        "verify_level": "none",
        "route_floor": "cheap",
    }

    decision = brainstem.decide(brain_home, signals, learned_override=override)

    # Guard 1: Budget is capped at hard_cap (2500), NOT 50000
    assert decision.inject_budget <= 2500
    assert any("OVERRIDE_BUDGET_CAPPED_AT_HARD_LIMIT" in r for r in decision.reason_codes)

    # Guard 2: Verification level cannot downgrade below full
    assert decision.verify_level == "full"
    assert "OVERRIDE_VERIFY_FLOOR_REJECTED" in decision.reason_codes

    # Guard 3: Route floor cannot downgrade below T2 for HIGH risk
    assert decision.route_floor == "T2"
    assert "OVERRIDE_ROUTE_FLOOR_REJECTED" in decision.reason_codes
