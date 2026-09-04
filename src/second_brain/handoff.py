"""
Brain Handoff Artifact Generator (Plan §3 P3.17).

Two layers, both reusing existing Brain primitives instead of a parallel
memory/artifact system:

- ``create_handoff`` / ``BrainHandoffArtifact`` (legacy, unchanged): a
  human-readable Markdown artifact, optionally seeded from the Active State
  Capsule (P3.1) with manual overrides for narrative fields.
- ``create_handoff_envelope`` / ``read_handoff_envelope`` (P3.17 closure): a
  bounded, harness-neutral ``BrainHandoffEnvelope`` (see
  :mod:`second_brain.contracts`) that binds identity + integrity hashes to a
  losslessly recoverable canonical payload. The payload (full Active State
  Capsule + requirement ledger) is stored through the existing
  content-addressed Artifact Store (:mod:`second_brain.artifacts`) rather
  than copied into the envelope or a new store. Cross-harness transport goes
  through the existing OMP (:mod:`second_brain.omp_adapter`) and Hermes
  (:mod:`second_brain.hermes_adapter`) adapters, both of which call the same
  functions here so semantics never diverge by harness.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import artifacts, ledger, working_set
from .contracts import (
    HANDOFF_LIST_MAX_ITEMS,
    HANDOFF_SCHEMA_VERSION,
    HANDOFF_STALE_AFTER_SECONDS,
    BrainHandoffEnvelope,
    HandoffError,
    canonical_json,
    stable_content_hash,
)
from .errors import BrainError


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _safe_stem(session_id: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_id) or "anon"


@dataclass
class BrainHandoffArtifact:
    """A structured, human-readable handoff artifact (§3 P3.17)."""
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
    # Populated only when generated via create_handoff_envelope(): traces this
    # Markdown to the canonical bounded envelope that carries integrity hashes.
    handoff_id: str = ""
    envelope_ref: str = ""
    source_harness: str = ""
    capsule_sha256: str = ""
    payload_sha256: str = ""

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

        if self.handoff_id:
            lines.extend([
                "",
                "## Canonical Handoff Envelope",
                f"- **Handoff ID**: `{self.handoff_id}`",
                f"- **Source Harness**: `{self.source_harness}`",
                f"- **Capsule SHA-256**: `{self.capsule_sha256}`",
                f"- **Payload SHA-256**: `{self.payload_sha256}`",
                f"- **Envelope Ref**: `{self.envelope_ref}`",
            ])

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

    final_objective = objective or capsule.get("objective") or "Continue session task"
    final_decisions = key_decisions or capsule.get("decisions_this_session") or []
    final_blockers = pending_blockers or capsule.get("open_questions") or []
    final_files = relevant_files or capsule.get("files_touched") or []
    final_next = next_actions or ([capsule["next_action"]] if capsule.get("next_action") else [])

    now = _utcnow()
    safe_stem = _safe_stem(session_id)
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


# ---------------------------------------------------------------------------
# Canonical bounded envelope (§3 P3.17 closure).
# ---------------------------------------------------------------------------


def _requirement_summary(requirements: list[dict[str, Any]]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for entry in requirements[:HANDOFF_LIST_MAX_ITEMS]:
        req_id = entry.get("id")
        status = entry.get("status")
        if isinstance(req_id, str) and isinstance(status, str):
            summary[req_id] = status
    return summary


def build_payload(home: Path | str, session_id: str) -> dict[str, Any]:
    """The full canonical, lossless payload for one session: capsule + requirement ledger.

    This is never embedded in the bounded envelope; it is stored through the
    existing content-addressed Artifact Store and recovered on demand.
    """
    home_path = Path(home)
    capsule = working_set.show_capsule(home_path, session_id)
    requirements = working_set.show_requirements(home_path, session_id)
    return {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "capsule": capsule,
        "requirements": requirements,
    }


def create_handoff_envelope(
    home: Path | str,
    session_id: str,
    *,
    source_harness: str,
    target_harness: str = "",
    target_role: str = "",
    source_task_id: str = "",
    source_role: str = "",
    project_id: str = "",
    context_refs: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    unavailable_evidence: list[str] | None = None,
) -> tuple[BrainHandoffEnvelope, BrainHandoffArtifact]:
    """Build and persist the canonical bounded Brain Handoff Envelope (§3 P3.17).

    Reuses the Active State Capsule (P3.1) and requirement ledger unmodified
    (full state, not a hand-picked subset) as the lossless payload, the
    existing content-addressed Artifact Store to hold it, and
    :func:`create_handoff` for the human-readable Markdown twin. Returns
    ``(envelope, markdown_artifact)``.
    """
    home_path = Path(home)
    if not source_harness:
        raise HandoffError("HANDOFF_MALFORMED", "source_harness is required")
    capsule = working_set.show_capsule(home_path, session_id)
    requirements = working_set.show_requirements(home_path, session_id)
    payload = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "capsule": capsule,
        "requirements": requirements,
    }
    payload_text = canonical_json(payload)
    payload_canonical_sha256 = stable_content_hash(payload)
    stored = artifacts.store_text(
        home_path, payload_text, kind="handoff_payload",
        tool="second_brain.handoff", session=session_id,
    )
    artifacts.add_ref(
        home_path, stored["hash"], owner=f"handoff:{ledger.internal_session_id(session_id)}"
    )
    payload_ref = artifacts.make_handle(stored["hash"])

    for name, values in (
        ("context_refs", context_refs),
        ("artifact_refs", artifact_refs),
        ("evidence_refs", evidence_refs),
        ("unavailable_evidence", unavailable_evidence),
    ):
        if values is not None and len(values) > HANDOFF_LIST_MAX_ITEMS:
            raise HandoffError(
                "HANDOFF_MALFORMED", f"{name} exceeds {HANDOFF_LIST_MAX_ITEMS} items"
            )

    fields: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "project_id": project_id,
        "source_harness": source_harness,
        "source_session_id": session_id,
        "source_task_id": source_task_id,
        "source_role": source_role,
        "destination_harness": target_harness,
        "destination_role": target_role,
        "capsule_ref": f"state/sessions/{session_id}/active-state.json",
        "capsule_sha256": stable_content_hash(capsule),
        "capsule_updated_at": capsule["updated_at"],
        "payload_ref": payload_ref,
        "payload_sha256": stored["hash"],
        "payload_canonical_sha256": payload_canonical_sha256,
        "context_refs": list(context_refs or []),
        "artifact_refs": list(
            artifact_refs
            if artifact_refs is not None
            else (capsule.get("artifact_refs") or [])[:HANDOFF_LIST_MAX_ITEMS]
        ),
        "evidence_refs": list(evidence_refs or []),
        "unavailable_evidence": list(unavailable_evidence or []),
        "requirement_summary": _requirement_summary(requirements),
        "created_at": _utcnow(),
    }
    handoff_id = BrainHandoffEnvelope.compute_id(fields)
    envelope = BrainHandoffEnvelope(handoff_id=handoff_id, **fields).validate()

    out_dir = home_path / "outputs" / "handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_stem(session_id)
    envelope_path = out_dir / f"handoff-{safe_stem}-{handoff_id[:12]}.json"
    envelope_path.write_text(envelope.canonical_json() + "\n", encoding="utf-8")

    artifact = create_handoff(
        home_path, session_id, target_agent=target_harness or "incoming-agent"
    )
    artifact.handoff_id = handoff_id
    artifact.envelope_ref = str(envelope_path)
    artifact.source_harness = source_harness
    artifact.capsule_sha256 = envelope.capsule_sha256
    artifact.payload_sha256 = envelope.payload_sha256
    Path(artifact.artifact_path).write_text(artifact.render_markdown(), encoding="utf-8")

    return envelope, artifact


def _classify_freshness(updated_at: str) -> str:
    try:
        ts = datetime.fromisoformat(updated_at)
    except ValueError:
        return "STALE"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - ts).total_seconds()
    return "FRESH" if 0 <= age <= HANDOFF_STALE_AFTER_SECONDS else "STALE"


def read_handoff_envelope(
    home: Path | str,
    envelope_data: Mapping[str, Any] | BrainHandoffEnvelope,
    *,
    expected_project_id: str | None = None,
    allow_stale: bool = False,
) -> dict[str, Any]:
    """Validate and losslessly recover a Brain Handoff Envelope (§3 P3.17).

    Resolves the bounded envelope to its full canonical payload through the
    existing content-addressed Artifact Store, proves every integrity
    invariant (envelope identity, payload byte hash, payload structural hash,
    capsule hash, referenced-artifact byte hashes), and returns only the
    bounded state relevant to continuation. The receiving harness never needs
    the source transcript: everything here comes from the Active State
    Capsule and requirement ledger, not conversation history.

    Raises :class:`~second_brain.contracts.HandoffError` (deterministic
    ``.code``) for every negative control: HANDOFF_SCHEMA_MISMATCH,
    HANDOFF_ID_MISMATCH (altered envelope), HANDOFF_ENVELOPE_TOO_LARGE,
    HANDOFF_PROJECT_MISMATCH, HANDOFF_STALE, HANDOFF_ARTIFACT_UNRESOLVED
    (missing/unresolvable artifact), HANDOFF_HASH_MISMATCH (altered payload
    or referenced artifact bytes).
    """
    home_path = Path(home)
    envelope = (
        envelope_data
        if isinstance(envelope_data, BrainHandoffEnvelope)
        else BrainHandoffEnvelope.from_dict(envelope_data)
    )
    envelope.validate()

    if expected_project_id and envelope.project_id != expected_project_id:
        raise HandoffError(
            "HANDOFF_PROJECT_MISMATCH",
            f"envelope project {envelope.project_id!r} != expected {expected_project_id!r}",
        )

    freshness = _classify_freshness(envelope.capsule_updated_at)
    if freshness == "STALE" and not allow_stale:
        raise HandoffError("HANDOFF_STALE", "capsule state is older than the freshness bound")

    payload_hash = artifacts.parse_ref(envelope.payload_ref)
    if payload_hash is None:
        raise HandoffError(
            "HANDOFF_MALFORMED", "payload_ref is not a recognized artifact reference"
        )
    try:
        raw = artifacts.expand(home_path, payload_hash)
    except BrainError as exc:
        raise HandoffError("HANDOFF_ARTIFACT_UNRESOLVED", f"payload unresolved: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != envelope.payload_sha256:
        raise HandoffError("HANDOFF_HASH_MISMATCH", "payload artifact bytes do not match envelope")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise HandoffError("HANDOFF_MALFORMED", f"payload is not valid JSON: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or stable_content_hash(payload) != envelope.payload_canonical_sha256
    ):
        raise HandoffError("HANDOFF_HASH_MISMATCH", "payload structure does not match envelope")

    capsule = payload.get("capsule")
    if not isinstance(capsule, dict) or stable_content_hash(capsule) != envelope.capsule_sha256:
        raise HandoffError("HANDOFF_HASH_MISMATCH", "capsule content does not match envelope")

    resolved_refs: list[dict[str, Any]] = []
    for ref in [*envelope.artifact_refs, *envelope.evidence_refs]:
        ref_hash = artifacts.parse_ref(ref)
        if ref_hash is None:
            continue  # non-artifact ref (e.g. memory:); not byte-verified here
        try:
            ref_raw = artifacts.expand(home_path, ref_hash)
        except BrainError as exc:
            raise HandoffError(
                "HANDOFF_ARTIFACT_UNRESOLVED", f"referenced artifact unresolved: {ref}"
            ) from exc
        if hashlib.sha256(ref_raw).hexdigest() != ref_hash:
            raise HandoffError("HANDOFF_HASH_MISMATCH", f"referenced artifact bytes altered: {ref}")
        resolved_refs.append({"ref": ref, "sha256": ref_hash, "bytes": len(ref_raw)})

    return {
        "handoff_id": envelope.handoff_id,
        "schema_version": envelope.schema_version,
        "project_id": envelope.project_id,
        "source_harness": envelope.source_harness,
        "source_session_id": envelope.source_session_id,
        "destination_harness": envelope.destination_harness,
        "freshness": freshness,
        "objective": capsule.get("objective"),
        "task_mode": capsule.get("task_mode"),
        "risk": capsule.get("risk"),
        "constraints": capsule.get("constraints"),
        "confirmed_facts": capsule.get("confirmed_facts"),
        "decisions_this_session": capsule.get("decisions_this_session"),
        "open_questions": capsule.get("open_questions"),
        "files_touched": capsule.get("files_touched"),
        "verification": capsule.get("verification"),
        "next_action": capsule.get("next_action"),
        "requirement_summary": envelope.requirement_summary,
        "requirements": payload.get("requirements"),
        "unavailable_evidence": envelope.unavailable_evidence,
        "resolved_artifact_refs": resolved_refs,
        "capsule_sha256": envelope.capsule_sha256,
        "payload_sha256": envelope.payload_sha256,
        "payload_canonical_sha256": envelope.payload_canonical_sha256,
        "capsule_updated_at": envelope.capsule_updated_at,
    }
