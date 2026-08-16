# P0–P2 Pre-P3 Truth Cleanup (final report)

## 1. Starting issue

`mem-ae7a34f105c5` — a VERIFIED Sparking Zero semantic fact ("SZ build 24497537 … LevelCurve is Curve_AiLevelLinear_0001 in the base game", UE4SS dual-boot validation, source "M02 live validation 2026-08-15 (runtime memory probe, both arms)") — was incorrectly scoped to project `second-brain` and appeared in Second Brain AutoInject retrieval (observer9 union, documented in `p0-autoinject-gate.md`). Additionally, `p1-orchestration-cache-gate.md` claimed "worker reuse 100%" against the canonical ~57.1% task-weighted metric.

## 2. Provenance classification: **B — CLI default silently forced `second-brain`**

Evidence:
- `cli.py:431` (`memory add` parser): `--project` default = `"second-brain"` — reproduced: `memory add` WITHOUT `--project` in a temp brain creates a project-scoped memory with `project_id=second-brain` (reproduction output: `[('repro title', 'second-brain', 'project')]`).
- Creation context: memory created 2026-08-15T19:41:33Z by the SZ-CPU-Lab sibling session (`01a0063a-fe14-765e-8079-27569963c2ac`, harness project "Dragon Ball SZ M-series validation") invoking the Second Brain CLI (`python -m second_brain`, cwd=The-Second-Brain) — an SZ work context with no `--project`; the silent default captured it into second-brain.
- `episodes create` shares the same default (`cli.py:398`) — noted, NOT changed (plan scope = `memory add` only; no broadening).

## 3. Corrective action (smallest complete)

- **Code fix (proven defect):** removed the silent `second-brain` default for `memory add`; `scope=project` without `--project` now resolves from the authoritative project registry (registered project whose root contains the working directory, `_project_from_cwd`) or **fails clearly** (exit 2, "requires --project") — never silently second-brain. Global/domain scopes unchanged; AutoInject/writeback resolution untouched.
- **Quarantine (supported API only, no raw SQLite):** `memory curate mem-ae7a34f105c5 --grade REJECTED --status archived` + audit source appended ("Archived/rejected as a Second Brain project memory because the content belongs to the Sparking Zero project. Technical evidence may remain valid; project assignment was invalid."). Original evidence source preserved.
- **Backup/pre-fix snapshot:** `brainctl backup --note "pre-P3 truth cleanup: quarantine mis-scoped mem-ae7a34f105c5"` → `backups/backup-20260816-033653-543207/`; raw file preserved as `mem-ae7a34f105c5.pre-fix.md` in that backup dir (outside `memory/semantic/`, uncommitted).
- **Re-home:** `brainctl project list` → only `second-brain` registered; **no authoritative Sparking Zero project id exists → re-homing intentionally DEFERRED (NOT REGISTERED)**, per plan (no invented identity).
- **P1 wording:** `p1-orchestration-cache-gate.md` stale sentence replaced with "16/16 substantive workstreams delegated; retained-worker reuse ≈57.1% task-weighted in the final campaign accounting; zero duplicate fresh children for the same role". `rg "worker reuse 100%|reuse 100%" outputs/reports` → NONE.

## 4. Code fix needed: YES (reproduced Outcome B)

Regression tests added (`tests/test_cli.py`):
1. `test_memory_add_without_project_fails_clearly` — exit 2, nothing written, never second-brain.
2. `test_memory_add_explicit_project_still_works` — `--project second-brain` unchanged.
3. `test_memory_add_resolves_registered_project_from_cwd` — registered project root in cwd resolves to itself.
AutoInject/writeback resolution unchanged (existing suites green).

## 5. Retrieval proof before/after

- BEFORE: `memory search "Curve_AiLevelLinear_0001" --project second-brain` → `mem-ae7a34f105c5 [candidate/VERIFIED] SZ build 24497537 …`.
- AFTER (reindexed): same search → `No matching memories.`; `memory show` → `grade: REJECTED status: archived`; `memories`/`memory_index` rows consistent; file frontmatter archived/REJECTED.
- AutoInject probe: `autoinject shadow --task "Curve_AiLevelLinear_0001" --project second-brain --session cleanup-probe` → `NO_INJECTION | NO_RELEVANT_MEMORY | selected: []` (contaminated fact no longer emitted).
- Inverse probe under an SZ project: N/A (no SZ project registered).

## 6. P1 metric wording: corrected (see §3)

## 7. Ledger checkpoint/verify (live session ledgers; no forced copy)

| Host session | checkpoint | verify |
|---|---|---|
| `01a0086d-41af-7608-b22c-d9a9148c84cc` (dogfood observer) | ok:true, seq_contiguous, orphans 0, digests ok (5 events) | replay_ok:true |
| `01a00880-fcb8-726d-a88a-900115d80e1a` (live mirror session) | ok:true, seq_contiguous, orphans 0, digests ok (148 events) | replay_ok:true |

This worker's own host session has no ledger (its extension instance predates the mirror auto-init); verified the live mirrored ledgers instead. No live SQLite file was copied; WAL set left intact for post-session archival.

## 8. Test/doctor results

- Targeted: test_semantic/test_memory_index/test_retrieval_filters/test_autoinject/test_autoinject_writeback/test_cli/test_registry → **109 passed**.
- FULL: **pytest 738 passed, 2 skipped** (735 baseline + 3 regression tests).
- ruff: clean · pyright: 0 errors · vitest: 257 passed · `git diff --check`: clean · doctor: **16 checks, 0 failed** (2 warnings pre-existing: tool:rg absent on PATH).

## 9. Final branch/HEAD

`brain/p0-p2-production-core` @ `fe3da625be4f6cf52e5e6851b42a09fac8ad9238` (pre-cleanup HEAD; **no commit made — parent review pending**). Changed surface: `src/second_brain/cli.py` (+39/−3), `tests/test_cli.py` (+47), `outputs/reports/p1-orchestration-cache-gate.md` (1 line), plus `memory/semantic/mem-ae7a34f105c5.md` (quarantined) and this report.
