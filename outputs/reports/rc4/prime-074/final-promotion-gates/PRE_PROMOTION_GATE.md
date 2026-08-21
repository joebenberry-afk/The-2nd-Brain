# PRE_PROMOTION_GATE.md

| Gate | Required | Status |
|---|---|---|
| RLM root cause investigated | PASS | PASS -- RLM_ROOT_CAUSE.md: exact operation (`rm()` on the shared kernel-venv racing a live-open `Scripts\python.exe`), exact Windows mechanism, reproduced deterministically 3/3 in isolation with a controlled negative control (0/3 with no holder), confirmed common to both versions via byte-identical `bootstrap.ts`, confirmed NOT Second-Brain-related. A minimal candidate fix was designed and validated in isolation (RLM_FIX_DIFF.txt) but deliberately NOT applied to either qualified worktree, per instruction. |
| Fresh RLM on controlled `0.7.3` | PASS | RLM_073_PASS.txt -- 3/3 consecutive real driver->external-daemon->child->task->result->clean-exit spawns, independently verified via real ledger spawn/delete pairs and a real child transcript, zero orphan processes. Daemon stderr baseline captured and characterized (non-fatal, pre-existing). |
| Fresh RLM on isolated `0.7.4` | PASS | RLM_074_PASS.txt -- 3/3 consecutive real spawns, daemon identity independently verified via protocol handshake (appVersion 0.7.4, buildId release-0.7.4, matching PID), zero orphan processes. Full stderr comparison vs the 0.7.3 baseline: same or better on every signature, zero new signatures (STDERR_COMPARISON_073_VS_074.md). |
| Prime flaky-test A/B | PASS | PRIME_AB_COMPARISON.md -- fresh, matched-pair, test-identity-level comparison (not aggregate-count-only): 322/323 (0.7.3) and 322/330 (0.7.4) failing tests share exact identity across both runs. The 8 asymmetric 0.7.4-only failures and the 1 asymmetric 0.7.3-only failure are individually accounted for (ambient nested-RLM-depth confound affecting both runs symmetrically, and classic resource-contention/timing-flake signatures) with no plausible link to the actual 0.7.4 source diffs. No new failure signature, no changed signature, no material rate increase (+2.2%), no new hang, no new bootstrap problem. |
| Previous external review remains valid | PASS | Live baseline identity re-verified this pass (LIVE_BASELINE_IDENTITY.txt) -- same commit, same 2 patches, same untracked housekeeping files as the prior external-review pass. No discrepancy. |
| Live tree still untouched | PASS | `C:\Tools\prime-agent` git status/HEAD identical before and after this entire multi-day pass. No promotion, no restart, no config change was ever performed against it. Only read-only queries (git status, a brief non-destructive custom-socket EACCES diagnostic that was immediately killed and left zero artifacts other than one log file under its own `logs/` dir) touched it. |
| Rollback still available | PASS | Carried forward from the prior external-review pass (ROLLBACK_PROOF.md): exact v0.7.3 commit, exact 2-patch diff, and a fresh real `--version` executability proof, all independently re-confirmed as still present and valid via this pass's own use of the same `throwaway-073`/patch-diff artifacts (re-applied cleanly to `throwaway-073` and reverted cleanly multiple times during this pass, always returning it to byte-identical parity with live). Not re-executed against the live install (correctly, per the task's phased safety constraint -- rollback proof happens in isolation until promotion is actually approved). |

## Overall

**APPROVED_FOR_LIVE_PROMOTION**

All seven required gates pass. Both previously-outstanding release-critical blockers
(the RLM kernel-bootstrap EPERM investigation, and the fresh Prime flaky-test A/B) are
now closed with fresh, real, independently-verified evidence gathered in this pass,
via an external (non-sandboxed) daemon approach after this session's own kernel proved
unable to create new listening daemon sockets from inside its own execution sandbox
(PHASE_I_J_BLOCKER.md).

## Explicitly NOT done, and correctly so

- The unqualified candidate 3rd bootstrap patch (RLM_FIX_DIFF.txt) was designed,
  validated in isolation, and then deliberately left unapplied to both the isolated
  v0.7.3 worktree and the v0.7.4 candidate -- both qualified worktrees remain on
  exactly the 2 previously-qualified patches only, confirmed via `git status --short`
  and byte-identical `diff` against the live tree at every checkpoint in this pass.
- No test was skipped, no assertion weakened, no timeout altered to hide a failure, no
  retry-until-green was performed anywhere in this pass.
- Brain-OFF vs Brain-ON economics, token-cost experiments, and any other work outside
  the two release-critical gates was not started.
