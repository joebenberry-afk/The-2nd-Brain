"""
Proof-Carrying Action Cache.

Plan §7: Phase 4 — Proof-Carrying Action Cache.
Caches idempotent, pure, and deterministic actions (file reads, tree scans,
pure verification checks, firewall distillations, and code searches) with
reproducible action keys and cryptographically verifiable safety proofs.

Safety Rules (§7.1, §7.4):
- Only pure/stable operations are cached.
- Every cache hit rigorously validates its proof conditions (input file hashes,
  git tree clean state, environment fingerprint, TTL) before replay.
- Cache hit produces exact output in <1ms with 0 net model tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import artifacts
from .contracts import estimate_tokens
from .errors import BrainError

ACTION_CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_MAX_ENTRIES = 5000

# Explicit allowlist of recognized verification predicate names (§7.4 fix;
# RC3 finding F4). The old check was `proof.verification_predicate !=
# "reject_always"`, which let ANY unrecognized predicate string pass as
# valid. Steps 1-4 in validate_proof already verify hashes/env/git-tree
# unconditionally; this predicate declares the proof's *kind* and must be
# a name Brain recognizes, or validation fails closed.
KNOWN_VERIFICATION_PREDICATES = frozenset(
    {
        "input_hashes_match",
        "git_tree_unchanged",
        "artifact_exists",
        "deterministic_read",
    }
)


class ActionType(StrEnum):
    FILE_READ = "FILE_READ"
    DIR_SCAN = "DIR_SCAN"
    PURE_VERIFICATION = "PURE_VERIFICATION"
    DISTILLATION = "DISTILLATION"
    CODE_SEARCH = "CODE_SEARCH"
    GENERIC_PURE = "GENERIC_PURE"


_ACTION_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_cache (
    action_key TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    proof_json TEXT NOT NULL,
    output_ref TEXT NOT NULL,
    output_summary TEXT NOT NULL,
    tokens_saved_estimate INTEGER NOT NULL DEFAULT 0,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_action_type ON action_cache (action_type);
CREATE INDEX IF NOT EXISTS idx_action_target ON action_cache (target);
CREATE INDEX IF NOT EXISTS idx_action_expires ON action_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_action_last_accessed ON action_cache (last_accessed_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def hash_file_content(path: Path | str) -> str:
    """Compute sha256 hash of a file's content."""
    p = Path(path)
    if not p.is_file():
        raise BrainError(f"Cannot hash non-existent file: {path}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_tree_hash_for(target_dir: Path | str) -> str | None:
    """Read the git tree hash for a directory (None if not a clean-checkable
    git worktree). Shared by ActionCacheStore._get_git_tree_hash (proof
    validation) and any caller building a git_tree_hash-gated ActionProof
    (e.g. `second_brain action-cache search`, Phase R5)."""
    import subprocess

    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def compute_action_key(
    action_type: ActionType | str,
    target: str,
    params: dict[str, Any] | None = None,
    input_hashes: dict[str, str] | None = None,
    git_tree_hash: str | None = None,
    env_fingerprint: dict[str, str] | None = None,
    verification_predicate: str = "input_hashes_match",
) -> str:
    """
    Construct a deterministic action key from all semantic dependencies (§7.2).
    """
    act_str = action_type.value if isinstance(action_type, ActionType) else str(action_type).upper()
    packet = {
        "v": ACTION_CACHE_SCHEMA_VERSION,
        "action_type": act_str,
        "target": target,
        "params": params or {},
        "input_hashes": input_hashes or {},
        "git_tree_hash": git_tree_hash,
        "env_fingerprint": env_fingerprint or {},
        "verification_predicate": verification_predicate,
    }
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ActionProof:
    """Validity proof carried with each cached action entry (§7.3)."""
    input_hashes: dict[str, str] = field(default_factory=dict)
    git_tree_hash: str | None = None
    env_fingerprint: dict[str, str] = field(default_factory=dict)
    verification_predicate: str = "input_hashes_match"
    expires_at: str | None = None
    ttl_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_hashes": self.input_hashes,
            "git_tree_hash": self.git_tree_hash,
            "env_fingerprint": self.env_fingerprint,
            "verification_predicate": self.verification_predicate,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionProof:
        return cls(
            input_hashes=d.get("input_hashes", {}),
            git_tree_hash=d.get("git_tree_hash"),
            env_fingerprint=d.get("env_fingerprint", {}),
            verification_predicate=d.get("verification_predicate", "input_hashes_match"),
            expires_at=d.get("expires_at"),
            ttl_seconds=d.get("ttl_seconds"),
        )


@dataclass
class ActionCacheEntry:
    """A proof-carrying action cache entry."""
    action_key: str
    action_type: ActionType
    target: str
    proof: ActionProof
    output_ref: str
    output_summary: str
    tokens_saved_estimate: int
    created_at: str
    last_accessed_at: str
    hit_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_key": self.action_key,
            "action_type": self.action_type.value,
            "target": self.target,
            "proof": self.proof.to_dict(),
            "output_ref": self.output_ref,
            "output_summary": self.output_summary,
            "tokens_saved_estimate": self.tokens_saved_estimate,
            "hit_count": self.hit_count,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
        }


@dataclass
class CacheHitResult:
    """Result of querying the action cache."""
    hit: bool
    entry: ActionCacheEntry | None = None
    content: str | None = None
    latency_ms: float = 0.0
    reason: str = "miss"


class ActionCacheStore:
    """Proof-Carrying Action Cache database and execution engine."""

    def __init__(self, home: Path | str, max_entries: int | None = None) -> None:
        self.home = Path(home)
        self.max_entries = (
            max_entries if max_entries is not None else DEFAULT_CACHE_MAX_ENTRIES
        )
        self._db_dir = self.home / "state" / "cache"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._dbfile = self._db_dir / "action_cache.sqlite"
        self._conn: sqlite3.Connection | None = None
        self._init_db()
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self._dbfile, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ActionCacheStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(_ACTION_CACHE_SCHEMA)
        conn.commit()

    def store_action(
        self,
        action_type: ActionType | str,
        target: str,
        content: str,
        output_summary: str = "",
        proof: ActionProof | None = None,
        params: dict[str, Any] | None = None,
        tokens_saved_estimate: int | None = None,
        ttl_seconds: int | None = None,
        max_entries: int | None = None,
    ) -> ActionCacheEntry:
        """
        Store a deterministic action output and its safety proof.
        """
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
        act_proof = proof or ActionProof()

        if ttl_seconds is not None:
            act_proof.ttl_seconds = ttl_seconds
            exp_time = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            act_proof.expires_at = exp_time.isoformat()

        # Store content in backing artifact store
        stored_artifact = artifacts.store_text(
            self.home, content, kind=act.value.lower(), tool="action_cache"
        )
        output_ref = stored_artifact["hash"]

        if tokens_saved_estimate is None:
            tokens_saved_estimate = estimate_tokens(content, home=self.home)

        action_key = compute_action_key(
            action_type=act,
            target=target,
            params=params,
            input_hashes=act_proof.input_hashes,
            git_tree_hash=act_proof.git_tree_hash,
            env_fingerprint=act_proof.env_fingerprint,
            verification_predicate=act_proof.verification_predicate,
        )

        now = _now()
        entry = ActionCacheEntry(
            action_key=action_key,
            action_type=act,
            target=target,
            proof=act_proof,
            output_ref=output_ref,
            output_summary=output_summary or f"{act.value} on {target}",
            tokens_saved_estimate=tokens_saved_estimate,
            created_at=now,
            last_accessed_at=now,
            hit_count=0,
        )

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO action_cache (
                action_key, action_type, target, proof_json, output_ref,
                output_summary, tokens_saved_estimate, hit_count,
                created_at, last_accessed_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_key) DO UPDATE SET
                proof_json=excluded.proof_json,
                output_ref=excluded.output_ref,
                output_summary=excluded.output_summary,
                tokens_saved_estimate=excluded.tokens_saved_estimate,
                last_accessed_at=excluded.last_accessed_at,
                expires_at=excluded.expires_at
            """,
            (
                entry.action_key,
                entry.action_type.value,
                entry.target,
                json.dumps(entry.proof.to_dict()),
                entry.output_ref,
                entry.output_summary,
                entry.tokens_saved_estimate,
                entry.hit_count,
                entry.created_at,
                entry.last_accessed_at,
                entry.proof.expires_at,
            ),
        )
        effective_max = max_entries if max_entries is not None else self.max_entries
        if effective_max is not None and effective_max > 0:
            count_row = conn.execute("SELECT COUNT(*) as c FROM action_cache").fetchone()
            count = count_row["c"] if count_row else 0
            if count > effective_max:
                excess = count - effective_max
                conn.execute(
                    "DELETE FROM action_cache WHERE action_key IN "
                    "(SELECT action_key FROM action_cache ORDER BY last_accessed_at ASC LIMIT ?)",
                    (excess,),
                )
        conn.commit()

        return entry

    def validate_proof(self, proof: ActionProof, cwd: Path | str | None = None) -> bool:
        """
        Validate proof conditions before replaying a cached action (§7.4).
        """
        # 1. Check TTL expiration
        if proof.expires_at:
            try:
                exp_dt = datetime.fromisoformat(proof.expires_at)
                if datetime.now(UTC) > exp_dt:
                    return False
            except Exception:
                return False

        # 2. Check input file hashes
        for file_path, expected_hash in proof.input_hashes.items():
            p = Path(file_path)
            if not p.is_file():
                return False
            try:
                actual_hash = hash_file_content(p)
                if actual_hash != expected_hash:
                    return False
            except Exception:
                return False

        # 3. Check environment variables
        for env_key, expected_val in proof.env_fingerprint.items():
            if os.environ.get(env_key) != expected_val:
                return False

        # 4. Check git tree hash if declared
        if proof.git_tree_hash is not None:
            actual_tree = self._get_git_tree_hash(cwd or self.home)
            if actual_tree != proof.git_tree_hash:
                return False

        # 5. Verification predicate must be an explicitly recognized kind.
        # Unknown/unrecognized predicate -> proof failure -> cache miss.
        return proof.verification_predicate in KNOWN_VERIFICATION_PREDICATES

    def _get_git_tree_hash(self, target_dir: Path | str) -> str | None:
        """Read git tree hash for directory (fail-closed if tree cannot be verified)."""
        return git_tree_hash_for(target_dir)

    def query(self, action_key: str, cwd: Path | str | None = None) -> CacheHitResult:
        """
        Query action cache by action_key and validate proof (§7.4).

        `cwd` is the directory a git_tree_hash proof should be re-checked
        against. Before this parameter existed, validate_proof() always fell
        back to `self.home` (the BRAIN home) regardless of what directory the
        entry's git_tree_hash was actually computed against — so any caller
        proving a target outside the brain home (e.g. `action-cache search
        --path <repo>`, Phase R5) could never validate its own proof and
        every query was a silent, permanent miss. Callers using a
        git_tree_hash proof MUST pass the same directory used to compute it.
        """
        t0 = time.perf_counter()
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM action_cache WHERE action_key = ?", (action_key,)
        ).fetchone()

        if not row:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return CacheHitResult(hit=False, reason="key_not_found", latency_ms=latency_ms)

        proof_data = json.loads(row["proof_json"])
        proof = ActionProof.from_dict(proof_data)

        # Validate proof
        if not self.validate_proof(proof, cwd=cwd):
            # Proof failed -> invalidate entry
            self.invalidate_by_key(action_key)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return CacheHitResult(
                hit=False, reason="proof_validation_failed", latency_ms=latency_ms
            )

        # Replay content
        try:
            raw_bytes = artifacts.expand(self.home, row["output_ref"])
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            self.invalidate_by_key(action_key)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return CacheHitResult(
                hit=False, reason=f"artifact_missing_{exc}", latency_ms=latency_ms
            )

        # Update hit count & last accessed
        now = _now()
        new_hit_count = row["hit_count"] + 1
        conn.execute(
            """
            UPDATE action_cache
            SET hit_count = ?, last_accessed_at = ?
            WHERE action_key = ?
            """,
            (new_hit_count, now, action_key),
        )
        conn.commit()

        entry = ActionCacheEntry(
            action_key=row["action_key"],
            action_type=ActionType(row["action_type"]),
            target=row["target"],
            proof=proof,
            output_ref=row["output_ref"],
            output_summary=row["output_summary"],
            tokens_saved_estimate=row["tokens_saved_estimate"],
            created_at=row["created_at"],
            last_accessed_at=now,
            hit_count=new_hit_count,
        )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return CacheHitResult(
            hit=True,
            entry=entry,
            content=content,
            latency_ms=latency_ms,
            reason="hit",
        )

    def get_or_execute(
        self,
        action_type: ActionType | str,
        target: str,
        compute_fn: Callable[[], str],
        params: dict[str, Any] | None = None,
        proof: ActionProof | None = None,
        output_summary: str = "",
        ttl_seconds: int | None = None,
        cwd: Path | str | None = None,
    ) -> tuple[str, bool, float]:
        """
        Execute or retrieve from cache.
        Returns (content, was_hit, latency_ms).

        `cwd`: directory a git_tree_hash proof should be re-validated
        against (see query()'s docstring). Required whenever `proof` sets
        git_tree_hash to anything outside `self.home`.
        """
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
        act_proof = proof or ActionProof()
        # Must match store_action's key computation exactly (same six
        # semantic-dependency fields), or a get_or_execute() lookup can never
        # find what store_action() saved. Bug found via manual smoke test of
        # Phase R5 `action-cache search`: this call omitted git_tree_hash and
        # verification_predicate, so any proof using either (e.g. the
        # git_tree_hash-gated CODE_SEARCH proof) was a permanent miss.
        action_key = compute_action_key(
            action_type=act,
            target=target,
            params=params,
            input_hashes=act_proof.input_hashes,
            git_tree_hash=act_proof.git_tree_hash,
            env_fingerprint=act_proof.env_fingerprint,
            verification_predicate=act_proof.verification_predicate,
        )

        hit_res = self.query(action_key, cwd=cwd)
        if hit_res.hit and hit_res.content is not None:
            return hit_res.content, True, hit_res.latency_ms

        # Cache miss: compute and store
        t0 = time.perf_counter()
        computed_content = compute_fn()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.store_action(
            action_type=act,
            target=target,
            content=computed_content,
            output_summary=output_summary,
            proof=act_proof,
            params=params,
            ttl_seconds=ttl_seconds,
        )
        return computed_content, False, latency_ms

    def invalidate_by_key(self, action_key: str) -> None:
        """Invalidate single entry by action_key."""
        conn = self._get_conn()
        conn.execute("DELETE FROM action_cache WHERE action_key = ?", (action_key,))
        conn.commit()

    def invalidate_by_path(self, path: Path | str) -> int:
        """
        Invalidate all cache entries whose proof depends on `path` (§7.5).

        The `target`-match branch uses the existing `idx_action_target`
        index directly (an indexed `IN` lookup on both the literal string a
        caller passed to `store_action`/`get_or_execute` and its resolved
        form) instead of a full-table scan + per-row `Path.resolve()`.
        Every real `target` in this codebase (FILE_READ/DIR_SCAN/
        GENERIC_PURE) is a bare path string, never a composite key, so this
        covers the real matching cases without fabricating an index lookup
        that never fires. The `input_hashes` fallback stays a linear scan
        (narrower "index on target" scope; not tightened here).
        """
        resolved_str = str(Path(path).resolve())
        candidates = {str(path), resolved_str}
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in candidates)
        to_delete: set[str] = {
            r["action_key"]
            for r in conn.execute(
                f"SELECT action_key FROM action_cache WHERE target IN ({placeholders})",
                tuple(candidates),
            ).fetchall()
        }

        for r in conn.execute("SELECT action_key, proof_json FROM action_cache").fetchall():
            proof_dict = json.loads(r["proof_json"])
            input_hashes = proof_dict.get("input_hashes", {})
            for p in input_hashes:
                if str(Path(p).resolve()) == resolved_str:
                    to_delete.add(r["action_key"])
                    break

        for key in to_delete:
            conn.execute("DELETE FROM action_cache WHERE action_key = ?", (key,))
        conn.commit()
        return len(to_delete)

    def get_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        conn = self._get_conn()
        total_entries = conn.execute("SELECT COUNT(*) as c FROM action_cache").fetchone()["c"]
        total_hits = (
            conn.execute("SELECT SUM(hit_count) as h FROM action_cache").fetchone()["h"] or 0
        )
        tokens_saved = (
            conn.execute(
                "SELECT SUM(hit_count * tokens_saved_estimate) as t FROM action_cache"
            ).fetchone()["t"]
            or 0
        )

        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "tokens_saved_estimate": tokens_saved,
        }

    def prune_expired(self) -> int:
        """Prune entries whose expires_at is past the current time."""
        now = _now()
        conn = self._get_conn()
        res = conn.execute(
            "DELETE FROM action_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        conn.commit()
        return res.rowcount

    def clear(self) -> None:
        """Clear all entries."""
        conn = self._get_conn()
        conn.execute("DELETE FROM action_cache")
        conn.commit()

    put = store_action


ActionCache = ActionCacheStore
