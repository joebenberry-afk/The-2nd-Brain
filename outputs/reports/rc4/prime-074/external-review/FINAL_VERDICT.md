# FINAL_VERDICT.md

## PRIME_0_7_4_SECOND_BRAIN_QUALIFIED_NOT_PROMOTED

This is a deliberate decision to withhold live promotion, not a finding
that Prime 0.7.4 is incompatible with Second Brain. See
REVIEW_VERDICT.md / REVIEW_SUMMARY.md for the full gate-by-gate reasoning.

## Identity

- Live Prime before (and after, unchanged): v0.7.3,
  61131b2d195ba7a67a4ce8ac60bb10cecae07b67, tree hash
  2722ef8eaa6ebf71b492564c6ffcfd7dd54e4219 (git-tree-hash comparison
  identical before/after this entire review).
- Candidate Prime: v0.7.4, af0b8e00b9f704e834787fd321065ca78281f2aa
  (independently cross-checked: `git rev-parse v0.7.4` ==
  `git rev-parse HEAD` in the candidate worktree).
- Live Prime after: UNCHANGED (v0.7.3) — no promotion was performed.
- Second Brain commit: b735c9c91b1d76ee5f4b3987be41da1c0eafddcf, branch
  brain/v1-rc4-prime-074-compat (plus this review's own evidence commit
  on top, see below).
- Windows patch hashes: bootstrap.ts
  f0ccf80567a35b51baed769d79df00a70cf444400f5e5251a75037c498d44c23,
  session-lease.ts
  b128dd81f703d65fd1b324d600e1937e9378919dfe5f0725e676cdb155998ea3
  (identical on both the live install and the patched candidate).

## Test results

- Python: 1064/1064 passed, freshly re-run this pass, exit 0. ruff
  clean. pyright clean.
- TypeScript: 560/560 passed, freshly re-run this pass. lint clean.
  typecheck clean.
- Prime A/B: NOT freshly re-executed this pass (carried forward from an
  earlier turn's real run: 316f/3867p/53s on 0.7.3, 318f/3886p/55s on
  0.7.4, matching failure signatures) — see PRIME_AB_0.7.3.txt /
  PRIME_AB_0.7.4.txt for the explicit limitation and recommendation to
  re-run fresh before promotion.
- Post-upgrade smoke: N/A — no upgrade was performed.

## Integration surfaces

- AutoInject, RTD firing, proactive paging, provider pointer proof,
  EVICTED reprojection, usage/cache telemetry: PASS, carried forward from
  the prior qualification pass's real evidence (itself independently
  spot-verified once already before this review); NOT freshly re-run in
  THIS pass due to the sub-agent spawn infrastructure blocker.
- RTD byte-exact recovery: PASS, freshly recomputed THIS pass (66,016
  bytes, exact sha256 match).
- RTD VMem metadata: PASS, freshly queried THIS pass via direct SQL
  (real toolCallId/artifactRef, not `{}`).
- Recovery/fault-in: PASS at the mechanism level only (HOST_INTEGRATION
  deterministic check, carried forward); genuine model-triggered fault-in
  remains unestablished for 0.7.4 specifically.
- RLM: PARTIAL/FAIL this pass — 3/3 fresh spawn attempts failed at the
  live 0.7.3 daemon's own kernel-bootstrap step (infrastructure issue,
  not a Brain-code or 0.7.4-candidate defect; documented in full in
  ENVIRONMENT.md).

## Limitations (preserved, not overclaimed)

1. Genuine naturally model-triggered fault-in was not established by the
   deterministic HOST_INTEGRATION proof alone (same limitation as the
   prior report; not disproven or strengthened by this review).
2. Fresh natural long-session compaction was not exercised during this
   qualification or this review.
3. RLM qualification remains single-child scope where it succeeded at
   all; this review pass's own 3 fresh spawn attempts FAILED outright due
   to a real infrastructure blocker, which is a stronger caveat than the
   prior report carried.
4. **New limitation surfaced by this review**: a real, reproducible
   Windows kernel-venv sub-agent bootstrap race exists in the live 0.7.3
   installation's own infrastructure (see ENVIRONMENT.md) — unrelated to
   the 0.7.4 candidate itself, but a legitimate operational-stability
   concern that should be resolved (or understood as transient) before
   any live daemon restart/upgrade is attempted.
5. The Prime flaky-test A/B (a release-critical regression check per the
   task's own framing) was not freshly re-executed in this specific
   review pass.

## Rollback state

- Prepared: YES (unchanged procedure from the prior qualification,
  re-documented in ROLLBACK_PROOF.md).
- Independently tested: YES, THIS pass — fresh `git apply --check`
  against the pristine throwaway v0.7.3 worktree (exit 0), plus a real
  `--version` execution proving the restored tree is genuinely
  executable (`0.7.3`).
- Used: NO — no promotion was attempted, so no rollback was needed.

## Final recommendation

Do not promote Prime 0.7.4 to the live installation yet. The technical
compatibility evidence is strong and has now been independently
cross-verified across three separate reviewing passes in this campaign
with zero discrepancies found. However, this specific review pass could
not complete two release-critical checks (a fresh Prime flaky-test A/B,
and a successful fresh RLM sub-agent spawn) to the same standard as
everything else, because of a real, newly-discovered infrastructure
instability in the live installation's own kernel-bootstrap path. Resolve
or characterize that instability first, then complete those two remaining
checks fresh, then re-evaluate promotion. Do not proceed to Brain-OFF/
Brain-ON economics regardless of this decision.
