# P0 — Existing Second Brain Primitives (Claude Code Adapter Audit)

Audit date: 2026-08-17. Scope: map every primitive a Claude Code adapter needs
against what already exists in this repo, so the adapter can reuse instead of
reinvent. Mirrors the shape of `brainstem/adapters/antigravity/` (the
Antigravity adapter) and `brainstem/codex-hooks/` (the Codex adapter) — both
already-shipped harness adapters over the same Brain core.

## Transport pattern (all existing adapters share this — reuse, don't reinvent)

There is **no server, no MCP, no RPC** anywhere in this repo (grepped
`mcp|fastapi|server|rpc|websocket|flask` across `src/second_brain` — no
hits). Every adapter is a thin script → subprocess call into
`python -m second_brain --home <home> autoinject <adapter>-hook` → JSON back
on stdout, **fail-open to `{}`** on any error. Policy (AutoInject mode, Lean
injection, Stop decision) lives entirely in Python; the launcher script is
transport only. See `brainstem/adapters/antigravity/scripts/run-hook.ps1` and
`src/second_brain/cli.py:2011` (`_cmd_antigravity_hook`, docstring at
line ~1994) for the canonical example.

A Claude Code adapter should follow the identical shape: a new
`autoinject claude-code-hook` CLI verb (mirroring `_cmd_antigravity_hook`)
plus a thin PowerShell (or Node, if Claude Code hooks need cross-platform)
launcher, registered in Claude Code's own hooks config format.

## Findings table

| Need | Existing primitive | Reusable as-is? | Gap for Claude adapter |
|---|---|---|---|
| Bootstrap/startup entrypoint | `python -m second_brain --home <home> autoinject antigravity-hook`; handler `cli.py:_cmd_antigravity_hook` | Yes — same CLI verb pattern | Add `claude-code-hook` verb; map Claude Code's hook JSON contract (differs from Antigravity's protobuf-shaped payload) |
| Memory query (read) | `second_brain memory search/show/list` → `semantic.py` (`search_memories`, `list_memories`) | Yes | None |
| Memory write / candidate submission | `second_brain memory add` → `semantic.add_memory`; `STATUSES=(candidate,current,labile,superseded,archived)` (`semantic.py:38`); promotion via `memory curate --status/--grade` | Yes | None — adapter must only ever write `candidate`, never call `curate` to promote |
| Bounded/ranked retrieval | `autoinject.prepare_injection` / `_fit_budget` / `jit.compile_context`; `config/retrieval.toml [scoring].max_results = 3` enforced | Yes | None — reuse `autoinject` path, no new retrieval stack |
| Rule lifecycle / active rules | `constitution/*.md` (static); per-adapter rule file e.g. `brainstem/adapters/antigravity/rules/second-brain-core.md` | Partial | Claude adapter needs its own `rules/second-brain-core.md` (same content, no dynamic rule engine exists) |
| Decision records | `decisions/global/*.md`, `decisions/projects/` — plain markdown, no schema/loader | Partial | Keep markdown convention; no JSON schema to invent |
| Policy engine (allow/warn/deny) | `risk.py::assess_risk()` scores `LOW/MEDIUM/HIGH/CRITICAL`; **no enforcement gate**, scorer only | No | Not needed for Stage 0/1; if a PreToolUse gate is built later, wrap `assess_risk()` output — do not build a second scorer |
| Lean Code | `src/second_brain/lean_runtime.py` (harness-neutral) + canonical `brainstem/prime-extension/src/lean-code.ts`; kernel text in `skills/<lifecycle>/lean-code/SKILL.md`; gated by `LEAN_ELIGIBLE_ROLES={driver,worker}` | Yes | None — already harness-neutral, call `lean_runtime.decide_lean_runtime` |
| Session/turn telemetry | `src/second_brain/telemetry.py` (`iter_records/validate/report`) reading `telemetry/*.jsonl`; schema `brainstem/telemetry/SCHEMA.md` | Yes | Add a `claude_code_hook_shadow_decision` (or similar) record kind to SCHEMA.md |
| PreCompact / session ledger / resume-packet | `ledger.py::LedgerRehydrator.rehydrate(level=1..4)`, CLI `second_brain ledger rehydrate`; `session recover` for crash recovery | Yes | Wire Claude Code's native `PreCompact` hook to call `ledger rehydrate` — no new code needed beyond the hook wiring |
| Evidence validation | `working_set.py::add_evidence` (Requirement Ledger); `verify.py::build_verifier_brief` | Yes | None |
| Project/repo scoping | `registry.py` — `detect_git_remote`, `detect_explicit_id`, `add_project/get_project`, `AGENTS.md` marker block | Yes | None |
| Agent/harness identity | `contracts.py::BrainSessionIdentity.host` (free-text); existing values: `antigravity`, `codex-hooks`, `prime-cli`, `brainctl` | Yes, pattern only | Adapter uses new value `host="claude-code"` |
| Health check / doctor | `second_brain doctor` → `doctor.run_doctor()` | Yes | Optionally extend doctor with a Claude-adapter check (hooks registered, rules file present) — not required for Stage 0 |
| Server/client transport | **None exists.** All CLI subprocess. | N/A | If an MCP server is ever wanted (P8/P9 territory), it's new — nothing to reuse. Not needed for Stage 0/1 (Claude Code's own hooks + CLAUDE.md cover local-first use without MCP) |
| Config system | No shared loader; every module does its own `tomllib.loads()` on its own `config/*.toml` with fail-soft try/except | Partial | Reuse the TOML + fail-soft convention; no shared `load_config()` to call |
| Circuit breaker / fail-open | No counter/backoff anywhere; convention is single-attempt try/catch → `{}`/neutral, same in Antigravity, Codex, Prime | Yes (as convention) | Copy the same single-shot fail-open try/catch in the Claude launcher script — no shared circuit-breaker module exists |

## Bottom line

Nothing about memory, retrieval, policy scoring, Lean Code, telemetry,
ledger, evidence, or project scoping needs to be rebuilt. The only new
surface is a thin Claude-facing adapter: one new `autoinject claude-code-hook`
CLI verb, a launcher script, a `rules/second-brain-core.md`, and Claude
Code's own hook/CLAUDE.md registration — the same shape as the Antigravity
and Codex adapters already in this repo. This matches the integration plan's
core rule: Claude consumes and contributes to the same Second Brain as every
other harness, via a thin adapter, not a parallel one.
