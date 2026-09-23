"""Historical host-patch seals are bound to their original subject, not HEAD."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "docs/integrations/omp-host-patch-2026-09-19"
SUCCESSOR = ROOT / "docs/integrations/omp-host-patch-2026-09-19-successor"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_budget_bridge_identity_is_recoverable_from_sealed_commit() -> None:
    identity = json.loads((SUCCESSOR / "CANDIDATE-IDENTITY.json").read_text(encoding="utf-8"))
    subject = identity["subject"]["commit"]
    name = "brainstem/prime-extension/src/budget-bridge.ts"
    historical = subprocess.run(
        ["git", "show", f"{subject}:{name}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.replace(b"\r\n", b"\n")
    assert hashlib.sha256(historical).hexdigest() == identity["files"][name]


def test_sealed_approval_records_still_bind_their_own_bytes() -> None:
    approval = json.loads((SUCCESSOR / "APPROVED-SUCCESSOR.json").read_text(encoding="utf-8"))
    for filename, field in (
        ("SUCCESSOR-RECORD.json", "record_sha256"),
        ("RUN-IDENTITIES.json", "identities_file_sha256"),
        ("HASHES.txt", "hashes_file_sha256"),
        ("SHIPPING-CANDIDATE-MANIFEST.json", "shipping_candidate_manifest_sha256"),
    ):
        assert _hash(SUCCESSOR / filename) == approval[field]
    predecessor = json.loads(
        (PREDECESSOR / "SHIPPING-CANDIDATE-MANIFEST.json").read_text(encoding="utf-8")
    )["candidate"]
    assert _hash(PREDECESSOR / "RUN-IDENTITIES.json") == predecessor["identities_file_sha256"]
    assert _hash(PREDECESSOR / "HASHES.txt") == predecessor["hashes_file_sha256"]
