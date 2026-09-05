# Phase 17-21 — Qualified Source SHA vs. Evidence HEAD SHA

## Lineage

| Point | SHA | Meaning |
|---|---|---|
| `QUALIFICATION_BASELINE_SHA` (`src/second_brain/build_identity.py`, never rewritten) | `4af64affdf4f1ec07b9483b67f440394d2853b32` | The commit the v2 architecture was originally independently verified against (`outputs/reports/v2/final/release-report.md`). |
| Prior HOLD candidate | `86585e114115bc43bf932145e716f2ed4d3dd30e` (branch `brain/v2-omp-qualification`) | `RELEASE_DECISION.md`'s HOLD candidate — Phase 22 sustained burn-in below minimums, no P0/P1 in the repaired candidate at that time, provider quota exhausted before Phase 23 could close. |
| Repair branch point | `0b2aaf9788c8df6f174bd738377333f10364fd20` | `00-starting-state.md`'s documented branch-point commit for `brain/v2-omp-final-p1-repair`, identical to the HOLD documentation HEAD. |
| **This repair's evidence HEAD** | `7cbc3ba06ff36230eb58db2554848ec254b7cf13` | Current `brain/v2-omp-final-p1-repair` HEAD: 4 commits ahead of the branch point (`a9ff745` worker-result fix, `2d39016` installer default fix, `393c717` build fingerprint, `7cbc3ba` Phase 11-16 evidence), plus this report and the two remaining Phase 17-21/22 reports still to be committed. |

## `qualification_baseline_current` semantics

`build_identity.describe()` reports `qualification_baseline_current: false`
for every commit in this lineage table except the baseline itself — this is
expected and correct: `4af64af` is a fixed historical anchor, not a moving
target, and no commit in this repair's lineage is intended to equal it.
`qualification_baseline_sha` in every `describe()` call
(`06-build-fingerprint.md`) correctly still reports the unchanged
`4af64affdf4f1ec07b9483b67f440394d2853b32` constant.

## What changed between the qualified/HOLD SHA and this evidence HEAD

Only the two files this repair's scope covers, plus their tests and this
evidence trail — confirmed by `git diff --stat 0b2aaf9..7cbc3ba` for source:

- `brainstem/prime-extension/src/index.ts` (+worker-result auto-delivery observer)
- `brainstem/prime-extension/types/prime.d.ts` (+`MessageEndMessage` shape)
- `brainstem/prime-extension/tests/wiring.test.ts` (+8 regression tests)
- `scripts/install-prime-extension.ps1` / `scripts/uninstall-prime-extension.ps1` (+OMP default path)
- `brainstem/prime-extension/README.md` (+documentation of the corrected default)
- `brainstem/tests/install-prime-extension.Tests.ps1` (+2 regression tests)
- `outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/final-p1-repair/*` (this evidence trail)

No other source file differs from the `0b2aaf9` branch point.
