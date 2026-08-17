# Retrieval Isolation & Lean Code Activation

## Purpose
Enforces strict project and campaign isolation in AutoInject retrieval, prevents cross-project context leakage, applies delta conservatism in mid-session turns, and activates the Lean Runtime Kernel via canonical configuration.

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
  - Unresolved project identity (`None` or `"default"`) fails safe: project-local memories from other projects are suppressed; only explicitly global policies are eligible.

### 2. Delta Strictness & Deduplication
- Mid-session delta conservatism (`intent.is_delta = True` when `invocationNum > 1`):
  - Token budget: target 400 tokens / hard cap 1000 tokens (configured via `[delta_budget]` in `config/autoinject.toml` and env overrides).
  - Confidence threshold: requires `status == "current"` and `evidence_grade` in `("VERIFIED", "TESTED")`.
  - Novelty/Deduplication: unchanged items already delivered in the session (`deliveries` table) are suppressed (`NoInjectionReason.ALREADY_DELIVERED`). Materially updated items (`v2 supersedes v1`) remain eligible.

### 3. Lean Runtime Kernel Activation
- Canonical activation path: `config/skills.toml` `[lean] eval = "advisory"`.
- Kernel parsed dynamically from `skills/candidates/lean-code/SKILL.md` (no duplicate constants).
- Role gate: injected only for code-capable roles (`driver`, `worker`).
- Dedup marker: `[second-brain-lean-code-kernel]` prevents duplicate injection within turn context.

### 4. Specialist Agents
Permanent Second Brain specialist set defined for bounded delegation:
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
