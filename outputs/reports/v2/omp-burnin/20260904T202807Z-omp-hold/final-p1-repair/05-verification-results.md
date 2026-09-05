# Phase 8-10 — Typecheck / Lint / Python Verification

## TypeScript typecheck

```text
npm run typecheck   # tsc --noEmit
```

Clean, zero errors.

## ESLint

```text
npm run lint   # eslint .
```

9 errors, all in files this repair never touched
(`tests/budget-caps.test.ts`, `tests/injection-placement.test.ts`,
`tests/lean-code.test.ts` — unused-var findings). Matches the documented
baseline (`RELEASE_DECISION.md`: "ESLint 9 findings"). Zero new lint errors
introduced by this repair's changed files (`src/index.ts`, `README.md`,
`types/prime.d.ts`, `tests/wiring.test.ts`,
`scripts/install-prime-extension.ps1`, `scripts/uninstall-prime-extension.ps1`,
`brainstem/tests/install-prime-extension.Tests.ps1`).

## Vitest full suite

```text
npx vitest run
```

**650 passed / 18 failed** (668 total) — identical to the
`03-worker-regression-results.md` full-suite comparison: same 18
pre-existing "Part B/E: context paging wiring" failures, zero new failures.

## Focused Python tests

No Python source file is touched by this repair (scope is
`brainstem/prime-extension/` TypeScript + `scripts/*-prime-extension.ps1`
PowerShell only). Ran the two suites most relevant to the upcoming build
fingerprint / identity gate as a sanity check:

```text
.venv\Scripts\python.exe -m pytest tests/test_build_identity.py tests/test_brainstem.py -v
```

`8 passed in 2.06s`. `PYTHONHOME`/`PYTHONPATH` removed from the environment
per this repo's `AGENTS.md` gotcha before invoking the venv Python.
