"""Independent, read-only qualification verifier for Second Brain v2.

The canonical requirement set comes from the twelve phase gates in
``docs/superpowers/plans/2026-09-02-second-brain-v2-implementation.md``.
A manifest binds that fixed set to the current source, build, configuration,
host artifact, ledger rows, and byte-addressed evidence.  Neither a manifest
nor ledger rows may redefine the required set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from second_brain import __version__, build_identity, contracts, db  # noqa: E402

MANIFEST_SCHEMA_VERSION = 2
EVIDENCE_SCHEMA_VERSION = 1
RELEASE_SCOPE_SCHEMA_VERSION = 1
QUALIFICATION_AUTHORITY = "docs/superpowers/plans/2026-09-02-second-brain-v2-implementation.md"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PRODUCTION_EVIDENCE_CLASSIFICATIONS = frozenset({"observed"})
ALLOWED_EVIDENCE_TYPES = frozenset(
    {"test", "integration", "host", "economics", "recovery", "security", "verification"}
)
_FUNCTIONAL_TYPES = frozenset({"test", "integration", "verification"})
_INTEGRATION_TYPES = frozenset({"integration", "verification"})

_CANONICAL_EVIDENCE_PRODUCERS: dict[str, frozenset[str]] = {
    "test": frozenset({"scripts/verify_v1_p4_qualification.py"}),
    "integration": frozenset({"scripts/run_v1_p4_qualification.py"}),
    "host": frozenset({"scripts/run_v1_p4_qualification.py"}),
    "economics": frozenset(
        {"scripts/run_paired_economics.py", "scripts/run_retrieval_economics.py"}
    ),
    "recovery": frozenset({"scripts/run_v1_p4_qualification.py"}),
    "security": frozenset({"scripts/run_v1_p4_qualification.py"}),
    "verification": frozenset({"scripts/verify_v1_p4_qualification.py"}),
}
_NONPRODUCTION_CLASSIFICATIONS = frozenset(
    {"simulation", "simulated", "fixture", "mechanism", "mechanism-only", "synthetic"}
)
EXPECTED_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("v2-0", "baseline_identity_and_schema"),
    ("v2-a", "trusted_retrieval_freshness"),
    ("v2-b", "low_friction_io"),
    ("earned-memory", "earned_memory"),
    ("meta-memory", "meta_memory"),
    ("retrieval-2", "retrieval_2"),
    ("brainstem", "brainstem"),
    ("causal-learning", "causal_learning"),
    ("engrams-culture", "engrams_culture"),
    ("control-plane", "universal_control_plane"),
    ("frontier", "knowledge_frontier"),
    ("v2-i", "governed_self_improvement_proof"),
)
_EXPECTED_SET = frozenset(EXPECTED_REQUIREMENTS)

# Every identifier below is a clause in the corresponding authoritative
# ``**Gate:**`` paragraph.  Sensitive real-world clauses deliberately exclude
# unit-test evidence: an installed host, economics run, recovery exercise, or
# governed promotion must be observed at that boundary.
REQUIRED_GATE_COVERAGE: dict[tuple[str, str], dict[str, frozenset[str]]] = {
    EXPECTED_REQUIREMENTS[0]: {
        "baseline_identity_reproducible": _INTEGRATION_TYPES,
        "schema_reproducible": _INTEGRATION_TYPES,
        "single_table_and_migration_owner": frozenset({"verification"}),
    },
    EXPECTED_REQUIREMENTS[1]: {
        "beats_or_safely_abstains_against_baseline": _FUNCTIONAL_TYPES,
        "v1_safe_defaults_unchanged": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[2]: {
        "equivalent_cli_operations": _INTEGRATION_TYPES,
        "real_supported_harness_paths": frozenset({"host"}),
        "no_transcript_replay": frozenset({"host"}),
        "single_command_module": frozenset({"verification"}),
    },
    EXPECTED_REQUIREMENTS[3]: {
        "repeated_regressions_earn_candidate": _FUNCTIONAL_TYPES,
        "duplicate_facts_dedupe": _FUNCTIONAL_TYPES,
        "conflicting_facts_remain_distinct": _FUNCTIONAL_TYPES,
        "severe_scoped_facts_retained": _FUNCTIONAL_TYPES,
        "protected_authority_not_escalated": _FUNCTIONAL_TYPES,
        "off_writes_nothing": _FUNCTIONAL_TYPES,
        "shadow_creates_no_semantic_memory": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[4]: {
        "unused_retrieval_cannot_self_reinforce": _FUNCTIONAL_TYPES,
        "useful_evidence_can_strengthen": _FUNCTIONAL_TYPES,
        "verified_or_protected_not_silently_downgraded": _FUNCTIONAL_TYPES,
        "narrow_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "update_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "split_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "merge_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "supersede_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "demote_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "archive_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "leave_unresolved_preserves_evidence_and_lineage": _FUNCTIONAL_TYPES,
        "archived_discoverable_in_history_and_explanation": _FUNCTIONAL_TYPES,
        "archived_excluded_from_default_retrieval": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[5]: {
        "bounded_explanations_reproduce_selection": _FUNCTIONAL_TYPES,
        "stale_or_unsafe_candidates_fail_closed": _FUNCTIONAL_TYPES,
        "diverse_useful_results_fit_budget": _FUNCTIONAL_TYPES,
        "no_useful_result_yields_zero_injection": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[6]: {
        "deterministic_replay_matches": _FUNCTIONAL_TYPES,
        "budgets_never_exceed_limits": _FUNCTIONAL_TYPES,
        "unavailable_capability_or_quota_degrades_conservatively": _FUNCTIONAL_TYPES,
        "protected_context_order": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[7]: {
        "controlled_direct_case": _FUNCTIONAL_TYPES,
        "controlled_contributory_case": _FUNCTIONAL_TYPES,
        "controlled_correlated_case": _FUNCTIONAL_TYPES,
        "controlled_unrelated_negative_case": _FUNCTIONAL_TYPES,
        "correlated_alone_cannot_promote": _FUNCTIONAL_TYPES,
        "tampered_evidence_ineligible": _FUNCTIONAL_TYPES,
        "stale_evidence_ineligible": _FUNCTIONAL_TYPES,
        "predictable_outcomes_do_not_reflect": _FUNCTIONAL_TYPES,
        "observation_does_not_activate_change": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[8]: {
        "candidates_require_support_and_evidence": _FUNCTIONAL_TYPES,
        "incompatible_transfers_refuse": _FUNCTIONAL_TYPES,
        "profile_fields_measured_or_null": _FUNCTIONAL_TYPES,
        "routing_cannot_promote_engram": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[9]: {
        "rich_to_limited_preserves_decisions": frozenset({"host"}),
        "rich_to_limited_preserves_evidence": frozenset({"host"}),
        "rich_to_limited_preserves_unresolved_work": frozenset({"host"}),
        "limited_to_rich_preserves_decisions": frozenset({"host"}),
        "limited_to_rich_preserves_evidence": frozenset({"host"}),
        "limited_to_rich_preserves_unresolved_work": frozenset({"host"}),
        "false_capabilities_rejected": frozenset({"host"}),
        "unavailable_hosts_reported_unavailable": frozenset({"host"}),
        "no_mock_host_substitution": frozenset({"host"}),
        "adapter_owns_no_canonical_state": frozenset({"host"}),
    },
    EXPECTED_REQUIREMENTS[10]: {
        "stale_evidence_cannot_authorize_experiment": _FUNCTIONAL_TYPES,
        "stale_evidence_cannot_authorize_promotion": _FUNCTIONAL_TYPES,
        "deterministic_ties_stable": _FUNCTIONAL_TYPES,
        "risky_expensive_low_information_experiments_refused": _FUNCTIONAL_TYPES,
    },
    EXPECTED_REQUIREMENTS[11]: {
        "every_phase_has_current_evidence": frozenset({"verification"}),
        "governed_improvement_promotes_only_with_all_guards": frozenset({"integration"}),
        "failed_guard_refuses": frozenset({"integration"}),
        "failed_guard_rolls_back": frozenset({"integration"}),
        "representative_scale_and_performance": frozenset({"economics"}),
        "complete_event_count_burn_in": _INTEGRATION_TYPES,
        "recovery_check": frozenset({"recovery"}),
        "security_check": frozenset({"security"}),
        "economics_check": frozenset({"economics"}),
        "v2_tag_requires_complete_gate": frozenset({"verification"}),
    },
}


def check(name: str, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "details": details}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(value: object) -> str:
    return _sha256_bytes(contracts.canonical_json(value).encode("utf-8"))


def _run_git(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_head() -> str | None:
    result = _run_git("rev-parse", "HEAD")
    if result is None:
        return None
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and _GIT_SHA_RE.fullmatch(value) else None


def _source_commit_is_current(recorded: object, current: str | None) -> bool:
    if not isinstance(recorded, str) or not _GIT_SHA_RE.fullmatch(recorded) or current is None:
        return False
    recorded = recorded.lower()
    if recorded == current:
        return True
    ancestor = _run_git("merge-base", "--is-ancestor", recorded, current)
    if ancestor is None or ancestor.returncode != 0:
        return False
    unchanged = _run_git(
        "diff",
        "--quiet",
        f"{recorded}..{current}",
        "--",
        "src",
        "scripts",
        "tests",
        "pyproject.toml",
        "uv.lock",
        QUALIFICATION_AUTHORITY,
    )
    return unchanged is not None and unchanged.returncode == 0


def _source_tree_dirty() -> bool:
    result = _run_git(
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "src",
        "scripts",
        "tests",
        "pyproject.toml",
        "uv.lock",
        QUALIFICATION_AUTHORITY,
    )
    return result is None or result.returncode != 0 or bool(result.stdout)


def _source_tree_fingerprint() -> str | None:
    return build_identity.source_tree_fingerprint(REPO_ROOT)


def _config_fingerprint(home: Path) -> str | None:
    return build_identity.configuration_fingerprint(home)


def _current_build_identity() -> dict[str, Any]:
    return {
        "package_version": __version__,
        "verifier_sha256": _sha256_file(Path(__file__)),
        "adapter_build_fingerprint": build_identity.adapter_build_fingerprint(REPO_ROOT),
        "source_tree_sha256": _source_tree_fingerprint(),
    }


def _parse_timestamp(value: object) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str):
        return None, "missing timestamp"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, "malformed timestamp"
    if parsed.tzinfo is None:
        return None, "timestamp has no timezone"
    return parsed.astimezone(UTC), None


def _normalized_token(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[\s_-]+", "-", value.strip().casefold())


def _contains_nonproduction_marker(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    for field in ("classification", "evidence_classification", "mode", "kind"):
        if _normalized_token(value.get(field)) in _NONPRODUCTION_CLASSIFICATIONS:
            return True
    return any(
        value.get(flag) not in (False, None, 0, "")
        for flag in ("fixture", "simulation", "simulated", "mechanism", "synthetic")
    )


def _raw_observation_matches(raw: object, observed_data: dict[str, Any]) -> bool:
    candidate = raw.get("observed_data") if isinstance(raw, dict) else raw
    try:
        return contracts.canonical_json(candidate) == contracts.canonical_json(observed_data)
    except (TypeError, ValueError):
        return False


def _evidence_path(home: Path, ref: object) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    raw = Path(ref)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    root = home.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _validate_file_ref(
    home: Path, value: object, *, allowed_types: frozenset[str] | None = None
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["evidence reference is not an object"]
    ref = value.get("path")
    expected_hash = value.get("sha256")
    evidence_type = _normalized_token(value.get("type"))
    if allowed_types is not None and evidence_type not in allowed_types:
        errors.append(f"unsupported evidence type {value.get('type')!r}")
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        errors.append("evidence sha256 is missing or malformed")
    path = _evidence_path(home, ref)
    if path is None:
        errors.append(f"unresolvable evidence path {ref!r}")
    elif not path.is_file():
        errors.append(f"missing evidence artifact {ref!r}")
    elif isinstance(expected_hash, str) and _SHA256_RE.fullmatch(expected_hash):
        try:
            if _sha256_file(path) != expected_hash:
                errors.append(f"tampered evidence artifact {ref!r}")
        except OSError as exc:
            errors.append(f"unreadable evidence artifact {ref!r}: {exc}")
    return errors


def check_database_integrity(home: Path) -> dict[str, Any]:
    dbfile = db.db_path(home)
    if not dbfile.is_file():
        return check("database_integrity", False, {"reason": f"missing db {dbfile}"})
    try:
        conn = db.connect(dbfile, readonly=True)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            ok = row is not None and row[0] == "ok"
            return check("database_integrity", ok, {"integrity": row[0] if row else None})
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return check("database_integrity", False, {"error": str(exc)})


def check_schema_migrations(home: Path) -> dict[str, Any]:
    try:
        expected = {int(path.name[:4]) for path in db.migration_files()}
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            applied = {
                int(row[0]) for row in conn.execute("SELECT version FROM schema_version").fetchall()
            }
        finally:
            conn.close()
        pending = sorted(expected - applied)
        unexpected = sorted(applied - expected)
        current_version = max(applied, default=0)
        return check(
            "schema_migrations",
            not pending and not unexpected and current_version >= 21,
            {
                "current_version": current_version,
                "pending": pending,
                "unexpected": unexpected,
            },
        )
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        return check("schema_migrations", False, {"error": str(exc)})


def check_v2_tables_present(home: Path) -> dict[str, Any]:
    retained = {
        "v2_candidates",
        "v2_interventions",
        "v2_observations",
        "v2_frontier_items",
        "v2_rollout_events",
        "v2_qualification",
    }
    try:
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return check("v2_tables_present", False, {"error": str(exc)})
    missing = retained - tables
    return check(
        "v2_tables_present",
        not missing,
        {
            "retained_tables_present": sorted(retained - missing),
            "missing": sorted(missing),
        },
    )


def _load_manifest(manifest_path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    if manifest_path is None:
        return None, ["qualification manifest is required"]
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"manifest is unavailable: {exc}"]
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"manifest is malformed: {exc}"]
    if not isinstance(manifest, dict):
        return None, ["manifest root must be an object"]
    return manifest, []


def _authority_gate_hashes() -> tuple[dict[tuple[str, str], str], list[str]]:
    authority_path = REPO_ROOT / QUALIFICATION_AUTHORITY
    try:
        text = authority_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [f"canonical requirement authority is unavailable: {exc}"]
    gates = re.findall(r"(?m)^\*\*Gate:\*\* ([^\r\n]+)$", text)
    if len(gates) != len(EXPECTED_REQUIREMENTS):
        return {}, [
            "canonical requirement authority does not contain exactly "
            f"{len(EXPECTED_REQUIREMENTS)} phase gates"
        ]
    return {
        key: _sha256_bytes(gate.encode("utf-8"))
        for key, gate in zip(EXPECTED_REQUIREMENTS, gates, strict=True)
    }, []


def load_release_scope(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load a versioned release-scope overlay that retires scope-specific Gate clauses.

    The overlay never rewrites the canonical requirement authority: it names the Gate
    clauses that the authorized release scope does not require, and the verifier then
    adjudicates completeness against the remaining clauses only. Retired clauses are not
    treated as proven.
    """
    errors: list[str] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"release scope is unavailable: {exc}"]
    if not isinstance(value, dict):
        return None, ["release scope root must be an object"]
    if value.get("schema_version") != RELEASE_SCOPE_SCHEMA_VERSION:
        errors.append(
            f"release scope schema_version must be {RELEASE_SCOPE_SCHEMA_VERSION}, "
            f"got {value.get('schema_version')!r}"
        )
    for field in ("scope_id", "supersedes", "authority", "authorized_by", "change_record"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(f"release scope {field} must be a non-empty string")
    if value.get("authority") != QUALIFICATION_AUTHORITY:
        errors.append("release scope must retain the canonical requirement authority")
    retired = value.get("retired_gates")
    if not isinstance(retired, dict) or not retired:
        errors.append("release scope retired_gates must be a non-empty object")
    else:
        for key_text, gate_ids in retired.items():
            key = tuple(str(key_text).split("/", 1))
            if not (isinstance(key_text, str) and len(key) == 2 and key in _EXPECTED_SET):
                errors.append(f"release scope names unknown requirement {key_text!r}")
                continue
            if not (
                isinstance(gate_ids, list)
                and gate_ids
                and all(isinstance(item, str) and item for item in gate_ids)
            ):
                errors.append(
                    f"release scope {key_text!r} retired gates must be a non-empty list of strings"
                )
                continue
            known = set(REQUIRED_GATE_COVERAGE[key])  # type: ignore[index]
            unknown = sorted(set(gate_ids) - known)
            if unknown:
                errors.append(f"release scope {key_text!r} retires unknown Gate clauses {unknown}")
            if len(set(gate_ids)) != len(gate_ids):
                errors.append(f"release scope {key_text!r} retires a Gate clause twice")
            if not known - set(gate_ids):
                errors.append(f"release scope {key_text!r} cannot retire every Gate clause")
    return (value if not errors else None), errors


def _scoped_required(scope: dict[str, Any] | None, key: tuple[str, str]) -> frozenset[str]:
    """Return the Gate clauses the release scope still requires for one requirement."""
    required = set(REQUIRED_GATE_COVERAGE[key])  # type: ignore[index]
    if scope is not None:
        retired = scope.get("retired_gates")
        if isinstance(retired, dict):
            clauses = retired.get(f"{key[0]}/{key[1]}", [])
            if isinstance(clauses, list):
                required -= {item for item in clauses if isinstance(item, str)}
    return frozenset(required)


def _load_json_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "artifact root must be an object"
    return value, None


def _validate_evidence_artifact(
    home: Path,
    ref: object,
    *,
    key: tuple[str, str],
    source_commit: object,
    source_tree_sha256: object,
    config_sha256: object,
    gate_sha256: str | None,
    latest_observed_at: datetime | None,
) -> tuple[list[str], set[str], dict[str, Any] | None]:
    errors = _validate_file_ref(home, ref, allowed_types=ALLOWED_EVIDENCE_TYPES)
    if not isinstance(ref, dict):
        return errors, set(), None
    path = _evidence_path(home, ref.get("path"))
    if path is None or not path.is_file() or errors:
        return errors, set(), None
    artifact, artifact_error = _load_json_artifact(path)
    if artifact is None:
        return [*errors, f"evidence artifact is malformed: {artifact_error}"], set(), None

    if (
        type(artifact.get("schema_version")) is not int
        or artifact.get("schema_version") != EVIDENCE_SCHEMA_VERSION
    ):
        errors.append(f"unsupported evidence schema_version {artifact.get('schema_version')!r}")
    classification = _normalized_token(artifact.get("classification"))
    if classification not in PRODUCTION_EVIDENCE_CLASSIFICATIONS:
        errors.append(f"ineligible evidence classification {artifact.get('classification')!r}")
    if artifact.get("qualification_eligible") is not True:
        errors.append("artifact is not qualification eligible")
    if (artifact.get("phase"), artifact.get("requirement")) != key:
        errors.append("artifact names the wrong canonical requirement")
    if artifact.get("source_commit") != source_commit:
        errors.append("artifact source_commit is not current")
    if artifact.get("source_tree_sha256") != source_tree_sha256:
        errors.append("artifact source_tree_sha256 is not current")
    if artifact.get("config_sha256") != config_sha256:
        errors.append("artifact config_sha256 is not current")
    if gate_sha256 is None or artifact.get("gate_sha256") != gate_sha256:
        errors.append("artifact is not bound to the exact authoritative Gate text")

    feature = artifact.get("feature")
    if not isinstance(feature, str) or not feature:
        errors.append("artifact feature binding is missing")
    elif artifact.get("target_ref") != f"policy:{feature}":
        errors.append("artifact target_ref does not match its feature")

    evidence_type = _normalized_token(ref.get("type"))
    if _normalized_token(artifact.get("evidence_type")) != evidence_type:
        errors.append("artifact evidence_type contradicts its reference")

    coverage_raw = artifact.get("coverage")
    coverage: set[str] = set()
    if not isinstance(coverage_raw, list) or not coverage_raw:
        errors.append("artifact coverage must be a non-empty list")
    else:
        if not all(isinstance(item, str) and item for item in coverage_raw):
            errors.append("artifact coverage contains a malformed identifier")
        else:
            coverage = set(coverage_raw)
            if len(coverage) != len(coverage_raw):
                errors.append("artifact coverage contains duplicate identifiers")
            unknown = sorted(coverage - set(REQUIRED_GATE_COVERAGE[key]))
            if unknown:
                errors.append(f"artifact claims unknown Gate coverage: {unknown}")
            for coverage_id in sorted(coverage & set(REQUIRED_GATE_COVERAGE[key])):
                if evidence_type not in REQUIRED_GATE_COVERAGE[key][coverage_id]:
                    errors.append(
                        f"coverage {coverage_id!r} cannot be proven by "
                        f"{artifact.get('evidence_type')!r} evidence"
                    )

    observed_data = artifact.get("observed_data")
    if not isinstance(observed_data, dict) or not observed_data:
        errors.append("artifact observed_data must be a non-empty object")
    gate_observations = artifact.get("gate_observations")
    if not isinstance(gate_observations, dict) or set(gate_observations) != coverage:
        errors.append("artifact gate_observations is not keyed by its exact Gate coverage")
    else:
        for coverage_id, observation in gate_observations.items():
            if not isinstance(observation, dict) or not observation:
                errors.append(
                    f"artifact Gate observation for {coverage_id!r} must be a non-empty object"
                )
    if _contains_nonproduction_marker(artifact) or _contains_nonproduction_marker(observed_data):
        errors.append("artifact content identifies simulation/fixture/mechanism evidence")

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("artifact provenance must be an object")
    else:
        producer = provenance.get("producer")
        allowed_producers = _CANONICAL_EVIDENCE_PRODUCERS.get(evidence_type or "", frozenset())
        if producer not in allowed_producers:
            errors.append(
                f"artifact producer {producer!r} is not authoritative for "
                f"{artifact.get('evidence_type')!r} evidence"
            )
        producer_path: Path | None = None
        if isinstance(producer, str):
            raw_producer = Path(producer)
            if not raw_producer.is_absolute() and ".." not in raw_producer.parts:
                candidate = (REPO_ROOT / raw_producer).resolve()
                try:
                    candidate.relative_to(REPO_ROOT.resolve())
                except ValueError:
                    pass
                else:
                    producer_path = candidate
        if producer_path is None or not producer_path.is_file():
            errors.append("artifact producer source is unavailable")
        elif provenance.get("producer_sha256") != _sha256_file(producer_path):
            errors.append("artifact producer source hash is not current")
        if provenance.get("observed_data_sha256") != _canonical_hash(observed_data):
            errors.append("artifact provenance does not bind observed_data")

        raw_refs = provenance.get("raw_evidence_refs")
        raw_match = False
        if not isinstance(raw_refs, list) or not raw_refs:
            errors.append("artifact provenance has no raw evidence references")
        else:
            raw_paths = [
                raw_ref.get("path")
                for raw_ref in raw_refs
                if isinstance(raw_ref, dict) and isinstance(raw_ref.get("path"), str)
            ]
            if len(raw_paths) != len(set(raw_paths)):
                errors.append("artifact provenance contains duplicate raw evidence refs")
            for raw_ref in raw_refs:
                raw_errors = _validate_file_ref(home, raw_ref)
                errors.extend(f"raw provenance: {error}" for error in raw_errors)
                if not isinstance(raw_ref, dict) or _normalized_token(raw_ref.get("type")) != "raw":
                    errors.append("raw provenance reference has unsupported type")
                    continue
                if raw_ref.get("path") == ref.get("path"):
                    errors.append("artifact cannot cite itself as raw provenance")
                    continue
                raw_path = _evidence_path(home, raw_ref.get("path"))
                if raw_path is None or not raw_path.is_file() or raw_errors:
                    continue
                raw_record, raw_error = _load_json_artifact(raw_path)
                if raw_record is None:
                    errors.append(f"raw provenance is malformed: {raw_error}")
                    continue
                if _normalized_token(raw_record.get("classification")) != "observed":
                    errors.append("raw provenance is not classified as observed")
                    continue
                if _contains_nonproduction_marker(raw_record) or _contains_nonproduction_marker(
                    raw_record.get("observed_data")
                ):
                    errors.append("raw provenance identifies nonproduction evidence")
                    continue
                if _raw_observation_matches(raw_record, observed_data):
                    raw_match = True
            if not raw_match:
                errors.append("no raw provenance artifact contains the exact observed_data")

    observed_at, timestamp_error = _parse_timestamp(artifact.get("observed_at"))
    if timestamp_error:
        errors.append(f"artifact observation timestamp failure: {timestamp_error}")
    elif (
        latest_observed_at is not None
        and observed_at is not None
        and observed_at > latest_observed_at
    ):
        errors.append("artifact observation occurs after its qualification record")

    return errors, coverage, artifact


def _observation_binding(
    home: Path, ref: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT o.observed_json, o.prediction_error_json, o.provenance_hash, "
                "i.target_ref FROM v2_observations AS o "
                "JOIN v2_interventions AS i ON i.intervention_id = o.intervention_id"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    matches = []
    for row in rows:
        try:
            observed = json.loads(row["observed_json"])
            prediction_error = json.loads(row["prediction_error_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(observed, dict):
            continue
        evidence = observed.get("_evidence")
        if not isinstance(evidence, dict):
            continue
        raw_observation = dict(observed)
        raw_observation.pop("_evidence", None)
        raw_observation.pop("_credit_evidence", None)
        expected_provenance = _canonical_hash({"obs": observed, "pred_err": prediction_error})
        if (
            evidence.get("path") == ref.get("path")
            and evidence.get("sha256") == ref.get("sha256")
            and evidence.get("feature") == artifact.get("feature")
            and evidence.get("source_commit") == artifact.get("source_commit")
            and evidence.get("source_tree_sha256") == artifact.get("source_tree_sha256")
            and evidence.get("config_sha256") == artifact.get("config_sha256")
            and row["target_ref"] == artifact.get("target_ref")
            and contracts.canonical_json(raw_observation)
            == contracts.canonical_json(artifact.get("observed_data"))
            and row["provenance_hash"] == expected_provenance
        ):
            matches.append(evidence)
    if len(matches) != 1:
        return None
    return {
        "path": ref["path"],
        "sha256": ref["sha256"],
        "feature": artifact["feature"],
        "source_commit": artifact["source_commit"],
        "source_tree_sha256": artifact["source_tree_sha256"],
        "config_sha256": artifact["config_sha256"],
    }


def check_manifest(
    home: Path, manifest_path: Path | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    manifest, errors = _load_manifest(manifest_path)
    if manifest is None:
        return check("qualification_manifest", False, {"errors": errors}), None

    now = datetime.now(UTC)
    authority_path = REPO_ROOT / QUALIFICATION_AUTHORITY
    gate_hashes, gate_errors = _authority_gate_hashes()
    errors.extend(gate_errors)
    source_commit = _git_head()
    source_tree_sha256 = build_identity.source_tree_fingerprint(REPO_ROOT)
    expected_build = _current_build_identity()
    expected_config = build_identity.configuration_fingerprint(home)

    if (
        type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
    ):
        errors.append(f"unsupported manifest schema_version {manifest.get('schema_version')!r}")
    classification = _normalized_token(manifest.get("classification"))
    if classification not in PRODUCTION_EVIDENCE_CLASSIFICATIONS:
        errors.append(f"ineligible manifest classification {manifest.get('classification')!r}")
    if manifest.get("authority") != QUALIFICATION_AUTHORITY:
        errors.append("manifest names the wrong canonical requirement authority")
    authority_hash = manifest.get("authority_sha256")
    if not authority_path.is_file() or authority_hash != _sha256_file(authority_path):
        errors.append("canonical requirement authority hash is missing or wrong")
    if not _source_commit_is_current(manifest.get("source_commit"), source_commit):
        errors.append("manifest source_commit is not current for the executed source tree")
    if classification in PRODUCTION_EVIDENCE_CLASSIFICATIONS and _source_tree_dirty():
        errors.append("production qualification cannot use an uncommitted source tree")
    if source_tree_sha256 is None or manifest.get("source_tree_sha256") != source_tree_sha256:
        errors.append("manifest source_tree_sha256 does not match executed source tree")
    if manifest.get("build_identity") != expected_build:
        errors.append("manifest build_identity does not match the verifier build")
    if expected_config is None or manifest.get("config_sha256") != expected_config:
        errors.append("manifest config_sha256 does not match current configuration")
    generated_at, timestamp_error = _parse_timestamp(manifest.get("generated_at"))
    if timestamp_error:
        errors.append(f"manifest chronology failure: {timestamp_error}")
    elif generated_at is not None and generated_at > now:
        errors.append("manifest chronology failure: generated_at is in the future")

    requirements = manifest.get("requirements")
    seen: list[tuple[str, str]] = []
    bindings: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(requirements, list):
        errors.append("manifest requirements must be a list")
    else:
        for index, row in enumerate(requirements):
            if not isinstance(row, dict):
                errors.append(f"manifest requirement {index} is not an object")
                continue
            raw_key = (row.get("phase"), row.get("requirement"))
            if not all(isinstance(part, str) and part for part in raw_key):
                errors.append(f"manifest requirement {index} has invalid identity")
                continue
            key = (str(raw_key[0]), str(raw_key[1]))
            seen.append(key)
            if key in bindings:
                errors.append(f"ambiguous duplicate manifest requirement {key!r}")
            else:
                bindings[key] = row
            if row.get("required") is not True:
                errors.append(f"canonical requirement {key!r} is marked unsupported/not required")
            artifact_hash = row.get("artifact_hash")
            if not isinstance(artifact_hash, str) or not _SHA256_RE.fullmatch(artifact_hash):
                errors.append(f"manifest requirement {key!r} has invalid artifact_hash")
            if key in _EXPECTED_SET and row.get("gate_sha256") != gate_hashes.get(key):
                errors.append(f"manifest requirement {key!r} has wrong Gate text binding")
        missing = sorted(_EXPECTED_SET - set(seen))
        unknown = sorted(set(seen) - _EXPECTED_SET)
        if missing:
            errors.append(f"manifest is missing canonical requirements: {missing}")
        if unknown:
            errors.append(f"manifest contains unknown requirements: {unknown}")
        if len(seen) != len(EXPECTED_REQUIREMENTS):
            errors.append("manifest does not contain exactly one row per canonical requirement")

    host = manifest.get("host_identity")
    if not isinstance(host, dict):
        errors.append("manifest host_identity must be an object")
    else:
        if not isinstance(host.get("name"), str) or not host.get("name"):
            errors.append("host identity name is missing")
        if not isinstance(host.get("build_id"), str) or not host.get("build_id"):
            errors.append("host identity build_id is missing")
        host_ref = host.get("evidence")
        errors.extend(_validate_file_ref(home, host_ref, allowed_types=frozenset({"host"})))
        host_path = _evidence_path(
            home, host_ref.get("path") if isinstance(host_ref, dict) else None
        )
        if host_path is not None and host_path.is_file():
            host_record, host_error = _load_json_artifact(host_path)
            if host_record is None:
                errors.append(f"host identity evidence is malformed: {host_error}")
            else:
                expected_host = {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "classification": "observed",
                    "qualification_eligible": True,
                    "evidence_type": "host",
                    "name": host.get("name"),
                    "build_id": host.get("build_id"),
                    "source_commit": manifest.get("source_commit"),
                    "source_tree_sha256": source_tree_sha256,
                    "config_sha256": expected_config,
                }
                if any(host_record.get(field) != value for field, value in expected_host.items()):
                    errors.append("host evidence contradicts current source/build/config identity")
                host_at, host_timestamp_error = _parse_timestamp(host_record.get("observed_at"))
                if host_timestamp_error:
                    errors.append(f"host evidence chronology failure: {host_timestamp_error}")
                elif generated_at is not None and host_at is not None and host_at > generated_at:
                    errors.append("host evidence occurs after manifest generation")

    details = {
        "manifest_path": str(manifest_path.resolve()) if manifest_path else None,
        "manifest_sha256": (
            _sha256_file(manifest_path)
            if manifest_path is not None and manifest_path.is_file()
            else None
        ),
        "authority": QUALIFICATION_AUTHORITY,
        "canonical_requirement_count": len(EXPECTED_REQUIREMENTS),
        "errors": errors,
    }
    return check("qualification_manifest", not errors, details), manifest


def check_qualification_ledger(
    home: Path, manifest: dict[str, Any] | None, scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        conn = db.connect(db.db_path(home), readonly=True)
        try:
            rows = conn.execute(
                "SELECT qualification_id, phase, requirement, status, evidence_json, "
                "source_commit, artifact_hash, created_at FROM v2_qualification"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return check("qualification_ledger", False, {"errors": [str(exc)]})
    return validate_qualification_rows(home, manifest, [dict(row) for row in rows], scope)


def load_candidate_records(home: Path, records_path: Path) -> list[dict[str, Any]]:
    """Load complete rows from a contained JSON list, without touching the ledger."""
    root = home.resolve()
    raw = records_path
    if ".." in raw.parts:
        raise ValueError("records path must be contained in home")
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    path.relative_to(root)
    rows = json.loads(path.read_text(encoding="utf-8"))
    columns = {
        "qualification_id",
        "phase",
        "requirement",
        "status",
        "evidence_json",
        "source_commit",
        "artifact_hash",
        "created_at",
    }
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or set(row) != columns
        or any(not isinstance(value, str) or not value for value in row.values())
        for row in rows
    ):
        raise ValueError("records must be a JSON list of complete qualification rows")
    if len({row["qualification_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate qualification_id")
    return rows


def validate_qualification_rows(
    home: Path,
    manifest: dict[str, Any] | None,
    records: list[dict[str, Any]],
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate supplied rows using the same release requirements as the ledger."""
    errors: list[str] = []
    if manifest is None:
        return check(
            "qualification_ledger",
            False,
            {
                "records": [],
                "proven_count": 0,
                "validated_evidence_bindings": [],
                "errors": ["valid manifest required"],
            },
        )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    malformed_identities: list[object] = []
    for row in records:
        phase, requirement = row.get("phase"), row.get("requirement")
        if isinstance(phase, str) and isinstance(requirement, str):
            grouped.setdefault((phase, requirement), []).append(row)
        else:
            malformed_identities.append((phase, requirement))
    if malformed_identities:
        errors.append(f"malformed qualification identities: {malformed_identities!r}")
    missing = sorted(_EXPECTED_SET - set(grouped))
    unknown = sorted(set(grouped) - _EXPECTED_SET)
    if missing:
        errors.append(f"missing canonical qualification records: {missing}")
    if unknown:
        errors.append(f"unknown qualification records: {unknown}")

    requirements = manifest.get("requirements")
    manifest_rows = (
        {
            (row["phase"], row["requirement"]): row
            for row in requirements
            if isinstance(requirements, list)
            and isinstance(row, dict)
            and isinstance(row.get("phase"), str)
            and isinstance(row.get("requirement"), str)
        }
        if isinstance(requirements, list)
        else {}
    )
    source_commit = manifest.get("source_commit")
    source_tree_sha256 = manifest.get("source_tree_sha256")
    config_sha256 = manifest.get("config_sha256")
    manifest_at, _ = _parse_timestamp(manifest.get("generated_at"))
    gate_hashes, gate_errors = _authority_gate_hashes()
    errors.extend(gate_errors)
    proven_count = 0
    coverage_complete_count = 0
    scoped_gate_total = 0
    scoped_gate_covered = 0
    validated_bindings: list[dict[str, Any]] = []

    for key in EXPECTED_REQUIREMENTS:
        matches = grouped.get(key, [])
        if len(matches) != 1:
            if len(matches) > 1:
                statuses = sorted({str(row.get("status")) for row in matches})
                label = "contradictory" if len(statuses) > 1 else "ambiguous"
                errors.append(f"{label} qualification records for {key!r}: statuses={statuses}")
            continue
        row = matches[0]
        if row.get("status") != "PROVEN":
            errors.append(f"failed/unresolved qualification {key!r}: status={row.get('status')!r}")
        else:
            proven_count += 1
        if row.get("source_commit") != source_commit:
            errors.append(f"qualification {key!r} has wrong source_commit")
        created_at, created_error = _parse_timestamp(row.get("created_at"))
        if created_error:
            errors.append(f"qualification {key!r} chronology failure: {created_error}")
        elif manifest_at is not None and created_at is not None and created_at > manifest_at:
            errors.append(f"qualification {key!r} occurs after manifest generation")

        try:
            evidence = json.loads(row.get("evidence_json"))
        except (TypeError, json.JSONDecodeError) as exc:
            errors.append(f"qualification {key!r} has malformed evidence_json: {exc}")
            continue
        if not isinstance(evidence, dict):
            errors.append(f"qualification {key!r} evidence must be an object")
            continue
        if (
            type(evidence.get("schema_version")) is not int
            or evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION
        ):
            errors.append(
                f"qualification {key!r} has unsupported evidence schema_version "
                f"{evidence.get('schema_version')!r}"
            )
        envelope_classification = _normalized_token(evidence.get("classification"))
        if envelope_classification not in PRODUCTION_EVIDENCE_CLASSIFICATIONS:
            errors.append(
                f"qualification {key!r} uses ineligible evidence classification "
                f"{evidence.get('classification')!r}"
            )
        if evidence.get("qualification_eligible") is not True:
            errors.append(f"qualification {key!r} evidence is not qualification eligible")
        if evidence.get("source_commit") != source_commit:
            errors.append(f"qualification {key!r} evidence has wrong source_commit")
        if evidence.get("source_tree_sha256") != source_tree_sha256:
            errors.append(f"qualification {key!r} evidence has wrong source_tree_sha256")
        if evidence.get("config_sha256") != config_sha256:
            errors.append(f"qualification {key!r} evidence has wrong config_sha256")
        if not isinstance(evidence.get("feature"), str) or not evidence.get("feature"):
            errors.append(f"qualification {key!r} evidence has no feature binding")
        observed_at, observed_error = _parse_timestamp(evidence.get("observed_at"))
        if observed_error:
            errors.append(f"qualification {key!r} chronology failure: {observed_error}")
        elif created_at is not None and observed_at is not None and observed_at > created_at:
            errors.append(f"qualification {key!r} evidence occurs after ledger creation")

        canonical_hash = _canonical_hash(evidence)
        if row.get("artifact_hash") != canonical_hash:
            errors.append(f"qualification {key!r} evidence_json hash is tampered")
        manifest_binding = manifest_rows.get(key)
        if manifest_binding is None or manifest_binding.get("artifact_hash") != row.get(
            "artifact_hash"
        ):
            errors.append(f"qualification {key!r} is not bound by the manifest")

        refs = evidence.get("evidence_refs")
        covered: set[str] = set()
        governed_promotion_bound = False
        if not isinstance(refs, list) or not refs:
            errors.append(f"qualification {key!r} has no evidence references")
        else:
            for ref in refs:
                artifact_errors, artifact_coverage, artifact = _validate_evidence_artifact(
                    home,
                    ref,
                    key=key,
                    source_commit=source_commit,
                    source_tree_sha256=source_tree_sha256,
                    config_sha256=config_sha256,
                    gate_sha256=gate_hashes.get(key),
                    latest_observed_at=created_at,
                )
                errors.extend(f"qualification {key!r}: {error}" for error in artifact_errors)
                covered.update(artifact_coverage)
                if not artifact_errors and isinstance(ref, dict) and artifact is not None:
                    binding = _observation_binding(home, ref, artifact)
                    if binding is not None:
                        validated_bindings.append(binding)
                        if (
                            "governed_improvement_promotes_only_with_all_guards"
                            in artifact_coverage
                        ):
                            governed_promotion_bound = True
        missing_coverage = sorted(_scoped_required(scope, key) - covered)
        scoped_gate_total += len(_scoped_required(scope, key))
        scoped_gate_covered += len(_scoped_required(scope, key) & covered)
        if missing_coverage:
            errors.append(
                f"qualification {key!r} is missing authoritative Gate coverage: {missing_coverage}"
            )
        else:
            coverage_complete_count += 1
        if (
            key == EXPECTED_REQUIREMENTS[-1]
            and "governed_improvement_promotes_only_with_all_guards" in covered
            and not governed_promotion_bound
        ):
            errors.append(
                "governed promotion evidence is not bound to a worker-independent "
                "causal observation"
            )

    unique_bindings = {
        (
            item["path"],
            item["sha256"],
            item["feature"],
            item["source_commit"],
            item["source_tree_sha256"],
            item["config_sha256"],
        ): item
        for item in validated_bindings
    }
    return check(
        "qualification_ledger",
        not errors,
        {
            "records": records,
            "canonical_requirement_count": len(EXPECTED_REQUIREMENTS),
            "proven_count": proven_count,
            "coverage_complete_count": coverage_complete_count,
            "validated_evidence_bindings": list(unique_bindings.values()),
            "release_scope_id": (scope or {}).get("scope_id"),
            "retired_gates": (scope or {}).get("retired_gates") or {},
            "retired_gate_count": sum(
                len(items)
                for items in ((scope or {}).get("retired_gates") or {}).values()
                if isinstance(items, list)
            ),
            "retired_gates_counted_as_passed": False,
            "scoped_gate_count": scoped_gate_total,
            "scoped_gate_covered": scoped_gate_covered,
            "errors": errors,
        },
    )


def check_privacy_absence() -> dict[str, Any]:
    forbidden = ["api_key", "secret_key", "private_key", "-----BEGIN PRIVATE KEY-----"]
    leaks: list[str] = []
    root = REPO_ROOT / "outputs" / "reports" / "v2"
    if root.is_dir():
        for path in root.rglob("*.json"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for marker in forbidden:
                if marker in text:
                    leaks.append(f"{path}: leaked {marker}")
    return check("privacy_absence", not leaks, {"leaks": leaks})


def _safe_check(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return operation()
    except Exception as exc:
        return check(name, False, {"error": f"{type(exc).__name__}: {exc}"})


def verify_all(
    home: Path,
    manifest_path: Path | None = None,
    records_path: Path | None = None,
    scope_path: Path | None = None,
) -> dict[str, Any]:
    release_scope: dict[str, Any] | None = None
    scope_errors: list[str] = []
    if scope_path is not None:
        release_scope, scope_errors = load_release_scope(scope_path)
    try:
        manifest_check, manifest = check_manifest(home, manifest_path)
    except Exception as exc:
        manifest = None
        manifest_check = check(
            "qualification_manifest",
            False,
            {"errors": [f"{type(exc).__name__}: {exc}"]},
        )
    ledger_check = _safe_check(
        "qualification_ledger",
        lambda: (
            check_qualification_ledger(home, manifest, release_scope)
            if records_path is None
            else validate_qualification_rows(
                home, manifest, load_candidate_records(home, records_path), release_scope
            )
        ),
    )
    results = [
        _safe_check("database_integrity", lambda: check_database_integrity(home)),
        _safe_check("schema_migrations", lambda: check_schema_migrations(home)),
        _safe_check("v2_tables_present", lambda: check_v2_tables_present(home)),
        manifest_check,
        ledger_check,
        _safe_check("privacy_absence", check_privacy_absence),
    ]
    if scope_path is not None:
        results.append(check("release_scope", not scope_errors, {"errors": scope_errors}))
    ok = all(result["ok"] for result in results)
    remaining: list[str] = []
    for result in results:
        if result["ok"]:
            continue
        details = result.get("details", {})
        reasons = details.get("errors")
        if isinstance(reasons, list) and reasons:
            remaining.extend(f"{result['check']}: {reason}" for reason in reasons)
        else:
            reason = details.get("reason", details.get("error", "check failed"))
            remaining.append(f"{result['check']}: {reason}")
    manifest_source = manifest.get("source_commit") if isinstance(manifest, dict) else None
    current_source = _git_head()
    bindings = ledger_check.get("details", {}).get("validated_evidence_bindings", []) if ok else []
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "ok": ok,
        "qualification_status": (
            ("QUALIFIED" if records_path is None else "READY_TO_RECORD") if ok else "HOLD"
        ),
        "remaining_prerequisites": remaining,
        "verifier": "scripts/verify_qualification.py",
        "verifier_sha256": _sha256_file(Path(__file__)),
        "release_scope": {
            "path": str(scope_path.resolve()) if scope_path is not None else None,
            "sha256": (
                _sha256_file(scope_path)
                if scope_path is not None and scope_path.is_file()
                else None
            ),
            "scope_id": (release_scope or {}).get("scope_id"),
            "supersedes": (release_scope or {}).get("supersedes"),
            "retired_gates": (release_scope or {}).get("retired_gates") or {},
            "retired_gate_count": sum(
                len(items)
                for items in ((release_scope or {}).get("retired_gates") or {}).values()
                if isinstance(items, list)
            ),
            "retired_gates_counted_as_passed": False,
            "errors": scope_errors,
        },
        "source_commit": manifest_source,
        "current_source_commit": current_source,
        "source_tree_sha256": _source_tree_fingerprint(),
        "config_sha256": _config_fingerprint(home),
        "validated_evidence_bindings": bindings if records_path is None else [],
        "records_path": str(
            (records_path if records_path.is_absolute() else home / records_path).resolve()
        )
        if records_path is not None
        else None,
        "records_sha256": (
            _sha256_file(records_path if records_path.is_absolute() else home / records_path)
            if records_path is not None and ok
            else None
        ),
        "records_content_sha256": (
            _canonical_hash(ledger_check["details"]["records"])
            if records_path is not None and ok
            else None
        ),
        "manifest_content_sha256": (
            _canonical_hash(manifest) if records_path is not None and ok else None
        ),
        "scope": [
            {"phase": phase, "requirement": requirement}
            for phase, requirement in EXPECTED_REQUIREMENTS
        ],
        "manifest_path": str(manifest_path.resolve()) if manifest_path else None,
        "manifest_sha256": (
            _sha256_file(manifest_path)
            if manifest_path is not None and manifest_path.is_file()
            else None
        ),
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON report to stdout")
    parser.add_argument(
        "--manifest", type=Path, default=None, help="Qualification manifest to validate"
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=None,
        help="Read-only candidate rows; success is READY_TO_RECORD, never QUALIFIED",
    )
    parser.add_argument("--out", type=Path, default=None, help="Output destination")
    parser.add_argument("--home", type=Path, default=REPO_ROOT, help="Brain home directory")
    parser.add_argument(
        "--scope",
        type=Path,
        default=None,
        help="Versioned release-scope overlay that retires scope-specific Gate clauses",
    )
    args = parser.parse_args(argv)

    result = verify_all(Path(args.home).resolve(), args.manifest, args.records, args.scope)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
