# Project Retrieval Isolation & Lean Code Activation

## Purpose
Enforces strict project isolation in AutoInject retrieval, prevents cross-project context leakage, applies delta conservatism in mid-session turns, and activates the Lean Runtime Kernel via canonical configuration.

## Problem it solves
1. Cross-project noise: unisolated queries or fallback ladders previously allowed memories from unrelated projects (e.g., Second Brain internals) to leak into external project sessions (e.g., SZ).
2. Delta injection noise: mid-session turns received weak or repeated context deltas.
3. Inactive Lean Code: the Lean Runtime Kernel implementation was inert because the activation gate was unconfigured.

## Responsibilities

### 1. Project & Scope Resolution Ladder
- `autoinject._resolve_project_id`:
  1. Explicit `--project` argument;
  2. CWD-based detection (explicit `.brain/project.toml` manifest, registered project `repo_path` containing CWD, git remote match against registered projects);
  3. If CWD is absent/empty: check if brain home path is registered;
  4. `SECOND_BRAIN_PROJECT` environment variable;
  5. `"default"` (unresolved fallback).
- Project isolation:
  - When `project_id` is resolved (e.g. `"sz"`), only memories matching `project_id == "sz"` or `scope == "global"` are eligible.
  - Wrong-project memories (`scope == "project"` and `project_id != intent.project_id`) are hard-filtered before scoring and ranking.
  - Unresolved project identity (`None`, `"default"`, `"unknown"`) fails safe: ALL project-scoped memories are suppressed (including any tagged `project_id="default"`); only explicitly global policies (`scope == "global"`) are eligible.
- Note on Campaign Affinity: The Second Brain schema natively supports `scope in ("global", "domain", "project", "model")`. Intra-project multi-campaign tagging and sub-project task affinity are not part of the current DB schema and are tracked as a separate follow-up.

### 2. Delta Strictness & Deduplication
- Mid-session delta conservatism (`intent.is_delta = True` when `invocationNum > 1`):
  - Token budget: target 400 tokens / hard cap 1000 tokens (configured via `[delta_budget]` in `config/autoinject.toml` and env overrides).
  - Confidence threshold: requires `status == "current"` and `evidence_grade` in `("VERIFIED", "TESTED")`.
  - Novelty/Deduplication: unchanged items already delivered in the session (`deliveries` table) are suppressed (`NoInjectionReason.ALREADY_DELIVERED`). Materially updated items (`v2 supersedes v1`) remain eligible.

### 3. Lean Runtime Kernel Activation
- Activation path: `config/skills.toml` `[lean] eval` (`"off"` by default in the V3 shipping
  profile, `"advisory"` to inject; env `SECOND_BRAIN_LEAN` overrides either value).
- Shipped default is `off`: no install injects the kernel unless the configuration (or the
  environment variable) asks for it. The kernel text is not deleted, only gated.
- Kernel parsed dynamically from `skills/candidates/lean-code/SKILL.md` (no duplicate constants).
- Role gate: injected only for code-capable roles (`driver`, `worker`).
- Dedup marker: `[second-brain-lean-code-kernel]` prevents duplicate injection within turn context.
- With `[lean] opportunity = true` (the V3 config) advisory decisions are rule-gated
  (`NOOP`/`NUDGE`/`FULL`); with the key absent they are classic (full kernel per turn).

### 4. Specialist Agents (Antigravity Harness)
Specialist agents defined for bounded delegation operate at the Antigravity harness level (stored in the Antigravity user runtime directory `<appDataDir>/.agents/agents/<name>/agent.md`, not committed as repository code):
- `brain_retrieval_specialist`: AutoInject retrieval, project isolation, ranking, delta filtering.
- `lean_code_specialist`: Lean Runtime Kernel activation, minimum-sufficient-change rules, stop conditions.
- `brain_memory_lifecycle_specialist`: Canonical memory state, update lifecycle, supersession.
- `brain_verification_specialist`: Independent in-worktree verifier for regression/adversarial test evidence.

## Verification Commands
```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest tests/test_retrieval_isolation.py tests/test_lean_canary.py tests/test_lean_runtime.py tests/test_autoinject.py tests/test_antigravity_adapter.py tests/test_semantic.py
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m pyright
.venv\Scripts\python.exe -m second_brain doctor
```
