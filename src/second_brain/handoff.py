"""
Brain Handoff Artifact Generator (Plan §3 P3.17).

Creates a structured, lossless cross-agent and cross-session handoff artifact
capturing goals, verified state, decisions, pending blockers, and context pointers.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import working_set


@dataclass
class BrainHandoffArtifact:
    """A structured handoff artifact (§3 P3.17)."""
    session_id: str
    target_agent: str
    objective: str
    completed_steps: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    pending_blockers: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    next_recommended_actions: list[str] = field(default_factory=list)
    created_at: str = ""
    artifact_path: str = ""

    def render_markdown(self) -> str:
        lines = [
            f"# Brain Handoff Artifact — Session `{self.session_id}`",
            "",
            f"- **Target Agent / Recipient**: `{self.target_agent}`",
            f"- **Generated At**: `{self.created_at}`",
            f"- **Core Objective**: {self.objective}",
            "",
            "## Completed Steps & Verified Milestones",
        ]
        if self.completed_steps:
            for s in self.completed_steps:
                lines.append(f"- [x] {s}")
        else:
            lines.append("- (none recorded)")

        lines.extend([
            "",
            "## Key Architectural Decisions",
        ])
        if self.key_decisions:
            for d in self.key_decisions:
                lines.append(f"- **Decision**: {d}")
        else:
            lines.append("- (none recorded)")

        lines.extend([
            "",
            "## Pending Blockers & Open Questions",
        ])
        if self.pending_blockers:
            for b in self.pending_blockers:
                lines.append(f"- [!] {b}")
        else:
            lines.append("- (no blockers)")

        lines.extend([
            "",
            "## Relevant Files & Context Artifacts",
        ])
        if self.relevant_files:
            for f in self.relevant_files:
                lines.append(f"- `{f}`")
        if self.evidence_refs:
            for e in self.evidence_refs:
                lines.append(f"- Evidence Ref: `{e}`")

        lines.extend([
            "",
            "## Recommended Next Actions",
        ])
        if self.next_recommended_actions:
            for a in self.next_recommended_actions:
                lines.append(f"1. {a}")
        else:
            lines.append("1. Continue from last verified milestone.")

        return "\n".join(lines) + "\n"


def create_handoff(
    home: Path | str,
    session_id: str,
    target_agent: str = "incoming-agent",
    objective: str = "",
    completed_steps: list[str] | None = None,
    key_decisions: list[str] | None = None,
    pending_blockers: list[str] | None = None,
    relevant_files: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> BrainHandoffArtifact:
    """
    Generate and save a Brain Handoff Artifact to outputs/handoffs/ (§3 P3.17).
    """
    home_path = Path(home)
    out_dir = home_path / "outputs" / "handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pull from active working set capsule if available
    capsule: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        capsule = working_set.show_capsule(home_path, session_id)

    final_objective = objective or capsule.get("current_objective") or "Continue session task"
    final_decisions = key_decisions or capsule.get("decisions_this_session") or []
    final_blockers = pending_blockers or capsule.get("open_questions") or []
    final_files = relevant_files or capsule.get("files_touched") or []
    final_next = next_actions or ([capsule["next_action"]] if capsule.get("next_action") else [])

    now = datetime.now(UTC).isoformat()
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_id) or "anon"
    target_file = out_dir / f"handoff-{safe_stem}.md"

    artifact = BrainHandoffArtifact(
        session_id=session_id,
        target_agent=target_agent,
        objective=final_objective,
        completed_steps=completed_steps or [],
        key_decisions=final_decisions,
        pending_blockers=final_blockers,
        relevant_files=final_files,
        evidence_refs=evidence_refs or [],
        next_recommended_actions=final_next,
        created_at=now,
        artifact_path=str(target_file),
    )

    md_content = artifact.render_markdown()
    target_file.write_text(md_content, encoding="utf-8")
    return artifact
