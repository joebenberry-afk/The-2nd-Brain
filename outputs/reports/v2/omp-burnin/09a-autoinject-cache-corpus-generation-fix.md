# Defect: AutoInject cross-process emit cache never hit

**Build:** 4a93dcb (branch `brain/v2-omp-qualification`)
**Found during:** live OMP session testing of `state/autoinject-emit-cache.json` reuse.

## Defect

`corpusGeneration()` in `brainstem/prime-extension/src/autoinject.ts` fingerprinted
the cache-relevant "has memory changed" signal as the mtime of the whole
`db/brain.sqlite` file. That file is rewritten by the ledger, ledger-mirror,
telemetry, and heartbeat paths on nearly every OMP turn, none of which touch
canonical memory. Result: `corpusGeneration` changed on almost every call,
so `emitKey()` never matched a prior entry and `cache_hit` was `false` on
every repeated identical task within a resumed session, live-confirmed via
`/tmp/omp-cache-test-2` and `/tmp/omp-cache-verify`: two turns issuing the
byte-identical shadow task in the same `--continue`d session both spawned
the Python CLI and both recorded `"cache_hit":false"`.

## Root cause

Wrong invalidation granularity: file-mtime-of-everything instead of a
dedicated "did canonical memory change" signal.

## Fix

`src/second_brain/db.py` already maintains exactly the right signal:
`brain_meta.memory_epoch`, bumped only by `bump_memory_epoch()` at the five
call sites where memory content actually changes (`reconsolidation.py`,
`semantic.py` add/purge paths). `corpusGeneration()` now reads that single
row directly via `node:sqlite`'s `DatabaseSync` (readonly), which is a
native module in both Bun (production runtime) and Node (dev/typecheck/
vitest tooling) — no new dependency, no Python spawn on the cache-hit path.

## Verification

Live OMP session, `--session-dir /tmp/omp-cache-verify`, identical task
`"reply with exactly: VERIFY_A"` issued twice via `--continue`:

- Turn 1: `autoinject_shadow_decision` — `cache_hit:false`, `latency_ms:369`
  (real spawn).
- Turn 2: `autoinject_shadow_decision` — `cache_hit:true`, `latency_ms:0`
  (no spawn) — session
  `2026-09-04T17-34-20-072Z_01a06d7c-55a8-71e7-9513-863269bc2480`, telemetry
  line 26.

Regression scope (`brainstem/prime-extension`):
- `npm run typecheck` — clean.
- `npm run lint` — 9 pre-existing errors unchanged (unrelated test files);
  zero new errors (verified against `git stash` baseline).
- `npx vitest run` — 637 passed / 18 failed, identical failing test set and
  count on this change and on the unmodified baseline (verified via
  `git stash`); all 18 are pre-existing Windows-timing/mocking flakes in
  `autoinject.test.ts`, `config.test.ts`, `ledger-mirror.test.ts`,
  `wiring.test.ts`, unrelated to `corpusGeneration`.
