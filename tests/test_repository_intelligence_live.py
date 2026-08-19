"""
Tests for Repository Intelligence & Driver/Worker Plane (Plan §3 P1.1, P1.2, P2.4).

Tests:
1. Incremental AST and symbol indexing (processes dirty files only).
2. Symbol lookup and file dependency queries.
3. Strict worker concurrency limit enforcement (max 2 concurrent workers).
4. Structured worker assignment & result lifecycle.
"""

import pytest

from second_brain.errors import BrainError
from second_brain.repository_intelligence import (
    RepositoryIntelligence,
    WorkerPlaneManager,
    WorkerResultPacket,
    WorkerStatus,
)


class TestRepositoryIntelligenceAndWorkerPlane:
    """Proves durable repository intelligence and worker control plane (§4 R8)."""

    def test_incremental_ast_and_symbol_indexing(self, brain_home, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        # Create two sample python files
        f1 = repo_dir / "service.py"
        f1.write_text(
            "import os\nfrom math import sqrt\n\n"
            "class MathService:\n"
            "    '''Service for math.'''\n"
            "    def calculate(self, x):\n"
            "        return sqrt(x)\n",
            encoding="utf-8",
        )

        f2 = repo_dir / "utils.py"
        f2.write_text("def helper_fn(): return True\n", encoding="utf-8")

        intel = RepositoryIntelligence(brain_home, repo_dir)

        # Run 1: Initial full index
        counts1 = intel.index_incremental()
        assert counts1["scanned"] == 2
        assert counts1["indexed"] == 2
        assert counts1["skipped"] == 0

        # Query symbols
        syms = intel.find_symbol("MathService")
        assert len(syms) == 1
        assert syms[0]["kind"] == "class"
        assert syms[0]["file_path"] == "service.py"

        # Query dependencies
        deps = intel.get_file_dependencies("service.py")
        assert len(deps) == 2
        dep_mods = [d["imported_module"] for d in deps]
        assert "os" in dep_mods
        assert "math" in dep_mods

        # Run 2: Unchanged files -> 0 files indexed, 2 skipped
        counts2 = intel.index_incremental()
        assert counts2["scanned"] == 2
        assert counts2["indexed"] == 0
        assert counts2["skipped"] == 2

        # Run 3: Modify one file -> only 1 indexed, 1 skipped
        f2.write_text("def helper_fn(): return False\ndef new_fn(): pass\n", encoding="utf-8")
        counts3 = intel.index_incremental()
        assert counts3["scanned"] == 2
        assert counts3["indexed"] == 1
        assert counts3["skipped"] == 1

        new_syms = intel.find_symbol("new_fn")
        assert len(new_syms) == 1

    def test_worker_concurrency_ceiling_enforcement(self, brain_home):
        session_id = "sess-worker-01"
        plane = WorkerPlaneManager(brain_home, session_id, max_concurrent_workers=2)

        # Spawn worker 1 (Active = 1)
        w1 = plane.spawn_worker("Subtask 1: Parse AST")
        assert plane.active_worker_count() == 1

        # Spawn worker 2 (Active = 2)
        w2 = plane.spawn_worker("Subtask 2: Run linters")
        assert plane.active_worker_count() == 2

        # Spawn worker 3 -> Exceeds max 2 -> Raises BrainError
        with pytest.raises(BrainError, match="Worker concurrency ceiling reached"):
            plane.spawn_worker("Subtask 3: Overflow task")

        # Complete worker 1 -> Active drops to 1
        plane.complete_worker(
            WorkerResultPacket(
                worker_id=w1.worker_id,
                session_id=session_id,
                status=WorkerStatus.COMPLETED,
                summary="AST parsed successfully",
                findings=["Found 12 classes"],
                tokens_used=120,
            )
        )
        assert plane.active_worker_count() == 1

        # Now worker 3 can spawn safely
        w3 = plane.spawn_worker("Subtask 3: Run tests")
        assert plane.active_worker_count() == 2

        # Clean up worker 2 & 3
        plane.complete_worker(
            WorkerResultPacket(
                worker_id=w2.worker_id,
                session_id=session_id,
                status=WorkerStatus.COMPLETED,
                summary="Linters passed",
            )
        )
        plane.complete_worker(
            WorkerResultPacket(
                worker_id=w3.worker_id,
                session_id=session_id,
                status=WorkerStatus.COMPLETED,
                summary="Tests passed",
            )
        )
        assert plane.active_worker_count() == 0
