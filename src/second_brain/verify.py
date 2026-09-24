"""Intent Verifier brief builder (plan §37-38, Phase 7 §103) + risk-adaptive
verification ladder (plan §10, P3-G).

Builds a fresh-context verifier brief from the session working set: the
requirements ledger, capsule constraints, the diff of capsule-recorded touched
files, and validation evidence. Solver reasoning (hypotheses, decisions,
next_action, open questions) is deliberately excluded, and the diff appears
BEFORE the requirements so the verifier must perform backward reconstruction
(plan §38) — infer intent from the patch before reading the task.

The brief is written atomically to ``outputs/verification/<session-id>.md``
and is deterministic for identical inputs (only ``generated_at`` differs).

P3-G: the smallest consumer that maps a risk result (risk.py level) to the
verification ladder from config/verification.toml ``[ladder]`` (read per
invocation). Output is a COMPACT deterministic action list per level
(plan §10.2/§10.4) — no verification engine, no new subsystem. Invalid or
absent config falls back to the documented defaults (safe default).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import stable_content_hash
from .errors import BrainError
from .risk import assess_risk
from .working_set import check_requirements, show_capsule, show_requirements

MAX_DIFF_LINES = 400

BACKWARD_MANDATE = (
    "Before reading any other section, infer the patch's apparent intent from "
    "the DIFF below. Write the inferred intent under '## Backward "
    "Reconstruction' before reading further. Then compare it with the "
    "Requirements section."
)

VERIFIER_QUESTIONS: tuple[str, ...] = (
    "1. What does the task require?",
    "2. What does this patch actually do?",
    "3. If I saw only the patch, what task would I infer?",
    "4. Are those aligned?",
    "5. What requirement lacks evidence?",
    "6. Did tests merely satisfy a narrow oracle?",
    "7. Was unrelated scope added?",
    "8. Are failure paths covered?",
)

# Capsule fields that must never leak into the brief (solver reasoning).
EXCLUDED_CAPSULE_FIELDS: tuple[str, ...] = (
    "current_hypotheses",
    "decisions_this_session",
    "next_action",
    "open_questions",
)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _load_or_none(loader, *args: object) -> dict | list | None:
    try:
        return loader(*args)
    except BrainError:
        return None


def _git_diff(repo: Path, files: list[str]) -> list[str]:
    """`git diff` for the touched files; error-graced, never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "diff", "--", *files],
            capture_output=True,
            text=True,
            timeout=30,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"(diff unavailable: {exc})"]
    if result.returncode != 0:
        return [f"(diff unavailable: git exit {result.returncode})"]
    return result.stdout.splitlines()


def build_verifier_brief(home: Path, session_id: str, repo: Path) -> Path:
    """Render the verifier brief and return its path.

    Missing capsule -> BrainError; missing/empty ledger -> ``(none)``;
    git problems -> ``(diff unavailable: ...)``.
    """
    capsule = show_capsule(home, session_id)
    # Solver-reasoning fields are excluded BY the constant: the builder reads
    # only a whitelist view, so the invariant is enforced, not incidental.
    safe_capsule = {k: v for k, v in capsule.items() if k not in EXCLUDED_CAPSULE_FIELDS}
    requirements = _load_or_none(show_requirements, home, session_id) or []

    out_dir = Path(home) / "outputs" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{session_id}.md"

    files = safe_capsule.get("files_touched") or []
    lines = [
        "# Intent Verifier Brief",
        "",
        f"session: {session_id}",
        f"generated_at: {_utcnow()}",
        f"repo: {repo}",
        "",
        "# Backward Reconstruction",
        "",
        BACKWARD_MANDATE,
        "",
        "## Backward Reconstruction",
        "(fill me)",
        "",
        "# Diff",
        "",
    ]
    if not files:
        lines.append("(no files recorded)")
    else:
        diff = _git_diff(Path(repo), files)
        lines.extend(diff[:MAX_DIFF_LINES] if diff else ["(empty diff)"])
    lines.append("")
    lines.append("# Requirements")
    lines.append("")
    if requirements:
        for entry in requirements:
            lines.append(
                f"- {entry['id']} [{entry['importance']}/{entry['status']}] {entry['requirement']}"
            )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("# Constraints")
    lines.append("")
    constraints = safe_capsule.get("constraints") or []
    if constraints:
        lines.extend(f"- {constraint}" for constraint in constraints)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("# Validation Evidence")
    lines.append("")
    evidence = [(entry["id"], entry["evidence"]) for entry in requirements if entry["evidence"]]
    if evidence:
        for req_id, entries in evidence:
            lines.append(f"{req_id}:")
            lines.extend(f"  - {entry}" for entry in entries)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("# Verifier Questions")
    lines.append("")
    lines.extend(VERIFIER_QUESTIONS)

    content = "\n".join(lines) + "\n"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise BrainError(f"Could not write verifier brief {target}: {exc}") from exc
    return target


# ---------------------------------------------------------------------------
# P3-G: risk-adaptive verification ladder (plan §10.2/§10.3/§10.4).
# ---------------------------------------------------------------------------

RISK_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# Documented defaults (mirror config/verification.toml [ladder]) — used when
# the config is absent/invalid. Cumulative tokens (all_medium/all_high) make
# the ladder self-referential: HIGH includes MEDIUM+LOW, CRITICAL includes all.
DEFAULT_VERIFICATION_LADDER: dict[str, list[str]] = {
    "LOW": ["targeted_test", "typecheck_or_compile", "diff_sanity"],
    "MEDIUM": [
        "targeted_plus_relevant_tests",
        "requirement_ledger",
        "affected_file_review",
        "simplification_check",
    ],
    "HIGH": [
        "all_medium",
        "repowise_impact_context",
        "independent_intent_verifier",
        "negative_adversarial_tests",
        "rollback_check",
    ],
    "CRITICAL": [
        "all_high",
        "human_approval_for_irreversible",
        "optional_second_independent_verification",
    ],
}

# Compact human-readable labels for each ladder token (deterministic).
LADDER_ACTION_LABELS: dict[str, str] = {
    "targeted_test": "run existing targeted test/check",
    "typecheck_or_compile": "typecheck or compile",
    "diff_sanity": "diff sanity review",
    "targeted_plus_relevant_tests": "run targeted + relevant tests",
    "requirement_ledger": "requirement-ledger check",
    "affected_file_review": "review affected files",
    "simplification_check": "confirm no unrelated simplification",
    "repowise_impact_context": "impact context (repo-wide scan)",
    "independent_intent_verifier": "fresh independent verifier brief (brainctl verify build-brief)",
    "negative_adversarial_tests": "negative/adversarial test where relevant",
    "rollback_check": "rollback/reversibility check",
    "human_approval_for_irreversible": (
        "explicit human approval for irreversible/high-impact actions"
    ),
    "optional_second_independent_verification": "optional second independent verification",
}


def ladder_from_toml(text: str) -> dict[str, list[str]]:
    """Parse the ``[ladder]`` section of config/verification.toml.

    Invalid TOML, a missing/empty section, or a non-string-list value for a level falls
    back to the documented default for that level (safe default — a broken config never
    silences verification). PURE, never throws, never reads the filesystem.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        data = {}
    section = data.get("ladder")
    if not isinstance(section, dict):
        return {level: list(DEFAULT_VERIFICATION_LADDER[level]) for level in RISK_LEVELS}
    out: dict[str, list[str]] = {}
    for level in RISK_LEVELS:
        value = section.get(level)
        if (
            isinstance(value, list)
            and len(value) > 0
            and all(isinstance(item, str) for item in value)
        ):
            out[level] = [str(item) for item in value]
        else:
            out[level] = list(DEFAULT_VERIFICATION_LADDER[level])
    return out


def load_verification_ladder(home: Path | str | None) -> dict[str, list[str]]:
    """Read ``<home>/config/verification.toml [ladder]`` per invocation.

    Missing/unreadable file -> documented defaults (never throws).
    """
    if home is None:
        return ladder_from_toml("")
    try:
        text = (Path(home) / "config" / "verification.toml").read_text(encoding="utf-8")
        return ladder_from_toml(text)
    except OSError:
        return ladder_from_toml("")


def expand_ladder_actions(ladder: dict[str, list[str]], level: str) -> list[str]:
    """Resolve the verification ladder into a self-contained, order-stable list of leaf
    action tokens for `level`.

    Cumulativity is STRUCTURAL (plan §10.2): every level includes all lower
    levels' actions (LOW subset MEDIUM subset HIGH subset CRITICAL), so the
    config's ``all_medium``/``all_high`` reference tokens are redundant and
    skipped — which also makes malformed self-referential configs (e.g.
    MEDIUM containing all_medium) degrade deterministically with no recursion.
    """
    if level not in RISK_LEVELS:
        raise BrainError(f"unknown risk level: {level!r}")
    resolved: list[str] = []
    seen: set[str] = set()
    for current in RISK_LEVELS[: RISK_LEVELS.index(level) + 1]:
        for token in ladder.get(current, []):
            if token in ("all_medium", "all_high"):
                continue  # structural cumulativity already covers them
            if token not in seen:
                seen.add(token)
                resolved.append(token)
    return resolved


def verification_ladder_payload(
    level: str,
    *,
    home: Path | str | None = None,
    ladder: dict[str, list[str]] | None = None,
) -> dict:
    """Compact deterministic verification-ladder payload for a risk level.

    Returns ``{"level", "actions", "independent_verifier", "approval_required"}``
    — level + actions + the two high-signal flags, nothing more (plan §10.4).
    ``ladder`` is a test seam; when omitted the config is read per invocation
    (``home``), falling back to the documented defaults.
    """
    ladder = ladder if ladder is not None else load_verification_ladder(home)
    tokens = expand_ladder_actions(ladder, level)
    actions = [LADDER_ACTION_LABELS.get(token, token.replace("_", " ")) for token in tokens]
    return {
        "level": level,
        "actions": actions,
        "independent_verifier": "independent_intent_verifier" in tokens,
        "approval_required": "human_approval_for_irreversible" in tokens,
    }


# ---------------------------------------------------------------------------
# SEC-AUTH-01 (fail closed): requested approval != effective approval.
#
# ``approval_state`` comes from the same caller that wants the verdict, so it is
# a REQUEST and evidence only. Effective approval additionally needs an
# attestation from an issuer the requesting caller cannot act as. The issuer
# registry is empty by construction in this build (no signer, no host-held
# token) and is deliberately NOT selectable through an environment variable,
# repo/Brain-home config, model setting or CLI flag, so nothing a caller can
# reach turns a request into authority: the irreversible path stays "required"
# and the gate reports the attestation as unavailable instead of faking an
# allow. Registering an issuer is a security review, not a configuration.
# ---------------------------------------------------------------------------
APPROVAL_ATTESTATION_ISSUERS: dict[str, Callable[[dict[str, Any]], bool]] = {}
APPROVAL_ATTESTATION_NOT_REQUIRED = "not_required"
APPROVAL_ATTESTATION_ATTESTED = "attested"
APPROVAL_ATTESTATION_UNAVAILABLE = "unavailable"


def approval_attested(attestation: dict[str, Any] | None) -> bool:
    """True only for an attestation vouched for by a registered independent issuer.

    Any malformed, unregistered or raising attestation is False: the default is
    always "no authority".
    """
    if not isinstance(attestation, dict):
        return False
    issuer = attestation.get("issuer")
    validator = APPROVAL_ATTESTATION_ISSUERS.get(issuer) if isinstance(issuer, str) else None
    if validator is None:
        return False
    try:
        return bool(validator(attestation))
    except Exception:
        return False


def evaluate_accuracy_gate(
    home: Path | str,
    session_id: str,
    repo: Path | str,
    files_touched: list[str],
    *,
    action_states: dict[str, str] | None = None,
    user_criticality: str | None = None,
    approval_state: str = "not_required",
    approval_attestation: dict[str, Any] | None = None,
    task_id: str = "",
    parent_session_id: str = "",
    worker_session_id: str = "",
    independent_verification: dict[str, object] | None = None,
    task_hash: str = "",
    requirements_hash: str = "",
    diff_hash: str = "",
    evidence_set_hash: str = "",
    environment_evidence: dict[str, object] | None = None,
    environment_required: bool = False,
) -> dict[str, Any]:
    """Evaluate completion against the existing risk ladder and evidence ledger.

    Authority boundary (SEC-AUTH-01): every other input here — action states,
    approval state, the independent verification record, environment evidence
    and the hashes compared against each other — is authored by the caller
    requesting the verdict. They remain evidence, but they cannot authorize
    completion of an irreversible/high-impact gate: that needs
    ``approval_attestation`` from an independent issuer, and no issuer is
    registered in this build, so such a gate always reports
    ``approval_state="required"``. No model identity is recorded either
    (SEC-AUTH-02): a claimed model id is not an authenticated runtime identity,
    so nothing privileged is written from a claim.
    """
    started_at = time.perf_counter()
    states = action_states or {}
    invalid = {
        key: value
        for key, value in states.items()
        if value not in {"passed", "failed", "unresolved"}
    }
    if invalid:
        raise BrainError(f"invalid verification action states: {sorted(invalid)}")
    assessment = assess_risk(Path(repo), files_touched, user_criticality=user_criticality)
    level = str(assessment["level"])
    ladder = load_verification_ladder(home)
    all_actions = expand_ladder_actions(ladder, level)
    required_actions = [
        action for action in all_actions if action != "optional_second_independent_verification"
    ]
    if level == "CRITICAL" and "human_approval_for_irreversible" not in required_actions:
        # SEC-AUTH-01 fail-closed: a critical gate requires approval even when a
        # home-config ladder dropped the token, so a caller can only restate the
        # requirement — nothing it supplies can satisfy it.
        required_actions.append("human_approval_for_irreversible")
    environment_reason = ""
    if environment_required:
        required_actions.append("environment_steward")
        if environment_evidence is None:
            states["environment_steward"] = "unresolved"
            environment_reason = "environment_steward_missing"
        else:
            env_state = environment_evidence.get("environment_state")
            repo_match = isinstance(env_state, dict) and env_state.get("repo") == str(
                Path(repo).resolve()
            )
            hash_match = isinstance(
                environment_evidence.get("environment_hash"), str
            ) and environment_evidence.get("environment_hash") == environment_evidence.get(
                "after_environment_hash"
            )
            valid_environment = (
                repo_match
                and hash_match
                and environment_evidence.get("verification_state") == "passed"
                and environment_evidence.get("completion_eligible") is True
            )
            states["environment_steward"] = "passed" if valid_environment else "failed"
            if not valid_environment:
                environment_reason = "environment_steward_invalid"
    independent_reason = ""
    independent_action_required = "independent_intent_verifier" in required_actions
    if independent_action_required:
        if independent_verification is None:
            states["independent_intent_verifier"] = "unresolved"
            independent_reason = "independent_verification_missing"
        else:
            expected_hashes = {
                "task_hash": task_hash,
                "requirements_hash": requirements_hash,
                "diff_hash": diff_hash,
                "evidence_set_hash": evidence_set_hash,
            }
            hash_mismatch = any(
                expected and independent_verification.get(name) != expected
                for name, expected in expected_hashes.items()
            )
            fresh_pass = (
                independent_verification.get("verdict") == "PASS"
                and independent_verification.get("freshness") == "fresh"
                and independent_verification.get("verifier_session_id") != parent_session_id
                and not hash_mismatch
            )
            if fresh_pass:
                states["independent_intent_verifier"] = "passed"
            else:
                states["independent_intent_verifier"] = "failed"
                independent_reason = (
                    "independent_verification_stale"
                    if hash_mismatch
                    else "independent_verification_invalid"
                )
    effective_parent_session = parent_session_id or (
        str(independent_verification.get("implementation_session_id"))
        if independent_verification and independent_verification.get("implementation_session_id")
        else ""
    )
    effective_worker_session = worker_session_id or (
        str(independent_verification.get("verifier_session_id"))
        if independent_verification and independent_verification.get("verifier_session_id")
        else ""
    )
    completed_actions = [action for action in required_actions if states.get(action) == "passed"]
    failed_actions = [action for action in required_actions if states.get(action) == "failed"]
    unresolved_actions = [
        action for action in required_actions if states.get(action) not in {"passed", "failed"}
    ]
    requirement_check = check_requirements(Path(home), session_id)
    unresolved_requirements = [str(entry["id"]) for entry in requirement_check["entries"]]
    approval_required = "human_approval_for_irreversible" in required_actions
    attested = approval_required and approval_attested(approval_attestation)
    # SEC-AUTH-01: the caller's `approval_state` is a request, never authority.
    # Only an independent attestation can make the approval effective.
    requested_approval_state = approval_state if isinstance(approval_state, str) else ""
    effective_approval = (
        "approved" if attested else "required" if approval_required else "not_required"
    )
    approval_attestation_state = (
        APPROVAL_ATTESTATION_ATTESTED
        if attested
        else APPROVAL_ATTESTATION_UNAVAILABLE
        if approval_required
        else APPROVAL_ATTESTATION_NOT_REQUIRED
    )
    if unresolved_requirements:
        completion_allowed = False
        decision_reason = "material_requirements_unresolved"
    elif independent_reason:
        completion_allowed = False
        decision_reason = independent_reason
    elif environment_reason:
        completion_allowed = False
        decision_reason = environment_reason
    elif failed_actions:
        completion_allowed = False
        decision_reason = "verification_actions_failed"
    elif unresolved_actions:
        completion_allowed = False
        decision_reason = "verification_actions_unresolved"
    elif effective_approval == "required":
        completion_allowed = False
        decision_reason = "irreversible_action_approval_required"
    else:
        completion_allowed = True
        decision_reason = "all_required_evidence_satisfied"
    risk_reasons = [
        str(signal["name"]) for signal in assessment["signals"] if int(signal["points"]) > 0
    ]
    ladder_id = stable_content_hash({"risk_level": level, "required_actions": required_actions})
    accuracy_gate_id = stable_content_hash(
        {
            "task_id": task_id,
            "session_id": session_id,
            "parent_session_id": effective_parent_session,
            "worker_session_id": effective_worker_session,
            "ladder_id": ladder_id,
        }
    )
    raw_verification_reasons = (
        independent_verification.get("reason_codes", []) if independent_verification else []
    )
    verification_reason_codes = (
        [str(item) for item in raw_verification_reasons]
        if isinstance(raw_verification_reasons, list)
        else [independent_reason]
        if independent_reason
        else []
    )
    # SEC-AUTH-02: no model identity is recorded here. A caller-supplied
    # `model_id` (directly or via the verification file) is a claim, not an
    # authenticated runtime identity, and `model_skill_outcomes` is policy
    # input (`models report` / `models policy`). With no authenticated identity
    # available the gate records nothing rather than falling back to the claim.

    return {
        "accuracy_gate_id": f"gate-{accuracy_gate_id[:24]}",
        "task_id": task_id,
        "parent_session_id": effective_parent_session,
        "worker_session_id": effective_worker_session,
        "risk_level": level,
        "risk_reasons": risk_reasons,
        "ladder_id": ladder_id,
        "required_actions": required_actions,
        "completed_actions": completed_actions,
        "failed_actions": failed_actions,
        "unresolved_actions": unresolved_actions,
        "unresolved_material_requirements": unresolved_requirements,
        "requested_approval_state": requested_approval_state,
        "approval_state": effective_approval,
        "approval_attestation": approval_attestation_state,
        "completion_allowed": completion_allowed,
        "decision_reason": decision_reason,
        "verification_id": (
            independent_verification.get("verification_id") if independent_verification else None
        ),
        "verifier_session_id": (
            independent_verification.get("verifier_session_id")
            if independent_verification
            else None
        ),
        "verification_verdict": (
            independent_verification.get("verdict") if independent_verification else None
        ),
        "verification_freshness": (
            independent_verification.get("freshness") if independent_verification else None
        ),
        "verification_reason_codes": verification_reason_codes,
        "environment_steward_id": (
            environment_evidence.get("environment_steward_id") if environment_evidence else None
        ),
        "environment_hash": (
            environment_evidence.get("environment_hash") if environment_evidence else None
        ),
        "environment_mutation_classification": (
            environment_evidence.get("mutation_classification") if environment_evidence else None
        ),
        "environment_completion_eligible": (
            environment_evidence.get("completion_eligible") if environment_evidence else None
        ),
        "economics": {
            "verification_model_calls": 0,
            "verification_tool_calls": 0,
            "verification_context_tokens": 0,
            "gate_bookkeeping_overhead_ms": round((time.perf_counter() - started_at) * 1000, 3),
            "retries": 0,
            "corrections": 0,
            "completion_blocked": not completion_allowed,
            "additional_work_required": None,
        },
    }
