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

import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__, artifacts, db, telemetry
from .contracts import estimate_tokens
from .errors import BrainError

ACTION_CACHE_SCHEMA_VERSION = 2
DEFAULT_CACHE_MAX_ENTRIES = 5000
RUNTIME_VERSION_ENV_KEY = "second_brain.runtime_version"
DISTILLER_VERSION = "artifacts-v1"

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


class DependencyClass(StrEnum):
    FILE_SET = "FILE_SET"
    WORKTREE = "WORKTREE"
    ENV = "ENV"
    TIME = "TIME"
    PURE_CONSTANT = "PURE_CONSTANT"


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
CREATE TABLE IF NOT EXISTS action_cache_economics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_key TEXT NOT NULL,
    dependency_class TEXT,
    outcome TEXT NOT NULL,
    validate_ms REAL NOT NULL,
    files_hashed INTEGER NOT NULL,
    bytes_hashed INTEGER NOT NULL,
    tokens_saved_estimate INTEGER NOT NULL,
    compute_ms REAL,
    compute_ms_avoided REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_cache_economics_class
    ON action_cache_economics (dependency_class, created_at);
CREATE INDEX IF NOT EXISTS idx_action_cache_economics_key
    ON action_cache_economics (action_key, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file_content(path: Path | str) -> str:
    """Compute sha256 hash of a file's content."""
    p = Path(path)
    if not p.is_file():
        raise BrainError(f"Cannot hash non-existent file: {path}")
    return _hash_bytes(p.read_bytes())


@dataclass(frozen=True)
class WorktreeFingerprint:
    fingerprint: str
    repository_root: str
    scope: str
    files_hashed: int
    bytes_hashed: int


def _git(root: Path, *args: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _repository_root(target: Path) -> Path | None:
    locator = target.resolve()
    cwd = locator if locator.is_dir() else locator.parent
    raw_root = _git(cwd, "rev-parse", "--show-toplevel")
    if raw_root is None:
        return None
    try:
        root = Path(raw_root.decode("utf-8", errors="strict").strip()).resolve()
        locator.relative_to(root)
    except (OSError, UnicodeError, ValueError):
        return None
    return root


def _normalize_scope(root: Path, scope: Path | str) -> str:
    candidate = Path(scope)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise BrainError("Worktree scope must be a repository-relative path")
    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise BrainError("Worktree scope escapes the repository") from exc
    return relative.as_posix() or "."


def worktree_fingerprint_for(
    target: Path | str,
    scope: Path | str | None = None,
) -> WorktreeFingerprint | None:
    """Build the canonical scoped Git worktree fingerprint, failing closed."""
    target_path = Path(target).resolve()
    root = _repository_root(target_path)
    if root is None:
        return None
    if scope is None:
        try:
            relative_target = target_path.relative_to(root)
        except ValueError as exc:
            raise BrainError("Worktree target is outside its repository") from exc
        normalized_scope = relative_target.as_posix() or "."
    else:
        normalized_scope = _normalize_scope(root, scope)

    head_tree = _git(root, "rev-parse", "HEAD^{tree}")
    index_tree = _git(root, "write-tree")
    dirty = _git(
        root,
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
        normalized_scope,
    )
    untracked_raw = _git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        normalized_scope,
    )
    dirty_names = _git(
        root,
        "diff",
        "--name-only",
        "-z",
        "HEAD",
        "--",
        normalized_scope,
    )
    if (
        head_tree is None
        or index_tree is None
        or dirty is None
        or untracked_raw is None
        or dirty_names is None
    ):
        return None

    untracked: list[tuple[str, str]] = []
    files_hashed = len([name for name in dirty_names.split(b"\0") if name])
    bytes_hashed = len(dirty)
    for raw_relative in untracked_raw.split(b"\0"):
        if not raw_relative:
            continue
        try:
            relative = raw_relative.decode("utf-8", errors="strict").replace("\\", "/")
            relative_path = _normalize_scope(root, relative)
            path = (root / Path(relative_path)).resolve()
            data = path.read_bytes()
        except (BrainError, OSError, UnicodeError):
            return None
        untracked.append((relative_path, _hash_bytes(data)))
        files_hashed += 1
        bytes_hashed += len(data)

    packet = {
        "head_tree": head_tree.decode("ascii", errors="strict").strip(),
        "index_tree": index_tree.decode("ascii", errors="strict").strip(),
        "dirty": _hash_bytes(dirty),
        "untracked": sorted(untracked),
    }
    canonical = json.dumps(
        packet,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return WorktreeFingerprint(
        fingerprint=_hash_bytes(canonical),
        repository_root=str(root),
        scope=normalized_scope,
        files_hashed=files_hashed,
        bytes_hashed=bytes_hashed,
    )


def compute_action_key(
    action_type: ActionType | str,
    target: str,
    params: dict[str, Any] | None = None,
    input_hashes: dict[str, str] | None = None,
    git_tree_hash: str | None = None,
    env_fingerprint: dict[str, str] | None = None,
    verification_predicate: str = "input_hashes_match",
    dependency_class: DependencyClass | str | None = None,
    worktree_root: str | None = None,
    worktree_scope: str | None = None,
    worktree_fingerprint: str | None = None,
    constant_fingerprint: dict[str, str] | None = None,
) -> str:
    """Construct a deterministic key from every declared semantic dependency."""
    act_str = action_type.value if isinstance(action_type, ActionType) else str(action_type).upper()
    dep_str = (
        dependency_class.value
        if isinstance(dependency_class, DependencyClass)
        else dependency_class
    )
    packet = {
        "v": ACTION_CACHE_SCHEMA_VERSION,
        "action_type": act_str,
        "target": target,
        "params": params or {},
        "input_hashes": input_hashes or {},
        "git_tree_hash": git_tree_hash,
        "env_fingerprint": env_fingerprint or {},
        "verification_predicate": verification_predicate,
        "dependency_class": dep_str,
        "worktree_root": worktree_root,
        "worktree_scope": worktree_scope,
        "worktree_fingerprint": worktree_fingerprint,
        "constant_fingerprint": constant_fingerprint or {},
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
    dependency_class: DependencyClass | None = None
    worktree_root: str | None = None
    worktree_scope: str | None = None
    worktree_fingerprint: str | None = None
    constant_fingerprint: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_hashes": self.input_hashes,
            "git_tree_hash": self.git_tree_hash,
            "env_fingerprint": self.env_fingerprint,
            "verification_predicate": self.verification_predicate,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
            "dependency_class": (
                self.dependency_class.value if self.dependency_class is not None else None
            ),
            "worktree_root": self.worktree_root,
            "worktree_scope": self.worktree_scope,
            "worktree_fingerprint": self.worktree_fingerprint,
            "constant_fingerprint": self.constant_fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionProof:
        raw_dependency_class = d.get("dependency_class")
        try:
            dependency_class = (
                DependencyClass(raw_dependency_class)
                if raw_dependency_class is not None
                else None
            )
        except (TypeError, ValueError):
            dependency_class = None
        return cls(
            input_hashes=d.get("input_hashes", {}),
            git_tree_hash=d.get("git_tree_hash"),
            env_fingerprint=d.get("env_fingerprint", {}),
            verification_predicate=d.get("verification_predicate", "input_hashes_match"),
            expires_at=d.get("expires_at"),
            ttl_seconds=d.get("ttl_seconds"),
            dependency_class=dependency_class,
            worktree_root=d.get("worktree_root"),
            worktree_scope=d.get("worktree_scope"),
            worktree_fingerprint=d.get("worktree_fingerprint"),
            constant_fingerprint=d.get("constant_fingerprint", {}),
        )


def _declared_dependency_is_complete(proof: ActionProof) -> bool:
    dep = proof.dependency_class
    if dep is DependencyClass.FILE_SET:
        return bool(proof.input_hashes) and all(
            isinstance(path, str)
            and bool(path)
            and isinstance(digest, str)
            and bool(digest)
            for path, digest in proof.input_hashes.items()
        )
    if dep is DependencyClass.WORKTREE:
        return all(
            isinstance(value, str) and bool(value)
            for value in (
                proof.worktree_root,
                proof.worktree_scope,
                proof.worktree_fingerprint,
            )
        )
    if dep is DependencyClass.ENV:
        return bool(proof.env_fingerprint)
    if dep is DependencyClass.TIME:
        return proof.expires_at is not None or proof.ttl_seconds is not None
    if dep is DependencyClass.PURE_CONSTANT:
        return bool(proof.constant_fingerprint) and all(
            isinstance(key, str)
            and bool(key)
            and isinstance(value, str)
            and bool(value)
            for key, value in proof.constant_fingerprint.items()
        )
    return False


def proof_is_complete(action_type: ActionType | str, proof: ActionProof) -> bool:
    """Apply the fail-closed action-type dependency table."""
    try:
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
    except ValueError:
        return False
    if not _declared_dependency_is_complete(proof):
        return False
    if act is ActionType.FILE_READ:
        return proof.dependency_class is DependencyClass.FILE_SET
    if act is ActionType.CODE_SEARCH:
        return proof.dependency_class in {
            DependencyClass.FILE_SET,
            DependencyClass.WORKTREE,
        }
    if act is ActionType.DIR_SCAN:
        return proof.dependency_class is DependencyClass.WORKTREE
    if act is ActionType.PURE_VERIFICATION:
        if proof.env_fingerprint.get(RUNTIME_VERSION_ENV_KEY) != __version__:
            return False
        return (
            proof.dependency_class is not DependencyClass.ENV
            or any(key != RUNTIME_VERSION_ENV_KEY for key in proof.env_fingerprint)
        )
    if act is ActionType.DISTILLATION:
        source_sha = proof.constant_fingerprint.get("source_artifact_sha", "")
        return (
            proof.dependency_class is DependencyClass.PURE_CONSTANT
            and len(source_sha) == 64
            and all(char in "0123456789abcdef" for char in source_sha.lower())
            and proof.constant_fingerprint.get("distiller_version") == DISTILLER_VERSION
        )
    if act is ActionType.GENERIC_PURE:
        return proof.dependency_class is DependencyClass.PURE_CONSTANT
    return False

def _prepared_proof(
    action_type: ActionType,
    proof: ActionProof | None,
    ttl_seconds: int | None = None,
) -> ActionProof:
    prepared = ActionProof.from_dict((proof or ActionProof()).to_dict())
    if action_type is ActionType.PURE_VERIFICATION:
        prepared.env_fingerprint.setdefault(RUNTIME_VERSION_ENV_KEY, __version__)
    if action_type is ActionType.DISTILLATION:
        prepared.constant_fingerprint.setdefault("distiller_version", DISTILLER_VERSION)
    if ttl_seconds is not None:
        prepared.ttl_seconds = ttl_seconds
        prepared.expires_at = (
            datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        ).isoformat()
    return prepared


def _action_key_for(
    action_type: ActionType,
    target: str,
    params: dict[str, Any] | None,
    proof: ActionProof,
) -> str:
    return compute_action_key(
        action_type=action_type,
        target=target,
        params=params,
        input_hashes=proof.input_hashes,
        git_tree_hash=proof.git_tree_hash,
        env_fingerprint=proof.env_fingerprint,
        verification_predicate=proof.verification_predicate,
        dependency_class=proof.dependency_class,
        worktree_root=proof.worktree_root,
        worktree_scope=proof.worktree_scope,
        worktree_fingerprint=proof.worktree_fingerprint,
        constant_fingerprint=proof.constant_fingerprint,
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
    validate_ms: float = 0.0
    files_hashed: int = 0
    bytes_hashed: int = 0


@dataclass(frozen=True)
class _ProofValidation:
    valid: bool
    validate_ms: float
    files_hashed: int
    bytes_hashed: int
    worktree: WorktreeFingerprint | None = None


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
        """Store a deterministic output only when its proof is complete."""
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
        act_proof = _prepared_proof(act, proof, ttl_seconds)
        if not proof_is_complete(act, act_proof):
            raise BrainError(f"Incomplete action-cache proof for {act.value}")

        # Store content in backing artifact store
        stored_artifact = artifacts.store_text(
            self.home, content, kind=act.value.lower(), tool="action_cache"
        )
        output_ref = stored_artifact["hash"]

        if tokens_saved_estimate is None:
            tokens_saved_estimate = estimate_tokens(content, home=self.home)

        action_key = _action_key_for(act, target, params, act_proof)
        artifacts.add_ref(self.home, output_ref, owner=f"action_cache:{action_key}")

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
                evicted = conn.execute(
                    "SELECT action_key, output_ref FROM action_cache "
                    "ORDER BY last_accessed_at ASC LIMIT ?",
                    (excess,),
                ).fetchall()
                conn.execute(
                    "DELETE FROM action_cache WHERE action_key IN "
                    "(SELECT action_key FROM action_cache ORDER BY last_accessed_at ASC LIMIT ?)",
                    (excess,),
                )
                for row in evicted:
                    artifacts.remove_ref(
                        self.home, row["output_ref"], owner=f"action_cache:{row['action_key']}"
                    )
        conn.commit()

        return entry

    def _validate_proof(
        self,
        proof: ActionProof,
        action_type: ActionType | None = None,
        worktree_snapshot: WorktreeFingerprint | None = None,
    ) -> _ProofValidation:
        started = time.perf_counter()
        files_hashed = 0
        bytes_hashed = 0

        def result(valid: bool, snapshot: WorktreeFingerprint | None = None) -> _ProofValidation:
            return _ProofValidation(
                valid=valid,
                validate_ms=(time.perf_counter() - started) * 1000.0,
                files_hashed=files_hashed,
                bytes_hashed=bytes_hashed,
                worktree=snapshot,
            )

        if action_type is not None:
            if not proof_is_complete(action_type, proof):
                return result(False)
        elif not _declared_dependency_is_complete(proof):
            return result(False)

        if proof.expires_at:
            try:
                if datetime.now(UTC) > datetime.fromisoformat(proof.expires_at):
                    return result(False)
            except (TypeError, ValueError):
                return result(False)

        for file_path, expected_hash in proof.input_hashes.items():
            try:
                data = Path(file_path).read_bytes()
            except OSError:
                return result(False)
            files_hashed += 1
            bytes_hashed += len(data)
            if _hash_bytes(data) != expected_hash:
                return result(False)

        for env_key, expected_val in proof.env_fingerprint.items():
            actual = __version__ if env_key == RUNTIME_VERSION_ENV_KEY else os.environ.get(env_key)
            if actual != expected_val:
                return result(False)

        if proof.git_tree_hash is not None:
            return result(False)

        if proof.dependency_class is DependencyClass.WORKTREE:
            snapshot = worktree_snapshot
            if (
                snapshot is None
                or snapshot.repository_root != proof.worktree_root
                or snapshot.scope != proof.worktree_scope
            ):
                try:
                    snapshot = worktree_fingerprint_for(
                        proof.worktree_root or "",
                        proof.worktree_scope or "",
                    )
                except BrainError:
                    snapshot = None
            if snapshot is None:
                return result(False)
            files_hashed += snapshot.files_hashed
            bytes_hashed += snapshot.bytes_hashed
            if snapshot.fingerprint != proof.worktree_fingerprint:
                return result(False, snapshot)
            worktree_snapshot = snapshot

        if action_type is ActionType.DISTILLATION:
            source_sha = proof.constant_fingerprint["source_artifact_sha"]
            try:
                source = artifacts.expand(self.home, source_sha)
            except BrainError:
                return result(False, worktree_snapshot)
            files_hashed += 1
            bytes_hashed += len(source)
            if _hash_bytes(source) != source_sha:
                return result(False, worktree_snapshot)

        if proof.verification_predicate not in KNOWN_VERIFICATION_PREDICATES:
            return result(False, worktree_snapshot)
        return result(True, worktree_snapshot)

    def validate_proof(
        self,
        proof: ActionProof,
        cwd: Path | str | None = None,
        action_type: ActionType | str | None = None,
    ) -> bool:
        """Validate a declared proof. ``cwd`` remains accepted for old callers."""
        del cwd
        act = None
        if action_type is not None:
            try:
                act = (
                    action_type
                    if isinstance(action_type, ActionType)
                    else ActionType(str(action_type).upper())
                )
            except ValueError:
                return False
        return self._validate_proof(proof, act).valid

    def _record_economics(
        self,
        *,
        action_key: str,
        dependency_class: DependencyClass | None,
        outcome: str,
        validate_ms: float,
        files_hashed: int,
        bytes_hashed: int,
        tokens_saved_estimate: int = 0,
        compute_ms: float | None = None,
        compute_ms_avoided: float | None = None,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO action_cache_economics (
                action_key, dependency_class, outcome, validate_ms,
                files_hashed, bytes_hashed, tokens_saved_estimate,
                compute_ms, compute_ms_avoided, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_key,
                dependency_class.value if dependency_class is not None else None,
                outcome,
                max(validate_ms, 0.0),
                max(files_hashed, 0),
                max(bytes_hashed, 0),
                max(tokens_saved_estimate, 0),
                compute_ms,
                compute_ms_avoided,
                _now(),
            ),
        )
        conn.commit()

    def _last_compute_ms(self, action_key: str) -> float | None:
        row = self._get_conn().execute(
            """
            SELECT compute_ms
            FROM action_cache_economics
            WHERE action_key = ? AND compute_ms IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (action_key,),
        ).fetchone()
        return float(row["compute_ms"]) if row is not None else None

    def _emit_inputs_changed(self, action_type: ActionType, proof: ActionProof) -> None:
        with contextlib.suppress(OSError, ValueError):
            telemetry.append_record(
                self.home,
                "action-cache",
                "cache_store_skipped_inputs_changed",
                {
                    "action_type": action_type.value,
                    "dependency_class": (
                        proof.dependency_class.value
                        if proof.dependency_class is not None
                        else ""
                    ),
                },
            )

    def query(
        self,
        action_key: str,
        cwd: Path | str | None = None,
        *,
        _record_lookup: bool = True,
        _expected_proof: ActionProof | None = None,
        _prevalidated: _ProofValidation | None = None,
    ) -> CacheHitResult:
        """Query by key, fail closed on incomplete or stale proofs, and replay."""
        del cwd
        started = time.perf_counter()
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM action_cache WHERE action_key = ?", (action_key,)
        ).fetchone()
        if row is None:
            latency_ms = (time.perf_counter() - started) * 1000.0
            if _record_lookup:
                self._record_economics(
                    action_key=action_key,
                    dependency_class=None,
                    outcome="key_not_found",
                    validate_ms=0.0,
                    files_hashed=0,
                    bytes_hashed=0,
                )
            return CacheHitResult(
                hit=False,
                reason="key_not_found",
                latency_ms=latency_ms,
            )

        try:
            action_type = ActionType(row["action_type"])
            proof = ActionProof.from_dict(json.loads(row["proof_json"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.invalidate_by_key(action_key)
            return CacheHitResult(
                hit=False,
                reason="proof_validation_failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        if (
            _prevalidated is not None
            and _expected_proof is not None
            and proof.to_dict() == _expected_proof.to_dict()
        ):
            validation = _prevalidated
        else:
            validation = self._validate_proof(proof, action_type)

        if not validation.valid:
            self.invalidate_by_key(action_key)
            if _record_lookup:
                self._record_economics(
                    action_key=action_key,
                    dependency_class=proof.dependency_class,
                    outcome="proof_invalid",
                    validate_ms=validation.validate_ms,
                    files_hashed=validation.files_hashed,
                    bytes_hashed=validation.bytes_hashed,
                )
            return CacheHitResult(
                hit=False,
                reason="proof_validation_failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                validate_ms=validation.validate_ms,
                files_hashed=validation.files_hashed,
                bytes_hashed=validation.bytes_hashed,
            )

        try:
            raw_bytes = artifacts.expand(self.home, row["output_ref"])
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            self.invalidate_by_key(action_key)
            if _record_lookup:
                self._record_economics(
                    action_key=action_key,
                    dependency_class=proof.dependency_class,
                    outcome="artifact_missing",
                    validate_ms=validation.validate_ms,
                    files_hashed=validation.files_hashed,
                    bytes_hashed=validation.bytes_hashed,
                )
            return CacheHitResult(
                hit=False,
                reason=f"artifact_missing_{exc}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                validate_ms=validation.validate_ms,
                files_hashed=validation.files_hashed,
                bytes_hashed=validation.bytes_hashed,
            )

        now = _now()
        new_hit_count = row["hit_count"] + 1
        conn.execute(
            "UPDATE action_cache SET hit_count = ?, last_accessed_at = ? WHERE action_key = ?",
            (new_hit_count, now, action_key),
        )
        conn.commit()
        entry = ActionCacheEntry(
            action_key=row["action_key"],
            action_type=action_type,
            target=row["target"],
            proof=proof,
            output_ref=row["output_ref"],
            output_summary=row["output_summary"],
            tokens_saved_estimate=row["tokens_saved_estimate"],
            created_at=row["created_at"],
            last_accessed_at=now,
            hit_count=new_hit_count,
        )
        if _record_lookup:
            self._record_economics(
                action_key=action_key,
                dependency_class=proof.dependency_class,
                outcome="hit",
                validate_ms=validation.validate_ms,
                files_hashed=validation.files_hashed,
                bytes_hashed=validation.bytes_hashed,
                tokens_saved_estimate=entry.tokens_saved_estimate,
                compute_ms_avoided=self._last_compute_ms(action_key),
            )
        return CacheHitResult(
            hit=True,
            entry=entry,
            content=content,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            reason="hit",
            validate_ms=validation.validate_ms,
            files_hashed=validation.files_hashed,
            bytes_hashed=validation.bytes_hashed,
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
        """Replay a complete valid proof, otherwise execute; verify again before store."""
        del cwd
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
        act_proof = _prepared_proof(act, proof, ttl_seconds)
        provisional_key = _action_key_for(act, target, params, act_proof)

        if not proof_is_complete(act, act_proof):
            started = time.perf_counter()
            content = compute_fn()
            compute_ms = (time.perf_counter() - started) * 1000.0
            self._record_economics(
                action_key=provisional_key,
                dependency_class=act_proof.dependency_class,
                outcome="incomplete",
                validate_ms=0.0,
                files_hashed=0,
                bytes_hashed=0,
                compute_ms=compute_ms,
            )
            return content, False, compute_ms

        before_snapshot = None
        if act_proof.dependency_class is DependencyClass.WORKTREE:
            try:
                before_snapshot = worktree_fingerprint_for(
                    act_proof.worktree_root or "",
                    act_proof.worktree_scope or "",
                )
            except BrainError:
                before_snapshot = None
            if before_snapshot is None:
                started = time.perf_counter()
                content = compute_fn()
                compute_ms = (time.perf_counter() - started) * 1000.0
                self._record_economics(
                    action_key=provisional_key,
                    dependency_class=act_proof.dependency_class,
                    outcome="fingerprint_unavailable",
                    validate_ms=0.0,
                    files_hashed=0,
                    bytes_hashed=0,
                    compute_ms=compute_ms,
                )
                return content, False, compute_ms
            act_proof.worktree_root = before_snapshot.repository_root
            act_proof.worktree_scope = before_snapshot.scope
            act_proof.worktree_fingerprint = before_snapshot.fingerprint

        action_key = _action_key_for(act, target, params, act_proof)
        before = self._validate_proof(act_proof, act, before_snapshot)
        if not before.valid:
            started = time.perf_counter()
            content = compute_fn()
            compute_ms = (time.perf_counter() - started) * 1000.0
            self._record_economics(
                action_key=action_key,
                dependency_class=act_proof.dependency_class,
                outcome="proof_invalid",
                validate_ms=before.validate_ms,
                files_hashed=before.files_hashed,
                bytes_hashed=before.bytes_hashed,
                compute_ms=compute_ms,
            )
            return content, False, compute_ms

        hit = self.query(
            action_key,
            _record_lookup=False,
            _expected_proof=act_proof,
            _prevalidated=before,
        )
        if hit.hit and hit.content is not None and hit.entry is not None:
            self._record_economics(
                action_key=action_key,
                dependency_class=act_proof.dependency_class,
                outcome="hit",
                validate_ms=before.validate_ms,
                files_hashed=before.files_hashed,
                bytes_hashed=before.bytes_hashed,
                tokens_saved_estimate=hit.entry.tokens_saved_estimate,
                compute_ms_avoided=self._last_compute_ms(action_key),
            )
            return hit.content, True, hit.latency_ms

        started = time.perf_counter()
        computed_content = compute_fn()
        compute_ms = (time.perf_counter() - started) * 1000.0
        after = self._validate_proof(act_proof, act)
        validate_ms = before.validate_ms + after.validate_ms
        files_hashed = before.files_hashed + after.files_hashed
        bytes_hashed = before.bytes_hashed + after.bytes_hashed
        if not after.valid:
            self._emit_inputs_changed(act, act_proof)
            self._record_economics(
                action_key=action_key,
                dependency_class=act_proof.dependency_class,
                outcome="inputs_changed",
                validate_ms=validate_ms,
                files_hashed=files_hashed,
                bytes_hashed=bytes_hashed,
                compute_ms=compute_ms,
            )
            return computed_content, False, compute_ms

        self.store_action(
            action_type=act,
            target=target,
            content=computed_content,
            output_summary=output_summary,
            proof=act_proof,
            params=params,
            ttl_seconds=ttl_seconds,
        )
        self._record_economics(
            action_key=action_key,
            dependency_class=act_proof.dependency_class,
            outcome="miss",
            validate_ms=validate_ms,
            files_hashed=files_hashed,
            bytes_hashed=bytes_hashed,
            compute_ms=compute_ms,
        )
        return computed_content, False, compute_ms

    def invalidate_by_key(self, action_key: str) -> None:
        """Invalidate single entry by action_key."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT output_ref FROM action_cache WHERE action_key = ?", (action_key,)
        ).fetchone()
        conn.execute("DELETE FROM action_cache WHERE action_key = ?", (action_key,))
        conn.commit()
        if row is not None:
            artifacts.remove_ref(self.home, row["output_ref"], owner=f"action_cache:{action_key}")

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
        to_delete: dict[str, str] = {
            r["action_key"]: r["output_ref"]
            for r in conn.execute(
                f"SELECT action_key, output_ref FROM action_cache WHERE target IN ({placeholders})",
                tuple(candidates),
            ).fetchall()
        }

        for r in conn.execute(
            "SELECT action_key, output_ref, proof_json FROM action_cache"
        ).fetchall():
            proof_dict = json.loads(r["proof_json"])
            input_hashes = proof_dict.get("input_hashes", {})
            for p in input_hashes:
                if str(Path(p).resolve()) == resolved_str:
                    to_delete[r["action_key"]] = r["output_ref"]
                    break

        for key in to_delete:
            conn.execute("DELETE FROM action_cache WHERE action_key = ?", (key,))
        conn.commit()
        for key, output_ref in to_delete.items():
            artifacts.remove_ref(self.home, output_ref, owner=f"action_cache:{key}")
        return len(to_delete)

    def get_stats(self) -> dict[str, Any]:
        """Return legacy totals plus per-dependency-class lookup economics."""
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
        rows = conn.execute(
            """
            SELECT dependency_class, outcome, validate_ms, files_hashed,
                   bytes_hashed, tokens_saved_estimate, compute_ms,
                   compute_ms_avoided
            FROM action_cache_economics
            """
        ).fetchall()
        by_class: dict[str, dict[str, Any]] = {}
        for dependency_class in DependencyClass:
            class_rows = [
                row for row in rows if row["dependency_class"] == dependency_class.value
            ]
            hits = [row for row in class_rows if row["outcome"] == "hit"]
            compute_rows = [row for row in class_rows if row["compute_ms"] is not None]
            comparable = [
                row for row in hits if row["compute_ms_avoided"] is not None
            ]

            def average(items: list[sqlite3.Row], field_name: str) -> float | None:
                if not items:
                    return None
                return sum(float(item[field_name]) for item in items) / len(items)

            avg_validate = average(class_rows, "validate_ms")
            avg_hit_validate = average(comparable, "validate_ms")
            avg_avoided = average(comparable, "compute_ms_avoided")
            status = (
                "RETIRE_CANDIDATE"
                if comparable
                and avg_hit_validate is not None
                and avg_avoided is not None
                and avg_hit_validate > avg_avoided
                else ("ACTIVE" if class_rows else "NO_DATA")
            )
            by_class[dependency_class.value] = {
                "lookups": len(class_rows),
                "hits": len(hits),
                "misses": len(class_rows) - len(hits),
                "comparable_samples": len(comparable),
                "avg_validate_ms": avg_validate,
                "avg_hit_validate_ms": avg_hit_validate,
                "avg_compute_ms_avoided": avg_avoided,
                "avg_miss_compute_ms": average(compute_rows, "compute_ms"),
                "files_hashed": sum(int(row["files_hashed"]) for row in class_rows),
                "bytes_hashed": sum(int(row["bytes_hashed"]) for row in class_rows),
                "tokens_saved_estimate": sum(
                    int(row["tokens_saved_estimate"]) for row in class_rows
                ),
                "status": status,
            }

        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "tokens_saved_estimate": tokens_saved,
            "economics_by_dependency_class": by_class,
        }

    def prune_expired(self) -> int:
        """Prune entries whose expires_at is past the current time."""
        now = _now()
        conn = self._get_conn()
        expired = conn.execute(
            "SELECT action_key, output_ref FROM action_cache "
            "WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        ).fetchall()
        res = conn.execute(
            "DELETE FROM action_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        conn.commit()
        for row in expired:
            artifacts.remove_ref(
                self.home, row["output_ref"], owner=f"action_cache:{row['action_key']}"
            )
        return res.rowcount

    def clear(self) -> None:
        """Clear all entries. Bulk-clears every action_cache-owned artifact
        ref in one statement (every owner under this store is being cleared
        at once, so a single bulk delete is correct and avoids an N-row
        round trip)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM action_cache")
        conn.commit()
        dbfile = db.db_path(self.home)
        if db.pending_migrations(dbfile):
            db.migrate(dbfile)
        refs_conn = db.connect(dbfile)
        try:
            refs_conn.execute("DELETE FROM artifact_refs WHERE owner LIKE 'action_cache:%'")
            refs_conn.commit()
        finally:
            refs_conn.close()

    def put(
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
        fingerprint_before: str | None = None,
    ) -> ActionCacheEntry | None:
        """Persist precomputed output only if its declared inputs are still current."""
        act = (
            action_type
            if isinstance(action_type, ActionType)
            else ActionType(str(action_type).upper())
        )
        prepared = _prepared_proof(act, proof, ttl_seconds)
        if not proof_is_complete(act, prepared):
            return None
        validation = self._validate_proof(prepared, act)
        worktree_changed = (
            prepared.dependency_class is DependencyClass.WORKTREE
            and (
                fingerprint_before is None
                or validation.worktree is None
                or validation.worktree.fingerprint != fingerprint_before
            )
        )
        if not validation.valid or worktree_changed:
            self._emit_inputs_changed(act, prepared)
            return None
        return self.store_action(
            action_type=act,
            target=target,
            content=content,
            output_summary=output_summary,
            proof=prepared,
            params=params,
            tokens_saved_estimate=tokens_saved_estimate,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
        )


ActionCache = ActionCacheStore
