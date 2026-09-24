"""V3 matched-arm measurement harness (VAL-01; evidence for PERF-01/02/03, RET-02, RET-05).

Arms share model, thinking level, prompt and corpus snapshot. Every run is a fresh
host process with a fresh copy of the snapshot, so no arm sees another arm's
deliveries, caches or ledger writes:

  native          omp --no-extensions -e <capture extension>
  inert           omp --no-extensions -e scripts/v3_inert_extension.ts -e <capture>
  m00             omp --no-extensions -e <installed extension> -e <capture> + production venv
  candidate       omp --no-extensions -e <worktree extension> -e <capture> + worktree venv
  candidate_lean  same as candidate, Lean gate forced to `advisory` (config ablation)

Provider-request capture (request-neutrality evidence)
-----------------------------------------------------
``scripts/v3_request_capture_extension.ts`` is loaded by EVERY arm - including
native - as the LAST ``-e`` path. OMP loads explicit ``-e`` paths in the order
given and ``ExtensionRunner.emitBeforeProviderRequest`` walks the loaded
extensions in that same order, threading the payload through each handler, so a
handler registered last observes the payload as every earlier extension
(including Second Brain) left it. ``--order-probe`` re-checks that claim
empirically with a mutating probe extension loaded before and after the capture.
Each run writes its final provider payloads under ``<out>/capture/<case>-<arm>-R<rep>/``. Every
payload gets two documented views: the **content view** (only this run's own path strings
tokenized; model-visible text and tool schemas untouched) and the **transport view** (that plus
exactly the declared ``TRANSPORT_PATHS`` replaced). The diff is computed on the content view —
so a changed tool-schema property named ``id`` or a changed UUID/date inside message text still
diffs — and the transport view is reported alongside as ``transport_identical``. Transport-looking
paths that are not declared are listed in ``unlisted_transport_like_keys`` and never rewritten.

Lean gate (configuration, never code)
-------------------------------------
The renderer decides Lean injection from ``<home>/config/skills.toml``
``[lean] eval`` (env ``SECOND_BRAIN_LEAN`` overrides). Every arm gets the corpus
snapshot's live config; the two candidate arms additionally get the candidate
worktree's shipped ``config/skills.toml`` copied into their disposable home:
  candidate       -> the shipped file as-is (Lean `off`: the V3 shipping default)
  candidate_lean  -> the same file with the single `[lean] eval` value flipped to
                     `advisory`: a one-value configuration ablation over identical code
  m00             -> the live snapshot setting (untouched)

Both overlays are hashed, their parse is recorded, and every arm's own
interpreter re-resolves the gate inside the run home (``lean_gate_probe``), so
the recorded configuration is the one that actually ran. ``SECOND_BRAIN_LEAN`` is
removed from every run's environment, so no arm can silently inherit an override
from the caller's shell; the extension's own ``lean_kernel`` telemetry shows which
source each live decision used. Config files the candidate branch ships but this
harness does not apply are inventoried in the manifest
(``config_deviation_inventory``) rather than silently mixed in.

The corpus snapshot copies ``config``, ``memory``, ``constitution``, ``templates``,
``skills`` and ``frontier``, so the canonical Lean kernel source and the live
home's skill-approval records are present in every arm's home exactly as in the
live home (role, lifecycle and approval gating still apply; the copied approvals
are inventoried in ``corpus.frontier_approvals``).

Example:
  python scripts/v3_matched_arms.py --reps 2 --out outputs/reports/v3-s2/arms
  python scripts/v3_matched_arms.py --reps 1 --cases-file outputs/reports/v3-s2/dev/cases.jsonl \\
      --cases D01,D02 --out outputs/reports/v3-s2/smoke
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
SNAPSHOT_DIRS = ("config", "memory", "constitution", "templates", "skills", "frontier")
MEMORY_TOKEN = "mem-a8d221e64549"
CAPTURE_EXTENSION = WORKTREE / "scripts" / "v3_request_capture_extension.ts"
ORDER_PROBE_EXTENSION = WORKTREE / "scripts" / "v3_capture_order_probe.ts"
INERT_EXTENSION = WORKTREE / "scripts" / "v3_inert_extension.ts"
# Candidate shipping profile (this branch's checked-in config) and the package
# seed a fresh `brainctl init` gets. Neither is the canonical home's config.
SHIPPED_LEAN_CONFIG = WORKTREE / "config" / "skills.toml"
SEEDED_LEAN_CONFIG = WORKTREE / "src" / "second_brain" / "defaults" / "config" / "skills.toml"
LEAN_CONFIG_REL = Path("config") / "skills.toml"
LEAN_ADVISORY = "advisory"
LEAN_OFF = "off"
USAGE_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "reasoningTokens")

# RET-02 named regression prompts: verbatim from the M00 activation live arms
# (outputs/reports/m00-activation-20260924/live, 2026-09-24).
CONCISE = "In what order should database migrations be applied?"
INSTRUCTION_HEAVY = (
    "Answer from your current context only; do not read files or run shell commands. "
    "Question: in Second Brain, in what order should database migrations be applied? "
    "If your context contains a Second Brain memory packet, quote every memory id it lists "
    "(ids look like mem-xxxxxxxxxxxx). Then call the task tool exactly once with agent 'sonic' "
    "and the task 'Reply with exactly: CHILD-OK-391. Do no other work.' Call no tool other than "
    "task, plus hub only if you must wait for the child's result. Finish with exactly one line: "
    "RESULT <memory ids or NONE> CHILD <child reply or NONE>"
)
NO_BENEFIT = "Reply with exactly: NB-OK-17. Do not use any tools."
CASES = {
    "memory_concise": {"prompt": CONCISE, "token": MEMORY_TOKEN},
    "memory_instruction_heavy": {"prompt": INSTRUCTION_HEAVY, "token": MEMORY_TOKEN},
    "no_benefit": {"prompt": NO_BENEFIT, "token": None},
}
BRAIN_CUSTOM_PREFIX = "brain."

# ---------------------------------------------------------------------------
# Request normalization (documented rule set, applied to every arm identically)
# ---------------------------------------------------------------------------

NORMALIZED_VALUE = "<normalized>"
TRANSPORT_PATHS: tuple[str, ...] = (
    # observed in this work's captures (provider deepseek/deepseek-flash, 2026-09-24)
    "messages[*].tool_calls[*].id",
    "messages[*].tool_call_id",
    # documented OMP provider-request / host message envelope fields for other providers
    "prompt_cache_key",
    "messages[*].id",
    "messages[*].timestamp",
    "messages[*].responseId",
)
TRANSPORT_LIKE_RE = re.compile(
    r"(?i)^(id|ids|.*_id|[a-z0-9]*id|timestamp|created|created_at|ttft|duration|.*cache_key)$"
)
NORMALIZATION_RULES = (
    "content view (primary diff): the only replacement is the run's own path strings -> "
    "<CWD>/<RUN_DIR>/<WORK_DIR>/<BRAIN_HOME>/<EXTENSION_n> (whole-string replacement inside the "
    "JSON text, longest path first, both separator spellings). Model-visible text and the tool "
    "schema subtree are otherwise NEVER rewritten.",
    "transport view (secondary flag): additionally, exactly these provider-request paths are "
    "replaced by <normalized>: " + ", ".join(TRANSPORT_PATHS),
    "any other transport-looking key path is recorded in unlisted_transport_like_keys and left "
    "untouched (differences must show, never be masked).",
)


def _probe() -> Any:
    spec = importlib.util.spec_from_file_location(
        "native_noninterference_probe", WORKTREE / "scripts" / "native_noninterference_probe.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path, *, normalize_newlines: bool = False) -> str:
    data = path.read_bytes()
    if normalize_newlines:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def load_cases_file(path: Path) -> dict[str, dict[str, Any]]:
    """Read a dev/held-out case file: one JSON object per line (id, prompt, expect)."""
    cases: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        expect = [str(item) for item in (obj.get("expect") or [])]
        cases[str(obj["id"])] = {
            "prompt": str(obj["prompt"]),
            "token": expect[0] if expect else None,
            "expect": expect,
            "category": obj.get("category"),
        }
    return cases


def resolve_cases(cases_file: Path | None) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {
        key: {**spec, "expect": [spec["token"]] if spec["token"] else [], "category": "ret02"}
        for key, spec in CASES.items()
    }
    if cases_file is not None:
        cases.update(load_cases_file(cases_file))
    return cases


# ---------------------------------------------------------------------------
# Lean gate configuration
# ---------------------------------------------------------------------------


def lean_eval_from_toml(text: str) -> str | None:
    """Mirror of ``lean_runtime.lean_eval_from_skills_toml`` (declaration use only).

    The harness never parses its own truth: every arm's own interpreter re-resolves
    the gate inside the run home (``lean_gate_probe``) and the extension's own
    telemetry records what the renderer used. This parser only labels the files the
    harness writes.
    """
    in_lean = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_lean = line.startswith("[lean]")
            continue
        if not in_lean or line == "" or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() != "eval":
            continue
        value = rest.split("#")[0].strip().strip('"').lower()
        if value == LEAN_ADVISORY:
            return LEAN_ADVISORY
        if value in {"off", "0", "false", "no"}:
            return LEAN_OFF
        return None
    return None


def with_lean_eval(text: str, value: str) -> tuple[str, int]:
    """Return ``text`` with the ``[lean] eval`` value replaced; count replacements.

    Only the value on the ``eval`` line inside ``[lean]`` is touched, so the
    ablation changes exactly one configuration value.
    """
    out: list[str] = []
    in_lean = False
    replaced = 0
    pattern = re.compile(r"^(\s*eval\s*=\s*)\S+(.*)$")
    for raw_line in text.splitlines(keepends=True):
        stripped = raw_line.strip()
        if stripped.startswith("["):
            in_lean = stripped.startswith("[lean]")
            out.append(raw_line)
            continue
        if in_lean and not stripped.startswith("#"):
            match = pattern.match(raw_line.rstrip("\r\n"))
            if match:
                out.append(f'{match.group(1)}"{value}"{match.group(2)}\n')
                replaced += 1
                continue
        out.append(raw_line)
    return "".join(out), replaced


def lean_overlay(
    shipped: Path, *, value: str | None, out_dir: Path, name: str
) -> dict[str, Any]:
    """Materialize one arm's ``config/skills.toml`` overlay and describe it.

    ``value=None`` keeps the shipped file byte-for-byte (the candidate's own
    shipping default); otherwise the single ``[lean] eval`` value is rewritten.
    """
    text = shipped.read_text(encoding="utf-8")
    if value is None:
        body = text
        changed_lines = 0
    else:
        body, changed_lines = with_lean_eval(text, value)
    if value is not None and changed_lines != 1:
        raise SystemExit(
            f"lean overlay {name}: expected exactly one [lean] eval line in {shipped}, "
            f"replaced {changed_lines}"
        )
    overlay_path = out_dir / f"overlay-{name}-skills.toml"
    overlay_path.write_text(body, encoding="utf-8")
    return {
        "source": str(shipped),
        "source_sha256": _sha256(shipped, normalize_newlines=True),
        "materialized": str(overlay_path),
        "sha256": _sha256_text(body),
        "eval": lean_eval_from_toml(body),
        "rewritten_lines": changed_lines,
    }


def lean_gate_probe(python: Path, home: Path) -> dict[str, Any]:
    """Resolve the Lean gate with the arm's own interpreter inside the arm's own home."""
    code = (
        "import json, pathlib, sys\n"
        "from second_brain import lean_runtime\n"
        "home = pathlib.Path(sys.argv[1])\n"
        "path, status = lean_runtime.resolve_lean_skill_file(home)\n"
        "def decide(role):\n"
        "    out = lean_runtime.decide_lean_runtime(home, role, 'probe task', env={})\n"
        "    return {'decision': out.decision, 'reason': out.reason, 'mode': out.mode,\n"
        "            'eval_source': out.eval_source, 'skill_status': out.skill_status,\n"
        "            'kernel_chars': out.kernel_chars, 'level': out.level,\n"
        "            'placement': out.placement, 'error': out.error}\n"
        "print(json.dumps({'gate': lean_runtime.resolve_lean_eval(home, env={}),\n"
        "                  'skill_file': path, 'skill_status': status,\n"
        "                  'driver': decide('driver'),\n"
        "                  'hard_orchestrator': decide('hard_orchestrator')}))"
    )
    proc = subprocess.run(
        [str(python), "-c", code, str(home)],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-400:] or f"exit {proc.returncode}"}
    return dict(json.loads(proc.stdout))


def read_lean_telemetry(home: Path) -> list[dict[str, Any]]:
    """Lean decisions the extension itself recorded in this run's home."""
    records: list[dict[str, Any]] = []
    for path in sorted((home / "telemetry" / "agent-performance").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("kind") == "lean_kernel":
                records.append(
                    {
                        key: record.get(key)
                        for key in (
                            "decision",
                            "reason",
                            "mode",
                            "eval_source",
                            "skill_status",
                            "kernel_chars",
                            "dedup_hit",
                        )
                    }
                )
    return records


# ---------------------------------------------------------------------------
# Request capture, normalization and diffing
# ---------------------------------------------------------------------------


def path_tokens(
    run_dir: Path, work_dir: Path, home: Path | None, extensions: list[Path]
) -> list[tuple[str, str]]:
    """(literal, token) pairs replaced inside the payload JSON text, longest first."""
    pairs: dict[str, str] = {}

    def add(value: str | Path | None, token: str) -> None:
        if value is None:
            return
        text = str(value)
        for variant in {text, Path(text).as_posix()}:
            for spelling in (variant, variant.replace("\\", "\\\\")):
                pairs.setdefault(spelling, token)

    add(run_dir / "proj", "<CWD>")
    add(run_dir, "<RUN_DIR>")
    add(work_dir, "<WORK_DIR>")
    add(home, "<BRAIN_HOME>")
    for index, entry in enumerate(extensions):
        add(entry, f"<EXTENSION_{index}>")
    return sorted(pairs.items(), key=lambda item: -len(item[0]))


def apply_path_tokens(
    payload: Any, tokens: list[tuple[str, str]]
) -> tuple[Any, dict[str, int]]:
    """Tokenize this run's own path strings in the payload text (the only content-view edit)."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    hits: dict[str, int] = {}
    for literal, token in tokens:
        count = text.count(literal)
        if count:
            text = text.replace(literal, token)
            hits[token] = hits.get(token, 0) + count
    return json.loads(text), hits


def _pattern_steps(pattern: str) -> list[str]:
    """Turn ``messages[*].tool_calls[*].id`` into key/array steps for path-directed edits."""
    steps: list[str] = []
    for chunk in pattern.split("."):
        name = chunk
        wildcards = 0
        while name.endswith("[*]"):
            name = name[: -len("[*]")]
            wildcards += 1
        if name:
            steps.append(name)
        steps.extend(["[*]"] * wildcards)
    return steps


def _strip_at(value: Any, parts: list[str], pattern: str, hits: dict[str, int]) -> Any:
    if not parts:
        hits[pattern] = hits.get(pattern, 0) + 1
        return NORMALIZED_VALUE
    head, rest = parts[0], parts[1:]
    if head == "[*]":
        if isinstance(value, list):
            return [_strip_at(item, rest, pattern, hits) for item in value]
        if isinstance(value, dict):
            return {key: _strip_at(item, rest, pattern, hits) for key, item in value.items()}
        return value
    if isinstance(value, dict) and head in value:
        out = dict(value)
        out[head] = _strip_at(out[head], rest, pattern, hits)
        return out
    return value


def strip_transport_paths(payload: Any) -> tuple[Any, dict[str, int]]:
    """Replace exactly the declared transport paths; every other path stays as captured."""
    hits: dict[str, int] = {}
    value = payload
    for pattern in TRANSPORT_PATHS:
        value = _strip_at(value, _pattern_steps(pattern), pattern, hits)
    return value, hits


def _as_pattern(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", path)


def unlisted_transport_like_keys(payload: Any) -> list[str]:
    """Transport-looking key paths that are NOT declared: reported, never normalized."""
    declared = set(TRANSPORT_PATHS)
    found: set[str] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if TRANSPORT_LIKE_RE.match(key) and _as_pattern(child_path) not in declared:
                    found.add(_as_pattern(child_path))
                walk(child, child_path)
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{path}[*]")

    walk(payload, "")
    return sorted(found)


def normalize_request(payload: Any, tokens: list[tuple[str, str]]) -> dict[str, Any]:
    """Return the two documented views of one captured payload plus the rule-hit report.

    ``content`` is the primary comparison view: the raw payload with only this run's own path
    strings tokenized, so model-visible text and the tool-schema subtree stay intact and any
    real content difference must appear in the diff. ``transport`` additionally replaces the
    declared transport-only paths, so provider-generated ids cannot mask a content change.
    """
    content, path_hits = apply_path_tokens(payload, tokens)
    transport, transport_hits = strip_transport_paths(content)
    return {
        "content": content,
        "transport": transport,
        "report": {
            "paths": path_hits,
            "transport": transport_hits,
            "unlisted_transport_like_keys": unlisted_transport_like_keys(content),
        },
    }


def message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return ""


def tool_name(tool: Any) -> str:
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return str(tool.get("name", ""))


def request_summary(request: dict[str, Any]) -> dict[str, Any]:
    """Structural, content-bounded view of one normalized provider payload."""
    payload = request.get("payload")
    if not isinstance(payload, dict):
        return {"parse_error": request.get("parse_error"), "bytes": request.get("payload_bytes")}
    raw_messages = payload.get("messages")
    messages: list[Any] = raw_messages if isinstance(raw_messages, list) else []
    raw_tools = payload.get("tools")
    tools: list[Any] = raw_tools if isinstance(raw_tools, list) else []
    scalars = {
        key: value
        for key, value in payload.items()
        if key not in ("messages", "tools")
        and isinstance(value, (str, int, float, bool, type(None)))
    }
    return {
        "keys": sorted(payload),
        "scalars": scalars,
        "messages": [
            {
                "role": message.get("role") if isinstance(message, dict) else None,
                "chars": len(message_text(message)),
                # the whole message object is fingerprinted, not just its text: tool_calls,
                # customType, details or any other field must be able to differ
                "sha256": _sha256_text(json.dumps(message, sort_keys=True)),
                "head": message_text(message)[:160],
            }
            for message in messages
        ],
        "tools": [
            {
                "name": tool_name(tool),
                "chars": len(json.dumps(tool, sort_keys=True)),
                "sha256": _sha256_text(json.dumps(tool, sort_keys=True)),
            }
            for tool in tools
        ],
        "fingerprint": _sha256_text(json.dumps(payload, sort_keys=True)),
    }


def _size_delta(arm: int, native: int) -> dict[str, Any]:
    return {
        "chars_before": native,
        "chars_after": arm,
        "chars_delta": arm - native,
    }


def _message_key(message: dict[str, Any]) -> tuple[Any, Any]:
    return (message.get("role"), message.get("sha256"))


def _message_index(summary: dict[str, Any]) -> dict[tuple[Any, Any], list[dict[str, Any]]]:
    index: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for message in summary.get("messages", []):
        index.setdefault(_message_key(message), []).append(message)
    return index


def _describe(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": message.get("role"),
        "chars": message.get("chars"),
        "head": message.get("head"),
    }


def _normalization_hits(reports: list[dict[str, Any]]) -> dict[str, int]:
    """Merged per-run count of each normalization rule that fired.

    ``path:<token>`` = the run's own path tokenization (content view), ``transport:<pattern>`` =
    a declared transport path replaced, ``unlisted:<path>`` = a transport-looking path that was
    left untouched (each occurrence counted) so unlisted noise is visible in the evidence.
    """
    hits: dict[str, int] = {}
    for report in reports:
        for token, count in (report.get("paths") or {}).items():
            key = f"path:{token}"
            hits[key] = hits.get(key, 0) + int(count)
        for pattern, count in (report.get("transport") or {}).items():
            key = f"transport:{pattern}"
            hits[key] = hits.get(key, 0) + int(count)
        for path in report.get("unlisted_transport_like_keys") or []:
            key = f"unlisted:{path}"
            hits[key] = hits.get(key, 0) + 1
    return hits


def diff_requests(
    native_summary: dict[str, Any], arm_summary: dict[str, Any]
) -> dict[str, Any]:
    """Content diff of one normalized provider request against its native twin.

    Messages are matched as a multiset by (role, sha256) rather than by position:
    a renderer may collapse two system blocks into one (Second Brain patches the
    system prompt) or insert a message, and position pairing would then report
    role changes that never happened. A message whose content changed shows up as
    one removed plus one added entry, each carrying its bounded head.
    """
    out: dict[str, Any] = {"identical": False}
    if "parse_error" in native_summary or "parse_error" in arm_summary:
        out["parse_error"] = {
            "native": native_summary.get("parse_error"),
            "arm": arm_summary.get("parse_error"),
        }
        return out
    keys_native = set(native_summary["keys"])
    keys_arm = set(arm_summary["keys"])
    out["fields_added"] = sorted(keys_arm - keys_native)
    out["fields_removed"] = sorted(keys_native - keys_arm)
    out["scalars_changed"] = sorted(
        key
        for key in keys_native & keys_arm
        if native_summary["scalars"].get(key) != arm_summary["scalars"].get(key)
    )
    messages_native = native_summary["messages"]
    messages_arm = arm_summary["messages"]
    before_index = _message_index(native_summary)
    after_index = _message_index(arm_summary)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for key, group in after_index.items():
        twin = before_index.get(key, [])
        added.extend(_describe(message) for message in group[len(twin):])
    for key, group in before_index.items():
        twin = after_index.get(key, [])
        removed.extend(_describe(message) for message in group[len(twin):])
    sequence_native = [list(_message_key(message)) for message in messages_native]
    sequence_arm = [list(_message_key(message)) for message in messages_arm]
    out["messages"] = {
        "count_before": len(messages_native),
        "count_after": len(messages_arm),
        "sequence_identical": sequence_native == sequence_arm,
        "matched": len(messages_arm) - len(added),
        "added": added,
        "removed": removed,
    }
    tools_native = {tool["name"]: tool for tool in native_summary["tools"]}
    tools_arm = {tool["name"]: tool for tool in arm_summary["tools"]}
    out["tools"] = {
        "added": sorted(set(tools_arm) - set(tools_native)),
        "removed": sorted(set(tools_native) - set(tools_arm)),
        "changed": [
            {
                "name": name,
                **_size_delta(tools_arm[name]["chars"], tools_native[name]["chars"]),
            }
            for name in sorted(set(tools_native) & set(tools_arm))
            if tools_native[name]["sha256"] != tools_arm[name]["sha256"]
        ],
    }
    out["identical"] = (
        not out["fields_added"]
        and not out["fields_removed"]
        and not out["scalars_changed"]
        and not added
        and not removed
        and out["messages"]["sequence_identical"]
        and not out["tools"]["added"]
        and not out["tools"]["removed"]
        and not out["tools"]["changed"]
    )
    return out


def read_capture(capture_dir: Path) -> dict[str, Any]:
    """Load one run's captured provider requests (payloads + index metadata)."""
    index_path = capture_dir / "index.jsonl"
    entries: list[dict[str, Any]] = []
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                entry = {"error": "unparseable capture index line"}
            entries.append(dict(entry) if isinstance(entry, dict) else {"error": "bad entry"})
    requests: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        item["payload"] = None
        item["parse_error"] = None
        name = entry.get("file")
        if isinstance(name, str):
            try:
                item["payload"] = json.loads(
                    (capture_dir / name).read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, ValueError) as exc:
                item["parse_error"] = f"{type(exc).__name__}: {exc}"
        requests.append(item)
    return {"dir": str(capture_dir), "count": len(entries), "requests": requests}


def capture_inventory(capture: dict[str, Any]) -> dict[str, Any]:
    """Request-count and per-request model inventory, separate from usage."""
    return {
        "request_count": capture["count"],
        "models": sorted({str(r.get("model")) for r in capture["requests"] if r.get("model")}),
        "pids": sorted({r.get("pid") for r in capture["requests"] if r.get("pid")}),
        "payload_bytes": [r.get("payload_bytes") for r in capture["requests"]],
        "truncated": any(bool(r.get("truncated")) for r in capture["requests"]),
        "files": [r.get("file") for r in capture["requests"]],
    }


# ---------------------------------------------------------------------------
# Corpus snapshot and identities
# ---------------------------------------------------------------------------


def snapshot_corpus(source: Path, dest: Path, tokens: list[str] | None = None) -> dict[str, Any]:
    """Copy one consistent corpus snapshot: SQLite backup + canonical text roots."""
    dest.mkdir(parents=True)
    (dest / "db").mkdir()
    src = sqlite3.connect(f"file:{(source / 'db' / 'brain.sqlite').as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(dest / "db" / "brain.sqlite")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for name in SNAPSHOT_DIRS:
        if (source / name).is_dir():
            shutil.copytree(source / name, dest / name)
    for marker in source.glob(".second-brain*"):
        if marker.is_file():
            shutil.copy2(marker, dest / marker.name)
    for name in ("VERSION",):
        if (source / name).is_file():
            shutil.copy2(source / name, dest / name)
    conn = sqlite3.connect(dest / "db" / "brain.sqlite")
    try:
        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        schema = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        has_token = (
            conn.execute("SELECT 1 FROM memories WHERE memory_id = ?", (MEMORY_TOKEN,)).fetchone()
            is not None
        )
        tokens_present = {
            token: conn.execute(
                "SELECT 1 FROM memories WHERE memory_id = ?", (token,)
            ).fetchone()
            is not None
            for token in (tokens or [])
        }
    finally:
        conn.close()
    live_lean: str | None = None
    lean_config = dest / LEAN_CONFIG_REL
    if lean_config.is_file():
        live_lean = lean_eval_from_toml(lean_config.read_text(encoding="utf-8"))
    frontier_files = {
        path.relative_to(dest / "frontier").as_posix(): _sha256(path, normalize_newlines=True)
        for path in sorted((dest / "frontier").rglob("*"))
        if path.is_file()
    }
    return {
        "source": str(source),
        "snapshot_dirs": list(SNAPSHOT_DIRS),
        "db_sha256": _sha256(dest / "db" / "brain.sqlite"),
        "memories": memories,
        "schema_version": schema,
        "contains_regression_memory": has_token,
        "tokens_present": tokens_present,
        "live_lean_eval": live_lean,
        "live_config_sha256": (
            _sha256(lean_config) if lean_config.is_file() else None
        ),
        "frontier_approvals": frontier_files,
    }


def config_deviation_inventory(snapshot: Path, candidate_config: Path) -> dict[str, Any]:
    """Config files the candidate branch ships that this harness does not apply."""
    differing: list[dict[str, Any]] = []
    only_candidate: list[str] = []
    only_live: list[str] = []
    live_dir = snapshot / "config"
    candidate_files = sorted(p for p in candidate_config.rglob("*.toml") if p.is_file())
    for path in candidate_files:
        rel = path.relative_to(candidate_config)
        live = live_dir / rel
        if not live.is_file():
            only_candidate.append(rel.as_posix())
            continue
        if _sha256(path, normalize_newlines=True) != _sha256(live, normalize_newlines=True):
            differing.append(
                {
                    "file": rel.as_posix(),
                    "candidate_sha256": _sha256(path, normalize_newlines=True),
                    "live_sha256": _sha256(live, normalize_newlines=True),
                }
            )
    for path in sorted(p for p in live_dir.rglob("*.toml") if p.is_file()):
        rel = path.relative_to(live_dir)
        if not (candidate_config / rel).is_file():
            only_live.append(rel.as_posix())
    return {
        "applied": [LEAN_CONFIG_REL.as_posix()],
        "differing_not_applied": differing,
        "only_in_candidate_not_applied": only_candidate,
        "only_live_retained": only_live,
    }


def runtime_identity(python: Path) -> dict[str, Any]:
    """Imported source identity of an interpreter (PORT-02): what the arm really runs."""
    code = (
        "import json, pathlib, second_brain\n"
        "from second_brain import build_identity as b\n"
        "src = pathlib.Path(second_brain.__file__).resolve().parents[2]\n"
        "print(json.dumps({'module': second_brain.__file__, 'git_sha': b.git_sha(src),"
        " 'dirty': b.git_dirty(src), 'source_tree': b.source_tree_fingerprint(src)}))"
    )
    proc = subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True, env=_clean_env(), check=False
    )
    if proc.returncode != 0:
        return {"python": str(python), "error": proc.stderr[-400:]}
    return {"python": str(python), **json.loads(proc.stdout)}


def extension_identity(entry: Path) -> dict[str, Any]:
    files = sorted(p for p in entry.parent.rglob("*.ts") if p.is_file())
    manifest = {p.relative_to(entry.parent).as_posix(): _sha256(p, normalize_newlines=True)
                for p in files}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return {"entry": str(entry), "files": len(files), "lf_manifest_sha256": digest}


# ---------------------------------------------------------------------------
# Host runs
# ---------------------------------------------------------------------------


def run_once(
    omp: str,
    argv_tail: list[str],
    env: dict[str, str],
    timeout: int,
    raw_path: Path,
) -> dict[str, Any]:
    """Run one host process, stamping each JSON event line with the harness clock."""
    started = time.perf_counter()
    marks: dict[str, float] = {}
    lines: list[str] = []
    proc = subprocess.Popen(
        [omp, *argv_tail], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        env=env, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    timed_out = False
    for line in proc.stdout:
        now = round((time.perf_counter() - started) * 1000, 1)
        lines.append(line)
        if now > timeout * 1000:
            proc.kill()
            timed_out = True
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        role = (event.get("message") or {}).get("role") if isinstance(event, dict) else None
        key = f"{kind}:{role}" if role else str(kind)
        marks.setdefault(key, now)
    stderr = proc.stderr.read() if proc.stderr else ""
    rc = proc.wait()
    raw = "".join(lines)
    raw_path.write_text(raw, encoding="utf-8")
    return {
        "returncode": None if timed_out else rc,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "marks_ms": marks,
        "raw": raw,
        "stderr_tail": stderr[-400:],
    }


def usage_totals(raw: str) -> dict[str, Any]:
    """Provider usage and request inventory, separately; unreported fields stay null.

    A field the host never reported is ``null`` (unknown), never 0: ``totals``
    only sums requests that carried the field and ``fields_reported`` counts them.
    """
    totals: dict[str, int | None] = {key: None for key in USAGE_FIELDS}
    reported: dict[str, int] = {key: 0 for key in USAGE_FIELDS}
    cost: float | None = None
    cost_reported = 0
    requests: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if event.get("type") != "message_end" or not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage")
        usage = usage if isinstance(usage, dict) else None
        for key in USAGE_FIELDS:
            value = usage.get(key) if usage else None
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = (totals[key] or 0) + value
                reported[key] += 1
        total_cost = usage.get("cost") if usage else None
        if isinstance(total_cost, dict) and total_cost.get("total") is not None:
            cost = (cost or 0.0) + float(total_cost["total"])
            cost_reported += 1
        requests.append(
            {
                "response_id": message.get("responseId"),
                "ttft": message.get("ttft"),
                "duration": message.get("duration"),
                "model": message.get("model"),
                "usage_present": usage is not None,
            }
        )
    return {
        "request_count": len(requests),
        "totals": totals,
        "fields_reported": reported,
        "cost_total": round(cost, 8) if cost is not None else None,
        "cost_reported_requests": cost_reported,
        "requests": requests,
    }


def sum_usage_field(rows: list[dict[str, Any]], field: str) -> int | None:
    """Sum one provider usage field across runs; null when any run never reported it."""
    values = [row["provider_usage"]["totals"].get(field) for row in rows]
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def capture_order_check(
    omp: str, work: Path, out: Path, args: argparse.Namespace
) -> dict[str, Any]:
    """Prove empirically that a later ``-e`` extension observes an earlier one's payload.

    ``scripts/v3_capture_order_probe.ts`` replaces the payload with a marker key.
    Loaded before the capture, the capture must see the marker; loaded after it,
    the capture must not.
    """
    marker = "v3-order-probe-marker"
    results: dict[str, Any] = {}
    for name, order in (
        ("probe_then_capture", [ORDER_PROBE_EXTENSION, CAPTURE_EXTENSION]),
        ("capture_then_probe", [CAPTURE_EXTENSION, ORDER_PROBE_EXTENSION]),
    ):
        run_dir = work / f"order-{name}"
        (run_dir / "proj").mkdir(parents=True, exist_ok=True)
        env = _clean_env()
        env["V3_CAPTURE_DIR"] = str(run_dir / "capture")
        env["V3_CAPTURE_LABEL"] = f"order-{name}"
        env["V3_ORDER_PROBE_MARKER"] = marker
        tail = [
            "-p", "--mode", "json", "--model", args.model, "--thinking", args.thinking,
            "--no-session", "--session-dir", str(run_dir / "sessions"),
            "--cwd", str(run_dir / "proj"), "--no-extensions",
        ]
        for entry in order:
            tail += ["-e", str(entry)]
        tail.append("Reply with exactly: OK")
        result = run_once(omp, tail, env, args.timeout, out / f"order-{name}.raw.jsonl")
        capture = read_capture(run_dir / "capture")
        seen = [
            (request["payload"] or {}).get("v3_order_probe_marker")
            if isinstance(request["payload"], dict)
            else None
            for request in capture["requests"]
        ]
        results[name] = {
            "extension_order": [str(entry) for entry in order],
            "returncode": result.pop("returncode"),
            "requests": capture["count"],
            "marker_seen_in_capture": seen,
        }
    probe_first = results["probe_then_capture"]["marker_seen_in_capture"]
    capture_first = results["capture_then_probe"]["marker_seen_in_capture"]
    results["verdict"] = {
        "capture_after_earlier_extension_sees_its_replacement": bool(
            probe_first and all(value == marker for value in probe_first)
        ),
        "capture_before_later_extension_does_not_see_it": all(
            value is None for value in capture_first
        ),
    }
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    canonical = WORKTREE.parents[1] if WORKTREE.parent.name == ".worktrees" else WORKTREE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--corpus-home", default=str(canonical))
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    ap.add_argument("--thinking", default="low")
    ap.add_argument(
        "--project-id",
        default="second-brain",
        help="host-observed project identity for Brain arms (the temp cwd is unregistered)",
    )
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--omp", default="omp")
    ap.add_argument("--arms", default="native,inert,m00,candidate,candidate_lean")
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument(
        "--cases-file",
        default=None,
        help="JSONL case file (id, prompt, expect) merged over the built-in RET-02 cases",
    )
    ap.add_argument(
        "--m00-extension",
        default=str(Path.home() / ".omp/agent/extensions/second-brain/index.ts"),
    )
    ap.add_argument("--m00-python", default=str(canonical / ".venv/Scripts/python.exe"))
    ap.add_argument(
        "--candidate-extension", default=str(WORKTREE / "brainstem/prime-extension/src/index.ts")
    )
    ap.add_argument("--candidate-python", default=str(WORKTREE / ".venv/Scripts/python.exe"))
    ap.add_argument(
        "--candidate-config",
        default=str(SHIPPED_LEAN_CONFIG),
        help="candidate shipping profile: the config file the candidate arms run with",
    )
    ap.add_argument(
        "--no-capture",
        action="store_true",
        help="S1-parity timing mode: load no capture extension (no request-diff evidence)",
    )
    ap.add_argument(
        "--order-probe",
        action="store_true",
        help="run the two-extension hook-order check and record it in the manifest",
    )
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="v3-arms-"))
    probe = _probe()
    cases = resolve_cases(Path(args.cases_file) if args.cases_file else None)
    selected_cases = [case for case in args.cases.split(",") if case]
    unknown = [case for case in selected_cases if case not in cases]
    if unknown:
        print(f"unknown cases: {', '.join(unknown)}", file=sys.stderr)
        return 2
    expect_tokens = sorted(
        {token for case in selected_cases for token in cases[case].get("expect", [])}
    )
    snapshot = work / "snapshot"
    corpus = snapshot_corpus(Path(args.corpus_home), snapshot, tokens=expect_tokens)

    candidate_config = Path(args.candidate_config)
    overlays = {
        "candidate": lean_overlay(candidate_config, value=None, out_dir=out, name="candidate"),
        "candidate_lean": lean_overlay(
            candidate_config, value=LEAN_ADVISORY, out_dir=out, name="candidate_lean"
        ),
    }
    arms: dict[str, dict[str, Any]] = {
        "native": {"extension": None, "python": None, "overlay": None},
        "inert": {"extension": INERT_EXTENSION, "python": None, "overlay": None},
        "m00": {
            "extension": Path(args.m00_extension),
            "python": Path(args.m00_python),
            "overlay": None,
        },
        "candidate": {
            "extension": Path(args.candidate_extension),
            "python": Path(args.candidate_python),
            "overlay": overlays["candidate"],
        },
        "candidate_lean": {
            "extension": Path(args.candidate_extension),
            "python": Path(args.candidate_python),
            "overlay": overlays["candidate_lean"],
        },
    }
    selected_arms = [a for a in args.arms.split(",") if a]
    for arm in selected_arms:
        if arm not in arms:
            print(f"unknown arm: {arm}", file=sys.stderr)
            return 2

    # One gate probe per arm against a scratch home carrying exactly the overlay
    # that arm's runs get, so the recorded configuration is the one that ran.
    gate_homes: dict[str, Path] = {}
    for arm in selected_arms:
        spec = arms[arm]
        if spec["python"] is None:
            continue
        scratch = work / f"gate-{arm}"
        shutil.copytree(snapshot, scratch)
        if spec["overlay"] is not None:
            overlay_path = Path(spec["overlay"]["materialized"])
            shutil.copy2(overlay_path, scratch / LEAN_CONFIG_REL)
        gate_homes[arm] = scratch

    manifest: dict[str, Any] = {
        "harness": "scripts/v3_matched_arms.py",
        "harness_sha256": _sha256(Path(__file__), normalize_newlines=True),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "omp_version": subprocess.run([args.omp, "--version"], capture_output=True, text=True,
                                      check=False).stdout.strip(),
        "model": args.model,
        "thinking": args.thinking,
        "project_id": args.project_id,
        "reps": args.reps,
        "seed": args.seed,
        "corpus_home": str(args.corpus_home),
        "corpus": corpus,
        "cases": {c: cases[c] for c in selected_cases},
        "capture": {
            "enabled": not args.no_capture,
            "extension": None if args.no_capture else extension_identity(CAPTURE_EXTENSION),
            "hook": "before_provider_request",
            "load_position": "last `-e` path in every arm (observed after earlier extensions)",
            "output_dir": str(out / "capture") if not args.no_capture else None,
            "normalization_rules": list(NORMALIZATION_RULES),
            "order_check": (
                capture_order_check(args.omp, work, out, args) if args.order_probe else None
            ),
        },
        "config_profile": {
            "applied_overlays": {
                arm: overlays[arm]
                for arm in ("candidate", "candidate_lean")
                if arm in selected_arms
            },
            "m00_setting": "live snapshot config",
            "env_override_removed": (
                "SECOND_BRAIN_LEAN (arm behavior is its configuration, never the caller's)"
            ),
            "deviation_inventory": config_deviation_inventory(snapshot, candidate_config.parent),
            "seed_config": {
                "path": str(SEEDED_LEAN_CONFIG),
                "sha256": _sha256(SEEDED_LEAN_CONFIG),
                "eval": lean_eval_from_toml(SEEDED_LEAN_CONFIG.read_text(encoding="utf-8")),
            },
        },
        "arms": {
            name: {
                "extension": extension_identity(spec["extension"]) if spec["extension"] else None,
                "runtime": runtime_identity(spec["python"]) if spec["python"] else None,
                "lean_overlay": spec["overlay"],
                "lean_gate_probe": (
                    lean_gate_probe(spec["python"], gate_homes[name]) if spec["python"] else None
                ),
            }
            for name, spec in arms.items() if name in selected_arms
        },
        "conditions": (
            "Every run is a fresh host process with a fresh copy of the corpus snapshot; "
            "no in-process warm state. rep 0 is the first run of each arm/case in this "
            "invocation (OS file cache cold for that arm); later reps are OS-cache warm. "
            + (
                "Every arm loads the capture extension as its last `-e` path, including "
                "native (one extra handler plus one payload dump per provider request)."
                if not args.no_capture
                else "Capture extension disabled (--no-capture): timing parity with S1, no "
                "request-diff evidence."
            )
        ),
    }
    if args.order_probe:
        (out / "capture-order-check.json").write_text(
            json.dumps(manifest["capture"]["order_check"], indent=1), encoding="utf-8"
        )

    rng = random.Random(args.seed)
    runs: list[dict[str, Any]] = []
    for case in selected_cases:
        spec_case = cases[case]
        missing = [
            token
            for token in spec_case.get("expect", [])
            if not corpus["tokens_present"].get(token)
        ]
        if missing:
            runs.append(
                {
                    "case": case,
                    "status": "NOT_RUN",
                    "reason": f"memory absent from corpus: {missing}",
                }
            )
            continue
        for rep in range(args.reps):
            order = list(selected_arms)
            rng.shuffle(order)
            for position, arm in enumerate(order):
                spec = arms[arm]
                # Same-length paths for every arm: the cwd is model-visible, so an
                # arm name in it would skew the input-token comparison.
                run_dir = work / f"run{len(runs):04d}"
                (run_dir / "proj").mkdir(parents=True)
                env = _clean_env()
                # The Lean gate must be exactly the arm's configuration: a stray
                # SECOND_BRAIN_LEAN in the caller's environment would silently
                # override the shipped setting under test.
                env.pop("SECOND_BRAIN_LEAN", None)
                tail = ["-p", "--mode", "json", "--model", args.model, "--thinking", args.thinking,
                        "--no-session", "--session-dir", str(run_dir / "sessions"),
                        "--cwd", str(run_dir / "proj"), "--no-extensions"]
                if spec["extension"] is not None:
                    tail += ["-e", str(spec["extension"])]
                capture_dir = run_dir / "capture"
                if not args.no_capture:
                    env["V3_CAPTURE_DIR"] = str(capture_dir)
                    env["V3_CAPTURE_LABEL"] = f"{case}-{arm}-R{rep}"
                    tail += ["-e", str(CAPTURE_EXTENSION)]
                home: Path | None = None
                if spec["python"] is not None:
                    home = run_dir / "home"
                    shutil.copytree(snapshot, home)
                    if spec["overlay"] is not None:
                        shutil.copy2(Path(spec["overlay"]["materialized"]), home / LEAN_CONFIG_REL)
                    env["SECOND_BRAIN_HOME"] = str(home)
                    env["SECOND_BRAIN_PYTHON"] = str(spec["python"])
                    env["SECOND_BRAIN_PROJECT"] = args.project_id
                tail.append(spec_case["prompt"])
                raw_path = out / f"{case}-{arm}-{rep}.jsonl"
                result = run_once(args.omp, tail, env, args.timeout, raw_path)
                raw = result.pop("raw")
                summary = probe.summarize_arm(raw, token=spec_case["token"])
                brain_messages = [m for m in summary.get("custom_messages", [])
                                  if str(m.get("customType", "")).startswith(BRAIN_CUSTOM_PREFIX)]
                record: dict[str, Any] = {
                    "case": case, "arm": arm, "rep": rep, "order_position": position,
                    "run_dir": str(run_dir),
                    "returncode": result["returncode"], "wall_ms": result["wall_ms"],
                    "marks_ms": result["marks_ms"], "stderr_tail": result["stderr_tail"],
                    "brain_custom_messages": [
                        {"customType": m.get("customType"), "chars": m.get("chars")}
                        for m in brain_messages
                    ],
                    "brain_visible_chars": sum(int(m.get("chars") or 0) for m in brain_messages),
                    "memory_delivered": bool(
                        spec_case["token"]
                        and summary.get("token_evidence", {}).get("injected_context_records")
                    ),
                    "tool_calls": summary.get("other_tool_calls", []),
                    "spawned_agents": summary.get("spawned_agents", []),
                    "final_text": summary.get("final_text", []),
                    "provider_usage": usage_totals(raw),
                    "capture": None,
                    "normalization": None,
                    "lean_kernel": read_lean_telemetry(home) if home is not None else None,
                    "lean_config_sha256": (
                        _sha256(home / LEAN_CONFIG_REL) if home is not None else None
                    ),
                }
                if not args.no_capture:
                    capture = read_capture(capture_dir)
                    record["capture"] = capture_inventory(capture)
                    capture_out = out / "capture" / f"{case}-{arm}-R{rep}"
                    if capture_out.exists():
                        shutil.rmtree(capture_out)
                    if capture_dir.is_dir():
                        shutil.copytree(capture_dir, capture_out)
                    normalized: list[dict[str, Any]] = []
                    transport_normalized: list[dict[str, Any]] = []
                    reports: list[dict[str, Any]] = []
                    tokens = path_tokens(
                        run_dir,
                        work,
                        home,
                        [p for p in (spec["extension"], CAPTURE_EXTENSION, spec["python"]) if p],
                    )
                    for request in capture["requests"]:
                        if request["payload"] is None:
                            normalized.append({"parse_error": request.get("parse_error")})
                            transport_normalized.append({"parse_error": request.get("parse_error")})
                            reports.append({})
                            continue
                        views = normalize_request(request["payload"], tokens)
                        normalized.append(request_summary({**request, "payload": views["content"]}))
                        transport_normalized.append(
                            request_summary({**request, "payload": views["transport"]})
                        )
                        reports.append(views["report"])
                    record["normalization"] = reports
                    (out / "normalized" / f"{case}-{arm}-R{rep}.json").parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    (out / "normalized" / f"{case}-{arm}-R{rep}.json").write_text(
                        json.dumps(
                            {
                                "content_summary": normalized,
                                "transport_summary": transport_normalized,
                                "normalization": reports,
                            },
                            indent=1,
                        ),
                        encoding="utf-8",
                    )
                    record["_normalized_requests"] = normalized
                    record["_transport_requests"] = transport_normalized
                runs.append(record)
                print(json.dumps({k: runs[-1][k] for k in
                                  ("case", "arm", "rep", "wall_ms", "brain_visible_chars",
                                   "memory_delivered")}), flush=True)

    # Request diff against native for the same case/repetition.
    diffs: dict[str, Any] = {}
    if not args.no_capture:
        for record in runs:
            if record.get("status") == "NOT_RUN" or record["arm"] == "native":
                continue
            native = next(
                (
                    row for row in runs
                    if row.get("case") == record["case"]
                    and row.get("arm") == "native"
                    and row.get("rep") == record["rep"]
                ),
                None,
            )
            key = f"{record['case']}/{record['arm']}/R{record['rep']}"
            if native is None:
                diffs[key] = {"status": "NO_NATIVE_REFERENCE"}
                continue
            native_requests = native.get("_normalized_requests") or []
            arm_requests = record.get("_normalized_requests") or []
            native_transport = native.get("_transport_requests") or []
            arm_transport = record.get("_transport_requests") or []
            per_request: list[dict[str, Any]] = []
            for content_pair, transport_pair in zip(
                zip(native_requests, arm_requests, strict=False),
                zip(native_transport, arm_transport, strict=False),
                strict=False,
            ):
                content_diff = diff_requests(content_pair[0], content_pair[1])
                transport_diff = diff_requests(transport_pair[0], transport_pair[1])
                content_diff["content_identical"] = content_diff["identical"]
                content_diff["transport_identical"] = transport_diff["identical"]
                content_diff["identical"] = content_diff["content_identical"]
                per_request.append(content_diff)
            fingerprints_native = sorted(
                summary.get("fingerprint", "") for summary in native_requests
            )
            fingerprints_arm = sorted(summary.get("fingerprint", "") for summary in arm_requests)
            transport_native = sorted(
                summary.get("fingerprint", "") for summary in native_transport
            )
            transport_arm = sorted(summary.get("fingerprint", "") for summary in arm_transport)
            deltas = {"system_chars": 0, "message_chars": 0, "tool_schema_chars": 0}

            def _chars(summary: dict[str, Any], *, role: str | None) -> int:
                return sum(
                    message["chars"]
                    for message in summary.get("messages", [])
                    if role is None or message.get("role") == role
                )

            for native_summary, arm_summary in zip(
                native_requests, arm_requests, strict=False
            ):
                system_delta = _chars(arm_summary, role="system") - _chars(
                    native_summary, role="system"
                )
                total_delta = _chars(arm_summary, role=None) - _chars(native_summary, role=None)
                deltas["system_chars"] += system_delta
                deltas["message_chars"] += total_delta - system_delta
                deltas["tool_schema_chars"] += sum(
                    tool["chars"] for tool in arm_summary.get("tools", [])
                ) - sum(tool["chars"] for tool in native_summary.get("tools", []))
            first_request = per_request[0] if per_request else None
            diffs[key] = {
                "case": record["case"],
                "arm": record["arm"],
                "rep": record["rep"],
                "native_run_dir": native["run_dir"],
                "request_count": {"native": len(native_requests), "arm": len(arm_requests)},
                "same_request_set": fingerprints_native == fingerprints_arm,
                "same_transport_request_set": transport_native == transport_arm,
                "normalized_fields": _normalization_hits(record.get("normalization") or []),
                "tail_requests_note": (
                    "Requests after the first are the model's own tool loop; their count and "
                    "content follow the model's choices (nondeterministic per run), so only the "
                    "first request is a content comparison of the arms' own injection."
                ),
                "tail_request_shapes": [
                    {
                        "index": index,
                        "keys": summary.get("keys"),
                        "roles": [message.get("role") for message in summary.get("messages", [])],
                    }
                    for index, summary in enumerate(arm_requests[1:], start=1)
                ],
                "first_request_identical": (
                    bool(first_request.get("identical")) if first_request else None
                ),
                "first_request_transport_identical": (
                    first_request.get("transport_identical") if first_request else None
                ),
                "first_request_added_messages": (
                    first_request.get("messages", {}).get("added") if first_request else None
                ),
                "first_request_removed_messages": (
                    first_request.get("messages", {}).get("removed") if first_request else None
                ),
                "first_request_deltas": (
                    {
                        "system_chars": _chars(arm_requests[0], role="system")
                        - _chars(native_requests[0], role="system"),
                        "message_chars": _chars(arm_requests[0], role=None)
                        - _chars(native_requests[0], role=None),
                        "tool_schema_chars": sum(
                            tool["chars"] for tool in arm_requests[0].get("tools", [])
                        )
                        - sum(tool["chars"] for tool in native_requests[0].get("tools", [])),
                    }
                    if native_requests and arm_requests
                    else None
                ),
                "content_identical": bool(per_request)
                and all(diff.get("identical") for diff in per_request)
                and len(native_requests) == len(arm_requests),
                "char_deltas": deltas,
                "per_request": per_request,
            }
        (out / "diffs.json").write_text(json.dumps(diffs, indent=1), encoding="utf-8")

    aggregate: dict[str, Any] = {}
    for case in selected_cases:
        for arm in selected_arms:
            rows = [r for r in runs if r.get("case") == case and r.get("arm") == arm]
            if not rows:
                continue
            walls = [r["wall_ms"] for r in rows]
            prep = [r["marks_ms"]["message_end:user"] for r in rows
                    if "message_end:user" in r["marks_ms"]]
            prep_median = round(statistics.median(prep), 1) if prep else None
            input_total = sum_usage_field(rows, "input")
            cache_read = sum_usage_field(rows, "cacheRead")
            aggregate[f"{case}/{arm}"] = {
                "n": len(rows),
                "failures": sum(1 for r in rows if r["returncode"] != 0),
                "wall_ms_median": round(statistics.median(walls), 1),
                "to_user_message_end_ms_median": prep_median,
                "brain_visible_chars": [r["brain_visible_chars"] for r in rows],
                "memory_delivered": [r["memory_delivered"] for r in rows],
                "input_tokens": (
                    None
                    if input_total is None or cache_read is None
                    else input_total + cache_read
                ),
                "cost_total": (
                    None
                    if any(r["provider_usage"]["cost_total"] is None for r in rows)
                    else round(sum(float(r["provider_usage"]["cost_total"]) for r in rows), 6)
                ),
                "provider_requests": [r["capture"]["request_count"] for r in rows
                                      if r.get("capture")],
                "provider_usage_totals": {
                    field: sum_usage_field(rows, field) for field in USAGE_FIELDS
                },
                "usage_reported_requests": [
                    {field: r["provider_usage"]["fields_reported"][field] for field in USAGE_FIELDS}
                    for r in rows
                ],
                "lean_kernel": [
                    record for r in rows for record in (r.get("lean_kernel") or [])
                ],
                "request_diff": [
                    {
                        "rep": r["rep"],
                        **{
                            key: diffs.get(f"{case}/{arm}/R{r['rep']}", {}).get(key)
                            for key in (
                                "first_request_identical",
                                "first_request_transport_identical",
                                "first_request_deltas",
                                "first_request_added_messages",
                                "first_request_removed_messages",
                                "content_identical",
                                "same_request_set",
                                "char_deltas",
                                "request_count",
                            )
                        },
                    }
                    for r in rows
                ] if not args.no_capture else None,
            }
    for record in runs:
        record.pop("_normalized_requests", None)
        record.pop("_transport_requests", None)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "runs.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")
    (out / "aggregate.json").write_text(json.dumps(aggregate, indent=1), encoding="utf-8")
    print(json.dumps(aggregate, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
