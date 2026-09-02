"""
Dynamic Tool Working Set & Lazy Loading.

Plan §10: Phase 7 — Dynamic Tool Working Set & Lazy Loading.
Manages tool definitions dynamically so models are not overloaded with 2,000-5,000+
tokens of unused tool schemas on every turn.

Key Capabilities (§10.1 - §10.4):
- Tool Tiers: Tier A (CORE_RESIDENT, ≤500 tokens), Tier B (LAZY_DOMAIN), Tier C (ON_DEMAND).
- Schema compression: Prunes verbose docstrings and redundant metadata (saving 40-60% tokens).
- Dynamic intent activation: Activates domain tools when subtask keywords match.
- Idle pruning: Deactivates domain tools after N turns of non-use.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .contracts import estimate_tokens
from .errors import BrainError


class ToolTier(StrEnum):
    CORE_RESIDENT = "CORE_RESIDENT"  # Tier A: Always in context
    LAZY_DOMAIN = "LAZY_DOMAIN"      # Tier B: Activated on domain demand
    ON_DEMAND = "ON_DEMAND"          # Tier C: Explicit activation only


# Default built-in tool catalog
DEFAULT_CORE_TOOLS = [
    {
        "name": "view_file",
        "description": "View file content at path with line slice.",
        "tier": ToolTier.CORE_RESIDENT,
        "domain": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "AbsolutePath": {"type": "string", "description": "Absolute file path"},
                "StartLine": {"type": "integer", "description": "Start line (1-indexed)"},
                "EndLine": {"type": "integer", "description": "End line (1-indexed)"},
            },
            "required": ["AbsolutePath"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute shell command in working directory.",
        "tier": ToolTier.CORE_RESIDENT,
        "domain": "terminal",
        "parameters": {
            "type": "object",
            "properties": {
                "CommandLine": {"type": "string", "description": "Command string to run"},
                "Cwd": {"type": "string", "description": "Working directory path"},
            },
            "required": ["CommandLine", "Cwd"],
        },
    },
    {
        "name": "replace_file_content",
        "description": "Edit existing file by replacing contiguous target content.",
        "tier": ToolTier.CORE_RESIDENT,
        "domain": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "TargetFile": {"type": "string", "description": "Target absolute path"},
                "TargetContent": {"type": "string", "description": "Exact text to replace"},
                "ReplacementContent": {"type": "string", "description": "Replacement text"},
                "StartLine": {"type": "integer", "description": "Start line"},
                "EndLine": {"type": "integer", "description": "End line"},
            },
            "required": [
                "TargetFile",
                "TargetContent",
                "ReplacementContent",
                "StartLine",
                "EndLine",
            ],
        },
    },
    {
        "name": "write_to_file",
        "description": "Create new file or overwrite with code content.",
        "tier": ToolTier.CORE_RESIDENT,
        "domain": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "TargetFile": {"type": "string", "description": "Target absolute path"},
                "CodeContent": {"type": "string", "description": "File text content"},
                "Overwrite": {"type": "boolean", "description": "Overwrite flag"},
            },
            "required": ["TargetFile", "CodeContent", "Overwrite"],
        },
    },
]

DEFAULT_DOMAIN_TOOLS = [
    {
        "name": "git_commit_and_sync",
        "description": "Stage changed files and commit with standard convention message.",
        "tier": ToolTier.LAZY_DOMAIN,
        "domain": "git",
        "keywords": ["git", "commit", "push", "branch", "diff", "merge", "pull"],
        "parameters": {
            "type": "object",
            "properties": {
                "Message": {"type": "string", "description": "Commit message"},
                "Files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["Message"],
        },
    },
    {
        "name": "database_migrate_query",
        "description": "Run SQLite or PostgreSQL schema migration and maintenance queries.",
        "tier": ToolTier.LAZY_DOMAIN,
        "domain": "database",
        "keywords": [
            "db", "database", "sqlite", "postgres", "sql", "migration", "schema", "query"
        ],
        "parameters": {
            "type": "object",
            "properties": {
                "Query": {"type": "string", "description": "SQL query text"},
                "DbPath": {"type": "string", "description": "Database file or URI"},
            },
            "required": ["Query"],
        },
    },
    {
        "name": "memory_curate_insight",
        "description": "Curate and record durable architectural memories in the Second Brain.",
        "tier": ToolTier.LAZY_DOMAIN,
        "domain": "memory",
        "keywords": ["memory", "curate", "insight", "learn", "second_brain", "engram", "recall"],
        "parameters": {
            "type": "object",
            "properties": {
                "Title": {"type": "string", "description": "Insight title"},
                "Body": {"type": "string", "description": "Markdown body"},
                "Grade": {"type": "string", "description": "OBSERVED, TESTED, or VERIFIED"},
            },
            "required": ["Title", "Body"],
        },
    },
]


def compress_tool_schema(tool_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Compress tool schema by trimming verbose redundant descriptions and whitespace (§10.2).
    """
    out: dict[str, Any] = {
        "name": tool_dict["name"],
        "description": tool_dict["description"][:80],
    }

    params = tool_dict.get("parameters", {})
    if params:
        compressed_params: dict[str, Any] = {
            "type": params.get("type", "object"),
        }
        if "required" in params:
            compressed_params["required"] = params["required"]

        props = params.get("properties", {})
        if props:
            compressed_props: dict[str, Any] = {}
            for p_name, p_val in props.items():
                p_entry: dict[str, Any] = {"type": p_val.get("type", "string")}
                if "items" in p_val:
                    p_entry["items"] = p_val["items"]
                compressed_props[p_name] = p_entry
            compressed_params["properties"] = compressed_props
        out["parameters"] = compressed_params

    return out


@dataclass
class ToolDefinition:
    """Tool definition managed by the working set."""
    name: str
    description: str
    parameters: dict[str, Any]
    tier: ToolTier = ToolTier.LAZY_DOMAIN
    domain: str = "general"
    keywords: list[str] = field(default_factory=list)
    active: bool = False
    last_used_turn: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tier": self.tier.value,
            "domain": self.domain,
            "keywords": self.keywords,
            "active": self.active,
            "last_used_turn": self.last_used_turn,
            "parameters": self.parameters,
        }


class ToolWorkingSetManager:
    """Dynamic tool working set manager and lazy activation engine."""

    def __init__(self, load_defaults: bool = True, home: Path | str | None = None) -> None:
        self.home = Path(home) if home is not None else None
        self._tools: dict[str, ToolDefinition] = {}
        if load_defaults:
            self._load_builtins()

    def _load_builtins(self) -> None:
        for t in DEFAULT_CORE_TOOLS:
            self.register_tool(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
                tier=t["tier"],
                domain=t["domain"],
                active=True,  # Core tools are active by default
            )
        for t in DEFAULT_DOMAIN_TOOLS:
            self.register_tool(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
                tier=t["tier"],
                domain=t["domain"],
                keywords=t.get("keywords", []),
                active=False,  # Domain tools are inactive by default
            )

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        tier: ToolTier = ToolTier.LAZY_DOMAIN,
        domain: str = "general",
        keywords: list[str] | None = None,
        active: bool = False,
    ) -> ToolDefinition:
        t = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            tier=tier,
            domain=domain,
            keywords=keywords or [],
            active=active or (tier == ToolTier.CORE_RESIDENT),
            last_used_turn=0,
        )
        self._tools[name] = t
        return t

    def activate_tool(self, name: str, turn: int = 0) -> None:
        """Activate a tool into the working set."""
        if name not in self._tools:
            raise BrainError(f"Unknown tool: {name}")
        self._tools[name].active = True
        self._tools[name].last_used_turn = turn

    def deactivate_tool(self, name: str) -> None:
        """Deactivate a tool (cannot deactivate CORE_RESIDENT)."""
        if name not in self._tools:
            raise BrainError(f"Unknown tool: {name}")
        if self._tools[name].tier == ToolTier.CORE_RESIDENT:
            return  # Core tools are immune from deactivation
        self._tools[name].active = False

    def mark_tool_used(self, name: str, turn: int) -> None:
        """Record usage on a turn."""
        if name in self._tools:
            self._tools[name].active = True
            self._tools[name].last_used_turn = turn

    def detect_and_activate(self, task_text: str, turn: int = 0) -> list[str]:
        """
        Scan task text for domain keywords and activate matching lazy tools (§10.3).
        """
        tokens = set(re.findall(r"[a-z0-9_-]+", task_text.lower()))
        activated: list[str] = []
        for name, tool in self._tools.items():
            if tool.active:
                continue
            if any(k.lower() in tokens for k in tool.keywords):
                tool.active = True
                tool.last_used_turn = turn
                activated.append(name)
        return activated

    def prune_idle_tools(self, current_turn: int, max_idle_turns: int = 3) -> list[str]:
        """
        Deactivate domain tools that have not been used in `max_idle_turns` (§10.3).
        """
        deactivated: list[str] = []
        for name, tool in self._tools.items():
            if not tool.active or tool.tier == ToolTier.CORE_RESIDENT:
                continue
            if current_turn - tool.last_used_turn >= max_idle_turns:
                tool.active = False
                deactivated.append(name)
        return deactivated

    def get_active_tools(self, compress: bool = True) -> list[dict[str, Any]]:
        """
        Get active tool schemas for context injection.
        """
        out: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if tool.active:
                raw_dict = {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                if compress:
                    out.append(compress_tool_schema(raw_dict))
                else:
                    out.append(raw_dict)
        return out

    def estimate_active_tokens(self) -> int:
        """Estimate token footprint of active tool schemas."""
        active_schemas = self.get_active_tools(compress=True)
        raw_json = json.dumps(active_schemas)
        return estimate_tokens(raw_json, home=self.home)

    def list_all(self) -> list[dict[str, Any]]:
        """List all tools with status."""
        return [t.to_dict() for t in self._tools.values()]
