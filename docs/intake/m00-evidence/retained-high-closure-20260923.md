# Retained-HIGH closure packet — executed gates (2026-09-23)

**Subject:** the orchestration-free M00 candidate on `brain/m00.3-producer-guard`,
parent `4d74719`, plus the changes listed in §3. Companion records:

- [`high-dispositions-20260923.md`](high-dispositions-20260923.md) — per-finding
  evidence and disposition.
- [`native-noninterference-20260923.json`](native-noninterference-20260923.json) —
  raw probe payload, arm-by-arm.
- [`orchestrator-removal-gate-20260923.md`](orchestrator-removal-gate-20260923.md) —
  the earlier frozen-subject (`ce15820`) gate. That record still describes its
  own subject; this packet does not rewrite it.

**Not** a qualification verdict and **not** a production claim. `SEC-AUTH-01`
and `SEC-AUTH-02` remain open and require an owner decision (§5).

## 1. How these gates were run (and one environment trap)

All Python gates ran with the candidate's interpreter addressed by **absolute
path**:

```
CAND=C:/Users/assas/Documents/The-Second-Brain/.worktrees/m00.3-producer-guard
$CAND/.venv/Scripts/python.exe -m pytest -q --no-header -p no:cacheprovider
```

Trap, recorded because it silently corrupts evidence: invoking the interpreter
as a **relative** path (`.venv/Scripts/python.exe`) from this shell reaches the
*main checkout's* venv, so `sys.executable` inside pytest is
`…\The-Second-Brain\.venv\Scripts\python.exe` with no `PYTHONPATH` binding.
Tests that spawn CLI children then import `second_brain` from a sibling worktree.
That produced two false failures in an earlier run of this packet
(`test_v1_p4_qualification`'s runtime-source guard, and
`test_hermes_adapter::test_unapproved_skill_descriptor_never_reaches_hermes_prefix`);
both pass with the absolute path, and both guards were doing their job. Treat a
`Qualification runtime source mismatch` failure as an environment error first and
a product finding second — and never "fix" it by adding an ambient `PYTHONPATH`
that only the parent process inherits.

## 2. Executed results

| Gate | Command | Result |
|---|---|---|
| Python lint | `python -m ruff check src tests scripts` | clean (`All checks passed!`) |
| Python types | `python -m pyright` | `0 errors, 0 warnings` |
| Python suite | `python -m pytest -q -p no:cacheprovider` (absolute candidate interpreter) | **2113 passed / 1 skipped / 0 failed** (2114 collected; the skip is the POSIX write-bit test on Windows ACLs) |
| Extension types | `npx tsc --noEmit` | exit 0 |
| Extension lint | `npx eslint .` | exit 0 |
| Extension suite | `npx vitest run` | **26 files / 600 tests passed**, matching the frozen-subject count |
| Installer/rollback | `Invoke-Pester brainstem/tests/install-prime-extension.Tests.ps1` | **20 passed / 0 failed**, including the two new post-swap cases |
| Dev advisories | `npm audit --package-lock-only` in `brainstem/prime-extension` | before: 1 high + 2 moderate; after: **0 high** + 2 moderate (dev-only, deferred) |
| Native non-interference | `python scripts/native_noninterference_probe.py --installed …` | 5 arms; **8/8 recorded verdicts true**; sensitivity control refused with 13 markers |
| Probe self-test | `python scripts/native_noninterference_probe.py --self-test` | extractor detects a known-refusal sample (exit 0) |

Provenance note for the Python suite: this pytest build emits no final summary
line when stdout is redirected here, so the counts above are counted from the
progress stream (2113 `.`, 1 `s`, 0 `F`, 0 `E`) and cross-checked against the
previous session's `2112 passed / 1 skipped` plus the one regression test this
packet adds.

## 3. What changed in this packet

| File | Change |
|---|---|
| `src/second_brain/ledger.py` | `LedgerRehydrator.rehydrate` verifies chain, sequence, parents and object digests before projecting payloads; fails closed (14 added lines). |
| `tests/test_ledger.py` | New `test_rehydrate_refuses_tampered_chain`; `_ev` accepts `artifact_sha256` so the level-3 fixture binds the artifact at append time instead of rewriting a chained column. |
| `scripts/native_noninterference_probe.py` | New, explicitly invoked host differential with a self-tested extractor; disposable brain home per run. |
| `scripts/install-prime-extension.ps1` | Post-swap re-verification of the installed tree with restore-on-mismatch; the reported manifest hash is now the installed tree's. |
| `brainstem/tests/install-prime-extension.Tests.ps1` | Two cases exercising the post-swap branch (fresh install must not be left in place; previous extension must come back byte-identically). |
| `brainstem/prime-extension/package-lock.json` | `js-yaml` 4.3.1 → 4.3.2 (transitive dev dependency of `@eslint/eslintrc`, inside its declared `^4.3.0` range). |
| `docs/intake/M00-CAMPAIGN-REGISTER.md` | Finding-disposition rows rewritten per finding; `M00-NATIVE-ORCH-01` status now records the executed differential and what it does not cover. |
| `docs/intake/Second_Brain_M00_OneShot_Closure_Mandate.md` | Obligations table now matches the register, with per-finding dispositions and the owner decisions called out. |
| `docs/intake/m00-evidence/*` | This record, the disposition record and the raw probe payload. |

## 4. What is now closed, narrowed, and still open

- **Fixed in this packet:** unverified ledger rehydration (fail-closed +
  regression test); installer post-swap integrity (fail-closed + Pester);
  `js-yaml` dev-dependency HIGH.
- **Clauses refuted with evidence:** SEC-INTEGRITY-01's three literal clauses;
  SEC-SKILL-01's consumption-time binding clause; SEC-HOOK-02's managed-hook
  PATH exposure; FSUPD-01's literal staging defect (retired with the file).
- **Narrowed but open:** SEC-INTEGRITY-01's unkeyed self-anchored chain;
  SEC-SKILL-01's caller-authored approval record; FSUPD-01's missing protected
  approval and unconstrained operator-chosen paths; SEC-HOOK-02's non-hook
  search-path resolution (low, same-user).
- **Open and blocking until decided:** `SEC-AUTH-01`, `SEC-AUTH-02` — reproduced
  on retained paths, not fixable by a candidate-local edit.
- **Observations, not proven rows:** `hub`/steering, workpool,
  cancellation/restart timing and model selection were not exercised by the
  probe. No retained candidate file touches them, but the probe did not measure
  them, so they stay listed as observations.

## 5. Owner decisions this packet cannot make

1. **`SEC-AUTH-01`** — accept at the M00 release boundary, or keep blocking
   until a non-agent-controlled approval/verification channel exists.
2. **`SEC-AUTH-02`** — accept, or keep blocking until a declared grade stops
   minting `project_rule` authority and bypassing the retrieval holdout.
3. **Dev toolchain** — accept the two remaining dev-only moderates at freeze, or
   schedule the `vitest@5` major upgrade with re-frozen test evidence.

No row above converts an open finding into a pass, and no production activation
follows from this packet.
