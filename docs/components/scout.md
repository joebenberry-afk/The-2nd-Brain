# Scout (Isolated Repository Explorer)

## Purpose
Run exploration in a separate read-only agent so main context is never polluted by search trajectories (plan §22-23, §102; Phase 6).

## Problem it solves
Unfamiliar-repo exploration is token-expensive and polluting; Scout isolates it and returns only an Evidence Map.

## Responsibilities
- `EVIDENCE_MAP_FIELDS` (9, plan §23) rendered as sections with `(fill me)` placeholders.
- `resolve_repo(home, target)`: existing path → resolved; else `registry.get_project` key; else BrainError.
- `deterministic_prepass(repo, task, max_candidates=10)`: git (branch, HEAD short sha, dirty via status --porcelain); repowise (cli available, index present, freshness from `repowise status` "Last sync" line, timeout 20s); candidates via `rg -l -i --max-count 1` per task word (alnum ≥4; excludes node_modules/.venv/.git/dist/build/__pycache__), repo-relative posix paths with match counts, capped. All probes capture/timeout and NEVER raise — failures become `{error: msg}`.
- `write_evidence_map`: slug file, numeric suffix on collision, prepass into Source Freshness + "Deterministic Pre-pass" appendix, atomic mkstemp write.
- `SCOUT_PROMPT_TEMPLATE`: read-only mandate; tool priority RepoWise → rg → ast-grep → direct read; fill map in place; final reply `<map_path>|<one-line summary>`.
- `scout_command`: prime-agent argv (bash, prime-agent.sh, -p, -t ipython,bash, --model, --cwd, --offline, --daemon-socket scout-<uuid>, optional -e ext, prompt as ONE argv element).
- `run_scout`: resolve → prepass → map → spawn (timeout 900, env sanitized) → `{map_path, rc, stdout_tail, stderr_tail, command, prepass}`.

## Non-responsibilities
Never edits code/runs tests/builds; main agent inherits only the map.

## Inputs
Repo path or project key; task; model/out_dir/ext options.

## Outputs
Evidence Map markdown + prepass dict.

## State ownership
None in the repo; writes outputs/evidence-maps (derived).

## Invariants
Prepass deterministic and probe-tolerant; command is a pure argv list (no shell — quotes/backticks/braces can't inject; plain `.replace` prompt embedding); 9-section structure preserved.

## Interactions
`registry` (keys), `repowise`/`rg`/`git` binaries; `brainctl scout` (--no-agent prepass-only); live baseline-vs-scout experiment run (milestone-06) — promoted to advisory.

## Failure behavior
Unresolvable target → BrainError; probe failures → error entries; spawn failure captured (rc -1), never raised.

## Verification
`tests/test_scout.py` (15): schema/slug, resolve (path/key/missing), prepass on fake git repo (candidates/counts/dirty), never-raises on non-repos, map content + collision, command shape/no-injection/unique socket. `run_scout` exercised live by parent.

## Known limitations
Depends on rg (skips gracefully); repowise freshness is the raw CLI line (may include box chars); no RepoWise index init (decision #4).

## Future extension
RepoWise index init + freshness gating (advisory promotion after baseline comparison already done — milestone-06, plan §102).

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #4, #10.

## Relevant tests
`tests/test_scout.py`, `tests/test_registry.py`, `tests/test_cli.py`.
