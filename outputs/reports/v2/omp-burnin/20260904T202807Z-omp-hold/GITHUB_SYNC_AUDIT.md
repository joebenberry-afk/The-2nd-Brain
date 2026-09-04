# GitHub Sync Audit

This audit records the OMP-first qualification state synchronized to the public
GitHub repository. The runtime qualification evidence remains distinct from
later documentation-only synchronization commits.

## Local State

- Qualification branch: `brain/v2-omp-qualification`
- Runtime qualification SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- Evidence SHA: `f0419788a776602b8922fb9a4a32f57b754060d9`
- Supersession documentation SHA: `f42f8096c2fe8c51e195453bdadb3015127ae26c`
- Runtime SHA ancestor of evidence SHA: **YES**
- Git status: **clean** at the synchronization checkpoint
- The evidence commit contains the five qualification reports only. The
  supersession commit changes release-report documentation only; neither commit
  changes executable runtime or extension source.

## Remote State

- Remote branch: `origin/brain/v2-omp-qualification`
- Remote SHA: `f42f8096c2fe8c51e195453bdadb3015127ae26c` at the last pushed
  synchronization checkpoint before this audit report commit
- Local/remote match: **PASS** at that checkpoint
- Evidence directory visible remotely: **PASS** — all five qualification
  reports are present under
  `outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/`
- `v2.0.0` tag absent: **PASS** — absent from local tags and `origin`

## Qualification State

- Doctor: **19/19 checks passed**, 0 failures, 0 warnings
- Schema: **21**
- Rollback: **PASS** — 89 canonical files and the database hash matched the
  pre-change snapshot; SQLite integrity check returned `ok`
- Focused regressions: **5 passed** on the repaired live paths
- Worker launches: **19/20**
- Worker results: **7/20** — 4 completed and 3 failed; failed results remain
  explicitly failed and are not counted as fabricated completions
- Compactions: **8/10**
- Project switches: **11/20**

## External Boundary

- Provider error: HTTP `429`, error type `rate_limit_error`
- `retry-after-ms`: `9017000`
- Qualification stopped without fabricated retries: **PASS** — no repeated live
  provider attempt was made after the authoritative throttle response

## Release Decision

**HOLD**

## Blocking Reason

Native OMP Phase 22 coverage remains incomplete because additional real
provider-backed runs are temporarily unavailable due to rate limiting.

## Prime Dependency

Prime binary required for OMP v2 release: **NO**

## Outstanding Repository Hygiene (at the b7d893b audit checkpoint)

- stale package metadata: `brainstem/prime-extension/package.json` is already
  OMP-first (`version` `0.2.0` and the OMP-first description). Its lockfile
  still records root `version` `0.1.0`; the historical package name
  `second-brain-observability` is stable in both manifests. These values do not
  affect OMP loading, because installation copies `src/` and `types/` directly;
  they do not affect build identity, which hashes deployed extension source;
  they do not affect diagnostics, which use the Brain build identity. This is a
  **P2 metadata cleanup item that must be resolved before `v2.0.0`**, without a
  broad package rename in this qualification.
- full-suite baseline/backlog failures: Python `1802 passed / 13 failed` and
  TypeScript `642 passed / 18 failed`; the recorded baseline delta identified
  no candidate-only regression
- lint/type backlog: ESLint `9` findings, Ruff `438` findings, and Pyright `85`
  diagnostics

## Authority and Historical Reports

- Current authoritative decision:
  `outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/FINAL_RELEASE_EVIDENCE.md`
- Superseded and retained as historical evidence:
  `outputs/reports/v2/burnin/14-final-release-gate.md`
- Superseded and retained as historical evidence:
  `outputs/reports/v2/final/release-report.md`
- Both historical reports now carry an explicit supersession banner. Their
  earlier Prime/Claude Code blocker is not the current OMP release gate.

## Proceeding Addendum

After the b7d893b checkpoint, the planned package cleanup was applied without
dependency regeneration: both `package.json` and the `package-lock.json` root
metadata now report version `0.2.0`. `npm run typecheck` and
`npm ci --dry-run --ignore-scripts` both passed. The four new proceeding
reports in this directory record the unchanged Phase 22 hold, the
non-recoverable stale worker rows, and the final release decision; no release
tag was created.
