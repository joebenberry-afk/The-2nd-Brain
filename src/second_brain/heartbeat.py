"""
Zero-Token Local Heartbeat & Maintenance Engine (Plan §3 P4.2).

Performs lightweight, deterministic local health checks without model calls:
- Database connectivity & PRAGMA integrity check.
- Action Cache TTL expiration pruning.
- Dirty working tree and unindexed file detection.
- Emits 0 model tokens when system state is unchanged.
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .action_cache import ActionCacheStore
from .paths import db_path


@dataclass
class HeartbeatStatus:
    """Result of local zero-token heartbeat check (§3 P4.2)."""
    healthy: bool
    db_ok: bool
    cache_pruned_count: int
    uncommitted_git_changes: bool
    issues: list[str] = field(default_factory=list)
    timestamp: str = ""
    model_tokens_used: int = 0  # Invariant: always 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "db_ok": self.db_ok,
            "cache_pruned_count": self.cache_pruned_count,
            "uncommitted_git_changes": self.uncommitted_git_changes,
            "issues": self.issues,
            "timestamp": self.timestamp,
            "model_tokens_used": self.model_tokens_used,
        }


class LocalHeartbeatEngine:
    """Deterministic local maintenance probe."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def pulse(self, repo_dir: Path | str | None = None) -> HeartbeatStatus:
        """
        Execute zero-token local health probe.
        """
        issues: list[str] = []
        db_ok = True
        cache_pruned = 0
        git_dirty = False
        now = datetime.now(UTC).isoformat()

        # 1. Check Primary SQLite DB
        main_db = db_path(self.home)
        if main_db.exists():
            try:
                with sqlite3.connect(main_db, timeout=2.0) as conn:
                    res = conn.execute("PRAGMA quick_check").fetchone()
                    if not res or res[0] != "ok":
                        db_ok = False
                        issues.append(f"DB integrity check failed: {res}")
            except Exception as exc:
                db_ok = False
                issues.append(f"DB error: {exc}")
        else:
            db_ok = False
            issues.append("Main DB does not exist")

        # 2. Prune Expired Action Cache Entries
        try:
            with ActionCacheStore(self.home) as cache:
                cache_pruned = cache.prune_expired()
        except Exception:
            pass

        # 3. Check Git Working Tree if in repo
        check_repo = Path(repo_dir) if repo_dir else self.home
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(check_repo),
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                git_dirty = True
        except Exception:
            pass

        healthy = db_ok and len(issues) == 0

        return HeartbeatStatus(
            healthy=healthy,
            db_ok=db_ok,
            cache_pruned_count=cache_pruned,
            uncommitted_git_changes=git_dirty,
            issues=issues,
            timestamp=now,
            model_tokens_used=0,  # 0 token local invariant
        )
