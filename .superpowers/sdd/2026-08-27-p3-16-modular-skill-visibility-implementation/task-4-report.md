# Task 4 Report: `hermes_adapter.py` visibility integration

## Status
Complete. All acceptance steps from the brief executed; full `test_hermes_adapter.py` suite green (31/31); ruff check, ruff format (for touched code), and pyright all clean; commit made.

## Files
- Modified `src/second_brain/hermes_adapter.py`:
  - Added `skills` to the `from . import (...)` block, alphabetically between `router` and `vmem`.
  - Added `_visibility_task(home, task, session_id, project_id) -> tuple[dict | None, dict[str, str]]` immediately after `_route_task`, mirroring its fail-open shape: calls `skills.build_plan` → `skills.hydrate_plan` → `skills.plan_to_evidence`, returns `(None, {})` on any exception.
  - In `_handle_pre_llm`, immediately after the existing `selected_routes, routing_error = _route_task(...)` line, added the `visibility_plan, hydrated_bodies = _visibility_task(...) if task else (None, {})` call, exactly as specified.
  - Confirmed the packet-holding local variable is `visible_packet` (unchanged from brief's assumption). Immediately after `visible_packet = packet if packet and mode in {"advisory", "active"} else None`, added the enforced-mode extension: when `visibility_plan.get("mode") == "enforced"` and `hydrated_bodies` is non-empty, the sorted hydrated bodies are joined and appended to (or become) `visible_packet`.
  - Added `"visibility_plan": visibility_plan,` alongside both existing `"selected_routes": selected_routes,` entries — in the `event_payload` telemetry/ledger dict and in the function's final returned response dict.

- Modified `tests/test_hermes_adapter.py`:
  - Added `_visibility_skill(home, name=...)` helper (writes a full-section shadow-pool `SKILL.md`).
  - Added `test_pre_llm_shadow_mode_never_injects_hydrated_skill`, `test_pre_llm_enforced_mode_injects_hydrated_skill`, `test_pre_llm_visibility_failure_does_not_break_existing_autoinject_path` — all via the real `_run_hook` subprocess CLI bridge, following the exact existing style (reusing `_current_memory`, `_start_payload`, `_run_hook`; no helper redefinitions).

## Deviation from the brief (and why)
The brief's literal shadow-mode test task text (`"demo-visibility-skill content trigger"`) shares zero tokens with the seeded memory's body text, so AutoInject's OR-fallback retrieval finds nothing and `out["packet"]` is `None` — the literal assertion `"demo-visibility-skill content" not in out["packet"]` then raises `TypeError: argument of type 'NoneType' is not iterable` rather than exercising the intended behavior (packet exists, is bounded, and never leaks the hydrated shadow skill body). I changed only the task string to `"How does Hermes retrieve bounded project context for demo-visibility-skill content?"` — this shares tokens with the seeded memory (so a real, non-null packet is produced via OR-fallback, matching the pattern used by the file's other memory tests) while still containing the exact skill's positive-trigger phrase (`"demo-visibility-skill content"`) so the router still selects and hydrates it. Added two extra assertions (`out["packet"] is not None` and `visibility_plan["hydrated_skill_ids"] == ["demo-visibility-skill"]`) to make the fixture's actual behavior explicit and prevent this from silently degenerating into a vacuous check again. No other test bodies, the enforced-mode test, or the failure-path test needed changes from the brief's literal code.

Two touched-code-only formatting fixes were also required beyond the brief's exact snippets (both introduced by my own additions, confirmed via `ruff format --check`, not pre-existing debt):
- `hermes_adapter.py`: needed a second blank line before the new `_visibility_task` def (PEP8/ruff 2-blank-line top-level rule).
- `test_hermes_adapter.py`: the `_visibility_skill` title tuple needed one-per-line formatting, and a stray triple-blank-line at the boundary with the next existing test (inherited from the insertion point) was collapsed to two.

## Tests
- `pytest tests/test_hermes_adapter.py -k "shadow_mode_never_injects or enforced_mode_injects or visibility_failure"` → 3 passed (new tests, individually verified against the real implementation).
- `pytest tests/test_hermes_adapter.py -q` → 31 passed, 0 failed (full file, no regressions).
- `ruff check src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py` → all checks passed.
- `ruff format --check` on both files → clean for all lines this task touched; both files carry pre-existing formatting debt elsewhere (unrelated line ranges: e.g. `hermes_adapter.py:386,1234,1388,1575,1640,1683` and `test_hermes_adapter.py:70,569,648,758,813,891,939,1023,1116,1201`), confirmed identical before and after my edits by inspecting that none of those line ranges fall inside my diff hunks. Left untouched per "don't restyle code you don't own."
- `pyright src/second_brain/hermes_adapter.py tests/test_hermes_adapter.py` → 0 errors, 0 warnings, 0 informations.

## Commit
`f5d77d0` — `feat(hermes-adapter): fold visibility plan into pre-llm response` (both files were previously untracked in this repo; git recorded them as new-file creations, 3091 insertions total, consistent with `git status` showing `??` for both paths before this commit).

## Concerns
- Neither `hermes_adapter.py` nor `test_hermes_adapter.py` had any prior git history in this repository (both were untracked before this commit, despite being large pre-existing files) — this is a pre-existing repo-state fact unrelated to Task 4, noted for visibility since it affected how I had to verify "pre-existing vs. newly introduced" formatting debt (via line-range inspection rather than `git diff`/`git stash`, since stash does not touch untracked files).
- Did not touch `skills.py`, `router.py`, `gardener.py`, `omp_adapter.py`, or any Prime-extension TS file, and did not begin P3.17, per the assignment's constraints.

## Post-review fix (P3_16_Task4Review finding)
Review correctly identified that `test_pre_llm_visibility_failure_does_not_break_existing_autoinject_path` did not exercise a real failure: `skills.resolve_visibility_mode` only catches `(OSError, tomllib.TOMLDecodeError)` around `config/skills.toml`, and the original malformed-TOML text (`"not valid toml [[["`) is exactly the case that clause already fail-safes to `"shadow"` on — it never raises, so `_visibility_task`'s `except Exception` fail-open branch had zero coverage and the test passed vacuously.

Fix applied: replaced the malformed-TOML setup with writing invalid UTF-8 bytes to `config/skills.toml` (`b'[visibility]\nmode = "shad\xffow"\n'`) via a binary file write. `Path.read_text(encoding="utf-8")` on invalid UTF-8 raises `UnicodeDecodeError` (a `ValueError` subtype), which is *not* caught by `resolve_visibility_mode`'s `except (OSError, tomllib.TOMLDecodeError)` clause, so it propagates out of `skills.build_plan` and is only caught by `_visibility_task`'s broad `except Exception`. Verified directly via a standalone script hitting the real subprocess CLI bridge: `visibility_plan` comes back `None` while `status`/`decision`/`packet` are unaffected. Added `assert out["visibility_plan"] is None` to the test (proving the fail-open branch actually ran) and corrected the inline comment to accurately describe the invalid-UTF-8 trigger instead of "malformed TOML".

Re-verified after the fix: `pytest tests/test_hermes_adapter.py -q` → 31 passed; `ruff check`/`ruff format --check` on the edited region clean (same pre-existing unrelated debt elsewhere, untouched); `pyright tests/test_hermes_adapter.py` → 0 errors. Committed as a follow-up commit on top of `f5d77d0`.

## Final cross-task review fix: bounded hydration

### Status
Complete. Finding 1 is closed at the canonical `skills.hydrate_plan` boundary.

### Files
- Modified `src/second_brain/skills.py`:
  - Added a fixed `_MAX_HYDRATED_BODY_CHARS = 4096` bound for each selected
    `SKILL.md` body.
  - Oversized bodies now fail closed as `body_too_large`, with no hydrated
    skill ID and no returned body. Their full-size economics remain in the
    avoided-body baseline.
  - Selected bodies within the bound continue to hydrate unchanged and are
    returned in full.
- Modified `tests/test_skills.py`:
  - Strengthened normal hydration coverage to assert the returned body is the
    complete file content.
  - Added oversized selected-body rejection coverage, including unavailable
    reason, empty body result, and zero hydrated economics.
- Modified `tests/test_hermes_adapter.py`:
  - Added enforced-mode subprocess coverage proving an oversized selected
    body is not appended to Hermes' visible packet while the existing
    AutoInject packet remains available.
- `src/second_brain/hermes_adapter.py` required no source change: it consumes
  the bounded core result, so both Hermes and OMP consumers receive no body
  for oversized selections.

### Tests
- `.venv/Scripts/python.exe -m pytest tests/test_skills.py -k 'hydrate_plan' -q`
  → 3 passed (red test was observed before the implementation).
- `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -k 'shadow_mode_never_injects or enforced_mode_injects or oversized_hydrated or visibility_failure' -q`
  → 4 passed.
- `.venv/Scripts/python.exe -m pytest tests/test_skills.py tests/test_hermes_adapter.py -q`
  → 43 passed.
- `.venv/Scripts/python.exe -m py_compile src/second_brain/skills.py src/second_brain/hermes_adapter.py tests/test_skills.py tests/test_hermes_adapter.py`
  → passed.

### Commit
`b147a64` — `fix(skills): bound hydrated specialist bodies`

### Concerns
- The 4096-character bound is per selected body; the existing selected-skill
  cap remains 3. Bodies are rejected rather than truncated, so no partial
  text is presented as complete instructions.
- No formatters, linters, project-wide suites, TS files, router, OMP adapter,
  or lifecycle/governance code were changed.

## Final Ruff E501 mechanical fix

Wrapped the oversized task string in `tests/test_hermes_adapter.py` across adjacent implicit string literals. The resulting value is unchanged; no production code or other tests were modified.

Focused verification:
- `.venv/Scripts/python.exe -m ruff check src/second_brain/skills.py src/second_brain/hermes_adapter.py tests/test_skills.py tests/test_hermes_adapter.py` → all checks passed.
- `.venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -k "shadow_mode_never_injects or enforced_mode_injects or visibility_failure" -q` → 3 passed.
