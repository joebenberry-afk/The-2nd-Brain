"""Native-orchestration non-interference probe (M00-NATIVE-ORCH-01).

Explicitly invoked evidence tool, not part of any runtime path. It runs the
installed host CLI in print/JSON mode against two extension conditions
(Second Brain absent vs. loaded from this repository) and compares only what
the *host* surfaced: whether a native single spawn and a native batch spawn
completed, and whether any Brain-side interference marker appeared.

Safety properties (do not relax them):
  * every arm runs with ``--no-session`` into a throwaway session directory;
  * the project directory is an empty temp directory;
  * the Brain-on arm gets a disposable ``SECOND_BRAIN_HOME``, so no arm can
    read or write live Second Brain state;
  * the probe never loads a production extension by default, and when it is
    asked to load one (``--installed``) that arm also gets the disposable home;
  * the disposable brain home is removed unless ``--keep-home`` is passed.

``--memory-check`` runs the retained memory/context real-path differential on the
same arm machinery and under the same safety rules. Each arm gets its own
disposable home seeded through retained write paths (``init`` -> ``project add``
-> ``remember --grade OBSERVED``) with one memory carrying a unique
``MEMPROBE-<hex>`` token, and the two arms differ only in whether the candidate
extension is loaded. Verdicts are read from the host's own JSON event stream --
in particular the ``role: "custom"`` message the host records for
extension-injected context -- never from the model's prose alone. The payload
also records, per arm, whether the child subagent's delivered answer carried the
token, as an observation rather than a pass/fail.

Usage:
    python scripts/native_noninterference_probe.py --out docs/intake/m00-evidence
    python scripts/native_noninterference_probe.py --memory-check
    python scripts/native_noninterference_probe.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SINGLE_PROMPT = (
    "Call the task tool exactly once, with agent 'sonic' and task "
    "'Reply with exactly: PROBE-OK. Do no other work.' Do not call any other tool. "
    "Then output one line of the form: RESULT <subagent id or status>"
)
BATCH_PROMPT = (
    "Call the task tool exactly once with a tasks array of exactly two items, both "
    "with agent 'sonic' and names ProbeA and ProbeB, each tasked with "
    "'Reply with exactly: PROBE-OK. Do no other work.' Do not call any other tool. "
    "Then output one line of the form: RESULT <how many subagent results you received>"
)

# --- memory/context real-path differential (--memory-check) ------------------
#
# One prompt for both arms. It asks the parent only about the TOKEN PREFIX, so
# the full MEMPROBE-<hex> token can reach the model through exactly one path:
# the extension-injected context. The child task text is the same question, so a
# child that quotes the full token received Brain context itself; the parent is
# told not to pass its own token down, which keeps that observation clean.
MEMPROBE_PREFIX = "MEMPROBE-"
MEMORY_PROMPT = (
    "Answer from your current context only. Does your context contain a token that "
    "starts with MEMPROBE-? If it does, quote that exact token. Then call the task "
    "tool exactly once with agent 'sonic' and the task 'Does your context contain a "
    "token starting with MEMPROBE-? Reply with that exact token, or NONE.' Do not "
    "put your own token in the child task text. Wait for the child result, then "
    "print one final line: RESULT <your token or NONE> CHILD <child token or NONE>"
)
# The token is minted per arm; the claim is what `remember` stores.
MEMORY_PROJECT_ID = "memprobe-temp"
MEMORY_CLAIM = "MEMPROBE context token: the current session context token is {token}."
# The custom_message type the extension returns from before_agent_start; the host
# records it in the event stream as a role:"custom" message. Verified in
# brainstem/prime-extension/src/autoinject.ts (AUTOINJECT_CUSTOM_TYPE).
INJECTED_CONTEXT_CUSTOM_TYPE = "brain.autoinject.packet"
# The three interference families this mode asserts are absent: Brain worker /
# admission markers, coordinator authorization, and the removed orchestration
# path itself.
MEMORY_INTERFERENCE_MARKERS = (
    "BRAIN_WORKER_",
    "UNAUTHORIZED_COORDINATOR",
    "ORCHESTRATION_REMOVED",
)
MEMORY_INTERFERENCE_AUTOMODE = "advisory"
MEMORY_SELF_TEST_TOKEN = MEMPROBE_PREFIX + "deadbeef"
# The host's own envelope for a child result delivered back into the parent's
# stream (seen in both an ``async-result`` custom message and a ``hub wait``
# tool result). Its presence is the delivery evidence; prose is not.
TASK_RESULT_MARKER = "<task-result"

# Markers that mean Second Brain interfered with host orchestration. The set is
# derived from the removed governed-orchestration subsystem, so its absence in a
# Brain-on run is the observation this probe exists to make.
INTERFERENCE_MARKERS = (
    "UNAUTHORIZED_COORDINATOR",
    "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE",
    "BRAIN_WORKER_ADMISSION",
    "brain_worker_admission",
    "driver_contract_",
    "orchestrator_policy_violation",
    "reserved_budget_required",
)

# Proves the extractor can see interference at all; a probe that cannot detect a
# marker is not evidence of its absence. Exercised by --self-test.
SELF_TEST_SAMPLE = "\n".join(
    [
        json.dumps(
            {
                "type": "tool_execution_start",
                "toolName": "task",
                "args": {"tasks": [{"name": "A", "agent": "sonic"}]},
            }
        ),
        json.dumps(
            {
                "type": "tool_execution_end",
                "toolName": "task",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE",
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "RESULT none"}],
                },
            }
        ),
    ]
)

# Same purpose as SELF_TEST_SAMPLE, for the memory/context extractor: a probe
# that cannot see a token inside a host-recorded injected context message is not
# evidence of its absence. Shapes copied from a real host stream (role "custom"
# message_start/message_end pairs, and the child's delivered async-result).
MEMORY_SELF_TEST_SAMPLE = "\n".join(
    [
        json.dumps(
            {
                "type": "message_start",
                "message": {
                    "role": "custom",
                    "customType": INJECTED_CONTEXT_CUSTOM_TYPE,
                    "content": (
                        "[BRAIN_CONTEXT_DELTA v1]\nauthority: advisory\n"
                        f"observation: the token is {MEMORY_SELF_TEST_TOKEN}\n"
                    ),
                    "display": True,
                },
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "custom",
                    "customType": INJECTED_CONTEXT_CUSTOM_TYPE,
                    "content": (
                        "[BRAIN_CONTEXT_DELTA v1]\nauthority: advisory\n"
                        f"observation: the token is {MEMORY_SELF_TEST_TOKEN}\n"
                    ),
                    "display": True,
                },
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "custom",
                    "customType": "async-result",
                    "content": (
                        f'<task-result id="ProbeChild">{MEMORY_SELF_TEST_TOKEN}</task-result>'
                    ),
                },
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"RESULT {MEMORY_SELF_TEST_TOKEN} "
                                f"CHILD {MEMORY_SELF_TEST_TOKEN}"
                            ),
                        }
                    ],
                },
            }
        ),
    ]
)


def _spawn_names(args: dict) -> tuple[list[str], list[str]]:
    """(names, agents) requested in one task-tool call, single or batch shape."""
    tasks = args.get("tasks")
    if isinstance(tasks, list):
        return (
            [str(t.get("name", "")) for t in tasks if isinstance(t, dict)],
            [str(t.get("agent", "")) for t in tasks if isinstance(t, dict)],
        )
    if args.get("task") is not None:
        return ([str(args.get("name", ""))], [str(args.get("agent", ""))])
    return ([], [])


def _unique_custom(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Dedupe (customType, text) pairs: the host emits start and end for one message."""
    seen: dict[tuple[str, str], None] = {}
    for pair in pairs:
        seen.setdefault(pair, None)
    return list(seen)


def _message_text(message: dict) -> str:
    """Text of one host message record, for either content shape."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return ""


def summarize_arm(raw: str, token: str | None = None) -> dict[str, Any]:
    """Host-observable summary of one arm's JSON event stream.

    ``token`` is the memory arm's probe token. When given, the summary records
    where the *host itself* put that token: inside the ``role: "custom"`` message
    it records for extension-injected context, in assistant text, in a delivered
    task result, or in the arguments of the spawn call (the parent echoing it
    down would confound the child observation).
    """
    spawns: list[dict[str, Any]] = []
    other_tools: list[str] = []
    final_text: list[str] = []
    custom_pairs: list[tuple[str, str]] = []
    spawn_args: list[str] = []
    role_text: dict[str, list[str]] = {}
    task_result_records: list[tuple[str, str, str]] = []
    events = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        events += 1
        kind = event.get("type")
        if kind == "tool_execution_start":
            name = event.get("toolName")
            if name == "task":
                args = event.get("args") or {}
                spawn_args.append(json.dumps(args, sort_keys=True))
                names, agents = _spawn_names(args)
                spawns.append({"names": names, "agents": agents})
            else:
                other_tools.append(str(name))
        elif kind == "tool_execution_end" and event.get("toolName") == "task":
            text = json.dumps(event.get("result"))
            if spawns:
                spawns[-1]["result"] = text[:300]
                spawns[-1]["refused"] = "Spawned" not in text
        elif kind in ("message_start", "message_end"):
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", ""))
            text = _message_text(message)
            role_text.setdefault(role, []).append(text)
            if TASK_RESULT_MARKER in text:
                # The host's own envelope for a delivered child result.
                task_result_records.append(
                    (
                        role,
                        str(message.get("customType", "")) if role == "custom" else role,
                        text,
                    )
                )
            if role == "custom":
                custom_pairs.append((str(message.get("customType", "")), text))
            if kind == "message_end" and role == "assistant":
                for part in message.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "text":
                        final_text.append(str(part.get("text", "")))

    markers = {name: raw.count(name) for name in INTERFERENCE_MARKERS}
    summary: dict[str, Any] = {
        "event_count": events,
        "spawn_calls": len(spawns),
        "spawns": spawns,
        "spawned_agents": [n for s in spawns if not s.get("refused") for n in s["names"]],
        "refused_spawns": [n for s in spawns if s.get("refused") for n in s["names"]],
        "other_tool_calls": other_tools,
        "final_text": final_text[-1:] if final_text else [],
        "interference_markers": {k: v for k, v in markers.items() if v},
        "interference_total": sum(markers.values()),
        "record_roles": {role: len(texts) for role, texts in sorted(role_text.items())},
        "custom_messages": [
            {"customType": custom_type, "chars": len(text), "head": text[:200]}
            for custom_type, text in _unique_custom(custom_pairs)
        ],
        "custom_types": sorted({custom_type for custom_type, _ in custom_pairs}),
        "task_result_records": {
            "unique": len({(role, kind) for role, kind, _ in task_result_records}),
            "roles": sorted({role for role, _, _ in task_result_records}),
        },
        "token_evidence": None,
    }
    if token:
        summary["token_evidence"] = {
            "token": token,
            "stream_hits": raw.count(token),
            "injected_context_records": sorted(
                {
                    custom_type
                    for custom_type, text in custom_pairs
                    if token in text and custom_type == INJECTED_CONTEXT_CUSTOM_TYPE
                }
            ),
            "other_custom_records": sorted(
                {
                    custom_type
                    for custom_type, text in custom_pairs
                    if token in text and custom_type != INJECTED_CONTEXT_CUSTOM_TYPE
                }
            ),
            "in_assistant_text": any(token in text for text in role_text.get("assistant", [])),
            "in_tool_result": any(token in text for text in role_text.get("toolResult", []))
            or any(token in json.dumps(s.get("result", "")) for s in spawns),
            "in_spawn_args": any(token in args for args in spawn_args),
            # The child's own reply, as delivered back into the parent stream by
            # the host's task-result envelope (never the parent's spawn args).
            "in_child_result": any(token in text for _, _, text in task_result_records),
        }
        summary["memory_interference_markers"] = {
            name: raw.count(name) for name in MEMORY_INTERFERENCE_MARKERS if raw.count(name)
        }
        summary["memory_interference_total"] = sum(
            raw.count(name) for name in MEMORY_INTERFERENCE_MARKERS
        )
    return summary


def run_arm(
    name: str,
    *,
    prompt: str,
    extension: Path | None,
    brain_home: Path | None,
    brain_python: Path,
    model: str,
    omp: str,
    timeout: int,
    workdir: Path,
    env_extra: dict[str, str] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    tmp = workdir / name
    (tmp / "proj").mkdir(parents=True, exist_ok=True)
    cmd = [
        omp,
        "-p",
        "--mode",
        "json",
        "--model",
        model,
        "--no-session",
        "--session-dir",
        str(tmp / "sessions"),
        "--cwd",
        str(tmp / "proj"),
        "--no-extensions",
    ]
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update(env_extra or {})
    if extension is not None:
        assert brain_home is not None
        cmd += ["-e", str(extension)]
        env["SECOND_BRAIN_HOME"] = str(brain_home)
        env["SECOND_BRAIN_PYTHON"] = str(brain_python)
    cmd.append(prompt)

    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc = None
        raw_out = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else exc.stdout
        )
        out = raw_out or ""
        err = f"TIMEOUT after {timeout}s"
    wall = round(time.time() - started, 1)
    (tmp / "raw.jsonl").write_text(out, encoding="utf-8")
    (tmp / "stderr.txt").write_text(err, encoding="utf-8")

    summary = summarize_arm(out, token=token)
    summary.update(
        {
            "arm": name,
            "extension": str(extension) if extension else None,
            "returncode": rc,
            "wall_seconds": wall,
            "raw_path": str(tmp / "raw.jsonl"),
            "argv": cmd,
            "stderr_tail": err[-400:],
        }
    )
    return summary


def build_arms(
    extension: Path | None, installed: Path | None
) -> list[tuple[str, str, Path | None]]:
    arms: list[tuple[str, str, Path | None]] = [
        ("brain_off_single", SINGLE_PROMPT, None),
        ("brain_on_single", SINGLE_PROMPT, extension),
        ("brain_off_batch", BATCH_PROMPT, None),
        ("brain_on_batch", BATCH_PROMPT, extension),
    ]
    if installed is not None:
        # Sensitivity control: the pre-removal build installed on this host. Its
        # refusal of the same prompt is what makes the candidate arms' clean
        # result meaningful rather than an artefact of an insensitive probe.
        arms.append(("installed_build_single", SINGLE_PROMPT, installed))
    return arms


def verdicts(arms: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(a["arm"]): a for a in arms}
    on_single = by_name.get("brain_on_single", {})
    on_batch = by_name.get("brain_on_batch", {})
    off_single = by_name.get("brain_off_single", {})
    control = by_name.get("installed_build_single")

    def spawned(arm: dict[str, Any], count: int) -> bool:
        return len(arm.get("spawned_agents") or []) == count

    return {
        "C1_native_single_spawn_succeeds": bool(spawned(on_single, 1)),
        "C2_native_batch_spawn_succeeds": bool(spawned(on_batch, 2)),
        "C5_no_brain_settlement_permission_needed": bool(
            spawned(on_single, 1) and not on_single.get("interference_total")
        ),
        "C6_no_unauthorized_coordinator": "UNAUTHORIZED_COORDINATOR"
        not in (on_single.get("interference_markers") or {}),
        "C7_no_worker_admission_required": bool(spawned(on_single, 1)),
        "C8_no_budget_reservation_prerequisite": "reserved_budget_required"
        not in (on_single.get("interference_markers") or {}),
        "C9_no_coordinator_instruction_injection": not any(
            k in (on_single.get("interference_markers") or {})
            for k in ("driver_contract_", "orchestrator_policy_violation")
        ),
        "C12_brain_on_matches_brain_off_spawn_semantics": (
            [s["names"] for s in (on_single.get("spawns") or [])]
            == [s["names"] for s in (off_single.get("spawns") or [])]
            and bool(spawned(on_single, 1))
            and bool(spawned(off_single, 1))
        ),
        "probe_sensitivity_demonstrated": (
            None
            if control is None
            else not spawned(control, 1) and bool(control.get("interference_total"))
        ),
    }


def _home_inventory(home: Path) -> list[str]:
    """Files written into a home, relative and bounded, for payload attribution."""
    try:
        return sorted(str(f.relative_to(home)) for f in home.rglob("*") if f.is_file())
    except OSError:
        return []


def _is_temp_path(path: Path) -> bool:
    """True when ``path`` lives under the OS temp root (disposable by construction)."""
    try:
        Path(path).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except (OSError, ValueError):
        return False


def build_memory_arms(extension: Path | None) -> list[dict[str, Any]]:
    """The two memory/context arms: identical prompt/model, extension on vs off."""
    return [
        {"name": "memory_off", "prompt": MEMORY_PROMPT, "extension": None},
        {"name": "memory_on", "prompt": MEMORY_PROMPT, "extension": extension},
    ]


def seed_memory(
    home: Path,
    project: Path,
    *,
    brain_python: Path,
    token: str,
    timeout: int,
) -> dict[str, Any]:
    """Put one injectable memory into a disposable home through retained paths.

    ``init`` -> ``project add`` (registry row + manifest, so the throwaway project
    directory resolves to a real id instead of ``default``, which the retrieval
    gate treats as unknown) -> ``remember --grade OBSERVED``. The token reaches
    the model only through the extension-injected context, never through the
    prompt. Returns the exact command lines and outputs so the payload pins how
    the memory got there.
    """
    home.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["SECOND_BRAIN_HOME"] = str(home)
    claim = MEMORY_CLAIM.format(token=token)
    steps = [
        (["-m", "second_brain", "init"], home),
        (
            [
                "-m",
                "second_brain",
                "project",
                "add",
                str(project),
                "--id",
                MEMORY_PROJECT_ID,
                "--no-marker",
            ],
            home,
        ),
        (["-m", "second_brain", "remember", claim, "--grade", "OBSERVED"], project),
    ]
    commands: list[dict[str, Any]] = []
    ok = True
    for argv, cwd in steps:
        cmd = [str(brain_python), *argv]
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env
        )
        commands.append(
            {
                "command": cmd,
                "cwd": str(cwd),
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip()[-200:],
                "stderr": proc.stderr.strip()[-200:],
            }
        )
        if proc.returncode != 0:
            ok = False
            break
    return {
        "ok": ok,
        "home": str(home),
        "project": str(project),
        "home_is_temp_dir": _is_temp_path(home),
        "project_id": MEMORY_PROJECT_ID,
        "token": token,
        "claim": claim,
        "commands": commands,
    }


def brain_delivery_state(home: Path, token: str) -> dict[str, Any]:
    """Brain-side corroboration read from the disposable home (diagnostic only).

    The extension persists the message it returned from ``before_agent_start`` in
    ``state/autoinject-emit-cache.json``. Reading it distinguishes "the extension
    computed an injectable packet" from "the host did not put it in the stream",
    which is exactly the difference the host-stream verdict cannot see.
    """
    path = home / "state" / "autoinject-emit-cache.json"
    state: dict[str, Any] = {"emit_cache": str(path), "present": False}
    if not path.is_file():
        return state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    entries = [e for e in data.values() if isinstance(e, dict)] if isinstance(data, dict) else []
    contents = [
        str((e.get("message") or {}).get("content", ""))
        for e in entries
        if isinstance(e.get("message"), dict)
    ]
    outcomes = [e.get("outcome") or {} for e in entries]
    state.update(
        {
            "present": True,
            "entries": len(entries),
            "decisions": sorted({str(o.get("decision")) for o in outcomes}),
            "reasons": sorted({str(o.get("reason")) for o in outcomes}),
            # Two different project ids on purpose: the entry's own provenance is
            # the extension-side resolution (env-only), while the outcome's is what
            # the CLI actually resolved for the request that rendered the packet.
            # Key names are the extension's serialized TS shape
            # (AutoInjectShadowOutcome / PersistedEmitEntry in autoinject.ts), not
            # the CLI's snake_case stdout.
            "entry_project_ids": sorted({str(e.get("projectId")) for e in entries}),
            "outcome_project_ids": sorted({str(o.get("projectId")) for o in outcomes}),
            "outcome_project_resolutions": sorted(
                {str(o.get("projectResolution")) for o in outcomes}
            ),
            "delivery_ids": sorted(
                {str(o.get("deliveryId")) for o in outcomes if o.get("deliveryId")}
            ),
            "message_chars": [len(c) for c in contents],
            "token_in_cached_packet": any(token in c for c in contents),
        }
    )
    return state


def canonical_home_state() -> dict[str, Any]:
    """Read-only snapshot of the canonical Brain home, if it can be located.

    Resolution mirrors the runtime (``SECOND_BRAIN_HOME`` first, then the
    packaged default) and touches nothing: a missing candidate is recorded as
    absent rather than created.
    """
    candidates: list[Path] = []
    env_home = (os.environ.get("SECOND_BRAIN_HOME") or "").strip()
    if env_home:
        candidates.append(Path(env_home))
    profile = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    if profile:
        candidates.append(Path(profile) / "Documents" / "The-Second-Brain")
    state: dict[str, Any] = {
        "env_home": env_home,
        "candidates": [str(c) for c in candidates],
        "found": None,
        "db": None,
        "db_size": None,
        "db_mtime_ns": None,
        "db_wal": None,
        "db_wal_size": None,
        "db_wal_mtime_ns": None,
    }
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        db = candidate / "db" / "brain.sqlite"
        state["found"] = str(candidate)
        state["db"] = str(db)
        if db.is_file():
            stat = db.stat()
            state["db_size"] = stat.st_size
            state["db_mtime_ns"] = stat.st_mtime_ns
        wal = candidate / "db" / "brain.sqlite-wal"
        state["db_wal"] = str(wal)
        if wal.is_file():
            wal_stat = wal.stat()
            state["db_wal_size"] = wal_stat.st_size
            state["db_wal_mtime_ns"] = wal_stat.st_mtime_ns
        break
    return state


def memory_observations(arms: list[dict[str, Any]]) -> dict[str, Any]:
    """What the host stream shows about the token and about the child subagent.

    The child runs in its own session under ``--no-session``, so its own stream is
    not recorded anywhere. The only host-side evidence of what the child received
    is the reply text the host delivered back to the parent.
    """
    by_name = {str(a["arm"]): a for a in arms}
    on = by_name.get("memory_on", {})
    off = by_name.get("memory_off", {})
    on_facts = on.get("token_evidence") or {}
    off_facts = off.get("token_evidence") or {}
    delivered = bool((on.get("task_result_records") or {}).get("unique"))
    child_quoted = bool(on_facts.get("in_child_result"))
    return {
        "child_result_delivered_to_parent_stream": delivered,
        "child_result_quoted_token": child_quoted if delivered else None,
        "child_received_brain_context": child_quoted if delivered else None,
        "child_evidence_note": (
            "The child session is not persisted under --no-session, so this is read "
            "from the reply text the host delivered to the parent, not from the "
            "child's own stream. Delivery is the host's own <task-result> envelope; "
            "the parent was told not to pass its token down, and in_spawn_args "
            "records whether it did."
        ),
        "on_task_result_records": on.get("task_result_records"),
        "off_task_result_records": off.get("task_result_records"),
        "token_in_spawn_args_brain_on": bool(on_facts.get("in_spawn_args")),
        "token_in_spawn_args_brain_off": bool(off_facts.get("in_spawn_args")),
        "brain_off_token_evidence": off_facts,
        "brain_on_final_text": on.get("final_text"),
        "brain_off_final_text": off.get("final_text"),
    }


def memory_verdicts(arms: list[dict[str, Any]]) -> dict[str, Any]:
    """The memory/context checks, each read from the host's own event stream."""
    by_name = {str(a["arm"]): a for a in arms}
    on = by_name.get("memory_on", {})
    off = by_name.get("memory_off", {})
    on_facts = on.get("token_evidence") or {}
    off_facts = off.get("token_evidence") or {}
    on_markers = on.get("memory_interference_markers") or {}

    return {
        "N1_injected_context_record_in_host_stream": bool(
            on_facts.get("injected_context_records")
        ),
        "N2_parent_reports_token": bool(on_facts.get("in_assistant_text")),
        "N3_brain_off_no_token": int(off_facts.get("stream_hits") or 0) == 0,
        "N4_single_native_child_spawn_no_interference": bool(
            len(on.get("spawned_agents") or []) == 1
            and not on.get("refused_spawns")
            and int(on.get("memory_interference_total") or 0) == 0
        ),
        "N5_no_brain_task_admission_and_no_removed_path": bool(
            "BRAIN_WORKER_" not in on_markers and "ORCHESTRATION_REMOVED" not in on_markers
        ),
    }


def self_test_delivery_cache() -> dict[str, Any]:
    """Check the emit-cache reader against the extension's persisted shape.

    The cache is the extension's own serialized TS objects (``PersistedEmitEntry``
    / ``AutoInjectShadowOutcome`` in autoinject.ts) -- camelCase, unlike the CLI's
    snake_case stdout. Reading the wrong spelling silently degrades every
    diagnostic to "None", so the shape is pinned here and no host process runs.
    """
    fixture = {
        "session:task": {
            "message": {
                "customType": INJECTED_CONTEXT_CUSTOM_TYPE,
                "content": f"observation: {MEMORY_SELF_TEST_TOKEN}",
                "display": True,
                "details": {"delivery_id": "del-fixture", "packet_tokens": 12},
            },
            "outcome": {
                "decision": "INJECT",
                "reason": None,
                "packet": f"observation: {MEMORY_SELF_TEST_TOKEN}",
                "packetTokens": 12,
                "deliveryId": "del-fixture",
                "candidateCount": 1,
                "selectedCount": 1,
                "packetSha256": "0" * 64,
                "cliPacketChars": 40,
                "cliStdoutChars": 200,
                "projectId": MEMORY_PROJECT_ID,
                "projectResolution": "manifest",
            },
            "emits": 2,
            "expiresAt": time.time() * 1000 + 60_000,
            "createdAt": time.time() * 1000,
            "taskSha256": "1" * 64,
            "projectId": "default",
            "retrievalConfigFingerprint": "fp",
            "corpusGeneration": "gen",
            "runtimeBuildIdentity": "build",
        }
    }
    home = Path(tempfile.mkdtemp(prefix="memcheck-cache-selftest-"))
    try:
        target = home / "state" / "autoinject-emit-cache.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture), encoding="utf-8")
        seen = brain_delivery_state(home, MEMORY_SELF_TEST_TOKEN)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return seen


def _transient_host_error(row: dict[str, Any]) -> bool:
    """A host run that returned no parseable event stream at all.

    That is the shape of a transient failure (spawn/timeout); a run that emitted
    events but failed is not retried, so the evidence keeps one live run per arm
    plus at most one retry.
    """
    return not row.get("event_count")


def memory_check(args: argparse.Namespace, out_dir: Path, extension: Path) -> int:
    """Run the memory/context real-path differential and write its payload."""
    stamp = time.strftime("%Y%m%d")
    stream_dir = out_dir / f"memory-realpath-{stamp}"
    stream_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="memcheck-arms-"))
    canonical_before = canonical_home_state()

    results: list[dict[str, Any]] = []
    for arm in build_memory_arms(extension):
        name = str(arm["name"])
        tmp = workdir / name
        proj = tmp / "proj"
        proj.mkdir(parents=True, exist_ok=True)
        token = MEMPROBE_PREFIX + secrets.token_hex(4)
        home = Path(tempfile.mkdtemp(prefix=f"memcheck-home-{name}-"))
        try:
            seed = seed_memory(
                home,
                proj,
                brain_python=Path(args.brain_python),
                token=token,
                timeout=args.timeout,
            )
            files_seeded = _home_inventory(home)
            env_extra = {
                "SECOND_BRAIN_HOME": str(home),
                "SECOND_BRAIN_AUTOINJECT_MODE": MEMORY_INTERFERENCE_AUTOMODE,
            }
            attempts = 0
            while True:
                attempts += 1
                print(
                    f"[arm] {name} attempt={attempts} extension={arm['extension']}",
                    file=sys.stderr,
                )
                row = run_arm(
                    name,
                    prompt=str(arm["prompt"]),
                    extension=arm["extension"],
                    brain_home=home if arm["extension"] else None,
                    brain_python=Path(args.brain_python),
                    model=args.model,
                    omp=args.omp,
                    timeout=args.timeout,
                    workdir=workdir,
                    env_extra=env_extra,
                    token=token,
                )
                if attempts >= 2 or not _transient_host_error(row):
                    break
                print(f"[arm] {name} produced no event stream; retrying once", file=sys.stderr)
            files_after = _home_inventory(home)
            seeded_set = set(files_seeded)
            added = [f for f in files_after if f not in seeded_set]
            row.update(
                {
                    "attempts": attempts,
                    "seed": seed,
                    "disposable_home": str(home),
                    # The isolation proof: this is the home the arm's processes
                    # (host, extension, and any child session) ran against.
                    "second_brain_home_env": env_extra["SECOND_BRAIN_HOME"],
                    "home_is_temp_dir": _is_temp_path(home),
                    "brain_home_file_count_before": len(files_seeded),
                    "brain_home_file_count_after": len(files_after),
                    "brain_home_files_added_by_arm": added[:40],
                    "brain_delivery": brain_delivery_state(home, token),
                }
            )
            raw = Path(str(row["raw_path"]))
            archived = stream_dir / f"{name}.jsonl"
            if raw.is_file():
                shutil.copyfile(raw, archived)
                row["raw_stream"] = str(archived.relative_to(out_dir.parent.parent))
        finally:
            if not args.keep_home:
                shutil.rmtree(home, ignore_errors=True)
        results.append(row)

    canonical_after = canonical_home_state()
    payload = {
        "probe": "memory-realpath",
        "date": stamp,
        "model": args.model,
        "extension": str(extension),
        "prompt": MEMORY_PROMPT,
        "injected_context_custom_type": INJECTED_CONTEXT_CUSTOM_TYPE,
        "autoinject_mode_override": MEMORY_INTERFERENCE_AUTOMODE,
        "arm_workdir": str(workdir),
        "arms": results,
        "verdicts": memory_verdicts(results),
        "observations": memory_observations(results),
        "home_disposability": {
            "all_arms_on_temp_dirs": all(bool(r.get("home_is_temp_dir")) for r in results),
            "temp_root": tempfile.gettempdir(),
            "arm_homes": [r.get("disposable_home") for r in results],
        },
        "canonical_home_before": canonical_before,
        "canonical_home_after": canonical_after,
        "canonical_home_untouched": canonical_before == canonical_after,
        "canonical_home_note": (
            "Read-only snapshots only. No arm process had the canonical home in "
            "SECOND_BRAIN_HOME (see second_brain_home_env per arm), so a canonical "
            "db mtime change during the run window is not attributable to this "
            "probe: in this environment the canonical home is a live checkout that "
            "other agent sessions also write. Treat a change here as a competing "
            "writer, not as probe leakage."
        ),
        "limits": [
            "One live run per arm (a second attempt only when a run produced no "
            "event stream at all), so this is a differential observation, not a "
            "statistical claim.",
            "The child subagent's own session is not persisted under --no-session; "
            "child context is read from the reply the host delivered to the parent.",
            "The token is asserted present in the host's own record of injected "
            "context; the probe does not claim to prove the model attended to it "
            "beyond the parent quoting it.",
        ],
    }
    out_file = out_dir / f"memory-realpath-{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(
            f"{row['arm']}: rc={row['returncode']} wall={row['wall_seconds']}s "
            f"events={row['event_count']} spawns={row['spawned_agents']} "
            f"token_hits={(row.get('token_evidence') or {}).get('stream_hits')} "
            f"markers={row['memory_interference_total']}"
        )
    print(json.dumps(payload["verdicts"], indent=2))
    print(f"payload: {out_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(repo / "docs/intake/m00-evidence"))
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    ap.add_argument("--extension", default=str(repo / "brainstem/prime-extension/src/index.ts"))
    ap.add_argument("--omp", default="omp")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--brain-python", default=sys.executable)
    ap.add_argument(
        "--installed", default="", help="pre-removal extension entry, for a sensitivity control"
    )
    ap.add_argument(
        "--keep-home", action="store_true", help="keep the disposable brain home for inspection"
    )
    ap.add_argument(
        "--self-test", action="store_true", help="check the extractor, run no host process"
    )
    ap.add_argument(
        "--memory-check",
        action="store_true",
        help="run the retained memory/context real-path differential instead of the spawn arms",
    )
    args = ap.parse_args(argv)

    if args.self_test:
        seen = summarize_arm(SELF_TEST_SAMPLE)
        memory_seen = summarize_arm(MEMORY_SELF_TEST_SAMPLE, token=MEMORY_SELF_TEST_TOKEN)
        print(json.dumps(seen, indent=2))
        print(json.dumps(memory_seen, indent=2))
        ok = (
            seen["interference_total"] == 1
            and seen["spawn_calls"] == 1
            and seen["refused_spawns"] == ["A"]
            and seen["spawned_agents"] == []
        )
        memory_facts = memory_seen["token_evidence"]
        cache_seen = self_test_delivery_cache()
        cache_ok = (
            cache_seen["present"] is True
            and cache_seen["decisions"] == ["INJECT"]
            and cache_seen["outcome_project_ids"] == [MEMORY_PROJECT_ID]
            and cache_seen["outcome_project_resolutions"] == ["manifest"]
            and cache_seen["delivery_ids"] == ["del-fixture"]
            and cache_seen["token_in_cached_packet"] is True
        )
        memory_ok = (
            memory_facts["injected_context_records"] == [INJECTED_CONTEXT_CUSTOM_TYPE]
            and memory_facts["other_custom_records"] == ["async-result"]
            and memory_facts["in_assistant_text"] is True
            and memory_facts["in_spawn_args"] is False
            # 5 = the injected custom message twice (start + end), the delivered
            # child result once, and twice in the assistant's final line.
            and memory_facts["stream_hits"] == 5
            and memory_facts["in_child_result"] is True
            and memory_seen["task_result_records"]["unique"] == 1
            and memory_seen["memory_interference_total"] == 0
        )
        print(
            f"extractor: markers={seen['interference_total']} "
            f"spawns={seen['spawn_calls']} refused={seen['refused_spawns']} ok={ok}"
        )
        print(
            f"memory extractor: injected={memory_facts['injected_context_records']} "
            f"other={memory_facts['other_custom_records']} hits={memory_facts['stream_hits']} "
            f"ok={memory_ok}"
        )
        print(
            f"delivery cache reader: decisions={cache_seen['decisions']} "
            f"outcome_projects={cache_seen['outcome_project_ids']} "
            f"deliveries={cache_seen['delivery_ids']} ok={cache_ok}"
        )
        return 0 if ok and memory_ok and cache_ok else 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(args.extension)
    if args.memory_check:
        return memory_check(args, out_dir, extension)
    installed = Path(args.installed) if args.installed else None
    workdir = Path(tempfile.mkdtemp(prefix="ni-arms-"))
    stamp = time.strftime("%Y%m%d")
    # Every arm gets its own disposable brain home, and each arm's raw stream is
    # copied beside the JSON. A single shared home could not attribute extension
    # activity to an arm (the installed control also writes there), and a payload
    # that only points at temp files is not evidence a later session can open.
    stream_dir = out_dir / f"native-noninterference-{stamp}"
    stream_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for name, prompt, ext in build_arms(extension, installed):
        print(f"[arm] {name} extension={ext}", file=sys.stderr)
        home = Path(tempfile.mkdtemp(prefix=f"ni-brain-home-{name}-")) if ext else None
        try:
            row = run_arm(
                name,
                prompt=prompt,
                extension=ext,
                brain_home=home,
                brain_python=Path(args.brain_python),
                model=args.model,
                omp=args.omp,
                timeout=args.timeout,
                workdir=workdir,
            )
            if home is not None:
                # Does the extension actually run in THIS arm? A loaded but inert
                # extension would make a clean result meaningless.
                row["brain_home_files"] = _home_inventory(home)[:40]
            stream = Path(str(row["raw_path"]))
            archived = stream_dir / f"{name}.jsonl"
            if stream.is_file():
                shutil.copyfile(stream, archived)
                row["raw_stream"] = str(archived.relative_to(out_dir.parent.parent))
        finally:
            if home is not None and not args.keep_home:
                shutil.rmtree(home, ignore_errors=True)
        results.append(row)

    payload = {
        "probe": "native-noninterference",
        "date": stamp,
        "model": args.model,
        "extension": str(extension),
        "installed_control": str(installed) if installed else None,
        "arm_workdir": str(workdir),
        "arms": results,
        "verdicts": verdicts(results),
    }
    (out_dir / f"native-noninterference-{stamp}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    for row in results:
        print(
            f"{row['arm']}: rc={row['returncode']} wall={row['wall_seconds']}s "
            f"spawn_calls={row['spawn_calls']} spawned={row['spawned_agents']} "
            f"refused={row['refused_spawns']} interference={row['interference_total']}"
        )
    print(json.dumps(payload["verdicts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
