# Phase 9 — AutoInject Cache Correctness

**Build:** c361537 (branch `brain/v2-omp-qualification`), includes the
memory_epoch cache-key fix (see `09a-autoinject-cache-corpus-generation-fix.md`).

All 9 scenarios exercised live against `.worktrees/v2-one-shot` as
`SECOND_BRAIN_HOME`, mode `active`, model `anthropic/claude-sonnet-5`.
Verdicts read directly from `autoinject_shadow_decision.cache_hit` in
real telemetry JSONL (never inferred).

| # | Scenario | Sessions | Result | Verdict |
|---|---|---|---|---|
| 1 | Same project + same task | `/tmp/omp-cache-verify` | turn1 `cache_hit:false` (369ms) -> turn2 `cache_hit:true` (0ms) | PASS |
| 2 | Changed task (same session) | `/tmp/omp-p9-task`, session `...c987...` | both turns `cache_hit:false` (task text differs -> different taskSha256) | PASS |
| 3 | Changed project (fresh sessions) | `/tmp/omp-p9-proj-a` / `-b`, `SECOND_BRAIN_PROJECT=p9-proj-a` vs `p9-proj-b` | session B `cache_hit:false` despite identical task text -> project string is part of the key, no cross-key reuse | PASS |
| 4 | Changed memory corpus (same session, same task) | `/tmp/omp-p9-corpus`, session `...bcba...` | turn1 `cache_hit:false`/`NO_INJECTION`; turn2 (before corpus change) `cache_hit:true`; **turn3 (after `memory add mem-697f82879357`, same task) `cache_hit:false` + `decision:INJECT` with the new memory actually retrieved** | PASS — direct proof of the `memory_epoch` fix |
| 5 | Changed config (`retrieval.toml` mutated mid-session) | `/tmp/omp-p9-config`, session `...e21d...` | turn2 `cache_hit:false` after appending a comment line to `config/retrieval.toml` | PASS |
| 6 | Changed build (`SECOND_BRAIN_RUNTIME_ROOT` set on turn2 only) | `/tmp/omp-p9-build`, session `...5dd9...` | turn2 `cache_hit:false` | PASS |
| 7 | Corrupted cache record (`state/autoinject-emit-cache.json` replaced with invalid JSON) | `/tmp/omp-p9-corrupt` | Session completed normally (exit 0), fresh retrieval computed and correctly injected the sentinel memory, cache file self-healed to valid JSON on next `persistEmitCache` | PASS (fail-open), **P3 note below** |
| 8 | Concurrent access (two `omp` processes against the same `SECOND_BRAIN_HOME` launched within ~15ms of each other) | `/tmp/omp-p9-conc-a` / `-b` | Both sessions completed cleanly; `state/autoinject-emit-cache.json` remained valid JSON afterward (lock-file `wx`-flag write in `persistEmitCache` makes the loser fail closed to "skip persist", never corrupt) | PASS |
| 9 | Interrupted write (SIGKILL mid-session via `hub` process control) | hub-managed process `p9-kill-test`, pid 49688, killed after 17.7s uptime | Cache file byte-identical (same md5, same size) and valid JSON after the kill; combined with code-level proof (`persistEmitCache` writes to a `.pid.timestamp.tmp` file then `renameSync`s it over the target — an OS-atomic rename, so a kill before rename leaves the prior file untouched and a kill after rename has already completed) | PASS |

## P3 note (test 7)

`loadEmitCache`'s corrupt-file branch (`autoinject.ts` — `catch { /* missing/corrupt file -> empty cache (fail open) */ }`) does not emit an `extension_error` or any other telemetry record when the JSON parse fails. Functionally safe — the code falls back to a cold cache and recomputes exactly the same way a cache-miss does, so **no stale or wrong packet is ever served** (Gate 9's actual bar). But it means an operator has no telemetry signal that the cache file was corrupted, only that performance silently reverted to always-recompute. Classified **P3** (observability gap on a derived/rebuildable, performance-only artifact — `state/` is explicitly rebuildable per repo convention); not a release blocker. Recommend adding an `extension_error` emission in that catch block in a follow-up pass, not blocking v2 qualification.

## Gate 9

**PASS.** No stale or foreign AutoInject packet was served in any of the 9 scenarios. Scenario 4 is the strongest evidence: an identical task in an identical session correctly flipped from cache-hit to a fresh, correctly-injected result the instant the underlying memory corpus changed — this is the exact defect this campaign found and fixed in `brainstem/prime-extension/src/autoinject.ts` (`corpusGeneration()` now keyed on `brain_meta.memory_epoch` via `node:sqlite`, not whole-DB mtime).
