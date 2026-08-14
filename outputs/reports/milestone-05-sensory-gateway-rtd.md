# Milestone 05 — Sensory Gateway / RTD (Phase 5)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_1_OneShot_Implementation_Plan.md`
Prior gate: milestone-04 (Working Set / JIT) — complete (PASS-WITH-FINDINGS, reconciled below).

## What changed

Hash-addressed artifact storage with deterministic distillation and
byte-identical recovery (`brainctl artifact store|expand|list`), plus a
shadow-only Reversible Tool Distillation trigger in the Prime extension that
logs `rtd_shadow` telemetry and never substitutes content.

### Exact files

- `src/second_brain/artifacts.py` — content-addressed blob store
  (state/artifacts/blobs/<sha256>.bin + meta/<sha256>.json), atomic writes,
  collision check, prefix expansion, distillers (pytest/git/generic)
- `src/second_brain/cli.py` — `artifact store|expand|list`
- `brainstem/prime-extension/src/rtd.ts` + `index.ts` — shouldDistill
  (size>threshold AND bash AND pytest/git/rg/grep command), rtd_shadow records,
  threshold env override; no substitution ever
- `brainstem/prime-extension/tests/rtd.test.ts` (13) + wiring.test.ts extended (14)
- `tests/test_artifacts.py` — 25 tests (incl. 3 Hypothesis suites)
- `config/context.toml` + defaults — `[rtd]` section (enabled=false shadow default)
- `brainstem/telemetry/SCHEMA.md` — rtd_shadow kind
- `outputs/reports/milestone-05-sensory-gateway-rtd.md` (this file)

## Requirement-to-evidence (Phase 5 acceptance, plan §101)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Hash verified | live: real pytest output stored -> sha256 blob + meta; expand (full + 12-char prefix) byte-identical to stored bytes; collision path tested (never overwrites) |
| 2 | Distillation deterministic | golden tests (exact strings) + Hypothesis determinism + size-cap property; live distill of 149-test run: "pytest: 149 passed, 0 failed, 0 errors, 0 skipped" |
| 3 | Expand byte-identical | live + Hypothesis roundtrip on arbitrary unicode; short/ambiguous prefixes -> clean BrainError, never wrong bytes |
| 4 | Never compress source edit regions | RTD whitelist = bash + pytest/git/rg/grep commands only; edit/read tools can never trigger; substitution disabled entirely (shadow) |

## Commands / checks actually run

```text
ruff check src tests / ruff format --check -> clean
pyright src tests                    -> 0 errors
pytest -q                            -> 149 passed (25 new)
npx tsc --noEmit / eslint / vitest   -> 65/65 (18 new)
live: artifact store (real pytest -v output) -> expand full+prefix byte-identical
live: 3 real prime-agent runs attempted for rtd_shadow (see Dogfooding/Limitations)
```

## Deviations

1. `distill_generic` counts non-empty lines; `distill_git` counts all non-empty
   lines, renders first 50, capped 2000 chars (documented worker choices).
2. pytest distiller: last-occurrence counts win; "0 passed" counts as a marker.
3. Blob files are `<sha256>.bin` (not bare hash) — layout detail.
4. `brainctl artifact` commands are an addition beyond the plan's §82 list
   (plan names only /brain-expand); the handle text uses that exact form.

## Known risks / limitations

- **rtd_shadow live trigger UNVERIFIED live** (honest gap): 3 real print-mode
  flash sessions declined to call the bash tool (agents answered via IPython or
  refused), so no live >threshold bash result occurred. The trigger logic is
  unit-tested (13+5 tests) against the documented event shape; a harness-level
  forced-tool-call test is deferred to Phase 8 tool_call work.
- Distillers are heuristic (plan's "start with" scope); kinds beyond
  pytest/git/search fall back to generic.

## Dogfooding / Self-Hosting

- The build's own working set gated Phase 5: 3 material requirements were
  carried unverified during implementation, each closed with concrete evidence
  (test names + live outputs), and `requirements check` flipped 3/3 -> 0/3.
- The Brain stored its own real pytest output as its first artifact and
  recovered it byte-identically — the store now serves later phases for
  oversized outputs.
- Capsule updated with 2 decisions (shadow-only substitution; live-trigger
  gap) and next_action=Phase 6 Scout — a fresh agent resuming from the
  compiled capsule gets the gate state without reconstruction.
- Completion-reserve: retrieval does not exist yet; context at 34% — no
  reserve pressure; nothing trimmed.

## Phase 4 verifier reconciliation (post-gate)

Phase 4 verdict PASS-WITH-FINDINGS. Fixed in this milestone's commits:
1. MINOR — project leaf `--home` truly fixed (parents on add/list/status/
   detach/remove) + new CLI regression test (postfix form).
2. NIT — milestone-04 test count corrected (123 at gate, not 118).
3. NIT — `context compile` write now atomic (tmp + os.replace).
4. NIT — working_set JSON writes use unique mkstemp names (no same-session
   tmp collision).
5. NIT — attach-created AGENTS.md left as 0-byte file after detach: accepted
   (safe direction; documented in milestone-03).

## Rollback

- Git: revert this milestone's commits.
- Artifacts/telemetry: derived — delete state/artifacts, telemetry files.
- RTD stays shadow: nothing active to disable; `SECOND_BRAIN_RTD` untouched.

## Next gate

**Phase 6 — Scout** (plan §102): isolated repository explorer returning only
Evidence Maps; RepoWise → rg → ast-grep → direct read → isolated subagent;
compare baseline vs Scout on edit localization / tool calls / tokens / main
context / success; promote to advisory only if beneficial.
