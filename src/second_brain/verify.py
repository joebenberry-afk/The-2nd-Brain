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
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from .errors import BrainError
from .working_set import show_capsule, show_requirements

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

    Invalid TOML, a missing/empty section, or a non-string-list value for a
    level falls back to the documented default for that level (safe default —
    a broken config never silences verification). PURE, never throws, never
    reads the filesystem.
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
        if isinstance(value, list) and len(value) > 0 and all(
            isinstance(item, str) for item in value
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
    """Resolve the verification ladder into a self-contained, order-stable
    list of leaf action tokens for `level`.

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
