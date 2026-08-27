"""Modular skill visibility core (plan P3.16) — harness-neutral.

Builds a bounded ``VisibilityPlan`` describing which skills are eligible,
which the router selected (re-capped at the frozen 0-3 invariant), and
which were actually hydrated (full ``SKILL.md`` body read) versus avoided.
This module never decides *how* a harness injects skills — Tasks 2/4 own
adapters that consume ``build_plan``/``hydrate_plan`` output. It only ever
narrows visibility (descriptor before full body, selected-only hydration,
fresh re-validation against content hash) — never widens it.

Report-only / shadow-by-default: ``resolve_visibility_mode`` fails safe to
``"shadow"`` on any missing/invalid config. Callers decide what "enforced"
means; this module only reports mode, it does not gate behavior on it.
"""

from __future__ import annotations

import hashlib
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import autoinject, contracts, paths, router, skillforge

_MAX_SPECIALIST_SKILLS = 3
_DESCRIPTOR_TEXT_MAX_CHARS = 400
_PURPOSE_SECTION_MAX_CHARS = 240


def _purpose_excerpt(text: str) -> str:
    """Bounded ``# Purpose`` section text: up to the next ``# `` heading or EOF."""
    marker = "# Purpose"
    start = text.find(marker)
    if start == -1:
        return ""
    body_start = start + len(marker)
    next_heading = text.find("\n# ", body_start)
    excerpt = text[body_start:] if next_heading == -1 else text[body_start:next_heading]
    return excerpt.strip()[:_PURPOSE_SECTION_MAX_CHARS]


def eligible_skills(home: Path) -> list[dict]:
    """List every skill under active/candidate/shadow (Phase 23 pool).

    Each entry: ``{"skill_id", "lifecycle_state", "content_hash", "path"}``.
    An unreadable ``SKILL.md`` is eligible-but-hash-less (``content_hash``
    is ``None``); it is never dropped and never raises.
    """
    results: list[dict] = []
    for level in ("active", "candidate", "shadow"):
        level_dir = Path(home) / paths.SKILL_LEVEL_DIRS[level]
        if not level_dir.is_dir():
            continue
        for entry in sorted(level_dir.iterdir()):
            skill_path = entry / "SKILL.md"
            if not entry.is_dir() or not skill_path.is_file():
                continue
            try:
                content_hash: str | None = skillforge.lifecycle_content_hash(skill_path)
            except OSError:
                content_hash = None
            results.append(
                {
                    "skill_id": entry.name,
                    "lifecycle_state": level,
                    "content_hash": content_hash,
                    "path": skill_path,
                }
            )
    return results


def descriptors(home: Path) -> dict[str, dict]:
    """Bounded per-skill descriptor for router-time display (not full body).

    Keyed by ``skill_id``; each value: ``{"lifecycle_state", "content_hash",
    "descriptor_text", "descriptor_ref"}``. ``descriptor_text`` is the
    ``# Purpose`` section only, truncated, plus a small metadata prefix —
    capped at ``_DESCRIPTOR_TEXT_MAX_CHARS`` total.
    """
    result: dict[str, dict] = {}
    for item in eligible_skills(home):
        skill_path = item["path"]
        try:
            text = skill_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        try:
            metadata = skillforge.read_metadata(skill_path)
        except Exception:
            metadata = {}
        prefix = f"{metadata.get('name', item['skill_id'])} v{metadata.get('version', '?')}: "
        purpose = _purpose_excerpt(text)
        descriptor_text = (prefix + purpose)[:_DESCRIPTOR_TEXT_MAX_CHARS]
        descriptor_ref = hashlib.sha256(descriptor_text.encode("utf-8")).hexdigest()[:16]
        result[item["skill_id"]] = {
            "lifecycle_state": item["lifecycle_state"],
            "content_hash": item["content_hash"],
            "descriptor_text": descriptor_text,
            "descriptor_ref": descriptor_ref,
        }
    return result


def resolve_visibility_mode(home: Path) -> str:
    """``[visibility] mode`` from ``<home>/config/skills.toml``.

    Same fail-safe ``tomllib``-read shape as ``router._router_max_active``
    (own copy — no private-name coupling). Returns ``"enforced"`` only for
    the exact string ``"enforced"``; every other case (missing file,
    malformed TOML, missing key, any other value) falls back to
    ``"shadow"``.
    """
    try:
        cfg = tomllib.loads((Path(home) / "config" / "skills.toml").read_text(encoding="utf-8"))
        value = (cfg.get("visibility") or {}).get("mode", "shadow")
    except (OSError, tomllib.TOMLDecodeError):
        return "shadow"
    return "enforced" if value == "enforced" else "shadow"


def _body_stats(skill_id: str, eligible: dict[str, dict]) -> tuple[int, int]:
    try:
        text = eligible[skill_id]["path"].read_text(encoding="utf-8")
    except OSError:
        return 0, 0
    return len(text), autoinject.token_estimate(text)


def build_plan(
    home: Path,
    task: str,
    *,
    session_id: str,
    project_id: str,
    max_active: int | None = None,
    mode: str | None = None,
) -> dict:
    """Build the canonical ``VisibilityPlan`` dict for one routing decision.

    Calls ``router.route`` and lets any exception propagate — this module
    never silently substitutes "select everything" on router failure;
    callers (Tasks 2/4) catch and fail open to zero selection.
    """
    router_result = router.route(home, task, max_active=max_active)
    eligible = {item["skill_id"]: item for item in eligible_skills(home)}
    described = descriptors(home)

    deduped_selected = list(dict.fromkeys(router_result["selected"]))
    selected_skill_ids: list[str] = []
    rejected_skill_ids: dict[str, str] = {}
    for skill_id in deduped_selected:
        if skill_id not in eligible:
            rejected_skill_ids[skill_id] = "not_eligible"
        elif len(selected_skill_ids) < _MAX_SPECIALIST_SKILLS:
            selected_skill_ids.append(skill_id)
        else:
            rejected_skill_ids[skill_id] = "over_cap"

    descriptor_refs = {skill_id: described[skill_id]["descriptor_ref"] for skill_id in eligible}
    descriptor_chars = sum(len(described[skill_id]["descriptor_text"]) for skill_id in eligible)
    descriptor_tokens = sum(
        autoinject.token_estimate(described[skill_id]["descriptor_text"]) for skill_id in eligible
    )

    avoided_full_chars = 0
    avoided_full_tokens = 0
    for skill_id in eligible:
        chars, tokens = _body_stats(skill_id, eligible)
        avoided_full_chars += chars
        avoided_full_tokens += tokens

    selected_key = ",".join(selected_skill_ids)
    visibility_plan_id = (
        "vplan-"
        + hashlib.sha256(f"{task}|{session_id}|{project_id}|{selected_key}".encode()).hexdigest()[
            :16
        ]
    )
    task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
    router_decision_hash = hashlib.sha256(
        contracts.canonical_json(
            {"selected": selected_skill_ids, "scores": router_result["scores"]}
        ).encode("utf-8")
    ).hexdigest()

    return {
        "visibility_plan_id": visibility_plan_id,
        "task_hash": task_hash,
        "session_id": session_id,
        "project_id": project_id,
        "router_decision_hash": router_decision_hash,
        "eligible_skill_ids": sorted(eligible),
        "descriptor_refs": descriptor_refs,
        "selected_skill_ids": selected_skill_ids,
        "hydrated_skill_ids": [],
        "rejected_skill_ids": rejected_skill_ids,
        "unavailable_skill_ids": {},
        "mode": mode if mode is not None else resolve_visibility_mode(home),
        "descriptor_chars": descriptor_chars,
        "descriptor_tokens": descriptor_tokens,
        "hydrated_chars": 0,
        "hydrated_tokens": 0,
        "avoided_full_chars": avoided_full_chars,
        "avoided_full_tokens": avoided_full_tokens,
        "created_at": datetime.now(UTC).isoformat(),
        "_selected_content_hashes": {
            skill_id: eligible[skill_id]["content_hash"] for skill_id in selected_skill_ids
        },
    }


def hydrate_plan(home: Path, plan: dict) -> tuple[dict, dict[str, str]]:
    """Revalidate and hydrate the plan's ``selected_skill_ids`` only.

    Re-scans the filesystem fresh (closing the TOCTOU window between
    ``build_plan`` and this call) and compares each selected skill's
    current content hash against the hash captured at plan-build time.
    Never raises; unreadable/stale/vanished skills become
    ``unavailable_skill_ids`` entries instead. Returns a new plan dict
    (the input is never mutated) plus ``{skill_id: full SKILL.md text}``
    for every skill that actually hydrated.
    """
    updated = dict(plan)
    eligible = {item["skill_id"]: item for item in eligible_skills(home)}
    selected_content_hashes: dict[str, str] = plan.get("_selected_content_hashes", {})

    hydrated_skill_ids: list[str] = []
    hydrated_bodies: dict[str, str] = {}
    unavailable_skill_ids: dict[str, str] = dict(plan.get("unavailable_skill_ids", {}))

    for skill_id in plan["selected_skill_ids"]:
        current = eligible.get(skill_id)
        if current is None or current["content_hash"] is None:
            unavailable_skill_ids[skill_id] = "not_eligible"
            continue
        if current["content_hash"] != selected_content_hashes.get(skill_id):
            unavailable_skill_ids[skill_id] = "stale_content_hash"
            continue
        try:
            body = current["path"].read_text(encoding="utf-8")
        except OSError:
            unavailable_skill_ids[skill_id] = "read_failed"
            continue
        hydrated_bodies[skill_id] = body
        hydrated_skill_ids.append(skill_id)

    hydrated_chars = 0
    hydrated_tokens = 0
    avoided_full_chars = plan["avoided_full_chars"]
    avoided_full_tokens = plan["avoided_full_tokens"]
    for body in hydrated_bodies.values():
        chars = len(body)
        tokens = autoinject.token_estimate(body)
        hydrated_chars += chars
        hydrated_tokens += tokens
        avoided_full_chars -= chars
        avoided_full_tokens -= tokens

    updated["hydrated_skill_ids"] = hydrated_skill_ids
    updated["unavailable_skill_ids"] = unavailable_skill_ids
    updated["hydrated_chars"] = hydrated_chars
    updated["hydrated_tokens"] = hydrated_tokens
    updated["avoided_full_chars"] = avoided_full_chars
    updated["avoided_full_tokens"] = avoided_full_tokens
    return updated, hydrated_bodies


def plan_to_evidence(plan: dict) -> dict[str, Any]:
    """Strip private/internal fields (e.g. ``_selected_content_hashes``)
    before anything reaches telemetry/ledger.

    Callers (Tasks 2/4) MUST call this — never pass a raw plan dict — to
    telemetry, the evidence ledger, or any other logging boundary.
    """
    return {k: v for k, v in plan.items() if not k.startswith("_")}
