# REVIEW_VERDICT.md — Phase K Gate

Skeptical, independent external review of the prior
"PRIME_0_7_4_SECOND_BRAIN_COMPATIBLE — EXTERNAL REVIEW REQUIRED" claim.

| Gate | Result | Evidence |
|---|---|---|
| Exact v0.7.4 identity | PASS | CANDIDATE_IDENTITY.txt — `git rev-parse HEAD` == `git rev-parse v0.7.4` == `af0b8e00b9f704e834787fd321065ca78281f2aa`, freshly cross-checked this pass |
| Candidate isolation | PASS | CANDIDATE_IDENTITY.txt — separate worktree, separate agent dir, no live write path |
| Live v0.7.3 untouched | PASS | LIVE_PRE_HASHES.txt / LIVE_POST_REVIEW_HASHES.txt — identical git-tree-hash + per-file sha256 before and after this entire review |
| Windows patch 1 (bootstrap.ts) | PASS | PATCH_1_CHECK.txt — fresh `git apply --check`/`apply` against a pristine v0.7.4 worktree, exit 0, zero conflicts; STILL_REQUIRED (upstream diff empty) |
| Windows patch 2 (session-lease.ts) | PASS | PATCH_2_CHECK.txt — same method; STILL_REQUIRED |
| Zero Brain adapter changes | PASS | SECOND_BRAIN_DIFF.txt — clean before/after this entire review, zero source diff |
| Python suite | PASS | PYTHON_TESTS.txt — freshly re-run, 1064/1064, exit 0, ruff clean, pyright clean |
| TypeScript suite | PASS | TYPESCRIPT_TESTS.txt — freshly re-run, 560/560, lint clean, typecheck clean |
| AutoInject | PASS (carried forward, not fresh this pass) | INTEGRATION_EVIDENCE.md |
| RTD firing | PASS (carried forward, not fresh this pass) | INTEGRATION_EVIDENCE.md |
| Byte-exact recovery | **PASS (fresh this pass)** | TELEMETRY_EVIDENCE.md — 66,016 bytes, exact sha256 match, independently recomputed |
| VMEM metadata | **PASS (fresh this pass)** | LEDGER_EVIDENCE.md — real toolCallId/artifactRef confirmed via direct SQL query |
| Proactive paging | PASS/PARTIAL — labeled deterministic, not natural (by design) | INTEGRATION_EVIDENCE.md |
| Provider pointer | PASS (carried forward, not fresh this pass) | INTEGRATION_EVIDENCE.md |
| EVICTED reprojection | PASS (carried forward, not fresh this pass) | INTEGRATION_EVIDENCE.md |
| Usage/cache telemetry | PASS (carried forward, not fresh this pass) | INTEGRATION_EVIDENCE.md |
| RLM one-child spawn | **PARTIAL/FAIL this pass** — 3/3 fresh spawn attempts failed at kernel bootstrap (infra, not Brain-code) | ENVIRONMENT.md, INTEGRATION_EVIDENCE.md |
| Compact telemetry | PASS | TELEMETRY_EVIDENCE.md — 382 records independently recomputed, exact match to prior claim |
| Per-session ledger | PASS | LEDGER_EVIDENCE.md — direct SQL query, cross-session isolation confirmed |
| Fault-in | PASS (mechanism only; carried forward, not fresh) — limitation preserved | INTEGRATION_EVIDENCE.md |
| Prime flaky A/B | **NOT independently re-executed this pass** (carried forward only) | PRIME_AB_0.7.3.txt / PRIME_AB_0.7.4.txt |
| Rollback readiness | PASS | ROLLBACK_PROOF.md — fresh apply-check + real `--version` == `0.7.3` executability proof |

## Gate-level conclusion

Every gate that COULD be freshly, independently re-verified within this
review pass's actual working conditions returned PASS, with several
(byte-exact RTD recovery, VMem metadata, both full regression suites,
patch disposition, live-install-untouched, telemetry record count, ledger
cross-session isolation, rollback executability) generating genuinely NEW
evidence this pass, not merely re-citing the prior report.

However, TWO items could not be brought to the same standard of fresh,
independent proof in this specific pass:
1. **RLM one-child spawn** — actively RE-TESTED this pass and found
   FAILING 3/3 times, due to a real, reproducible live-0.7.3
   kernel-bootstrap infrastructure race (documented in full in
   ENVIRONMENT.md). This is not a Prime-0.7.4-candidate defect (the
   failure occurs entirely within the LIVE 0.7.3 daemon's own bootstrap
   path, before candidate code is ever reached), but it is a real,
   currently-reproducible instability in the exact infrastructure that
   would need to host a live 0.7.4 daemon restart.
2. **Prime flaky-test A/B** — not freshly re-executed this pass at all
   (carried forward from the prior pass only); this is the plan's own
   explicitly designated "release-critical regression check" and
   deserves an independent third confirmation before production
   promotion, which this pass did not obtain.

## Phase K decision

**NOT_APPROVED for immediate live promotion this pass.**

This is NOT a finding that Prime 0.7.4 is incompatible with Second
Brain — the evidence, where it could be freshly and independently
obtained, is uniformly strong and consistent with the prior qualification
across three separate reviewing turns now. Rather, this is a deliberate,
conservative decision to withhold promotion until (a) the newly-discovered
live sub-agent kernel-bootstrap instability is understood or at minimum
shown to be transient/resolved, and (b) the Prime flaky-test A/B
regression check receives its own independent, fresh re-execution rather
than remaining carried-forward evidence only. Per the task's own
instruction: "treat any unexplained discrepancy as a reason to stop rather
than rationalize."
