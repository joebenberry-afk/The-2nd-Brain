from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from proof.runner.integrity import hash_tree


def test_hashing_is_stable_under_read_concurrency(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("one", encoding="utf-8")
    (tmp_path / "b.txt").write_text("two", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(lambda _: hash_tree(tmp_path), range(8)))
    assert len(set(hashes)) == 1
