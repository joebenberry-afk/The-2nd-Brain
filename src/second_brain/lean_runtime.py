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

import contextlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

LEAN_KERNEL_MARKER = "second-brain-lean-code-kernel"
LEAN_ENV = "SECOND_BRAIN_LEAN"
LEAN_KERNEL_HEADING = "# Runtime Kernel"
LEAN_NUDGE_HEADING = "# Nudge"
LEAN_NUDGE_TEXT = (
    "LEAN NUDGE: make the minimum sufficient change to meet acceptance; "
    "reuse existing code, avoid new abstractions or dependencies, and stop at acceptance."
)
LEAN_OPPORTUNITY_ENV = "SECOND_BRAIN_LEAN_OPPORTUNITY"
LEAN_OPPORTUNITY_REASONS = (
    "REPEAT_READ",
    "SCOPE_EXPANSION",
    "NEW_DEPENDENCY",
    "NEW_ABSTRACTION",
    "POST_ACCEPTANCE_WORK",
    "UNRELATED_DIFF",
    "TEST_WEAKENING_RISK",
)
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
    reason: str  # active | advisory | off | role | skill-missing | rule reason
    mode: str | None
    eval_source: str | None  # "env" | "file" | None
    skill_status: str | None
    kernel_chars: int
    dedup_hit: bool
    error: str | None
    kernel: str | None
    level: str = "NOOP"  # "NOOP" | "NUDGE" | "FULL"
    placement: str = "tail"
    reasons: tuple[str, ...] = ()
    nudge: str | None = None


class _KernelCache:
    """Process-scoped cache keyed by resolved path + (mtime_ns, size)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, int, str | None, str | None, str | None]] = {}

    def get(self, path: str) -> tuple[int, int, str | None, str | None, str | None] | None:
        return self._entries.get(path)

    def set(self, path: str, entry: tuple[int, int, str | None, str | None, str | None]) -> None:
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


def extract_runtime_nudge(skill_text: str) -> str | None:
    """Extract the '# Nudge' section from skill text."""
    lines = skill_text.split("\r\n") if "\r\n" in skill_text else skill_text.splitlines()
    in_nudge = False
    body: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not in_nudge:
            if line == LEAN_NUDGE_HEADING:
                in_nudge = True
            continue
        if re.match(r"^#\s", line):
            break
        body.append(raw)
    if not in_nudge:
        return None
    nudge = "\n".join(body).strip()
    return nudge if nudge else None


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
            "nudge": None,
            "error": "lean-code skill file not found under skills/active|shadow|candidates|retired",
        }
    try:
        stat = os.stat(path)
    except OSError as exc:
        return {
            "path": path,
            "status": status,
            "kernel": None,
            "nudge": None,
            "error": f"cannot stat lean-code skill file: {exc}",
        }
    cached = _CACHE.get(path)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return {
            "path": path,
            "status": status,
            "kernel": cached[2],
            "nudge": cached[3],
            "error": cached[4],
        }
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        entry = (
            stat.st_mtime_ns,
            stat.st_size,
            None,
            None,
            f"cannot read lean-code skill file: {exc}",
        )
        _CACHE.set(path, entry)
        return {"path": path, "status": status, "kernel": None, "nudge": None, "error": entry[4]}
    kernel = extract_runtime_kernel(text)
    nudge = extract_runtime_nudge(text) or LEAN_NUDGE_TEXT
    error = (
        None
        if kernel is not None
        else f"lean-code skill file has no parsable '# Runtime Kernel' section ({path})"
    )
    _CACHE.set(path, (stat.st_mtime_ns, stat.st_size, kernel, nudge, error))
    return {"path": path, "status": status, "kernel": kernel, "nudge": nudge, "error": error}


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


def lean_opportunity_from_skills_toml(text: str) -> bool:
    """Parse `[lean] opportunity` from config/skills.toml text."""
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
        if key.strip() != "opportunity":
            continue
        value = rest.split("#")[0].strip().strip('"').lower()
        return value in ("true", "1", "yes", "on", "active")
    return False


def parse_git_diff(diff_text: str) -> dict[str, Any]:
    """Parse unified git diff for modified files, new files, and line changes."""
    modified_files: list[str] = []
    new_files: dict[str, int] = {}
    removed_assert_or_test_lines = False

    current_file: str | None = None
    is_new_file = False
    new_file_lines = 0
    is_test_file = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current_file and is_new_file:
                new_files[current_file] = new_file_lines
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                current_file = b_path[2:] if b_path.startswith("b/") else b_path
            else:
                current_file = None
            is_new_file = False
            new_file_lines = 0
            is_test_file = bool(
                current_file
                and (
                    "test" in current_file.lower()
                    or current_file.endswith(("_test.py", ".test.ts", ".test.js"))
                )
            )
            if current_file and current_file not in modified_files:
                modified_files.append(current_file)
            continue

        if line.startswith("new file mode") or line.startswith("--- /dev/null"):
            is_new_file = True
            continue

        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        if line.startswith("+") and is_new_file:
            new_file_lines += 1

        if line.startswith("-"):
            removed_content = line[1:].strip()
            if "assert" in removed_content or (
                is_test_file
                and any(
                    removed_content.startswith(kw) or kw in removed_content
                    for kw in ("def test_", "test(", "it(", "expect(", "self.assert")
                )
            ):
                removed_assert_or_test_lines = True

    if current_file and is_new_file:
        new_files[current_file] = new_file_lines

    return {
        "modified_files": modified_files,
        "new_files": new_files,
        "removed_assert_or_test_lines": removed_assert_or_test_lines,
    }


def _path_matches_ref(path: str, ref: str) -> bool:
    p_norm = path.replace("\\", "/").strip().lower()
    r_norm = ref.replace("\\", "/").strip().lower()
    if not p_norm or not r_norm:
        return False
    if p_norm == r_norm:
        return True
    if p_norm.startswith(r_norm.rstrip("/") + "/"):
        return True
    if r_norm.startswith(p_norm.rstrip("/") + "/"):
        return True
    return Path(p_norm).name == Path(r_norm).name


def extract_requirement_refs(
    requirements: Sequence[dict[str, Any]],
    explicit_refs: Sequence[str] | None = None,
) -> set[str]:
    refs: set[str] = set(explicit_refs or [])
    for req in requirements:
        for r in req.get("refs") or []:
            if isinstance(r, str) and r.strip():
                refs.add(r.strip())
        for ev in req.get("evidence") or []:
            if isinstance(ev, str) and ev.strip():
                clean_ev = ev.split("@")[0].split(":")[0].strip()
                if clean_ev and ("/" in clean_ev or "\\" in clean_ev or "." in clean_ev):
                    refs.add(clean_ev)
        text = str(req.get("requirement") or "")
        for word in text.split():
            clean_word = word.strip("`'\",:;()")
            if (
                "/" in clean_word
                or clean_word.endswith((".py", ".ts", ".js", ".json", ".toml", ".md"))
            ) and len(clean_word) > 2:
                refs.add(clean_word)
    return refs


def evaluate_lean_rules(
    *,
    read_ledger: Sequence[dict[str, Any]] | None = None,
    diff: str | None = None,
    capsule: dict[str, Any] | None = None,
    requirements: Sequence[dict[str, Any]] | None = None,
    modified_files: Sequence[str] | None = None,
    requirement_refs: Sequence[str] | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    post_acceptance_work: bool = False,
    reasons: Sequence[str] | None = None,
) -> list[str]:
    """Evaluate literal rule table against evidence.

    Returns list of triggered rule names from LEAN_OPPORTUNITY_REASONS.
    """
    triggered: list[str] = list(reasons or [])

    # 1. REPEAT_READ: same blob read >= 3 times (from read-ledger/T1.5)
    if "REPEAT_READ" not in triggered and read_ledger:
        counts: dict[str, int] = {}
        for entry in read_ledger:
            blob = entry.get("blob_sha") or entry.get("hash") or entry.get("path")
            if blob:
                counts[str(blob)] = counts.get(str(blob), 0) + 1
        if any(cnt >= 3 for cnt in counts.values()):
            triggered.append("REPEAT_READ")

    parsed_diff = (
        parse_git_diff(diff)
        if diff
        else {
            "modified_files": list(modified_files or []),
            "new_files": {},
            "removed_assert_or_test_lines": False,
        }
    )
    all_modified = list(parsed_diff["modified_files"])
    if modified_files:
        for mf in modified_files:
            if mf not in all_modified:
                all_modified.append(mf)

    # 2. TEST_WEAKENING_RISK: assert or test lines removed in git diff
    if "TEST_WEAKENING_RISK" not in triggered and parsed_diff.get("removed_assert_or_test_lines"):
        triggered.append("TEST_WEAKENING_RISK")

    # 3. NEW_DEPENDENCY: lockfile / pyproject.toml / package.json diff detected
    if "NEW_DEPENDENCY" not in triggered:
        dep_names = {
            "pyproject.toml",
            "package.json",
            "requirements.txt",
            "requirements-dev.txt",
            "pipfile",
            "setup.py",
            "setup.cfg",
            "go.mod",
            "go.sum",
            "cargo.toml",
        }
        for f in all_modified:
            fname = Path(f).name.lower()
            if (
                fname in dep_names
                or fname.endswith((".lock", ".lockb", "-lock.json", ".lock.yaml"))
                or "lock" in fname
            ):
                triggered.append("NEW_DEPENDENCY")
                break

    req_list = list(requirements or [])
    all_req_refs = extract_requirement_refs(req_list, requirement_refs)

    # SCOPE_EXPANSION: at least two files outside capsule or requirement references.
    if "SCOPE_EXPANSION" not in triggered:
        capsule_dict = capsule or {}
        allowed_files = set(capsule_dict.get("files_touched") or []) | all_req_refs
        outside_files = [
            f for f in all_modified if not any(_path_matches_ref(f, a) for a in allowed_files)
        ]
        if len(outside_files) >= 2:
            triggered.append("SCOPE_EXPANSION")

    # 5. NEW_ABSTRACTION: new module or file >= 80 lines not named in requirements
    if "NEW_ABSTRACTION" not in triggered:
        new_files = parsed_diff.get("new_files") or {}
        for nf, lines in new_files.items():
            if lines >= 80 and not any(_path_matches_ref(nf, r) for r in all_req_refs):
                triggered.append("NEW_ABSTRACTION")
                break

    # 6. POST_ACCEPTANCE_WORK: tool calls occurred after all material requirements verified
    if "POST_ACCEPTANCE_WORK" not in triggered:
        if post_acceptance_work:
            triggered.append("POST_ACCEPTANCE_WORK")
        elif req_list and tool_calls:
            material_reqs = [
                r
                for r in req_list
                if r.get("importance") in ("critical", "high", "normal", "material")
            ]
            if (
                material_reqs
                and all(r.get("status") in ("verified", "not_applicable") for r in material_reqs)
                and len(tool_calls) > 0
            ):
                triggered.append("POST_ACCEPTANCE_WORK")

    # 7. UNRELATED_DIFF: diff paths not under any requirement ref
    if (
        "UNRELATED_DIFF" not in triggered
        and all_req_refs
        and all_modified
        and any(not any(_path_matches_ref(f, r) for r in all_req_refs) for f in all_modified)
    ):
        triggered.append("UNRELATED_DIFF")

    return triggered


def compute_lean_severity(reasons: Sequence[str]) -> str:
    """Map reasons to severity level: NOOP, NUDGE, or FULL.

    - 0 reasons -> NOOP
    - Any single reason (except TEST_WEAKENING_RISK) -> NUDGE
    - TEST_WEAKENING_RISK OR >= 2 distinct reasons -> FULL
    """
    distinct = set(reasons)
    if not distinct:
        return "NOOP"
    if "TEST_WEAKENING_RISK" in distinct or len(distinct) >= 2:
        return "FULL"
    return "NUDGE"


@dataclass
class LeanCooldownState:
    current_phase: str = "default"
    nudges_emitted_in_phase: int = 0
    emitted_reasons: set[str] = field(default_factory=set)
    last_severity: str = "NOOP"


_COOLDOWN_STATES: dict[str, LeanCooldownState] = {}


def reset_lean_cooldown() -> None:
    """Test seam: clear all session cooldown states."""
    _COOLDOWN_STATES.clear()


def apply_lean_cooldown(
    reasons: Sequence[str],
    *,
    session_id: str | None = None,
    phase: str | None = None,
) -> tuple[str, list[str]]:
    """Apply cooldown and gating to evaluated reasons.

    Cooldown rules:
    - One NUDGE per task phase.
    - Same reason never repeated after emission.
    - FULL only emitted on a new severity transition.

    Returns:
        (final_level, active_reasons)
    """
    key = session_id or "default"
    state = _COOLDOWN_STATES.setdefault(key, LeanCooldownState())

    task_phase = phase or "default"
    if task_phase != state.current_phase:
        state.current_phase = task_phase
        state.nudges_emitted_in_phase = 0

    candidate_reasons = [r for r in reasons if r not in state.emitted_reasons]
    if not candidate_reasons:
        state.last_severity = "NOOP"
        return "NOOP", []

    target_severity = compute_lean_severity(candidate_reasons)

    if target_severity == "NUDGE":
        if state.nudges_emitted_in_phase >= 1:
            state.last_severity = "NOOP"
            return "NOOP", []
        state.nudges_emitted_in_phase += 1
        for r in candidate_reasons:
            state.emitted_reasons.add(r)
        state.last_severity = "NUDGE"
        return "NUDGE", candidate_reasons

    if target_severity == "FULL":
        if state.last_severity == "FULL":
            return "NOOP", []
        for r in candidate_reasons:
            state.emitted_reasons.add(r)
        state.last_severity = "FULL"
        return "FULL", candidate_reasons

    state.last_severity = "NOOP"
    return "NOOP", []


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
    home: Path | None,
    role: str,
    base: str | None,
    env: dict[str, str] | None = None,
    *,
    session_id: str | None = None,
    phase: str | None = None,
    opportunity: bool | None = None,
    reasons: Sequence[str] | None = None,
    read_ledger: Sequence[dict[str, Any]] | None = None,
    diff: str | None = None,
    capsule: dict[str, Any] | None = None,
    requirements: Sequence[dict[str, Any]] | None = None,
    modified_files: Sequence[str] | None = None,
    requirement_refs: Sequence[str] | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    post_acceptance_work: bool = False,
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
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
            level="NOOP",
            placement="tail",
        )

    is_opportunity = (
        opportunity is True
        or reasons is not None
        or read_ledger is not None
        or diff is not None
        or capsule is not None
        or requirements is not None
        or modified_files is not None
        or requirement_refs is not None
        or tool_calls is not None
        or post_acceptance_work
    )
    if not is_opportunity and opportunity is not False:
        raw_env_opp = (
            ((env if env is not None else os.environ).get(LEAN_OPPORTUNITY_ENV, "") or "")
            .strip()
            .lower()
        )
        if raw_env_opp in ("1", "true", "yes", "on"):
            is_opportunity = True
        elif raw_env_opp in ("0", "false", "no", "off"):
            is_opportunity = False
        elif home is not None:
            cfg_path = Path(home) / "config" / "skills.toml"
            if cfg_path.is_file():
                with contextlib.suppress(OSError):
                    is_opportunity = lean_opportunity_from_skills_toml(
                        cfg_path.read_text(encoding="utf-8")
                    )

    nudge_text = loaded.get("nudge") or LEAN_NUDGE_TEXT

    if is_opportunity:
        raw_reasons = evaluate_lean_rules(
            read_ledger=read_ledger,
            diff=diff,
            capsule=capsule,
            requirements=requirements,
            modified_files=modified_files,
            requirement_refs=requirement_refs,
            tool_calls=tool_calls,
            post_acceptance_work=post_acceptance_work,
            reasons=reasons,
        )
        final_level, active_reasons = apply_lean_cooldown(
            raw_reasons,
            session_id=session_id,
            phase=phase,
        )
        dedup_hit = base is not None and LEAN_KERNEL_MARKER in base

        if final_level == "NOOP" or dedup_hit:
            return LeanRuntimeOutcome(
                decision="omit",
                reason="noop" if not dedup_hit else ("active" if lifecycle_active else "advisory"),
                mode=mode,
                eval_source=source,
                skill_status=loaded["status"],
                kernel_chars=0,
                dedup_hit=dedup_hit,
                error=None,
                kernel=None,
                level="NOOP",
                placement="tail",
                reasons=tuple(active_reasons),
                nudge=nudge_text,
            )

        if final_level == "NUDGE":
            return LeanRuntimeOutcome(
                decision="inject",
                reason=active_reasons[0]
                if active_reasons
                else ("active" if lifecycle_active else "advisory"),
                mode=mode,
                eval_source=source,
                skill_status=loaded["status"],
                kernel_chars=len(nudge_text),
                dedup_hit=False,
                error=None,
                kernel=nudge_text,
                level="NUDGE",
                placement="tail",
                reasons=tuple(active_reasons),
                nudge=nudge_text,
            )

        # final_level == "FULL"
        full_kernel = loaded["kernel"]
        return LeanRuntimeOutcome(
            decision="inject",
            reason=active_reasons[0]
            if active_reasons
            else ("active" if lifecycle_active else "advisory"),
            mode=mode,
            eval_source=source,
            skill_status=loaded["status"],
            kernel_chars=len(full_kernel),
            dedup_hit=False,
            error=None,
            kernel=full_kernel,
            level="FULL",
            placement="tail",
            reasons=tuple(active_reasons),
            nudge=nudge_text,
        )

    # Classic mode (opportunity not enabled)
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
            level="FULL",
            placement="tail",
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
        level="FULL",
        placement="tail",
    )


def evaluate_lean_opportunity(
    home: Path | None = None,
    role: str = "driver",
    base: str | None = None,
    env: dict[str, str] | None = None,
    *,
    session_id: str | None = None,
    phase: str | None = None,
    reasons: Sequence[str] | None = None,
    read_ledger: Sequence[dict[str, Any]] | None = None,
    diff: str | None = None,
    capsule: dict[str, Any] | None = None,
    requirements: Sequence[dict[str, Any]] | None = None,
    modified_files: Sequence[str] | None = None,
    requirement_refs: Sequence[str] | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    post_acceptance_work: bool = False,
) -> LeanRuntimeOutcome:
    """Convenience helper: evaluate Lean opportunity controller directly."""
    return decide_lean_runtime(
        home=home,
        role=role,
        base=base or "base",
        env=env,
        session_id=session_id,
        phase=phase,
        opportunity=True,
        reasons=reasons,
        read_ledger=read_ledger,
        diff=diff,
        capsule=capsule,
        requirements=requirements,
        modified_files=modified_files,
        requirement_refs=requirement_refs,
        tool_calls=tool_calls,
        post_acceptance_work=post_acceptance_work,
    )


def compose_lean_kernel_block(kernel: str) -> str:
    """Wrap the canonical kernel in the stable dedup marker block."""
    return f"[{LEAN_KERNEL_MARKER}]\n{kernel}"
