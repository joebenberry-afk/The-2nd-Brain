# Phase 11-16 — 4-Worker Hub Proof & Dedup Proof: External Blocker

## What happened

Both the 4-worker explicit-`hub`-poll live proof and the async-result/hub
dedup live proof require spawning NEW real `task` workers against this
worktree's `SECOND_BRAIN_HOME`. Every attempt after the successful 8-worker
run (`10-live-8worker-autodelivery-proof.md`) returned:

```text
[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED
```

from the `task` spawn tool call itself — before any worker could be
created, and the block applies to `hub` tool calls too (verified: a
follow-up `hub jobs` call in the same blocked session returned the identical
hard-cap line, so polling is not usable as a workaround either).

## Root cause (pre-existing, out of scope for this repair)

`brainstem/prime-extension/src/budget-bridge.ts` calls
`second_brain governor check-budget`, which calls
`governor.check_budget()` -> `_descendant_total_tokens()`
(`src/second_brain/governor.py`). This function scans **every**
`state/sessions/*/ledger.sqlite` under `SECOND_BRAIN_HOME` for rows whose
`root_parent_session_id` matches the current session's computed root, and
sums `total_tokens` across all matches. Measured directly:

| Session (brand new, never previously used) | `used` reported | `cap` (`worker_tokens`) |
|---|---:|---:|
| Before the successful 8-worker run | 510,751 | 120,000 |
| After the successful 8-worker run | 755,888 | 120,000 |

Both figures are far above the `[budgets] worker_tokens = 120000` cap in
`config/governor.toml`, **for a session that had not yet spawned a single
worker of its own** — confirmed via `second_brain governor check-budget
--session <brand-new-id> --role worker --json` run directly, independent of
any OMP process. `used` grew by exactly the token volume of the prior
successful 8-worker batch, which strongly suggests `_descendant_total_tokens`
is not correctly scoping to descendants of the *current* session root, and
is instead accumulating some or all historical worker-session token usage
under this `SECOND_BRAIN_HOME` regardless of which top-level session spawned
them. `SECOND_BRAIN_HOME` is unchanged across all live-proof attempts in
this repair (only the OMP `--profile` changed, which does not isolate
Brain-side ledger state — profiles isolate OMP's own
`agent/{extensions,sessions}` tree, not this repository's
`state/sessions/*/ledger.sqlite`).

This is a real defect in `governor.py`/`budget-bridge.ts` — separate,
pre-existing code this repair's two-defect scope
(`P1-OMP-WORKER-AUTODELIVERY`, `P1-OMP-INSTALLER-DEFAULT`) never touches.
Per `00-starting-state.md`'s explicit scope boundary ("Two P1 defects
only... No broad re-implementation"), it is not fixed here. Editing
`config/governor.toml` to raise the cap, or hand-clearing
`state/sessions/*/ledger.sqlite` (derived data), would be an unreviewed
scope-expanding change to shared, unrelated infrastructure — not performed.

## Disposition

**Documented infeasibility**, consistent with this same qualification
campaign's own precedent for external blockers
(`22-sustained-burn-in/SUSTAINED_BURN_IN.md`'s HTTP 429 provider
rate-limit). Live re-verification of the 4-worker explicit-`hub`-poll path
and of dedup-under-race could not be completed against this
`SECOND_BRAIN_HOME` once its ledger crossed the (apparently
mis-scoped) budget threshold.

## Why this does not block the P1 release gate

1. **The `hub` explicit-poll path is unchanged by this repair** except a
   pure refactor (`pendingWorkerJobs.get`+`.delete` extracted into the
   shared `takePendingWorkerJob` helper both paths now call) — behaviorally
   identical, proven by the unit suite:
   `03-worker-regression-results.md` — 12/12 pass, including the 3
   pre-existing unmodified hub-path tests ("completed via hub, failed via
   hub, no double-report on repeated hub polls, running job produces no
   telemetry").
2. **The `hub` explicit-poll path already has extensive real live
   coverage** from this same qualification campaign, predating this repair:
   `deployment-alignment/09-worker-result-undercount-defect.md` and
   `10-worker-coverage.md` record real 20-worker and 5-worker batches
   captured via explicit `hub jobs` polling in a tight loop — the exact
   `P1-OMP-WORKER-AUTODELIVERY` defect this repair fixes was found precisely
   *because* that pre-existing hub-path coverage worked correctly and the
   auto-delivery path did not.
3. **Dedup is fully covered by 2 unit regression tests** exercising both
   race orders exhaustively (`03-worker-regression-results.md`: "hub
   observes first, then async-result" and "async-result observes first,
   then hub polls again" — both assert exactly 1 telemetry record and 1
   result-runner call). The dedup guard (`takePendingWorkerJob`'s
   read-and-delete atomicity plus `reportedWorkerTaskIds`) is pure,
   synchronous, in-memory logic with no live-environment dependency; a
   passing unit proof is equivalent to a live proof for this specific
   mechanism, unlike the auto-delivery path itself, which depended on
   confirming OMP's real `message_end` event shape (already independently
   confirmed live in `09-worker-result-undercount-defect.md`'s raw session
   JSON *before* this repair, and again in `10-live-8worker-autodelivery-proof.md`
   *after* it).
