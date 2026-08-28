# Task 1 Report: `skills.py` harness-neutral visibility core

## Status
Complete. All acceptance criteria from `task-1-brief.md` met.

## Files changed
- Created `src/second_brain/skills.py` — `eligible_skills`, `descriptors`, `build_plan`,
  `hydrate_plan`, `plan_to_evidence`, `resolve_visibility_mode`, plus private helpers
  (`_purpose_excerpt`, `_body_stats`) and constants (`_MAX_SPECIALIST_SKILLS = 3`,
  `_DESCRIPTOR_TEXT_MAX_CHARS = 400`, `_PURPOSE_SECTION_MAX_CHARS = 240`).
- Created `tests/test_skills.py` — the brief's 10 tests verbatim, with one adjustment:
  dropped the unused `skillforge` import (brief's Step 1 code imports it but never calls
  it; keeping it would fail the brief's own Step 5 `ruff check` gate). No assertions,
  fixtures, or exact values were changed.
- Modified `config/skills.toml` — added `[visibility] mode = "shadow"` block after
  `[router]`, in the same commented-key style as `max_active`, with a blank line before
  `[lean]` preserved.

## Implementation notes / where I exercised judgment
- `router.route` is called as `router.route(...)` via `from . import router` (module-
  attribute access), per the brief's explicit import-style requirement — verified this
  is what makes `monkeypatch.setattr("second_brain.router.route", ...)` actually take
  effect in every test.
- `eligible_skills` iterates the fixed `("active", "candidate", "shadow")` order (same
  pool as `router.LEVEL_PRIORITY`), treats unreadable `SKILL.md` as eligible-but-hash-less
  (`content_hash=None`, never raises).
- `descriptors` slices only the `# Purpose` section (bounded local helper, not
  `router._parse_sections`/`skillforge._parse_sections` — avoids private-name coupling
  as instructed), capped at 400 chars total including a `name`/`version` prefix.
- `build_plan`: dedupes router's `selected` via `dict.fromkeys`, caps at 3
  (`_MAX_SPECIALIST_SKILLS`) independent of whatever `max_active` router itself used,
  reasons `"over_cap"` (eligible but beyond cap) vs `"not_eligible"` (never a key of
  `eligible`) exactly as specified. Router exceptions propagate untouched (verified by
  `test_router_failure_yields_zero_selection_not_all_skills`). Sets `hydrated_chars/
  tokens=0` and `avoided_full_*` to the full eligible-pool sum at build time (conservative
  baseline), per the brief's economics-timing note. Carries a private
  `_selected_content_hashes` field for `hydrate_plan`'s TOCTOU check.
- `hydrate_plan`: returns a new dict (never mutates the input), re-scans the filesystem
  fresh, rejects on missing/`None`/mismatched content hash (`"stale_content_hash"` or
  `"not_eligible"`) or read failure (`"read_failed"`), moves hydrated bytes from
  `avoided_full_*` to `hydrated_*`.
- `plan_to_evidence`: strips any `_`-prefixed key (currently just
  `_selected_content_hashes`); documented as the mandatory pre-telemetry boundary for
  Tasks 2/4.
- `resolve_visibility_mode`: own `tomllib`-read-with-fallback copy (not importing
  `router._router_max_active`), fails safe to `"shadow"` on any missing/malformed/
  non-`"enforced"` value.

## Tests
Command: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Result: `..........` — 10 passed.

Also ran adjacent regression checks (not required by the brief, done for safety, no
project-wide suite run):
- `.venv/Scripts/python.exe -m pytest tests/test_router.py tests/test_skillforge.py -q`
  → 50 passed.

Static checks (brief Step 5), all clean:
- `ruff check src/second_brain/skills.py tests/test_skills.py` → All checks passed.
- `ruff format --check src/second_brain/skills.py tests/test_skills.py` → both already
  formatted (ran `ruff format` once to normalize line-wrapping/quote style introduced
  while writing the files; no semantic change).
- `pyright src/second_brain/skills.py tests/test_skills.py` → 0 errors, 0 warnings,
  0 informations.

## Commit
`08367ca3ae788ef5bda882ec2e8c4ba06b263334` — "feat(skills): add harness-neutral
visibility plan core" (3 files changed: `src/second_brain/skills.py`,
`tests/test_skills.py`, `config/skills.toml`). Only these three files were staged/
committed; the working tree has many unrelated in-flight changes from sibling
P3.15/P3.16/P3.17-adjacent tasks that were left untouched.

## Concerns
- The brief's literal Step 1 test source imports `skillforge` without using it. I
  removed that one unused import to satisfy the brief's own required `ruff check` gate
  (Step 5) — every test name, assertion, fixture, and helper is otherwise byte-for-byte
  as specified. Flagging this explicitly since the brief says "exact values... verbatim."
- `router.py` is unmodified (read-only consumer), and `gardener.py`/P3.15
  evidence-provenance code were not touched, per constraints.
- Did not touch or start P3.17; scope stayed to Task 1 only.
