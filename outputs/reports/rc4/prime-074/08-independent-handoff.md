# 08 — Independent Handoff Summary (Prime 0.7.4 Compatibility Qualification)

**Verdict: PRIME_0_7_4_SECOND_BRAIN_COMPATIBLE — EXTERNAL REVIEW REQUIRED**

## What was tested

Sections 6-27 of the RC4 Prime 0.7.4 upgrade qualification plan, following
directly on Sections 1-5 (frozen baseline + static audits, already
complete, zero breaking changes found statically). This pass provided the
required **live runtime proof**: an isolated Prime 0.7.4 instance was
built, Prime's own gates were run, the frozen RC4 candidate Second Brain
extension code (`98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72`, combined
sha256 `5c44759771...`) was re-synced into it, and two real sessions were
run against it — a smoke session and one bounded compatibility session
exercising every interface Pilot 5 proved on 0.7.3 (AutoInject, RTD
live-reduction + byte-exact recovery, RTD VMem metadata, proactive
paging, provider pointer proof, EVICTED reprojection, fault-in
(HOST_INTEGRATION), usage/cache telemetry, RLM subagent spawn).

## Exact versions

- Prime 0.7.4: commit `af0b8e00b9f704e834787fd321065ca78281f2aa`
  ("chore(release): prepare v0.7.4 (#1569)"), `--version` reports exactly
  `0.7.4`, build id `v0.7.4-dirty` (dirty = the 2 known local Windows
  patches only).
- RC4 candidate SHA (unchanged runtime code throughout): `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72`.
- Isolated worktree: `C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`.
- Isolated agent dir (new, never used by the live daemon):
  `C:\Users\assas\.prime-074-compat\agent`.

## Real session ids

- Section 11 smoke: `01a02105-475b-745f-b4ee-e58402682abf` (internal id
  `01a02105-654c-764d-b059-a4f4ed84b903`).
- Section 12 compat: `01a02107-1a9d-73ef-8dfb-e8239b63dada` (internal id
  `01a02107-386b-72e4-9c1c-704849eab650`), disposable branch
  `rc4-prime074-compat-disposable` @ `98f147f9...`.
- Section 12 RLM child: `sub-c7eff7cb`, child session
  `01a0211a-5385-724c-9610-34340315f95b`.

## Compatibility matrix summary

21/21 rows PASS or NOT_APPLICABLE/HOST_INTEGRATION-labeled-PASS. No
BREAKING_FOR_BRAIN row. Full matrix: `05-compatibility-matrix.md`.

## Test/lint/typecheck counts

- Second Brain Python (main worktree): pytest 1064/1064 passed, ruff
  clean, pyright 0/0/0.
- Second Brain Prime extension (TS): vitest 560/560 passed (18/18 files),
  eslint clean, tsc clean.
- Prime's own suite (0.7.4 isolated worktree): 318 failed / 3886 passed /
  55 skipped (4259 total), 14 errors — proven via direct A/B against a
  fresh 0.7.3 throwaway install (316 failed / 3867 passed / 53 skipped of
  4236, 14 errors) to be a pre-existing Windows/Node-v26/vitest
  environment failure baseline, not a 0.7.4 regression (see
  `05-compatibility-matrix.md`'s "Note on Prime's own gates" and
  `07-prime-074-qualification.md` Section 8 for the full reasoning).

## Live installation confirmation

`C:\Tools\prime-agent` (live 0.7.3 checkout serving the live daemon):
`git status --short` shows only the same 2 pre-existing local Windows
patches, nothing new; `git rev-parse HEAD` still `61131b2d195ba7a67a4ce8ac60bb10cecae07b67`
(v0.7.3). `C:\Users\assas\.prime\agent\extensions\second-brain\`
combined sha256 re-confirmed unchanged (`5c44759771...`). The 5 live
daemon-related node.exe processes (all referencing `C:\Tools\prime-agent`)
were enumerated by full command line before and after this pass and are
identical; 19 isolated-instance node.exe processes (all referencing
`prime-upgrade-worktrees\prime-074`) were separately identified and
cleanly terminated.

## `config/context.toml` confirmation

Reverted to all-OFF in the MAIN Second Brain worktree; `git diff
config/context.toml` is empty.

## Files changed / committed

This report-writing pass adds only files under `outputs/reports/rc4/prime-074/`
(this file, `05-compatibility-matrix.md`, `06-rollback.md`,
`07-prime-074-qualification.md`, and `raw/02-prime-074-compat-evidence-bundle.json`).
No source files under `brainstem/prime-extension/src/`, `src/second_brain/`,
or `config/` remain changed (all config toggles reverted; no adapter code
change was needed since every compatibility interface tested PASSED
without requiring any narrow patch).

## Anomalies / unresolved risks

1. Four process-quality lessons about running the isolation setup itself
   (kernel-venv env var independence, extension directory flat-layout
   requirement, PYTHONHOME pollution, RTD's narrow eligibility grammar) —
   documented in `07-prime-074-qualification.md`'s "Anomalies" section,
   all corrected before any evidence in this report was captured, none a
   Prime 0.7.4 or Second Brain runtime defect.
2. RLM subagent/RTD Q10 check exercised one small, fast child only (a
   documented, honest limitation of a bounded `--print`/`--continue`
   check, not a gap requiring further action before promotion).
3. Compaction lifecycle (Section 12 Q8) did not occur naturally in the
   bounded session (context usage stayed ≤5.08% of the window) — not
   forced, per instruction; the static contract audit (`04-static-contract-audit.md`)
   already independently confirmed the relevant event types/dispatch are
   byte-identical between 0.7.3 and 0.7.4.
4. `before_provider_request`'s exact real-world payload shape is now
   closed for the Anthropic provider (the only provider this whole
   qualification campaign has exercised); the OpenAI-Codex adapter's
   equivalent payload shape was confirmed unchanged **statically**
   (comment-only diff) but was not separately re-captured live in this
   pass, consistent with earlier pilots.

## Recommendation

Adopt Prime 0.7.4 as the qualified target. No Second Brain adapter code
change was required. This is an evidence-backed compatibility finding
subject to external review, not a self-certified final promotion.
