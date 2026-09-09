"""Run bounded paired economics tasks against real hosts, using telemetry only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain import economics, governor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "proof" / "tasks" / "economics"
RAW_DIR = ROOT / "outputs" / "reports" / "v2" / "economics" / "raw"
QUALIFICATION = ROOT / "outputs" / "reports" / "v2" / "v2-0" / "qualification.json"
HARNESS_EXECUTABLES = {"prime": "prime", "claude-code": "claude", "hermes": "hermes"}
PROFILE_TO_ABLATION = {"OFF": "A_BRAIN_OFF", "ON": "I_FULL_V1"}
MAX_PAIRS = 100
_REQUIRED_USAGE = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
)
_READ_REUSE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "outputs"
    / "reports"
    / "v1-v2-closure-20260908T011250Z"
    / "current-build-read-reuse"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duration_ms(record: dict[str, Any]) -> int | None:
    try:
        started = datetime.fromisoformat(str(record["started_at"]).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(record["finished_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return round((finished - started).total_seconds() * 1000)


def _write_json_once(path: Path, value: object) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"refusing to replace retained evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def _canonical_exporter():
    # Lazy import keeps fixture-only CLI use independent of the producer package.
    try:
        from scripts.run_v1_p4_qualification import export_v2_observation, qualification_identity
    except ModuleNotFoundError:
        path = ROOT / "scripts" / "run_v1_p4_qualification.py"
        spec = importlib.util.spec_from_file_location("canonical_qualification_producer", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("canonical qualification producer is unavailable") from None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        export_v2_observation = module.export_v2_observation
        qualification_identity = module.qualification_identity
    return qualification_identity, export_v2_observation


def _resolve_protocol_path(value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("protocol path field must be a non-empty string")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _model_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"protocol {field} is missing")
    return value.split(":", 1)[0]


def _protocol_paths(protocol_path: Path, protocol: dict[str, Any]) -> dict[str, Path]:
    base = protocol_path.parent
    skill = _resolve_protocol_path(protocol.get("skill_path"), base)
    executable_value = (
        protocol.get("executable_path")
        or protocol.get("omp_executable")
        or protocol.get("host_executable")
    )
    executable = (
        _resolve_protocol_path(executable_value, base)
        if executable_value
        else (Path.home() / ".bun" / "bin" / "omp.exe").resolve()
    )
    operation_value = (
        protocol.get("operation_path")
        or protocol.get("macro_path")
        or protocol.get("approved_operation")
    )
    operation = (
        _resolve_protocol_path(operation_value, base)
        if operation_value
        else (_READ_REUSE_ROOT / "run-observed-config-macro.py").resolve()
    )
    input_value = (
        protocol.get("input_spec_path") or protocol.get("input_path") or protocol.get("macro_input")
    )
    input_spec = (
        _resolve_protocol_path(input_value, base)
        if input_value
        else (_READ_REUSE_ROOT / "observed-config-macro-input.json").resolve()
    )
    config_value = protocol.get("config_path") or protocol.get("model_config")
    config = (
        _resolve_protocol_path(config_value, base)
        if config_value
        else (_READ_REUSE_ROOT / "qualification-model-config.yml").resolve()
    )
    return {
        "protocol": protocol_path.resolve(),
        "skill": skill,
        "executable": executable,
        "operation": operation,
        "input": input_spec,
        "config": config,
    }


def _study_identity(home: Path, protocol_path: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    qualification_identity, _ = _canonical_exporter()
    identity = qualification_identity(home)
    paths = _protocol_paths(protocol_path, protocol)
    captured: dict[str, str] = {}
    for label, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"native study input is unavailable: {path}")
        captured[label] = _sha256_file(path)
    expected_skill = protocol.get("skill_sha256")
    if expected_skill is not None and captured["skill"] != expected_skill:
        raise RuntimeError("candidate skill changed before native study")
    expected_inputs = protocol.get("same_input_hashes", protocol.get("input_hashes", {}))
    if not isinstance(expected_inputs, dict):
        raise ValueError("protocol same_input_hashes must be an object")
    for raw_path, expected in expected_inputs.items():
        path = Path(raw_path)
        path = (path if path.is_absolute() else protocol_path.parent / path).resolve()
        if not path.is_file() or _sha256_file(path) != expected:
            raise RuntimeError(f"study input changed before native study: {path}")
        captured[f"input:{path.as_posix()}"] = expected
    for label in ("operation", "input", "config"):
        expected_path_hash = protocol.get(f"{label}_sha256")
        if expected_path_hash is not None and captured[label] != expected_path_hash:
            raise RuntimeError(f"native study {label} changed before native study")
    expected_executable = (
        protocol.get("executable_sha256")
        or protocol.get("omp_executable_sha256")
        or protocol.get("host_executable_sha256")
    )
    if expected_executable is not None and captured["executable"] != expected_executable:
        raise RuntimeError("native executable changed before native study")
    identity["study_inputs"] = captured
    identity["protocol_sha256"] = captured["protocol"]
    return identity


def _assert_study_identity(
    home: Path, protocol_path: Path, protocol: dict[str, Any], before: dict[str, Any]
) -> dict[str, Any]:
    current = _study_identity(home, protocol_path, protocol)
    for key in ("source_commit", "source_tree_sha256", "config_sha256", "protocol_sha256"):
        if current.get(key) != before.get(key):
            raise RuntimeError(f"{key} changed during native study")
    if current.get("study_inputs") != before.get("study_inputs"):
        raise RuntimeError("native study executable, skill, or input identity changed")
    return current


def _protocol_study(protocol_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid native study protocol: {protocol_path}") from exc
    if not isinstance(protocol, dict):
        raise ValueError("native study protocol must be an object")
    pairs = protocol.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 3:
        raise ValueError("native study protocol must contain exactly three pairs")
    normalized: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict) or type(pair.get("pair")) is not int:
            raise ValueError("each native study pair needs an integer pair")
        order = pair.get("order")
        if order not in (["baseline", "candidate"], ["candidate", "baseline"]):
            raise ValueError("each native study pair needs a baseline/candidate order")
        normalized.append({"pair": pair["pair"], "order": list(order)})
    if {pair["pair"] for pair in normalized} != {1, 2, 3}:
        raise ValueError("native study pair IDs must be 1, 2, and 3")
    expected = protocol.get("same_postconditions")
    required = {"autoinject_mode", "admission_stage", "learning_stage", "retrieval_token_budget"}
    if (
        not isinstance(expected, dict)
        or set(expected) != required
        or any(not isinstance(expected[key], str) for key in required - {"retrieval_token_budget"})
        or type(expected["retrieval_token_budget"]) is not int
    ):
        raise ValueError("protocol same_postconditions must be exactly four typed settings")
    _model_name(protocol.get("controller_model"), "controller_model")
    _model_name(protocol.get("worker_model"), "worker_model")
    return normalized, protocol


def _macro_command(home: Path, paths: dict[str, Path], protocol: dict[str, Any]) -> str:
    command = protocol.get("macro_command")
    if isinstance(command, str) and command.strip():
        return command
    python = protocol.get("python_executable")
    python_path = (
        _resolve_protocol_path(python, paths["protocol"].parent)
        if isinstance(python, str) and python
        else home / ".venv" / "Scripts" / "python.exe"
    )
    return " ".join([str(python_path), str(paths["operation"]), str(paths["input"])]).replace(
        "\\", "/"
    )


def _native_prompt(
    run_id: str,
    arm: str,
    pair: int,
    protocol: dict[str, Any],
    macro_command: str,
    skill: Path,
) -> tuple[str, list[str]]:
    schema = protocol.get(
        "output_schema",
        "object with required autoinject_mode:string, admission_stage:string, "
        "learning_stage:string, retrieval_token_budget:integer; additionalProperties:false",
    )
    first = f"{arm.title()}P{pair}One"
    second = f"{arm.title()}P{pair}Two"
    common = (
        f"Qualification {run_id}. Return the four current settings using strict outputSchema "
        f"{schema}. The run configuration selects worker models; do not add unsupported model "
        "parameters. No guessed values or unavailable placeholders. Skip builds, formatters, lint, "
        "and tests. Do not edit source, configuration, the skill, or the approved operation. Wait "
        "for real native completions through hub and report the two IDs/results separately. "
    )
    if arm == "baseline":
        prompt = (
            common
            + f"Reproduce the standard full-worker workflow. Launch {first} as the default task "
            "worker with access_intent mutating, wait for terminal completion and cleanup, then "
            f"launch {second} with the same contract. Do not overlap writers. Each worker must "
            f"execute exactly this approved operation once and return its observed_settings: "
            f"`{macro_command}`. No controller execution. Mutating admission covers only "
            "derived cache writes. No other shell commands are permitted."
        )
        return prompt, []
    prompt = (
        common
        + "Follow the complete supplied candidate skill. The study launcher verified the skill and "
        "input configuration hashes immediately before this run. Execute the approved owned macro "
        f"once in the controller through bash: `{macro_command}`. Then launch two read-only Scouts "
        f"in one batch: {first} and {second}, both with access_intent read_only. Give both the "
        "actual computed observed_settings and its provenance as bounded context. They must verify "
        "the four requested keys are present and return those actual values without reopening "
        "inputs, rerunning the macro, shell commands, edits, or further workers. Never substitute "
        "a teacher answer for executed macro output. Count controller and student usage; "
        "macro_model_calls=0 is not a whole-workflow token claim."
    )
    return prompt, ["@" + str(skill)]


def run_native_read_reuse_study(home: Path, protocol_path: Path, out_dir: Path) -> dict[str, Any]:
    """Run exactly the preregistered three-pair native study in a fresh directory."""
    home = Path(home).resolve()
    protocol_path = Path(protocol_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.relative_to(home)
    pairs, protocol = _protocol_study(protocol_path)
    paths = _protocol_paths(protocol_path, protocol)
    before = _study_identity(home, protocol_path, protocol)
    run_dir = out_dir / f"native-read-reuse-{_utc()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json_once(run_dir / "identity-before.json", before)
    env = {
        key: value for key, value in os.environ.items() if key not in {"PYTHONHOME", "PYTHONPATH"}
    }
    env["SECOND_BRAIN_HOME"] = str(home)
    controller_model = _model_name(protocol["controller_model"], "controller_model")
    thinking = (
        str(protocol["controller_model"]).split(":", 1)[1]
        if ":" in str(protocol["controller_model"])
        else "low"
    )
    max_time = str(protocol.get("max_time", "8m"))
    if not max_time.startswith("--max-time="):
        max_time = f"--max-time={max_time}"
    base_args = [
        str(paths["executable"]),
        "--print",
        f"--model={controller_model}",
        f"--thinking={thinking}",
        max_time,
        f"--config={paths['config']}",
        "--no-skills",
        "--no-rules",
        "--no-lsp",
        "--no-title",
        "--tools=read,bash,task,hub",
        f"--cwd={home}",
    ]
    executions: list[dict[str, Any]] = []
    for pair in pairs:
        for arm in pair["order"]:
            _assert_study_identity(home, protocol_path, protocol, before)
            run_id = f"pair-{pair['pair']}-{arm}"
            run_path = run_dir / run_id
            sessions = run_path / "sessions"
            sessions.mkdir(parents=True, exist_ok=False)
            prompt, skill_arg = _native_prompt(
                run_id,
                arm,
                pair["pair"],
                protocol,
                _macro_command(home, paths, protocol),
                paths["skill"],
            )
            args = [*base_args, f"--session-dir={sessions}", *skill_arg, prompt]
            started = datetime.now(UTC)
            record: dict[str, Any] = {
                "run_id": run_id,
                "pair": pair["pair"],
                "arm": arm,
                "sessions": str(sessions),
                "argv": args,
                "started_at": started.isoformat(),
                "protocol_sha256": before["protocol_sha256"],
                "study_inputs": before["study_inputs"],
                "source_skill_sha256": before["study_inputs"]["skill"],
            }
            try:
                completed = subprocess.run(
                    args,
                    cwd=home,
                    env=env,
                    input=b"",
                    capture_output=True,
                    timeout=int(protocol.get("timeout_seconds", 600)),
                    check=False,
                )
                (run_path / "stdout.txt").write_bytes(completed.stdout)
                (run_path / "stderr.txt").write_bytes(completed.stderr)
                record.update(
                    {
                        "exit": completed.returncode,
                        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
                        "stdout_bytes": len(completed.stdout),
                        "stderr_bytes": len(completed.stderr),
                    }
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or b""
                stderr = exc.stderr or b""
                (run_path / "stdout.txt").write_bytes(stdout)
                (run_path / "stderr.txt").write_bytes(stderr)
                record.update({"exit": None, "error": "timeout"})
            except OSError as exc:
                record.update({"exit": None, "error": f"{type(exc).__name__}: {exc}"})
            record["finished_at"] = datetime.now(UTC).isoformat()
            _write_json_once(run_path / "execution.json", record)
            executions.append(record)
            (run_dir / "executions.json").write_bytes(
                json.dumps(
                    executions, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
                ).encode("utf-8")
            )
    identity_after = _assert_study_identity(home, protocol_path, protocol, before)
    manifest = {
        "schema_version": 1,
        "classification": "observed",
        "study_id": protocol.get("study_id"),
        "protocol_path": str(protocol_path),
        "protocol_sha256": before["protocol_sha256"],
        "run_dir": str(run_dir),
        "identity": before,
        "identity_after": identity_after,
        "executions": executions,
        "complete_execution_count": len(executions) == 6
        and all(record.get("exit") == 0 for record in executions),
    }
    _write_json_once(run_dir / "study.json", manifest)
    return manifest


def _collect_native_usage(
    path: Path, output: Path, expected_model: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = path.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    rows = [json.loads(line) for line in source.decode("utf-8").splitlines() if line.strip()]
    messages = [
        row["message"]
        for row in rows
        if isinstance(row, dict)
        and row.get("type") == "message"
        and isinstance(row.get("message"), dict)
        and row["message"].get("role") == "assistant"
    ]
    if not messages:
        raise RuntimeError(f"no actual assistant usage: {path}")
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        actual = f"{message.get('provider')}/{message.get('model')}"
        if actual != expected_model or message.get("stopReason") == "error":
            raise RuntimeError(f"unexpected effective model or failed turn: {path}")
        usage = message.get("usage")
        if not isinstance(usage, dict):
            raise RuntimeError(f"unavailable complete usage: {path}")
        fields = {
            "input_tokens": "input",
            "output_tokens": "output",
            "cache_read_tokens": "cacheRead",
            "cache_write_tokens": "cacheWrite",
            "total_tokens": "totalTokens",
        }
        if any(type(usage.get(field)) is not int or usage[field] < 0 for field in fields.values()):
            raise RuntimeError(f"incomplete native counters: {path}")
        normalized.append(
            {
                "kind": "assistant_usage",
                "model": actual,
                "native_message_index": index,
                "native_source_sha256": source_hash,
                **{target: usage[source_name] for target, source_name in fields.items()},
            }
        )
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in normalized).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != payload:
            raise RuntimeError(f"native translation changed: {output}")
    else:
        with output.open("xb") as stream:
            stream.write(payload)
    usage = aggregate_telemetry([output])
    if any(usage[field] is None for field in _REQUIRED_USAGE):
        raise RuntimeError(f"canonical aggregation found unavailable usage: {path}")
    if _sha256_file(path) != source_hash:
        raise RuntimeError(f"native source changed during aggregation: {path}")
    return rows, usage


def _file_refs(root: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            refs.append({"path": str(path), "sha256": _sha256_file(path), "type": "raw"})
    return refs


def _command_tokens(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, str):
        return None
    try:
        parts = shlex.split(value, posix=False)
    except ValueError:
        return None
    return tuple(part.strip("\"'").replace("\\", "/").casefold() for part in parts)


def _macro_command_matches(actual: object, approved: str) -> bool:
    return _command_tokens(actual) == _command_tokens(approved)


def _settings(value: object, expected: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value != expected:
        return None
    if (
        not isinstance(value.get("autoinject_mode"), str)
        or not isinstance(value.get("admission_stage"), str)
        or not isinstance(value.get("learning_stage"), str)
        or type(value.get("retrieval_token_budget")) is not int
    ):
        return None
    return dict(value)


def _macro_result(tool_result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any] | None:
    if tool_result.get("isError") is not False:
        return None
    content = tool_result.get("content")
    texts = (
        [
            text
            for part in content
            if isinstance(part, dict) and isinstance(text := part.get("text"), str)
        ]
        if isinstance(content, list)
        else []
    )
    candidates: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for text in texts:
        for start, marker in enumerate(text):
            if marker != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "observed_settings" in value:
                candidates.append(value)
    if len(candidates) != 1:
        return None
    result = candidates[0]
    observed = _settings(result.get("observed_settings"), expected)
    if observed is None:
        return None
    provenance_types = {
        "engram_id": str,
        "version": int,
        "macro_model_calls": int,
        "cache_hit": bool,
        "native_commands": list,
    }
    for field, kind in provenance_types.items():
        value = result.get(field)
        if field == "engram_id" and (not isinstance(value, kind) or not value):
            return None
        if field != "engram_id" and (
            type(value) is not kind or (isinstance(value, int) and value < 0)
        ):
            return None
    return {
        "observed_settings": observed,
        "provenance": {field: result[field] for field in provenance_types},
    }


def _yielded_answer(
    child_messages: list[dict[str, Any]], expected: dict[str, Any]
) -> dict[str, Any] | None:
    yields: list[tuple[dict[str, Any], dict[str, Any]]] = []
    replies = {
        message.get("toolCallId"): message
        for message in child_messages
        if isinstance(message, dict) and message.get("role") == "toolResult"
    }
    for message in child_messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if (
                not isinstance(part, dict)
                or part.get("type") != "toolCall"
                or part.get("name") != "yield"
            ):
                continue
            arguments = part.get("arguments")
            if not isinstance(arguments, dict) or arguments.get("error") is not None:
                continue
            answer = _settings(arguments.get("data"), expected)
            reply = replies.get(part.get("id"))
            if answer is not None and isinstance(reply, dict) and reply.get("isError") is False:
                yields.append((answer, reply))
    if len(yields) != 1:
        return None
    return {"answer": yields[0][0], "source": "native_yield"}


def _native_acceptance(
    parent: Path,
    children: list[Path],
    arm: str,
    pair: int,
    protocol: dict[str, Any],
    macro_command: str,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    expected = protocol["same_postconditions"]
    answers: list[dict[str, Any]] = []
    parent_rows = [
        json.loads(line) for line in parent.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    messages = [
        row["message"]
        for row in parent_rows
        if isinstance(row, dict) and isinstance(row.get("message"), dict)
    ]
    calls = [
        part
        for message in messages
        if message.get("role") == "assistant"
        for part in message.get("content", [])
        if isinstance(part, dict) and part.get("type") == "toolCall"
    ]
    replies = {
        message.get("toolCallId"): message
        for message in messages
        if message.get("role") == "toolResult"
    }

    def arguments(call: dict[str, Any]) -> dict[str, Any]:
        value = call.get("arguments")
        return value if isinstance(value, dict) else {}

    items = [
        item
        for call in calls
        if call.get("name") == "task"
        for item in arguments(call).get("tasks", [])
        if isinstance(item, dict)
    ]
    expected_ids = {f"{arm.title()}P{pair}One", f"{arm.title()}P{pair}Two"}
    if len(items) != 2 or {item.get("name") for item in items} != expected_ids:
        errors.append("native dispatch did not contain the exact two expected worker IDs")
    if len({item.get("name") for item in items}) != len(items):
        errors.append("native worker dispatch IDs were not unique")
    for item in items:
        if arm == "candidate" and (
            item.get("agent") != "scout" or item.get("access_intent") != "read_only"
        ):
            errors.append("candidate worker access intent differs from protocol")
        if arm == "baseline" and item.get("access_intent") != "mutating":
            errors.append("baseline worker access intent differs from protocol")

    macro_calls = [call for call in calls if call.get("name") == "bash"]
    exact_macro_calls = [
        call
        for call in macro_calls
        if _macro_command_matches(arguments(call).get("command"), macro_command)
    ]
    if len(macro_calls) != len(exact_macro_calls):
        errors.append("native session attempted an alternate macro command")
    if arm == "candidate":
        if len(exact_macro_calls) != 1:
            errors.append("candidate controller macro execution was not observed exactly once")
        parent_macro = (
            _macro_result(replies.get(exact_macro_calls[0].get("id"), {}), expected)
            if len(exact_macro_calls) == 1
            else None
        )
        if parent_macro is None:
            errors.append(
                "candidate controller macro result lacked successful settings and provenance"
            )
    else:
        if exact_macro_calls:
            errors.append("baseline controller unexpectedly executed the macro")
        parent_macro = None

    for child in children:
        child_rows = [
            json.loads(line)
            for line in child.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        child_messages = [
            row["message"]
            for row in child_rows
            if isinstance(row, dict) and isinstance(row.get("message"), dict)
        ]
        child_calls = [
            part
            for message in child_messages
            if message.get("role") == "assistant"
            for part in message.get("content", [])
            if isinstance(part, dict)
            and part.get("type") == "toolCall"
            and part.get("name") == "bash"
        ]
        child_replies = {
            message.get("toolCallId"): message
            for message in child_messages
            if message.get("role") == "toolResult"
        }
        child_exact_calls = [
            call
            for call in child_calls
            if _macro_command_matches(arguments(call).get("command"), macro_command)
        ]
        if len(child_calls) != len(child_exact_calls):
            errors.append(f"{child.stem} attempted an alternate macro command")
        if arm == "baseline" and len(child_exact_calls) != 1:
            errors.append("baseline worker macro execution was not observed exactly once")
        if arm == "candidate" and child_calls:
            errors.append("candidate worker executed a shell command instead of reusing the result")
        child_macro = (
            _macro_result(child_replies.get(child_exact_calls[0].get("id"), {}), expected)
            if len(child_exact_calls) == 1
            else None
        )
        if arm == "baseline" and child_macro is None:
            errors.append(f"{child.stem} macro result lacked successful settings and provenance")
        answer = _yielded_answer(child_messages, expected)
        if answer is None:
            errors.append(f"{child.stem} had no successful native yielded answer")
            continue
        expected_macro = parent_macro if arm == "candidate" else child_macro
        if expected_macro is None or answer["answer"] != expected_macro["observed_settings"]:
            errors.append(f"{child.stem} yielded settings not bound to the successful macro result")
        answers.append({"agent_id": child.stem, **answer})
    if {child.stem for child in children} != expected_ids:
        errors.append("native child transcript IDs did not match the exact expected worker IDs")
    return not errors, errors, answers


def collect_native_read_reuse_study(
    home: Path, protocol_path: Path, run_dir: Path, out_dir: Path
) -> dict[str, Any]:
    """Collect only fresh native sessions and export economics when complete."""
    home = Path(home).resolve()
    protocol_path = Path(protocol_path).resolve()
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.relative_to(home)
    pairs, protocol = _protocol_study(protocol_path)
    paths = _protocol_paths(protocol_path, protocol)
    manifest_path = run_dir / "study.json"
    if not manifest_path.is_file():
        raise ValueError("run_dir is not a fresh native study capture")

    collector_errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        manifest = {}
        collector_errors.append(f"invalid native study manifest: {exc}")
    before = manifest.get("identity") if isinstance(manifest, dict) else None
    if not isinstance(before, dict):
        before = {}
        collector_errors.append("native study identity capture is missing")
    identity_after = None
    if before:
        try:
            identity_after = _assert_study_identity(home, protocol_path, protocol, before)
        except (OSError, RuntimeError, ValueError) as exc:
            collector_errors.append(str(exc))

    executions_path = run_dir / "executions.json"
    try:
        executions = json.loads(executions_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        executions = []
        collector_errors.append(f"invalid native study executions: {exc}")
    if not isinstance(executions, list):
        executions = []
        collector_errors.append("native study executions must be a list")

    expected_order = [(pair["pair"], arm) for pair in pairs for arm in pair["order"]]
    actual_order = [
        (row.get("pair"), row.get("arm")) for row in executions if isinstance(row, dict)
    ]
    observations: list[dict[str, Any]] = []
    for execution in executions:
        if not isinstance(execution, dict):
            observations.append({"complete": False, "errors": ["malformed execution record"]})
            continue
        errors: list[str] = []
        run_id = execution.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            errors.append("execution record is missing a valid run_id")
            run_id = "malformed-execution"
        raw_sessions = execution.get("sessions")
        sessions: Path | None = None
        if isinstance(raw_sessions, str) and raw_sessions:
            sessions = Path(raw_sessions)
            if not sessions.is_absolute():
                sessions = run_dir / sessions
        else:
            errors.append("execution record is missing a valid sessions path")
        parents = (
            sorted(sessions.glob("*.jsonl")) if sessions is not None and sessions.is_dir() else []
        )
        parent = parents[0] if len(parents) == 1 else None
        children = sorted(parent.with_suffix("").glob("*.jsonl")) if parent else []
        parent_usage = None
        child_records: list[dict[str, Any]] = []
        if execution.get("exit") != 0:
            errors.append("controller did not exit successfully")
        if parent is None:
            errors.append("expected exactly one controller session")
        else:
            try:
                _, parent_usage = _collect_native_usage(
                    parent,
                    run_dir / "native-usage" / run_id / "controller.jsonl",
                    _model_name(protocol["controller_model"], "controller_model"),
                )
            except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        if len(children) != 2:
            errors.append("expected exactly two worker sessions")
        for child in children:
            try:
                _, usage = _collect_native_usage(
                    child,
                    run_dir / "native-usage" / run_id / f"{child.stem}.jsonl",
                    _model_name(protocol["worker_model"], "worker_model"),
                )
                child_records.append(
                    {
                        "agent_id": child.stem,
                        "source_path": str(child),
                        "source_sha256": _sha256_file(child),
                        "usage": usage,
                    }
                )
            except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        arm, pair = execution.get("arm"), execution.get("pair")
        if not isinstance(arm, str) or type(pair) is not int:
            errors.append("execution record has invalid arm or pair")
            observations.append({**execution, "complete": False, "errors": errors})
            continue
        if parent is not None and len(children) == 2:
            try:
                accepted, acceptance_errors, answers = _native_acceptance(
                    parent,
                    children,
                    arm,
                    pair,
                    protocol,
                    _macro_command(home, paths, protocol),
                )
                if not accepted:
                    errors.extend(acceptance_errors)
                answers_by_id = {answer["agent_id"]: answer for answer in answers}
                for child_record in child_records:
                    answer = answers_by_id.get(child_record["agent_id"])
                    if answer is not None:
                        child_record["answer"] = answer["answer"]
                        child_record["answer_source"] = answer["source"]
                        child_record["acceptance_passed"] = accepted
            except (OSError, TypeError, AttributeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        parent_source_sha256 = None
        if parent and parent.is_file():
            try:
                parent_source_sha256 = _sha256_file(parent)
            except OSError as exc:
                errors.append(str(exc))
        complete = not errors and parent_usage is not None and len(child_records) == 2
        observation = {
            **execution,
            "run_id": execution.get("run_id"),
            "complete": complete,
            "errors": errors,
            "parent_source_sha256": parent_source_sha256,
            "parent_usage": parent_usage,
            "children": child_records,
            "complete_tokens": (
                parent_usage["total_tokens"]
                + sum(row["usage"]["total_tokens"] for row in child_records)
                if complete and parent_usage is not None
                else None
            ),
            "complete_model_turns": (
                parent_usage["model_turns"]
                + sum(row["usage"]["model_turns"] for row in child_records)
                if complete and parent_usage is not None
                else None
            ),
            "wall_ms": _duration_ms(execution),
            "acceptance_passed": complete,
        }
        observations.append(observation)

    if before:
        try:
            identity_after = _assert_study_identity(home, protocol_path, protocol, before)
        except (OSError, RuntimeError, ValueError) as exc:
            collector_errors.append(str(exc))
            identity_after = None
    complete_study = (
        not collector_errors
        and identity_after is not None
        and actual_order == expected_order
        and len(observations) == 6
        and all(row.get("complete") is True for row in observations)
    )
    paired_metrics: list[dict[str, Any]] = []
    if complete_study:
        for pair in pairs:
            arms = {row["arm"]: row for row in observations if row.get("pair") == pair["pair"]}
            if set(arms) != {"baseline", "candidate"}:
                complete_study = False
                break
            paired_metrics.append(
                {
                    "pair": pair["pair"],
                    "off": {
                        "tokens": arms["baseline"]["complete_tokens"],
                        "turns": arms["baseline"]["complete_model_turns"],
                        "wall_ms": arms["baseline"]["wall_ms"],
                        "dollars": None,
                        "pass": True,
                    },
                    "on": {
                        "tokens": arms["candidate"]["complete_tokens"],
                        "turns": arms["candidate"]["complete_model_turns"],
                        "wall_ms": arms["candidate"]["wall_ms"],
                        "dollars": None,
                        "pass": True,
                    },
                }
            )
    if not complete_study:
        paired_metrics = []
    verdict = economics.verdict(paired_metrics) if paired_metrics else "INSUFFICIENT"
    report: dict[str, Any] = {
        "schema_version": 1,
        "classification": "observed",
        "scope": "current_native_read_reuse_workflow",
        "study_id": protocol.get("study_id"),
        "protocol_path": str(protocol_path),
        "protocol_sha256": before.get("protocol_sha256"),
        "source_commit": before.get("source_commit"),
        "source_tree_sha256": before.get("source_tree_sha256"),
        "config_sha256": before.get("config_sha256"),
        "study_input_identities": before.get("study_inputs"),
        "run_dir": str(run_dir),
        "identity": before or None,
        "identity_after": identity_after,
        "collector_errors": collector_errors,
        "executions": observations,
        "paired_metrics": paired_metrics,
        "complete": complete_study,
        "verdict": verdict,
        "costs": None,
        "usage_aggregation_producer": "scripts/run_paired_economics.py",
        "usage_aggregation_producer_sha256": _sha256_file(Path(__file__)),
        "collector_sha256": _sha256_file(Path(__file__)),
        "release_wide_savings_claim": False,
    }
    report_path = out_dir / "native-read-reuse-observations.json"
    _write_json_once(report_path, report)
    if complete_study and identity_after is not None:
        _, export_v2_observation = _canonical_exporter()
        export_v2_observation(
            home,
            out_dir,
            phase="v2-i",
            requirement="governed_self_improvement_proof",
            evidence_type="economics",
            feature="native_read_reuse_economics",
            observed_data={
                "study_id": protocol.get("study_id"),
                "protocol_sha256": before.get("protocol_sha256"),
                "paired_metrics": paired_metrics,
                "verdict": verdict,
                "costs": None,
            },
            gate_observations={
                "representative_scale_and_performance": {
                    "pair_count": 3,
                    "controller_count": 6,
                    "worker_count": 12,
                    "all_runs_complete": True,
                    "all_four_settings_accepted": True,
                },
                "economics_check": {
                    "paired_metrics_observed": True,
                    "complete_parent_child_usage_counted_once": True,
                    "costs_measured": False,
                },
            },
            identity=identity_after,
            producer=Path(__file__),
            raw_refs=[*_file_refs(run_dir), {"path": str(report_path), "type": "raw"}],
        )
    return report


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def profile_env(profile: str) -> dict[str, str]:
    """Resolve the explicit OFF/ON profile mapping without a KeyError."""
    try:
        ablation = PROFILE_TO_ABLATION[profile]
    except KeyError as exc:
        raise ValueError(f"unknown economics profile: {profile}") from exc
    return {
        **governor.get_profile_env(ablation),
        "SECOND_BRAIN_AUTOINJECT_MODE": "off" if profile == "OFF" else "advisory",
    }


def load_tasks() -> list[dict[str, Any]]:
    """Load and validate the complete seven-class, two-task fixture set."""
    expected = {"MICRO", "STANDARD", "DEEP", "DEBUG", "RESEARCH", "REVIEW", "HANDOFF"}
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    if {path.stem for path in paths} != expected or len(paths) != 7:
        raise ValueError("economics fixtures must contain exactly seven class files")
    tasks: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("class") != path.stem:
            raise ValueError(f"fixture class must match filename: {path.name}")
        economics.validate_fixture(data)
        tasks.extend(data["tasks"])
    ids = [task["task_id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("economics task IDs must be unique")
    return tasks


def _telemetry_files(home: Path) -> set[Path]:
    path = home / "telemetry" / "agent-performance"
    return set(path.glob("*.jsonl")) if path.is_dir() else set()


def _parse_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def aggregate_telemetry(paths: Iterable[Path]) -> dict[str, Any]:
    """Aggregate all host telemetry files from one attempt, preserving nulls."""
    totals: dict[str, Any] = {field: 0 for field in _REQUIRED_USAGE}
    seen: dict[str, bool] = {field: False for field in _REQUIRED_USAGE}
    nulls: dict[str, bool] = {field: False for field in _REQUIRED_USAGE}
    models: set[str] = set()
    unknown_model = False
    model: str | None = None
    model_turns = 0
    tool_calls = 0
    saw_event = False
    stamps: list[float] = []
    for path in sorted(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            saw_event = True
            stamp = _parse_ts(record.get("ts"))
            if stamp is not None:
                stamps.append(stamp)
            kind = record.get("kind")
            if kind == "tool_call":
                tool_calls += 1
            if kind not in {"assistant_usage", "model_invocation_completed"}:
                continue
            usage = record if kind == "assistant_usage" else record.get("usage")
            if not isinstance(usage, dict):
                continue
            model_turns += 1
            raw_model = record.get("model")
            if isinstance(raw_model, str) and raw_model:
                model = raw_model
                models.add(raw_model)
            else:
                unknown_model = True
            for field in _REQUIRED_USAGE:
                if field not in usage or usage[field] is None:
                    nulls[field] = True
                elif isinstance(usage[field], int) and not isinstance(usage[field], bool):
                    seen[field] = True
                    totals[field] += usage[field]
                else:
                    nulls[field] = True
    for field in _REQUIRED_USAGE:
        totals[field] = None if nulls[field] or not seen[field] else totals[field]
    totals.update(
        {
            "model": model,
            "models": sorted(models),
            "mixed_model": unknown_model or len(models) > 1,
            "model_turns": model_turns if saw_event else None,
            "tool_calls": tool_calls if saw_event else None,
            "wall_ms": round(max(stamps) - min(stamps)) if len(stamps) >= 2 else None,
        }
    )
    return totals


def _host_command(harness: str) -> list[str] | None:
    override = os.environ.get(f"SECOND_BRAIN_{harness.upper().replace('-', '_')}_COMMAND")
    if override:
        parts = shlex.split(override, posix=False)
        return [part.strip('"') for part in parts]
    located = shutil.which(HARNESS_EXECUTABLES[harness])
    if not located:
        return None
    return [located, "-p"] if harness == "claude-code" else [located]


def _run_host(command: list[str], prompt: str, worktree: Path, env: dict[str, str]) -> int | None:
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            cwd=worktree,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode


def _acceptance(command: str, worktree: Path) -> bool | None:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    try:
        completed = subprocess.run(
            command,
            cwd=worktree,
            env=env,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode == 0


def _run_one(
    harness: str, task: dict[str, Any], profile: str, command: list[str]
) -> dict[str, Any] | None:
    run_id = f"{harness}-{task['task_id']}-{profile}-{_utc()}"
    run_dir = RAW_DIR / run_id
    worktree = run_dir / "repo"
    telemetry_home = run_dir / "brain"
    # Retain the executed checkout beside its observations. A host can leave
    # handles open after returning; deleting it here loses provenance and races
    # native cleanup, particularly on Windows.
    run_dir.mkdir(parents=True, exist_ok=True)
    added = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), task["repo_fixture_commit"]],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=60,
    )
    if added.returncode != 0:
        return None
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update(profile_env(profile))
    env["SECOND_BRAIN_HOME"] = str(telemetry_home)
    env["SECOND_BRAIN_PYTHON"] = sys.executable
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    try:
        initialized = subprocess.run(
            [sys.executable, "-m", "second_brain", "--home", str(telemetry_home), "init"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        initialization_error = f"{type(exc).__name__}: {exc}"
    else:
        initialization_error = (
            f"Brain initialization exited {initialized.returncode}"
            if initialized.returncode != 0
            else None
        )
    if initialization_error is not None:
        return {
            "classification": "observed",
            "raw_directory": str(run_dir),
            "worktree": str(worktree),
            "run_id": run_id,
            "harness": harness,
            "task_id": task["task_id"],
            "profile": profile,
            "repo_fixture_commit": task["repo_fixture_commit"],
            "host_exit": None,
            "initialization_error": initialization_error,
            "dollars_reason": "missing_usage",
            "acceptance_pass": None,
            "usage_capture": False,
            "telemetry": aggregate_telemetry(()),
            "dollars": None,
        }
    before = _telemetry_files(telemetry_home)
    host_exit = _run_host(command, task["prompt"], worktree, env)
    after = _telemetry_files(telemetry_home) - before
    telemetry = aggregate_telemetry(after)
    usage_capture = bool(
        telemetry["model_turns"] and all(telemetry[field] is not None for field in _REQUIRED_USAGE)
    )
    config = economics.load_config(ROOT)
    dollars = None
    dollars_reason = None
    if not usage_capture:
        dollars_reason = "missing_usage"
    elif telemetry["mixed_model"]:
        dollars_reason = "mixed_or_unknown_model"
    elif telemetry["model"]:
        dollars = economics.cost_per_run(
            {field: telemetry[field] for field in _REQUIRED_USAGE[:4]},
            config.prices.get(telemetry["model"]),
            multipliers={
                "uncached_in": config.uncached_in,
                "cache_read": config.cache_read,
                "cache_write": config.cache_write,
            },
        )
        if dollars is None:
            dollars_reason = "missing_or_null_price"
    elif not telemetry["model"]:
        dollars_reason = "unknown_model"
    acceptance_pass = (
        _acceptance(task["acceptance"]["command"], worktree) if host_exit == 0 else None
    )
    return {
        "classification": "observed",
        "raw_directory": str(run_dir),
        "worktree": str(worktree),
        "run_id": run_id,
        "harness": harness,
        "task_id": task["task_id"],
        "profile": profile,
        "repo_fixture_commit": task["repo_fixture_commit"],
        "host_exit": host_exit,
        "dollars_reason": dollars_reason,
        "acceptance_pass": acceptance_pass,
        "usage_capture": usage_capture,
        "telemetry": telemetry,
        "dollars": dollars,
    }


def _paired(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["task_id"], {})[record["profile"]] = record
    pairs = []
    for arms in grouped.values():
        if "OFF" not in arms or "ON" not in arms:
            continue

        def metrics(record: dict[str, Any]) -> dict[str, Any]:
            tel = record.get("telemetry") or {}
            return {
                "tokens": tel.get("total_tokens"),
                "dollars": record.get("dollars"),
                "turns": tel.get("model_turns"),
                "wall_ms": tel.get("wall_ms"),
                "pass": record.get("acceptance_pass"),
            }

        pairs.append(
            {
                "off": metrics(arms["OFF"]),
                "on": metrics(arms["ON"]),
                "off_usage_capture": bool(arms["OFF"].get("usage_capture")),
                "on_usage_capture": bool(arms["ON"].get("usage_capture")),
            }
        )
    return pairs


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _write_qualification(summary: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(
            QUALIFICATION.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite
        )
        if not isinstance(loaded, dict):
            raise ValueError("qualification export must be a JSON object")
        existing = loaded
    except FileNotFoundError:
        pass
    economics_section = existing.get("economics")
    economics_section = dict(economics_section) if isinstance(economics_section, dict) else {}
    economics_section[summary["harness"]] = summary
    existing["economics"] = economics_section
    results = existing.get("results")
    if isinstance(results, list):
        results = [
            item
            for item in results
            if not isinstance(item, dict) or item.get("harness") != summary["harness"]
        ]
        results.append(summary)
        existing["results"] = results
    existing["generated_at"] = datetime.now(UTC).isoformat()
    QUALIFICATION.parent.mkdir(parents=True, exist_ok=True)
    QUALIFICATION.write_text(
        json.dumps(existing, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )


def run(harness: str, requested_profile: str, pair_count: int) -> dict[str, Any]:
    tasks = load_tasks()[:pair_count]
    command = _host_command(harness)
    records: list[dict[str, Any]] = []
    if command is not None:
        for task in tasks:
            for profile in ("OFF", "ON"):
                print(f"Running {harness} {task['task_id']} {profile}", file=sys.stderr, flush=True)
                record = _run_one(harness, task, profile, command)
                if record is not None:
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    (RAW_DIR / f"{record['run_id']}.json").write_text(
                        json.dumps(record, indent=2, sort_keys=True, allow_nan=False),
                        encoding="utf-8",
                    )
                    records.append(record)
    pairs = _paired(records)
    summary = {
        "harness": harness,
        "requested_profile": requested_profile,
        "profile_mapping": PROFILE_TO_ABLATION,
        "requested_pairs": pair_count,
        "host_available": command is not None,
        "usage_capture": bool(pairs)
        and all(pair["off_usage_capture"] and pair["on_usage_capture"] for pair in pairs),
        "pairs_recorded": len(pairs),
        "verdict": economics.verdict(pairs, config=economics.load_config(ROOT)),
    }
    _write_qualification(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded paired economics from host telemetry."
    )
    parser.add_argument("--harness", choices=sorted(HARNESS_EXECUTABLES), required=True)
    parser.add_argument("--profile", choices=("OFF", "ON"), required=True)
    parser.add_argument("--pairs", type=int, required=True)
    parser.add_argument("--out", type=Path, help="Preserve this campaign in a separate directory")
    args = parser.parse_args()
    global RAW_DIR, QUALIFICATION
    if not 1 <= args.pairs <= MAX_PAIRS:
        parser.error(f"--pairs must be between 1 and {MAX_PAIRS}")
    if args.out is not None:
        RAW_DIR = args.out.resolve() / "raw"
        QUALIFICATION = args.out.resolve() / "qualification.json"
    print(json.dumps(run(args.harness, args.profile, args.pairs), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
