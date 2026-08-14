from pathlib import Path

from proof.runner.integrity import hash_tree


def test_hash_tree_handles_a_ten_thousand_file_fixture(tmp_path: Path):
    for index in range(10_000):
        (tmp_path / f"memory-{index:05d}.md").write_text(f"memory {index}\n", encoding="utf-8")
    assert len(hash_tree(tmp_path)) == 64
