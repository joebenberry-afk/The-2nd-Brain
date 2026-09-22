"""Conformance harness: judge a host bridge against BrainHostProtocol v1.

Reads the advertisement a bridge prints (a disposable candidate install prints it —
never the production extension) and reports which Brain features that host may run.
Also validates any observation samples the bridge emitted.

Exit status is 0 only when every payload validated. Feature refusals are *reported*,
not failures: a host that cannot attest cleanup is conformant, it simply may not run
mutating delegation.

    python scripts/host-bridge-conformance.py --advertisement adv.json [--observations obs.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from second_brain import host_protocol


def _read_bytes(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    return Path(path).read_bytes()


def _read_observations(path: str) -> list[bytes]:
    raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    return [line for line in raw.splitlines() if line.strip()]


def _render(decision: dict) -> Iterable[str]:
    host = decision["host"]
    features = decision["features"]
    yield f"Host:   {host['vendor']}/{host['name']} {host['version']}"
    yield f"Bridge: {decision['bridge']['name']} {decision['bridge']['version']}"
    yield f"Protocol: BrainHostProtocol v{decision['protocol_version']}"
    digest = decision["advertisement_sha256"][:16]
    yield f"Provenance: {decision['provenance']} (advertisement {digest}…)"
    yield ""
    yield "Capabilities"
    yield "──────────────────────────────────────"
    for name, available in decision["capabilities"].items():
        yield f"  {name:<28} {'yes' if available else 'no'}"
    yield ""
    yield "Features"
    yield "──────────────────────────────────────"
    for name, info in sorted(features.items()):
        mark = "enabled" if info["enabled"] else "REFUSED"
        narrowed = f"; narrowed by {', '.join(info['narrowed_by'])}" if info["narrowed_by"] else ""
        yield f"  {name:<24} {mark:<8} {info['reason']}{narrowed}"
    yield ""
    availability = sorted(name for name, info in features.items() if info["enabled"])
    unavailable = sorted(name for name, info in features.items() if not info["enabled"])
    yield f"Available:   {', '.join(availability)}"
    yield f"Unavailable: {', '.join(unavailable) or '(none)'}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--advertisement", required=True, help="bridge advertisement JSON ('-' for stdin)"
    )
    parser.add_argument(
        "--observations", default=None, help="optional JSONL of observation samples"
    )
    parser.add_argument("--json", action="store_true", help="emit the decision as JSON only")
    parser.add_argument(
        "--qualified-identity",
        default=None,
        help=(
            "JSON record {vendor,name,version,advertisement_sha256,bridge_sha256} qualifying "
            "this host; without it every safety feature is refused"
        ),
    )
    args = parser.parse_args()

    raw_advertisement = _read_bytes(args.advertisement)
    provenance = None
    if args.qualified_identity:
        try:
            record = host_protocol.loads_strict(_read_bytes(args.qualified_identity))
            if not isinstance(record, dict):
                raise host_protocol.HostProtocolError(
                    "MALFORMED_QUALIFICATION", "the qualification record must be an object"
                )
            qualified = host_protocol.QualifiedHostIdentity(**record)
            provenance = host_protocol.verify_advertisement(
                raw_advertisement, qualified=qualified
            )
        except host_protocol.HostProtocolError as exc:
            print(
                json.dumps(
                    {
                        "provenance": "refused",
                        "code": exc.code,
                        "message": exc.message,
                        "consequence": "safety features remain refused",
                    },
                    indent=2,
                )
            )
            return 3
        except TypeError as exc:
            print(json.dumps({"provenance": "malformed", "message": str(exc)}, indent=2))
            return 3

    try:
        decision = host_protocol.negotiate(raw_advertisement, provenance=provenance)
    except host_protocol.HostProtocolError as exc:
        print(json.dumps({"conformant": False, "code": exc.code, "message": exc.message}, indent=2))
        return 2

    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    else:
        print("\n".join(_render(decision)))

    if args.observations is not None:
        samples = _read_observations(args.observations)
        validated: list[str] = []
        for sample in samples:
            try:
                parsed = host_protocol.parse_observation(host_protocol.loads_strict(sample))
            except host_protocol.HostProtocolError as exc:
                print(f"\nOBSERVATION REFUSED: {exc.code}: {exc.message}")
                return 2
            validated.append(parsed["kind"])
        kinds = ", ".join(sorted(set(validated)))
        print(f"\nObservations validated: {len(validated)} ({kinds})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
