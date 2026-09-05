"""Read-only coverage inventory. Observed activity is not release qualification."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--home", type=Path, required=True)
parser.add_argument("--omp-root", type=Path, required=True)
args = parser.parse_args()
records = []
inputs = []
for file in sorted((args.home / "telemetry" / "agent-performance").glob("*.jsonl")):
    data = file.read_bytes()
    inputs.append({"name": file.name, "sha256": hashlib.sha256(data).hexdigest()})
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict):
            records.append((file.name, line_number, record))
wanted = {r.get("session") for _, _, r in records}
native_matches = defaultdict(list)
for file in sorted(args.omp_root.glob("**/*.jsonl")):
    if not {file.stem, file.stem.rsplit("_", 1)[-1]} & wanted:
        continue
    data = file.read_bytes()
    for line in data.decode("utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(entry, dict)
            and entry.get("type") == "session"
            and isinstance(entry.get("id"), str)
        ):
            digest = hashlib.sha256(data).hexdigest()
            for alias in {file.stem, entry["id"]} & wanted:
                native_matches[alias].append(
                    {
                        "path": file.as_posix(),
                        "sha256": digest,
                        "version": entry.get("version"),
                        "native_session_id": entry["id"],
                    }
                )
            break
native = {
    alias: {**matches[0], "matched_transcripts": matches}
    for alias, matches in native_matches.items()
    if len({match["native_session_id"] for match in matches}) == 1
}
by_session = defaultdict(list)
for _, _, record in records:
    session = record.get("session")
    if session in native:
        by_session[native[session]["native_session_id"]].append(record)
turns, calls, handoffs, terminals = set(), set(), set(), set()
paired_compactions = 0
for session, rows in by_session.items():
    pending_compaction = False
    for record in sorted(rows, key=lambda r: str(r.get("ts", ""))):
        kind = record.get("kind")
        if kind == "turn_start":
            turns.add((session, record.get("turn"), record.get("ts")))
        elif kind == "tool_call" and record.get("id"):
            calls.add((session, record["id"]))
        elif kind == "omp_worker_context_handoff" and record.get("task_id"):
            handoffs.add((session, record["task_id"]))
        elif kind == "omp_worker_child_result" and record.get("task_id"):
            terminals.add((session, record["task_id"], record.get("status")))
        elif kind == "session_before_compact":
            pending_compaction = True
        elif kind == "session_compact" and pending_compaction:
            paired_compactions += 1
            pending_compaction = False
print(
    json.dumps(
        {
            "method": "Native-header activity; source/deployment epoch requires separate proof",
            "telemetry_inputs": inputs,
            "native_transcripts_local_only": native,
            "observed": {
                "native_sessions_with_telemetry": len(by_session),
                "turn_events_deduplicated": len(turns),
                "tool_calls_deduplicated": len(calls),
                "prepared_handoffs_not_launches": len(handoffs),
                "brain_terminal_observations": dict(Counter(status for _, _, status in terminals)),
                "ordered_compaction_pairs_without_canary_verification": paired_compactions,
                "unmatched_or_ambiguous_session_ids_not_rejected": sorted(
                    str(s) for s in wanted if s not in native
                ),
            },
            "qualified_final_candidate": {
                "natural_successes": 0,
                "observed_natural_successes": 0,
                "durably_accepted_natural_successes": 0,
                "missing_results": None,
                "duplicate_terminal_transitions": None,
                "remaining_natural_success_target": 20,
                "reason": "No frozen live qualification epoch for the final candidate",
            },
            "historical_qualified_totals_not_reestablished": {
                "clean_restarts": None,
                "controlled_project_switches": None,
                "verified_compaction_continuations": None,
                "actual_worker_launches": None,
                "reason": "Link launch/resume/canary proof to source and installation per sequence",
            },
        },
        indent=2,
        sort_keys=True,
    )
)
