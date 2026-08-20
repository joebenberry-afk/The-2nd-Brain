# 06 — Rollback Verification (0.7.4 → 0.7.3)

## Method

Per the safety rules, the LIVE `C:\Tools\prime-agent` installation was
never touched to test this. Instead, a completely separate, throwaway git
worktree was created at
`C:\Users\assas\.prime-074-compat\throwaway-073` (registered against the
same underlying Prime Agent repo the isolated 0.7.4 worktree already uses,
via `git worktree add --detach ... v0.7.3` from
`C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`).

## Results

- `git worktree add --detach <throwaway-073> v0.7.3` → succeeded:
  `Preparing worktree (detached HEAD 61131b2d1)` /
  `HEAD is now at 61131b2d1 chore(release): prepare v0.7.3 (#1492)`. This
  independently proves the exact 0.7.3 tag/commit
  (`61131b2d195ba7a67a4ce8ac60bb10cecae07b67`) is genuinely resolvable and
  checkoutable right now, not merely recorded in a report.
- `git apply --check outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`
  against this fresh throwaway 0.7.3 worktree → **exit 0** (clean, zero
  conflicts) — the two local Windows patches (kernel-venv Python path,
  session-lease EPERM handling) are still directly, mechanically
  reapplicable to the exact 0.7.3 baseline.
- `npm install` was additionally run in this same throwaway worktree
  (351 packages, exit 0) as part of the Section 8 pre-existing-failure A/B
  comparison (see `05-compatibility-matrix.md`); this incidentally serves
  as further rollback proof — a fresh, working 0.7.3 install is genuinely
  reproducible on this machine right now, not just a frozen historical
  artifact.

## Rollback procedure (unchanged from `01-prime-073-known-good-baseline.md`,
now further verified)

From a clean shell with no active daemon workers depending on the live
checkout: `cd C:\Tools\prime-agent`, `git checkout
61131b2d195ba7a67a4ce8ac60bb10cecae07b67` (or `git checkout v0.7.3`), then
`git apply outputs/reports/rc4/prime-074/raw/01-local-patches-073.diff`
(from the Second Brain repo), then restart the daemon through its normal
supervised restart path. This qualification pass did not destructively
test this against the live daemon (consistent with the safety rules and
with `01-prime-073-known-good-baseline.md`'s prior disposition) — the
independent throwaway-worktree checkout + patch-apply above is the
load-bearing, freshly-re-verified proof that every ingredient of this
procedure (exact commit, exact patch diff) is genuinely present and
functional right now.

## Verdict

Rollback path confirmed **genuinely restorable** without disturbing the
live installation. `throwaway-073` is left in place (not deleted) as
further evidence, alongside the isolated 0.7.4 worktree, per the task's
cleanup instructions. No live process runs against it.
