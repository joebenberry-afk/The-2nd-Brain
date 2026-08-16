"""P3-D Lean Code runtime adapter — harness-neutral Python mirror (plan §7-§8).

Mirrors the proven Prime `lean-code.ts` decision semantics so that any
harness (Prime extension, Antigravity adapter, campaign runner) resolves the
SAME Lean behavior from the SAME canonical single source:

  skills/<lifecycle>/lean-code/SKILL.md  ->  "# Runtime Kernel" section

Lifecycle behavior:
  candidate -> no runtime influence by default (measurement only);
  shadow    -> measurement/eval only; no live policy effect by default;
  active    -> inject the compact Runtime Kernel into code-capable roles;
  retired   -> no injection;
  missing/corrupt skill file -> FAIL OPEN (no invented text).

Smallest reversible eval gate (plan §8.2, P3-E fix):
  env `SECOND_BRAIN_LEAN` (advisory/off) OVERRIDES;
  else `config/skills.toml` `[lean] eval = "advisory" | "off"` (absent => inert).
  Precedence: env advisory/off > file advisory/off > inert.

The kernel text is NEVER duplicated as a Python constant: it is parsed from
the canonical skill file at runtime. In-process cache keyed by resolved path
+ mtime/size (plan §8.6: no reread per event).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import paths

LEAN_KERNEL_MARKER = "second-brain-lean-code-kernel"
LEAN_ENV = "SECOND_BRAIN_LEAN"
LEAN_KERNEL_HEADING = "# Runtime Kernel"
LEAN_SKILL_NAME = "lean-code"
LEAN_OFF_VALUES = {"off", "0", "false", "no"}
LEAN_ADVISORY_VALUES = {"advisory"}
# Role gate mirrors Prime: only code-capable roles (driver/worker) receive
# the kernel; hard_orchestrator and other roles never do.
LEAN_ELIGIBLE_ROLES = {"driver", "worker"}
LEAN_REFUSED_ROLES = {"hard_orchestrator"}

# Lifecycle precedence (active wins over shadow/candidate; retired disables).
LEAN_LEVELS = ("active", "shadow", "candidate", "retired")


@dataclass(frozen=True)
class LeanRuntimeOutcome:
    decision: str  # "inject" | "omit"
    reason: str  # active | advisory | off | role | skill-missing
    mode: str | None
    eval_source: str | None  # "env" | "file" | None
    skill_status: str | None
    kernel_chars: int
    dedup_hit: bool
    error: str | None
    kernel: str | None


class _KernelCache:
    """Process-scoped cache keyed by resolved path + (mtime_ns, size)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, int, str | None, str | None]] = {}

    def get(self, path: str) -> tuple[int, int, str | None, str | None] | None:
        return self._entries.get(path)

    def set(self, path: str, entry: tuple[int, int, str | None, str | None]) -> None:
        self._entries[path] = entry

    def clear(self) -> None:
        self._entries.clear()


_CACHE = _KernelCache()


def reset_lean_kernel_cache() -> None:
    """Test seam: clear the process-scoped kernel cache."""
    _CACHE.clear()


def extract_runtime_kernel(skill_text: str) -> str | None:
    """Extract the '# Runtime Kernel' section from skill text.

    The section is the block after the exact heading until the next markdown
    heading (or EOF), trimmed. None when the heading or a non-empty body is
    absent (corrupt/unrecognized file -> fail open).
    """
    lines = skill_text.split("\r\n") if "\r\n" in skill_text else skill_text.splitlines()
    in_kernel = False
    body: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not in_kernel:
            if line == LEAN_KERNEL_HEADING:
                in_kernel = True
            continue
        if re.match(r"^#\s", line):
            break
        body.append(raw)
    if not in_kernel:
        return None
    kernel = "\n".join(body).strip()
    return kernel if kernel else None


def _level_dirs(home: Path) -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for level, rel in paths.SKILL_LEVEL_DIRS.items():
        dirs[level] = Path(home) / rel
    dirs["retired"] = Path(home) / "skills" / "retired"
    return dirs


def resolve_lean_skill_file(home: Path) -> tuple[str | None, str | None]:
    """Resolve the canonical skill file path + lifecycle status, or (None, None)."""
    dirs = _level_dirs(home)
    for level in LEAN_LEVELS:
        candidate = dirs[level] / LEAN_SKILL_NAME / "SKILL.md"
        if candidate.is_file():
            return str(candidate), level
    return None, None


def load_lean_kernel(home: Path) -> dict:
    """Load + parse the canonical kernel with the in-process cache.

    Never throws: every failure becomes a fail-open result (kernel None +
    bounded error).
    """
    path, status = resolve_lean_skill_file(home)
    if path is None:
        return {
            "path": "",
            "status": "missing",
            "kernel": None,
            "error": "lean-code skill file not found under skills/active|shadow|candidates|retired",
        }
    try:
        stat = os.stat(path)
    except OSError as exc:
        return {
            "path": path,
            "status": status,
            "kernel": None,
            "error": f"cannot stat lean-code skill file: {exc}",
        }
    cached = _CACHE.get(path)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return {"path": path, "status": status, "kernel": cached[2], "error": cached[3]}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        entry = (stat.st_mtime_ns, stat.st_size, None, f"cannot read lean-code skill file: {exc}")
        _CACHE.set(path, entry)
        return {"path": path, "status": status, "kernel": None, "error": entry[3]}
    kernel = extract_runtime_kernel(text)
    error = (
        None
        if kernel is not None
        else f"lean-code skill file has no parsable '# Runtime Kernel' section ({path})"
    )
    _CACHE.set(path, (stat.st_mtime_ns, stat.st_size, kernel, error))
    return {"path": path, "status": status, "kernel": kernel, "error": error}


def lean_eval_from_skills_toml(text: str) -> str | None:
    """Parse `[lean] eval` from config/skills.toml text (tiny deterministic parser).

    Returns "advisory" | "off" when the `[lean]` section carries a recognized
    `eval` value, None when absent/invalid (absent => inert).
    """
    in_lean = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_lean = line.startswith("[lean]")
            continue
        if not in_lean or line == "" or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() != "eval":
            continue
        value = rest.split("#")[0].strip().strip('"').lower()
        if value in LEAN_ADVISORY_VALUES:
            return "advisory"
        if value in LEAN_OFF_VALUES:
            return "off"
        return None
    return None


def resolve_lean_eval(home: Path | None, env: dict[str, str] | None = None) -> dict:
    """Resolve the eval gate: env SECOND_BRAIN_LEAN overrides; else [lean] eval."""
    raw_env = (
        (env if env is not None else os.environ).get(LEAN_ENV, "") or ""
    ).strip().lower() or None
    if raw_env is not None and raw_env in LEAN_ADVISORY_VALUES:
        return {"mode": "advisory", "source": "env", "error": None}
    if raw_env is not None and raw_env in LEAN_OFF_VALUES:
        return {"mode": "off", "source": "env", "error": None}
    if home is None:
        return {"mode": None, "source": None, "error": None}
    file = Path(home) / "config" / "skills.toml"
    if not file.is_file():
        return {"mode": None, "source": None, "error": None}
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        return {"mode": None, "source": None, "error": f"cannot read config/skills.toml: {exc}"}
    mode = lean_eval_from_skills_toml(text)
    if mode is None:
        return {"mode": None, "source": None, "error": None}
    return {"mode": mode, "source": "file", "error": None}


def decide_lean_runtime(
    home: Path | None, role: str, base: str | None, env: dict[str, str] | None = None
) -> LeanRuntimeOutcome:
    """Decide Lean runtime behavior for one event (pure + fail-open; never throws)."""
    role_l = (role or "").strip().lower()
    if role_l in LEAN_REFUSED_ROLES or role_l not in LEAN_ELIGIBLE_ROLES:
        return LeanRuntimeOutcome(
            decision="omit",
            reason="role",
            mode=None,
            eval_source=None,
            skill_status=None,
            kernel_chars=0,
            dedup_hit=False,
            error=None,
            kernel=None,
        )

    gate = resolve_lean_eval(home, env=env)
    if gate["error"] is not None:
        return LeanRuntimeOutcome(
            decision="omit",
            reason="off",
            mode=None,
            eval_source=None,
            skill_status=None,
            kernel_chars=0,
            dedup_hit=False,
            error=gate["error"],
            kernel=None,
        )
    mode: str | None = gate["mode"]
    source: str | None = gate["source"]

    if mode == "off":
        return LeanRuntimeOutcome(
            decision="omit",
            reason="off",
            mode=mode,
            eval_source=source,
            skill_status=None,
            kernel_chars=0,
            dedup_hit=False,
            error=None,
            kernel=None,
        )
    if home is None:
        return LeanRuntimeOutcome(
            decision="omit",
            reason="skill-missing",
            mode=mode,
            eval_source=source,
            skill_status=None,
            kernel_chars=0,
            dedup_hit=False,
            error="brain home unavailable",
            kernel=None,
        )
    loaded = load_lean_kernel(home)
    if loaded["error"] is not None or loaded["kernel"] is None:
        return LeanRuntimeOutcome(
            decision="omit",
            reason="skill-missing",
            mode=mode,
            eval_source=source,
            skill_status=loaded["status"],
            kernel_chars=0,
            dedup_hit=False,
            error=loaded["error"],
            kernel=None,
        )
    if loaded["status"] == "retired":
        return LeanRuntimeOutcome(
            decision="omit",
            reason="off",
            mode=mode,
            eval_source=source,
            skill_status=loaded["status"],
            kernel_chars=len(loaded["kernel"]),
            dedup_hit=False,
            error=None,
            kernel=None,
        )
    lifecycle_active = loaded["status"] == "active"
    advisory = mode == "advisory"
    if not lifecycle_active and not advisory:
        return LeanRuntimeOutcome(
            decision="omit",
            reason="off",
            mode=mode,
            eval_source=source,
            skill_status=loaded["status"],
            kernel_chars=len(loaded["kernel"]),
            dedup_hit=False,
            error=None,
            kernel=None,
        )
    reason = "active" if lifecycle_active else "advisory"
    if base is None or base.strip() == "":
        return LeanRuntimeOutcome(
            decision="omit",
            reason=reason,
            mode=mode,
            eval_source=source,
            skill_status=loaded["status"],
            kernel_chars=len(loaded["kernel"]),
            dedup_hit=False,
            error=None,
            kernel=None,
        )
    dedup_hit = LEAN_KERNEL_MARKER in base
    return LeanRuntimeOutcome(
        decision="omit" if dedup_hit else "inject",
        reason=reason,
        mode=mode,
        eval_source=source,
        skill_status=loaded["status"],
        kernel_chars=len(loaded["kernel"]),
        dedup_hit=dedup_hit,
        error=None,
        kernel=None if dedup_hit else loaded["kernel"],
    )


def compose_lean_kernel_block(kernel: str) -> str:
    """Wrap the canonical kernel in the stable dedup marker block."""
    return f"[{LEAN_KERNEL_MARKER}]\n{kernel}"
