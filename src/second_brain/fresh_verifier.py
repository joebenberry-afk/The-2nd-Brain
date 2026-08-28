"""
Fresh Verifier "record" plumbing (plan §15, Phase R9).

`brainstem/policies/verifier-role.md` states the contract but flags itself
"no hard enforcement yet — Phase D2 will wire a fresh-verifier delegation
path." The "prepare" half of that path already exists:
`verify.build_verifier_brief()` (Phase 7) builds a real, deterministic,
backward-reconstruction brief from a session's working set. This module is
the missing other half: capturing what a genuinely fresh session actually
returned, and parsing its verdict from that — never inventing one.

It never invents a verdict. `parse_verdict()` only ever reads a raw
response that was actually produced, and returns UNPARSEABLE rather than
guessing when the expected shape isn't present.

Provenance fields (model, provider, host, session/conversation ID) are
supplied by the caller and recorded as given; a missing session ID is
recorded as `{"available": false, "reason": ...}` (plan Rule B), never
invented. Usage fields absent from the caller are recorded as `null`
(plan Rule A) - the caller either had the real value or didn't.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

VERDICT_LINE_RE = re.compile(
    r"^\s*(?:result|verdict)\s*[:\-]\s*(PASS|FAIL|PARTIAL)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CONFIDENCE_RE = re.compile(
    r"^\s*confidence\s*[:\-]\s*([0-9]*\.?[0-9]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class VerifierProvenance:
    """Caller-supplied, never inferred. A missing session_id is recorded as
    unavailable (plan Rule B), never fabricated."""

    provider: str | None
    model: str | None
    host: str | None
    session_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def session_id_dict(self) -> dict[str, Any]:
        if self.session_id:
            return {"available": True, "value": self.session_id}
        return {"available": False, "reason": "host does not expose provider run ID"}

    def usage_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": (
                self.input_tokens + self.output_tokens
                if self.input_tokens is not None and self.output_tokens is not None
                else None
            ),
        }


@dataclass
class VerifierVerdict:
    """Parsed strictly from a raw response that already exists. UNPARSEABLE
    when the expected `Result: PASS|FAIL|PARTIAL` line is absent — never a
    guessed default."""

    verdict: str  # "PASS" | "FAIL" | "PARTIAL" | "UNPARSEABLE"
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "confidence": self.confidence}


def parse_verdict(raw_response: str) -> VerifierVerdict:
    """
    Parse a verdict from an ALREADY-PRODUCED raw response. Never called
    before the raw response exists; never returns PASS/FAIL/PARTIAL unless
    the exact expected marker line is present in the text.
    """
    match = VERDICT_LINE_RE.search(raw_response)
    if not match:
        return VerifierVerdict(verdict="UNPARSEABLE")
    confidence_match = CONFIDENCE_RE.search(raw_response)
    confidence = float(confidence_match.group(1)) if confidence_match else None
    return VerifierVerdict(verdict=match.group(1).upper(), confidence=confidence)


def bounded_independent_verification(
    *,
    raw_response: str,
    verification_id: str,
    task_id: str,
    verifier_session_id: str,
    implementation_session_id: str,
    task_hash: str,
    requirements_hash: str,
    diff_hash: str,
    evidence_set_hash: str,
    failed_requirement_ids: list[str] | None = None,
    unresolved_requirement_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded verdict metadata without persisting verifier response text."""
    verdict = parse_verdict(raw_response)
    reason_codes: list[str] = []
    hashes = (task_hash, requirements_hash, diff_hash, evidence_set_hash)
    hashes_valid = all(re.fullmatch(r"[0-9a-f]{64}", value or "") for value in hashes)
    distinct = bool(verifier_session_id and implementation_session_id) and (
        verifier_session_id != implementation_session_id
    )
    freshness = "fresh" if distinct and hashes_valid else "invalid"
    if not distinct:
        reason_codes.append("self_verification")
    if not hashes_valid:
        reason_codes.append("evidence_identity_invalid")
    effective_verdict = verdict.verdict if freshness == "fresh" else "UNPARSEABLE"
    if effective_verdict == "UNPARSEABLE":
        reason_codes.append("verdict_unparseable")
    return {
        "verification_id": verification_id,
        "task_id": task_id,
        "verifier_session_id": verifier_session_id,
        "implementation_session_id": implementation_session_id,
        "task_hash": task_hash,
        "requirements_hash": requirements_hash,
        "diff_hash": diff_hash,
        "evidence_set_hash": evidence_set_hash,
        "verdict": effective_verdict,
        "confidence": verdict.confidence,
        "failed_requirement_ids": list(failed_requirement_ids or []),
        "unresolved_requirement_ids": list(unresolved_requirement_ids or []),
        "reason_codes": reason_codes,
        "freshness": freshness,
    }


@dataclass
class VerifierEvidence:
    """The full capture: prompt, raw response, provenance, usage, and the
    verdict parsed from the raw response — in that order, matching plan
    §15's "The parsed JSON must be created AFTER the raw response.\""""

    prompt: str
    raw_response: str
    provenance: VerifierProvenance
    verdict: VerifierVerdict
    captured_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "provider": self.provenance.provider,
            "model": self.provenance.model,
            "host": self.provenance.host,
            "session_id": self.provenance.session_id_dict(),
            "usage": self.provenance.usage_dict(),
            "verdict": self.verdict.to_dict(),
            "captured_at": self.captured_at,
        }


def record_verifier_response(
    prompt: str,
    raw_response: str,
    provenance: VerifierProvenance,
) -> VerifierEvidence:
    """
    Build the final evidence bundle from a raw response the caller already
    has in hand. Verdict is parsed here, strictly after `raw_response`
    exists as an argument — this function cannot be called before a real
    response is available.
    """
    return VerifierEvidence(
        prompt=prompt,
        raw_response=raw_response,
        provenance=provenance,
        verdict=parse_verdict(raw_response),
        captured_at=datetime.now(UTC).isoformat(),
    )
