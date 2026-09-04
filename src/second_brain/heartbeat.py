"""Deterministic, event-driven local heartbeat coordination."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import subprocess
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from . import artifacts, db
from .action_cache import ActionCacheStore
from .paths import db_path

_DEFAULT_MODE = "shadow"
_DEFAULT_INTERVAL = 60
_DEFAULT_HISTORY = 256
_VALID_MODES = frozenset({"off", "shadow", "active"})
_MAX_WARNING_LENGTH = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _as_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return _utc_now()
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class HeartbeatConfig:
    """Live heartbeat policy read from ``config/brain.toml``."""

    mode: str = _DEFAULT_MODE
    min_interval_seconds: int = _DEFAULT_INTERVAL
    max_run_history: int = _DEFAULT_HISTORY
    warning: str | None = None

    @classmethod
    def load(cls, home: Path | str) -> HeartbeatConfig:
        path = Path(home) / "config" / "brain.toml"
        try:
            with path.open("rb") as stream:
                raw = tomllib.load(stream)
            section = raw.get("heartbeat", {})
            if not isinstance(section, dict):
                raise ValueError("heartbeat must be a table")
            mode = section.get("mode", _DEFAULT_MODE)
            interval = section.get("min_interval_seconds", _DEFAULT_INTERVAL)
            history = section.get("max_run_history", _DEFAULT_HISTORY)
            if (
                mode not in _VALID_MODES
                or isinstance(interval, bool)
                or not isinstance(interval, int)
                or interval < 0
                or isinstance(history, bool)
                or not isinstance(history, int)
                or history < 1
                or history > 10000
            ):
                raise ValueError("heartbeat values out of bounds")
            return cls(mode=mode, min_interval_seconds=interval, max_run_history=history)
        except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
            warning = "invalid heartbeat configuration; using safe defaults"[:_MAX_WARNING_LENGTH]
            return cls(warning=warning)


@dataclass
class HeartbeatStatus:
    """Result of a local zero-token heartbeat check."""

    healthy: bool
    db_ok: bool
    cache_pruned_count: int
    uncommitted_git_changes: bool
    issues: list[str] = field(default_factory=list)
    timestamp: str = ""
    model_tokens_used: int = 0
    maintenance_mutated: bool = False
    artifacts_gc_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "db_ok": self.db_ok,
            "cache_pruned_count": self.cache_pruned_count,
            "uncommitted_git_changes": self.uncommitted_git_changes,
            "issues": list(self.issues),
            "timestamp": self.timestamp,
            "model_tokens_used": 0,
            "maintenance_mutated": self.maintenance_mutated,
            "artifacts_gc_count": self.artifacts_gc_count,
        }


class LocalHeartbeatEngine:
    """Deterministic local maintenance probe; it never invokes a model."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def _cache_expired_count(self, now: str) -> int:
        cache_file = self.home / "state" / "cache" / "action_cache.sqlite"
        if not cache_file.exists():
            return 0
        uri = f"file:{cache_file.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM action_cache "
                "WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            ).fetchone()
        return int(row[0] if row else 0)

    def pulse(
        self, repo_dir: Path | str | None = None, *, mode: str = _DEFAULT_MODE
    ) -> HeartbeatStatus:
        """Run local probes according to ``off``, ``shadow``, or ``active``."""
        if mode not in _VALID_MODES:
            mode = _DEFAULT_MODE
        timestamp = _iso(_utc_now())
        if mode == "off":
            return HeartbeatStatus(True, True, 0, False, timestamp=timestamp)

        issues: list[str] = []
        db_ok = True
        cache_count = 0
        gc_count = 0
        git_dirty = False
        main_db = db_path(self.home)
        if not main_db.exists():
            db_ok = False
            issues.append("db_missing")
        else:
            try:
                with sqlite3.connect(main_db, timeout=2.0) as conn:
                    check = conn.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    db_ok = False
                    issues.append("db_integrity")
            except Exception:
                db_ok = False
                issues.append("db_integrity")

        if mode == "shadow":
            try:
                cache_count = self._cache_expired_count(timestamp)
            except Exception:
                issues.append("cache_probe")
        else:
            try:
                cache = ActionCacheStore(self.home)
            except Exception:
                issues.append("cache_probe")
            else:
                try:
                    cache_count = cache.prune_expired()
                except Exception:
                    issues.append("cache_prune")
                finally:
                    try:
                        cache.close()
                    except Exception:
                        issues.append("cache_prune")
            try:
                gc_result = artifacts.gc(self.home, min_age_days=30)
                gc_count = int(gc_result.get("deleted_count", 0))
            except Exception:
                issues.append("artifacts_gc_probe")

        check_repo = Path(repo_dir) if repo_dir is not None else self.home
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(check_repo),
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if result.returncode != 0:
                issues.append("git_probe")
            elif result.stdout.strip():
                git_dirty = True
        except Exception:
            issues.append("git_probe")

        unique_issues = list(dict.fromkeys(issues))
        return HeartbeatStatus(
            healthy=db_ok and not unique_issues,
            db_ok=db_ok,
            cache_pruned_count=cache_count,
            uncommitted_git_changes=git_dirty,
            issues=unique_issues,
            timestamp=timestamp,
            model_tokens_used=0,
            maintenance_mutated=mode == "active",
            artifacts_gc_count=gc_count,
        )


class HeartbeatCoordinator:
    """Reserve and execute at most one heartbeat for an interval."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    @staticmethod
    def _base_result(mode: str, event: str, *, due: bool, ran: bool) -> dict[str, Any]:
        return {
            "mode": mode,
            "event": event,
            "due": due,
            "ran": ran,
            "healthy": True,
            "db_ok": True,
            "cache_pruned_count": 0,
            "git_dirty": False,
            "issue_codes": [],
            "latency_ms": 0,
            "model_tokens_used": 0,
            "maintenance_mutated": False,
            "artifacts_gc_count": 0,
        }

    def _record_failure(self, mode: str, event: str, code: str, *, due: bool) -> dict[str, Any]:
        result = self._base_result(mode, event, due=due, ran=False)
        result.update(
            healthy=False,
            db_ok=code not in {"db_missing", "db_integrity"},
            issue_codes=[code],
        )
        if code in {"db_missing", "db_integrity"}:
            result["db_ok"] = False
        return result

    def _prune_history(self, conn: sqlite3.Connection, maximum: int) -> None:
        conn.execute(
            "DELETE FROM heartbeat_runs WHERE run_id IN ("
            "SELECT run_id FROM heartbeat_runs ORDER BY started_at ASC "
            "LIMIT MAX(0, (SELECT COUNT(*) FROM heartbeat_runs) - ?))",
            (maximum,),
        )

    def run_if_due(
        self,
        event: str,
        session_id: str,
        repo_dir: Path | str | None = None,
        *,
        force: bool = False,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        config = HeartbeatConfig.load(self.home)
        result = self._base_result(config.mode, event, due=False, ran=False)
        if config.warning:
            result["configuration_warning"] = config.warning
        if config.mode == "off":
            return result

        current = _as_datetime(now)
        current_text = _iso(current)
        main_db = db_path(self.home)
        if not main_db.exists():
            return self._record_failure(config.mode, event, "db_missing", due=True) | (
                {"configuration_warning": config.warning} if config.warning else {}
            )

        run_id = str(uuid.uuid4())
        conn: sqlite3.Connection | None = None
        try:
            conn = db.connect(main_db)
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                "SELECT last_run_at FROM heartbeat_state WHERE singleton = 1"
            ).fetchone()
            last = state[0] if state else None
            due = force or not last
            if not due:
                try:
                    due = (
                        current - _as_datetime(last)
                    ).total_seconds() >= config.min_interval_seconds
                except (TypeError, ValueError, OverflowError):
                    due = True
            if not due:
                conn.rollback()
                result["due"] = False
                return result
            conn.execute(
                "INSERT INTO heartbeat_runs "
                "(run_id, session_id, event, mode, started_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, session_id, event, config.mode, current_text, "reserved"),
            )
            conn.execute(
                "UPDATE heartbeat_state SET last_run_at = ? WHERE singleton = 1",
                (current_text,),
            )
            conn.commit()
        except sqlite3.Error:
            if conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    conn.rollback()
            return self._record_failure(config.mode, event, "db_integrity", due=True) | (
                {"configuration_warning": config.warning} if config.warning else {}
            )
        finally:
            if conn is not None:
                conn.close()

        started = perf_counter()
        status = LocalHeartbeatEngine(self.home).pulse(repo_dir, mode=config.mode)
        result = {
            "mode": config.mode,
            "event": event,
            "due": True,
            "ran": True,
            "healthy": status.healthy,
            "db_ok": status.db_ok,
            "cache_pruned_count": status.cache_pruned_count,
            "git_dirty": status.uncommitted_git_changes,
            "issue_codes": list(status.issues),
            "latency_ms": int((perf_counter() - started) * 1000),
            "model_tokens_used": 0,
            "maintenance_mutated": status.maintenance_mutated,
            "artifacts_gc_count": status.artifacts_gc_count,
        }
        if config.warning:
            result["configuration_warning"] = config.warning

        final_conn: sqlite3.Connection | None = None
        try:
            final_conn = db.connect(main_db)
            final_conn.execute("BEGIN IMMEDIATE")
            final_conn.execute(
                "UPDATE heartbeat_runs SET completed_at = ?, status = ?, "
                "issue_codes_json = ?, result_json = ? WHERE run_id = ?",
                (
                    _iso(_utc_now()),
                    "healthy" if status.healthy else "unhealthy",
                    json.dumps(status.issues, separators=(",", ":")),
                    json.dumps(result, separators=(",", ":")),
                    run_id,
                ),
            )
            self._prune_history(final_conn, config.max_run_history)
            final_conn.commit()
        except sqlite3.Error:
            if final_conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    final_conn.rollback()
        finally:
            if final_conn is not None:
                final_conn.close()
        return result



