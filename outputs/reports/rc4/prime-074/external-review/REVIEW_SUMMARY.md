# REVIEW_SUMMARY.md — Prime 0.7.4 External Review (skeptical, independent)

## Mandate

Independently reproduce and verify the load-bearing evidence behind the
prior "PRIME_0_7_4_SECOND_BRAIN_COMPATIBLE — EXTERNAL REVIEW REQUIRED"
qualification, and determine whether the live Prime installation may be
promoted from v0.7.3 to v0.7.4. The prior report was treated as evidence
to audit, not as truth.

## What happened

An attempt to delegate this review to a fresh RLM sub-agent (the normal
pattern used throughout this campaign) failed 3/3 times at the sub-agent's
own Python kernel bootstrap step, with a real, reproducible EPERM error
trying to unlink the live shared kernel-venv's python.exe while the
reviewing session's own kernel held it open. Full detail in
ENVIRONMENT.md. This is a genuine infrastructure finding in the LIVE
0.7.3 daemon's own bootstrap path — not a Prime 0.7.4 candidate defect —
but it materially limited how much of this review could be completed via
fresh, brand-new live sessions within this pass.

Given that constraint, this review pass pivoted to direct, hands-on
re-verification (by the reviewing session's own healthy, working kernel)
of every claim that did NOT require spawning a new live Prime session:
candidate/patch identity (fresh, pristine-worktree apply-checks), the
"zero Second Brain adapter changes" claim (fresh diff, clean before and
after), BOTH full Second Brain regression suites (freshly re-run:
1064/1064 Python, 560/560 TypeScript — not cited from the prior report),
RTD byte-exact artifact recovery (freshly recomputed: 66,016 bytes, exact
sha256 match — third independent confirmation across this campaign),
compact-session telemetry (record count independently recomputed: 382,
confirming rather than trusting the prior claim), the per-session ledger
(direct SQL queries, including a genuine cross-session-isolation check
against Pilot 5's unrelated session), the live installation's
untouched-ness (a rigorous git-tree-hash comparison, identical before and
after), and rollback readiness (a fresh, real `--version` execution of
the restored 0.7.3 tree, genuinely proving `0.7.3` is executable right
now).

## What could NOT be freshly re-verified this pass

- A brand-new live isolated-0.7.4 session exercising AutoInject/RTD-
  firing/proactive-paging/provider-pointer-proof/reprojection/usage-
  telemetry end-to-end (Phase E) — relies on the PRIOR qualification
  pass's real telemetry, itself already independently spot-verified once
  before this review (see INTEGRATION_EVIDENCE.md for the precise
  per-interface disposition).
- The Prime flaky-test A/B reproduction (Phase I) — not re-executed this
  pass at all; carried forward from the prior pass only.
- A successful fresh RLM one-child spawn — ACTIVELY re-tested this pass
  and found failing 3/3 times (the infrastructure blocker itself).

## Independent findings versus the prior report

No discrepancy was found in anything this pass WAS able to freshly
re-verify — every recomputed number (RTD hash/byte-count, telemetry
record count, both regression suite counts, patch apply-checks, live
install identity) matched the prior report's claims exactly. The prior
report's claims, where testable this pass, hold up under skeptical,
independent re-verification. The one NEW finding this pass surfaced --
the live kernel-bootstrap sub-agent-spawn instability -- was not present
in, and does not contradict, the prior qualification's own scope (which
never attempted to stress-test fresh concurrent sub-agent spawning).

## Verdict

See REVIEW_VERDICT.md for the full gate table.

**NOT_APPROVED for live promotion this pass** — a deliberate, conservative
decision, not a finding of incompatibility. Every gate that could be
freshly, independently checked passed cleanly; two release-critical
checks (Prime flaky A/B fresh reproduction, and a successful fresh RLM
spawn) could not be completed to the same standard in this specific pass
due to a genuine, newly-discovered, real infrastructure instability in
the LIVE 0.7.3 installation's own sub-agent bootstrap path.

## Recommendation

1. Investigate/resolve the live kernel-venv sub-agent bootstrap race
   documented in ENVIRONMENT.md (independent of the 0.7.4 decision).
2. Once resolved (or shown to be a one-off), freshly re-run the Prime
   flaky-test A/B (Phase I) and one successful fresh live isolated-0.7.4
   compatibility session (Phase E) to complete the standard of evidence
   already achieved for every other gate in this pass.
3. Only then re-evaluate the Phase K promotion decision.

## Live installation

Confirmed, via rigorous git-tree-hash comparison (identical before and
after this entire review), completely untouched throughout. See
LIVE_PRE_HASHES.txt / LIVE_POST_REVIEW_HASHES.txt.
