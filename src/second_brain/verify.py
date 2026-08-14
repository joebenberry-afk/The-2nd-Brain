"""Intent Verifier brief builder (plan §37-38, Phase 7 §103).

Builds a fresh-context verifier brief from the session working set: the
requirements ledger, capsule constraints, the diff of capsule-recorded touched
files, and validation evidence. Solver reasoning (hypotheses, decisions,
next_action, open questions) is deliberately excluded, and the diff appears
BEFORE the requirements so the verifier must perform backward reconstruction
(plan §38) — infer intent from the patch before reading the task.

The brief is written atomically to ``outputs/verification/<session-id>.md``
and is deterministic for identical inputs (only ``generated_at`` differs).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
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
