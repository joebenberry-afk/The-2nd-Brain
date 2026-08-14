from pathlib import Path

import pytest
from proof.runner.integrity import IntegrityError, freeze_hash, sha256_path


def test_missing_frozen_input_fails_closed(tmp_path: Path):
    path = tmp_path / "missing.json"
    with pytest.raises(IntegrityError, match="missing"):
        freeze_hash(path, "0" * 64)


def test_hash_is_not_silently_replaced(tmp_path: Path):
    path = tmp_path / "input.json"
    path.write_text("{}\n", encoding="utf-8")
    expected = sha256_path(path)
    path.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(IntegrityError):
        freeze_hash(path, expected)
