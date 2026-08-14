from pathlib import Path

import pytest

from proof.runner.integrity import IntegrityError, freeze_hash, sha256_path


def test_frozen_artifact_hash_rejects_mutation(tmp_path: Path):
    artifact = tmp_path / "SKILL.md"
    artifact.write_text("version A\n", encoding="utf-8")
    expected = sha256_path(artifact)
    assert freeze_hash(artifact, expected) == expected
    artifact.write_text("version B\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="changed"):
        freeze_hash(artifact, expected)
