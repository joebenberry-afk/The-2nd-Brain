"""E01 turn bridge — one bounded memory-preparation call per host turn.

The Prime adapter used to reach this module's three phases through three
separate CLI processes per prompt (`capsule ensure` -> `vmem hot-context`
render -> `autoinject shadow`). Each process pays the same package-import
cost, so the adapter's pre-dispatch latency was dominated by interpreter
startup, not by memory work. This module exposes the SAME three phase
implementations in ONE interpreter, in the SAME order, with three entry
points:

* :func:`prepare_turn` — batch the phases into one bounded process per prompt
  ("one-shot" design);
* :func:`serve` — a JSON-lines loop that keeps the interpreter alive across
  the turns of one host session ("reused interpreter" design). The helper is
  a memory operation only: it never authorizes, never decides host lifecycle
  and never holds host-agent authority. Every response is advisory data;
* :func:`identity` / :func:`identity_drift` — code/config/DB fingerprints
  that make a reused helper answer `identity_changed` (and be restarted)
  instead of answering from stale loaded state.

Semantics contract: `prepare_turn` calls exactly the functions the three CLI
commands call, with the same arguments and in the same order, so a batched
turn cannot disagree with the separate commands (`tests/test_turn_bridge.py`
asserts field equality against the CLI paths). Every phase is fail-open: a
failure is reported as `<phase>_error` and never raises into the host turn.

Timing: when ``SECOND_BRAIN_E01_TRACE`` names a file, each phase appends one
JSON line (epoch milliseconds, same clock as the Prime extension's own spans)
so the harness can reconcile Python work against the extension's critical
path.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from . import build_identity, capsule_runtime, contracts, db, ledger, vmem
from .errors import BrainError

TRACE_ENV = "SECOND_BRAIN_E01_TRACE"

PHASES: tuple[str, ...] = ("capsule", "render", "autoinject")

#: Bound on one JSON-lines request (a prompt is never larger than the
#: adapter's own `--task` argv bound of 4000 chars; 64 KiB leaves headroom for
#: multi-byte characters and future fields).
MAX_REQUEST_BYTES = 64 * 1024
#: Windows CreateProcess argv safety margin, same value the Prime adapter uses
#: for `--task` (AUTOINJECT_MAX_TASK_ARG_CHARS).
MAX_TASK_CHARS = 4000
#: Bounded helper lifetime: request count, wall clock and resident set. Any
#: bound being reached ends the helper AFTER the current response; the
#: adapter restarts a fresh interpreter on its next need.
DEFAULT_MAX_REQUESTS = 256
DEFAULT_MAX_LIFETIME_S = 1800.0
DEFAULT_MAX_RSS_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_ERRORS = 8


def now_ms() -> float:
    """Wall clock in epoch milliseconds (shared clock with the host adapter)."""
    return time.time() * 1000.0


def trace_path() -> str | None:
    value = os.environ.get(TRACE_ENV, "").strip()
    return value or None


def trace(kind: str, **fields: Any) -> None:
    """Append one trace line; measurement must never break a host turn."""
    path = trace_path()
    if path is None:
        return
    record = {"t": kind, "t_wall": now_ms(), "pid": os.getpid(), **fields}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    except OSError:
        # Unwritable trace file: measurement degrades, the turn does not.
        return


@contextlib.contextmanager
def traced_phase(name: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Time one phase and emit a `phase` span (start/end/duration_ms)."""
    start = now_ms()
    box: dict[str, Any] = {}
    try:
        yield box
    finally:
        end = now_ms()
        trace(
            "phase",
            name=name,
            start_ms=start,
            end_ms=end,
            duration_ms=round(end - start, 3),
            **fields,
            **box,
        )


def _repo_root() -> Path | None:
    """Repository root that contains the imported package (identity source)."""
    module = Path(__file__).resolve()
    # <root>/src/second_brain/turn_bridge.py
    root = module.parents[2] if len(module.parents) > 2 else None
    return root if root is not None and (root / "pyproject.toml").is_file() else None


def _source_mtime_ns() -> int:
    """Cheap change signal: newest mtime under the imported package tree."""
    newest = 0
    root = Path(__file__).resolve().parent
    with contextlib.suppress(OSError):
        for entry in root.rglob("*.py"):
            with contextlib.suppress(OSError):
                newest = max(newest, entry.stat().st_mtime_ns)
    return newest


def _db_stat(home: Path) -> dict[str, Any]:
    """Cheap database identity: path plus size/mtime (no connection)."""
    path = db.db_path(home)
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def identity(home: Path | str) -> dict[str, Any]:
    """Code/config/DB identity of this interpreter's view of the Brain.

    The adapter compares the value it received at helper startup against
    :func:`identity_drift` on every request and restarts the helper when the
    memory authority it was built against has changed.
    """
    home = Path(home)
    root = _repo_root()
    return {
        "home": str(home),
        "python": sys.executable,
        "pid": os.getpid(),
        "code": build_identity.source_tree_fingerprint(root) if root is not None else None,
        "source_mtime_ns": _source_mtime_ns(),
        "config": build_identity.configuration_fingerprint(home),
        "db": _db_stat(home),
        "schema_version": build_identity.db_schema_version(home),
        "loaded_at_ms": now_ms(),
    }


def identity_drift(base: Mapping[str, Any] | None, home: Path | str) -> str | None:
    """Reason the helper's loaded state is stale, or None when it is current."""
    if base is None:
        return None
    home = Path(home)
    if str(home) != str(base.get("home")):
        return "home_changed"
    if _db_stat(home) != base.get("db"):
        return "db_changed"
    if build_identity.configuration_fingerprint(home) != base.get("config"):
        return "config_changed"
    if _source_mtime_ns() != base.get("source_mtime_ns"):
        return "code_changed"
    return None


def _resolve_project_id(home: Path, cwd: str | None, project_id: str | None) -> dict[str, str]:
    """`autoinject.resolve_project`, kept behind one seam for tests."""
    from . import autoinject

    return autoinject.resolve_project(home, cwd, project_id)


def _capsule_phase(
    home: Path,
    session_id: str,
    *,
    objective: str,
    next_action: str | None,
) -> dict[str, Any]:
    return capsule_runtime.ensure_capsule(
        home,
        session_id,
        objective=objective,
        next_action=next_action,
    )


def _render_phase(home: Path, session_id: str, *, budget_tokens: int) -> dict[str, Any]:
    store = vmem.VMemStore(home, session_id)
    return store.render_hot_context(max_tokens=budget_tokens)


def _autoinject_phase(
    home: Path,
    *,
    session_id: str,
    task: str,
    cwd: str | None,
    project_id: str | None,
    agent_id: str,
    branch: str,
    role_profile: str,
) -> dict[str, Any]:
    from . import autoinject

    resolved = _resolve_project_id(home, cwd, project_id)
    session = contracts.BrainSessionIdentity(
        internal_session_id=ledger.internal_session_id(session_id),
        host="prime-cli",
        host_session_id=session_id,
        project_id=resolved["project_id"],
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )
    lifecycle = autoinject.BrainLifecycle(home, session)
    decision = lifecycle.prepare_injection(
        task,
        project_id=project_id,
        agent_id=agent_id,
        role_profile=role_profile,
        session_id=session_id,
        branch_id=branch,
        cwd=cwd,
    )
    packet = autoinject.render_packet(decision)
    delivery_id = lifecycle.last_delivery_ids[0] if lifecycle.last_delivery_ids else None
    return autoinject.shadow_output(decision, packet, delivery_id, resolved)


def prepare_turn(
    home: Path | str,
    *,
    session_id: str,
    task: str,
    cwd: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    branch: str = "main",
    role_profile: str = "worker",
    objective: str | None = None,
    next_action: str | None = None,
    budget_tokens: int = 256,
    want: Sequence[str] = PHASES,
) -> dict[str, Any]:
    """Capsule ensure -> hot-context render -> AutoInject decision, in order.

    Returns one JSON-serializable object. `capsule`/`active_state`/
    `autoinject` carry exactly what the separate CLI commands return (the
    AutoInject section is `autoinject.shadow_output`, the same shape
    `autoinject shadow --json` prints). A failing phase records
    `<phase>_error` and leaves the other phases untouched; this function
    never raises.
    """
    home_path = Path(home)
    session = str(session_id)
    task_text = (task or "")[:MAX_TASK_CHARS]
    agent = agent_id if agent_id is not None else session
    selected = PHASES if not want else tuple(want)
    requested = tuple(name for name in PHASES if name in set(selected))
    started = now_ms()
    result: dict[str, Any] = {
        "ok": True,
        "session_id": session,
        "phases": list(requested),
        "capsule": None,
        # Always present (null when the phase was not requested) so a client
        # can distinguish "not asked for" from "ran and failed".
        "capsule_stdout": None,
        "active_state": None,
        "render_stdout": None,
        "autoinject": None,
        "autoinject_stdout": None,
        # Per-phase success so a client can CONSUME the phases that succeeded
        # and retry only the failed ones: a later phase can succeed and commit
        # its delivery (AutoInject) while an earlier one failed, and discarding
        # that result would re-run the decision and lose the packet
        # (ALREADY_DELIVERED).
        "phases_ok": {name: None for name in PHASES},
        "timings_ms": {},
    }
    trace(
        "turn_before",
        session_id=session,
        home=str(home_path),
        phases=list(requested),
        task_chars=len(task_text),
    )

    if "capsule" in requested:
        with traced_phase("capsule", session_id=session) as box:
            phase_start = now_ms()
            try:
                result["capsule"] = _capsule_phase(
                    home_path,
                    session,
                    objective=(task_text if objective is None else objective),
                    next_action=task_text if next_action is None else next_action,
                )
                # Byte-identical `capsule ensure --json` stdout, so the adapter's
                # existing parser (not a second one) consumes the batched result.
                result["capsule_stdout"] = json.dumps(result["capsule"], indent=2) + "\n"
            except (BrainError, OSError, ValueError) as exc:
                result["capsule_error"] = f"{type(exc).__name__}: {exc}"
            box["error"] = result.get("capsule_error")
            result["phases_ok"]["capsule"] = result.get("capsule_error") is None
            result["timings_ms"]["capsule"] = round(now_ms() - phase_start, 3)

    if "render" in requested:
        with traced_phase("render", session_id=session) as box:
            phase_start = now_ms()
            try:
                rendered = _render_phase(home_path, session, budget_tokens=budget_tokens)
                result["active_state"] = {
                    "ok": True,
                    "session_id": rendered.get("session_id", session),
                    "rendered_text": rendered.get("rendered_text"),
                    "resident_count": rendered.get("resident_count"),
                    "evicted_count": rendered.get("evicted_count"),
                    "resident_tokens": rendered.get("resident_tokens"),
                }
                # Byte-identical `vmem hot-context --json` stdout.
                result["render_stdout"] = json.dumps(rendered, indent=2) + "\n"
            except (BrainError, OSError, ValueError) as exc:
                result["render_error"] = f"{type(exc).__name__}: {exc}"
                result["active_state"] = {"ok": False, "error": result["render_error"]}
            box["error"] = result.get("render_error")
            result["phases_ok"]["render"] = result.get("render_error") is None
            result["timings_ms"]["render"] = round(now_ms() - phase_start, 3)

    if "autoinject" in requested:
        with traced_phase("autoinject", session_id=session) as box:
            phase_start = now_ms()
            try:
                result["autoinject"] = _autoinject_phase(
                    home_path,
                    session_id=session,
                    task=task_text,
                    cwd=cwd,
                    project_id=project_id,
                    agent_id=agent,
                    branch=branch,
                    role_profile=role_profile,
                )
                # Byte-identical `autoinject shadow --json` stdout (canonical JSON),
                # including the trailing newline print() adds.
                result["autoinject_stdout"] = contracts.canonical_json(result["autoinject"]) + "\n"
            except (BrainError, OSError, ValueError) as exc:
                result["autoinject_error"] = f"{type(exc).__name__}: {exc}"
            box["error"] = result.get("autoinject_error")
            result["phases_ok"]["autoinject"] = result.get("autoinject_error") is None
            result["timings_ms"]["autoinject"] = round(now_ms() - phase_start, 3)

    errors = [key for key in result if key.endswith("_error")]
    result["ok"] = not errors
    result["errors"] = errors
    result["timings_ms"]["total"] = round(now_ms() - started, 3)
    trace(
        "turn_after",
        session_id=session,
        ok=result["ok"],
        errors=errors,
        total_ms=result["timings_ms"]["total"],
    )
    return result


def phase_selection(raw: Any) -> tuple[tuple[str, ...] | None, str | None]:
    """Validate a client-supplied phase list: (phases, error).

    Bounded and explicit: an unknown phase name is refused (never silently
    ignored), so a client can rely on `want=["capsule","render"]` meaning "do
    not run the AutoInject decision".
    """
    if raw is None:
        return None, None
    if not isinstance(raw, (list, tuple)) or not all(isinstance(item, str) for item in raw):
        return None, "invalid_want"
    cleaned = [item.strip().lower() for item in raw if item.strip()]
    unknown = sorted(set(cleaned) - set(PHASES))
    if unknown:
        return None, "invalid_want"
    if not cleaned:
        return None, "invalid_want"
    ordered = tuple(name for name in PHASES if name in set(cleaned))
    return (ordered, None)


def _want_from_request(request: Mapping[str, Any]) -> tuple[tuple[str, ...] | None, str | None]:
    """`want` from a helper request, or (None, None) when absent."""
    return phase_selection(request.get("want"))


def _optional_str(request: Mapping[str, Any], key: str) -> str | None:
    """One request field as a string, or None when absent/not a string."""
    value = request.get(key)
    return value if isinstance(value, str) else None


def _rss_bytes() -> int:
    """Resident set size, best effort (0 when unavailable)."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
            handle = k32.GetCurrentProcess()
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return 0
            return int(counters.WorkingSetSize)
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError, IndexError):
        return 0


class TurnSession:
    """One helper process's serve loop state (bounded, request-scoped only).

    No per-session decision is cached across requests: every request re-reads
    config and DB through :func:`prepare_turn`, so a reused interpreter can
    never answer a turn from another turn's state.
    """

    def __init__(
        self,
        home: Path,
        *,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        max_lifetime_s: float = DEFAULT_MAX_LIFETIME_S,
        max_rss_bytes: int = DEFAULT_MAX_RSS_BYTES,
        max_errors: int = DEFAULT_MAX_ERRORS,
    ) -> None:
        self.home = Path(home)
        self.max_requests = max_requests
        self.max_lifetime_s = max_lifetime_s
        self.max_rss_bytes = max_rss_bytes
        self.max_errors = max_errors
        self.requests = 0
        self.errors = 0
        self.started_monotonic = time.monotonic()
        self.base_identity = identity(self.home)

    # -- bounded lifetime -------------------------------------------------
    def exit_reason(self) -> str | None:
        if self.max_requests > 0 and self.requests >= self.max_requests:
            return "max_requests"
        if (
            self.max_lifetime_s > 0
            and (time.monotonic() - self.started_monotonic) >= self.max_lifetime_s
        ):
            return "max_lifetime"
        if self.max_rss_bytes > 0:
            rss = _rss_bytes()
            if rss and rss >= self.max_rss_bytes:
                return "max_rss"
        return None

    # -- ops --------------------------------------------------------------
    def handle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one request, or refuse it when the memory authority moved.

        The DB baseline is refreshed after every answered request: the helper's
        OWN writes (delivery/ledger rows) must not look like drift, while a
        change made between two requests — another process replacing or
        migrating the database — still forces the adapter to restart this
        interpreter instead of answering from state loaded before it.
        """
        op = str(request.get("op") or "")
        if op == "ping":
            return {
                "ok": True,
                "op": "ping",
                "requests": self.requests,
                "uptime_s": round(time.monotonic() - self.started_monotonic, 3),
                "identity": self.base_identity,
            }
        if op != "prepare_turn":
            return {"ok": False, "op": op, "error": "unsupported_op"}
        home = request.get("home")
        if isinstance(home, str) and home and Path(home) != self.home:
            return {
                "ok": False,
                "op": op,
                "error": "home_mismatch",
                "expected_home": str(self.home),
            }
        drift = identity_drift(self.base_identity, self.home)
        if drift is not None:
            return {"ok": False, "op": op, "error": "identity_changed", "drift": drift}
        task = request.get("task")
        if not isinstance(task, str) or not task.strip():
            return {"ok": False, "op": op, "error": "empty_task"}
        want, want_error = _want_from_request(request)
        if want_error is not None:
            return {"ok": False, "op": op, "error": want_error}
        session_id = request.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return {"ok": False, "op": op, "error": "missing_session_id"}
        result = prepare_turn(
            self.home,
            session_id=session_id,
            task=task,
            want=want if want is not None else PHASES,
            cwd=request.get("cwd") if isinstance(request.get("cwd"), str) else None,
            project_id=request.get("project_id")
            if isinstance(request.get("project_id"), str)
            else None,
            agent_id=request.get("agent_id") if isinstance(request.get("agent_id"), str) else None,
            branch=_optional_str(request, "branch") or "main",
            role_profile=_optional_str(request, "role_profile") or "worker",
            objective=request.get("objective")
            if isinstance(request.get("objective"), str)
            else None,
            next_action=request.get("next_action")
            if isinstance(request.get("next_action"), str)
            else None,
            budget_tokens=(
                int(request["budget_tokens"])
                if isinstance(request.get("budget_tokens"), int)
                else 256
            ),
        )
        self.base_identity["db"] = _db_stat(self.home)
        return {"ok": bool(result.get("ok")), "op": op, "result": result}


def serve(
    home: Path | str,
    *,
    stream_in: TextIO | None = None,
    stream_out: TextIO | None = None,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    max_lifetime_s: float = DEFAULT_MAX_LIFETIME_S,
    max_rss_bytes: int = DEFAULT_MAX_RSS_BYTES,
    max_errors: int = DEFAULT_MAX_ERRORS,
    request_handler: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> int:
    """JSON-lines helper loop: one request per line, one response per line.

    Reads until EOF (the adapter closing the pipe is the cleanup signal),
    `{"op":"shutdown"}` or a bounded-lifetime exit. Responses are flushed
    immediately so the adapter never waits on buffering.
    """
    source = stream_in if stream_in is not None else sys.stdin
    sink = stream_out if stream_out is not None else sys.stdout
    session = TurnSession(
        Path(home),
        max_requests=max_requests,
        max_lifetime_s=max_lifetime_s,
        max_rss_bytes=max_rss_bytes,
        max_errors=max_errors,
    )
    handler = request_handler or session.handle

    def write(payload: dict[str, Any]) -> None:
        sink.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        sink.flush()

    write(
        {
            "ok": True,
            "op": "ready",
            "identity": session.base_identity,
            "limits": {
                "max_requests": session.max_requests,
                "max_lifetime_s": session.max_lifetime_s,
                "max_rss_bytes": session.max_rss_bytes,
            },
        }
    )
    trace("helper_ready", home=str(session.home), rss_bytes=_rss_bytes())
    exit_reason: str | None = None
    shutdown = False
    while True:
        line = source.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            exit_reason = "eof"
            break
        if len(line) > MAX_REQUEST_BYTES:
            session.errors += 1
            write({"ok": False, "op": "unknown", "error": "request_too_large"})
            if session.errors >= session.max_errors:
                exit_reason = "error_budget"
                break
            continue
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            session.errors += 1
            write({"ok": False, "op": "unknown", "error": "malformed_json"})
            if session.errors >= session.max_errors:
                exit_reason = "error_budget"
                break
            continue
        if not isinstance(request, dict):
            session.errors += 1
            write({"ok": False, "op": "unknown", "error": "request_not_object"})
            if session.errors >= session.max_errors:
                exit_reason = "error_budget"
                break
            continue
        request_id = request.get("id")
        if str(request.get("op") or "") == "shutdown":
            write({"ok": True, "op": "shutdown", "id": request_id, "requests": session.requests})
            exit_reason = "shutdown"
            shutdown = True
            break
        session.requests += 1
        try:
            response = handler(request)
        except Exception as exc:  # one bad request never kills the helper
            session.errors += 1
            response = {
                "ok": False,
                "op": str(request.get("op") or ""),
                "error": "handler_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        response["id"] = request_id
        write(response)
        exit_reason = session.exit_reason()
        if exit_reason is not None:
            break
    trace(
        "helper_exit",
        home=str(session.home),
        requests=session.requests,
        errors=session.errors,
        reason=exit_reason,
    )
    if not shutdown and exit_reason is not None:
        with contextlib.suppress(Exception):
            write({"ok": True, "op": "exit", "reason": exit_reason, "requests": session.requests})
    return 0
