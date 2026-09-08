"""Focused tests for the corrected v2 policy owner."""

from dataclasses import FrozenInstanceError

import pytest

from second_brain import v2_policy
from second_brain.errors import BrainError

_POLICY = """schema_version = 1
[rollout]
admission = "SHADOW"
retrieval = "SHADOW"
brainstem = "SHADOW"
learning = "SHADOW"
culture = "SHADOW"
frontier = "SHADOW"
verification = "SHADOW"
[admission]
min_score = 0.7
[retrieval]
max_candidates = 10
top_k = 3
token_budget = 100
[brainstem]
context_char_budget = 1000
worker_slots = 1
premium_model_turns = 1
[learning]
surprise_threshold = 0.8
[culture]
[frontier]
min_importance = 0.7
[verification]
floor = "targeted"
"""


def _write_policy(home, text=_POLICY):
    config = home / "config"
    config.mkdir()
    (config / "v2.toml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "text, message",
    [
        (_POLICY + "\n[unexpected]\nactive = true\n", "unknown"),
        ("schema_version = 1\n", "missing required table"),
        (_POLICY.replace("min_score = 0.7", 'min_score = "bad"'), "between 0 and 1"),
    ],
)
def test_policy_rejects_unknown_missing_and_invalid_types(tmp_path, text, message):
    _write_policy(tmp_path, text)
    with pytest.raises(BrainError, match=message):
        v2_policy.load_policy(tmp_path)


def test_policy_rollout_is_immutable_and_stage_gate_is_strict(tmp_path):
    _write_policy(tmp_path)
    policy = v2_policy.load_policy(tmp_path)
    with pytest.raises(TypeError):
        policy.rollout["admission"] = v2_policy.RolloutStage.ACTIVE
    with pytest.raises(FrozenInstanceError):
        policy.__setattr__("worker_slots", 2)
    assert (
        v2_policy.require_stage(policy, "admission", v2_policy.RolloutStage.SHADOW)
        is v2_policy.RolloutStage.SHADOW
    )
    with pytest.raises(BrainError, match="requires"):
        v2_policy.require_stage(policy, "admission", v2_policy.RolloutStage.CANARY)


def test_policy_rejects_invalid_utf8(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "v2.toml").write_bytes(b"schema_version = 1\n\xff")
    with pytest.raises(BrainError, match="cannot read"):
        v2_policy.load_policy(tmp_path)


def test_policy_accepts_current_model_and_provider_defaults(tmp_path):
    _write_policy(
        tmp_path,
        _POLICY
        + "\n[models.default]\ncontext_tokens = 128000\n"
        + '\n[providers.default]\ncache_scope = "model"\n',
    )
    policy = v2_policy.load_policy(tmp_path)
    assert policy.rollout["admission"] is v2_policy.RolloutStage.SHADOW
