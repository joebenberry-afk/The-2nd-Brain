# RC4 Runtime Implementation Checkpoint

`RC4_RUNTIME_IMPLEMENTATION_COMPLETE — REAL PILOT REQUIRED`

## Branch / HEAD

- Branch: `brain/v1-rc4-genuine-proof`
- Base: `7842b68e15a95799748404e442714aa6dc580976` (RC3)
- HEAD: `11650b97342797ddb1d9cc7336239003965b6e45`
- Pushed to `origin/brain/v1-rc4-genuine-proof`.

## Exact runtime/test files changed (base → HEAD)

```
brainstem/prime-extension/src/config.ts             |  61 ++++
brainstem/prime-extension/src/index.ts              | 109 +++++-
brainstem/prime-extension/src/sensors.ts            |  63 ++++
brainstem/prime-extension/src/vmem.ts               | 161 +++++++++ (new)
brainstem/prime-extension/tests/config.test.ts      |  76 +++++
brainstem/prime-extension/tests/ledger-mirror.test.ts | 115 +++++++
brainstem/prime-extension/tests/vmem.test.ts        | 117 +++++++ (new)
brainstem/prime-extension/tests/wiring.test.ts      |  36 ++
brainstem/telemetry/SCHEMA.md                       |  28 ++
config/context.toml                                 |  13 +
src/second_brain/action_cache.py                    |  88 +++--
src/second_brain/cli.py                             | 366 +++++++++++++++++++++
src/second_brain/defaults/config/context.toml       |   9 +
src/second_brain/fresh_verifier.py                  | 139 ++++++++ (new)
tests/test_action_cache_safety_proof.py             |  69 ++++
tests/test_cli.py                                   | 187 +++++++++++
tests/test_fresh_verifier.py                        |  98 ++++++ (new)

17 files changed, 1709 insertions(+), 26 deletions(-)
```

Nine commits, one per phase: `a415fb6` (R0 quarantine + R1 callgraph),
`af9db0e` (R4 predicate fix), `c0f11e3` (R2 decision), `c5ee6f9` (R3 VMem),
`314b4fd` (R5 action-cache search + 2 real bugs fixed), `ba7f048` (R6 tool
surface), `d60ba27` (R7 worker-plane), `566fc92` (R8 verification, no
code), `11650b9` (R9 fresh-verifier record).

## Prime hooks now capable of host mutation

Ground truth from `brainstem/prime-extension/types/prime.d.ts` (the
extension's ambient type surface, "verified against the installed
runtime"), cross-checked against `index.ts`:

| Hook | Mutation-capable? | Status this pass |
|---|---|---|
| `before_agent_start` | yes (`{systemPrompt}`) | unchanged, already live (AutoInject/driver contract/lean kernel/recall) |
| `tool_call` | yes, but **only** `{block, reason}` — no result field | unchanged; confirmed (R1) it cannot return cached content, so Action Cache bypass was built one layer below it instead (R5) |
| `tool_result` | yes (`{content, details, isError}`) | unchanged, already live (RTD) |
| `context` | yes (`{messages}`) — **was structurally unreachable** | **fixed (R3):** moved off `wire()`/`safeHandler()` (which always returned `void`, discarding any patch) onto direct `pi.on` registration. Still returns `undefined` today — capability unlocked, no mutation content yet (message shape unknown, see below) |
| `session_before_compact` | yes (`{cancel}`) | unchanged, already live (ledger checkpoint durability barrier); R3 added advisory VMem bookkeeping alongside it (never cancels on VMem failure) |
| `session_compact` | no result consumed | unchanged; R3 added fire-and-forget VMem hot-context telemetry |
| `session_start`, `turn_start`, `turn_end`, `agent_end`, `session_shutdown`, `before_provider_request`, `after_provider_response`, `message_end` | measurement-only by design | unchanged; R6 added `pi.getAllTools()`/`getActiveTools()` read at `session_start` |
| *(no spawn/subagent event exists at all)* | n/a | confirmed exhaustively (R1): `PrimeEvent` union has no such member. R7 enforces the worker ceiling in a Brain-owned CLI layer instead |

## What is actually integrated vs. capability-limited

**Live / integrated this pass:**
- Action Cache predicate validation fails closed on any unrecognized
  predicate (was `!= "reject_always"`, R4).
- `context` handler can legally return a host mutation (structural fix,
  R3) — currently a no-op by design, not by bug.
- VMem compaction-boundary bookkeeping (`compact-prep`/`hot-context`) runs
  against real Prime lifecycle events when `[vmem] enabled=true` (default
  `false`).
- `second_brain action-cache search` — real execution bypass on a cache
  hit, for any caller willing to invoke it (not yet Prime's own tool
  calls).
- `second_brain worker-plane spawn|complete|status` — real concurrency
  ceiling enforcement, for any caller willing to invoke it.
- `pi.getAllTools()`/`getActiveTools()` captured into telemetry at
  `session_start`.
- `second_brain fresh-verifier record` — parses a real verdict from a raw
  response file that must already exist.

**Confirmed host-capability-limited (not worked around):**
- Action Cache cannot bypass Prime's own `tool_call` execution —
  `ToolCallEventResult` has no result field.
- Worker/subagent spawn has no Prime extension hook at all.

**Confirmed data-limited, not host-limited (documented, not fabricated):**
- `context` event: the API can mutate messages, but `event.messages` is
  `unknown[]` everywhere in this codebase — no live session has ever
  captured Prime's actual message shape, so no replacement content is
  generated yet.
- `setActiveTools`: the API is real, but Tool Working Set's Python catalog
  (`view_file`, `run_command`, `git_commit_and_sync`, ...) doesn't match
  Prime's real tool names (`bash`/`edit`/`websearch`), and `setActiveTools`
  takes a *replacement* list — calling it with fictional names risks
  stripping real tool exposure. The new `prime_tool_surface` telemetry
  (R6) is what a live session must produce before this can be built
  honestly.

**Verified, not rebuilt (no defect found):**
- RTD already performs the full preserve→verify→reduce→replace→record
  path at the real `tool_result` hook (R2).
- Hybrid Retrieval cascade (`_CASCADE.retrieve()`) is genuinely the
  primary path inside `prepare_injection()` (R8). One capability gap
  found and documented, not fixed: Tier 3/4 dense vector fallback has no
  implementation anywhere in the repo.

## Tests / typecheck / lint (final run, this session)

```
Python:
  .venv\Scripts\python -m ruff check src tests      → All checks passed
  .venv\Scripts\python -m pyright src                → 0 errors, 0 warnings, 0 informations
  .venv\Scripts\python -m pytest -q                  → full suite, exit 0, no failures

TypeScript (brainstem/prime-extension):
  npx eslint .        → clean
  npx tsc --noEmit    → clean
  npx vitest run      → 16 test files, 397 passed
```

Per-phase counts and the two real bugs found by testing (not asserted
from code presence) are in each phase's own report (05, 07 in
particular).

## Exact procedure for the first real Prime pilot

This session cannot execute this — it requires an actual Prime Agent
process. Recorded here as the literal next step, not performed.

1. **Environment.** Set `SECOND_BRAIN_HOME` and `SECOND_BRAIN_OBSERVABILITY`
   (if previously disabled) *before* starting `prime-agent`, so its daemon
   inherits them (documented gotcha in `SCHEMA.md`: the daemon pins its
   startup environment).
2. **Build the extension.** From `brainstem/prime-extension/`: confirm
   `npx tsc --noEmit` and `npx vitest run` are clean (already true at this
   HEAD), then let Prime load the extension per its normal installation
   path (no separate build step beyond what Prime's `jiti` loader needs —
   this repo's extension is loaded as TS source, per the ambient-types
   header comment).
3. **Enable the phases under test.** In `<home>/config/context.toml`:
   - `[vmem] enabled = true` — to exercise R3's compact-prep/hot-context
     calls for real.
   - `[rtd] enabled = true` if RTD substitution proof is also wanted
     (already live, orthogonal to this pass).
4. **Run one substantive real task** in that Prime session: enough tool
   calls to exercise `tool_call`/`tool_result`, at least one compaction
   (or force one to exercise `session_before_compact`/`session_compact`
   and the new VMem bookkeeping), and let `session_start` fire naturally.
5. **Capture, don't summarize:**
   - The real `<home>/telemetry/agent-performance/<session>.jsonl` file
     — this is the primary evidence artifact; see §7 below for what it
     should contain.
   - The real Prime session transcript/session file
     (`ctx.sessionManager.getSessionFile()` path, mirrored into telemetry
     as a `host_artifact_ref` record).
   - Provider/host session ID if Prime exposes one (record `{"available":
     false, "reason": ...}` if not — never invent one, per plan Rule B).
6. **Manually inspect** the captured JSONL before drawing any conclusion
   — per this session's own operating rule (Rule F / Claude-specific
   discipline): confirm the records actually show what's claimed, don't
   infer from the fact that code exists.
7. **Only then**, if the pilot evidence is genuine, proceed to the larger
   campaign work (still out of scope until the user authorizes paid
   spend).

For the fresh-verifier mechanism specifically (R9): run `second_brain
verify build-brief <session_id> <repo>` for a real completed task, hand
the resulting brief to a genuinely fresh session (separate context, no
implementation transcript) on whatever harness is chosen, capture its raw
output verbatim to a file, then run `second_brain fresh-verifier record
--out DIR --prompt-file <brief> --raw-response <captured file> --provider
--model --host [--session-id] [--input-tokens] [--output-tokens]` with
the real values the host reports.

## Expected evidence files a real pilot will naturally produce

No file below should be created by hand; each is a natural byproduct of
step 4–5 above, written by the extension/CLI code that already exists at
this HEAD:

- `<home>/telemetry/agent-performance/<session-stem>.jsonl` — every
  lifecycle event's record, including (if `[vmem] enabled=true` and a
  compaction actually happens) real `vmem_compact_prep` and
  `vmem_hot_context` records with real `evicted_at_compaction`/
  `resident_count`/etc. values, not zeros; and (always, at
  `session_start`, if the host exposes the API) a real
  `prime_tool_surface` record with Prime's actual tool names — the first
  time this codebase will have ever seen them.
- `<home>/telemetry/ledger/...` (or wherever `ledger segment
  checkpoint`/`open` write) — real checkpoint/segment-rollover state from
  the actual compaction, via `runLedgerCheckpoint`/
  `runLedgerSegmentRollover`.
- `<home>/state/cache/action_cache.sqlite` — only if something is
  actually made to call `second_brain action-cache search` during the
  pilot (Prime itself won't call it automatically yet — R5's honest
  finding).
- `<home>/state/repo_intel/repo_intel.sqlite` — only if something calls
  `second_brain worker-plane spawn` during the pilot (same caveat as
  above — R7's honest finding).
- A `second_brain verify build-brief` output file
  (`outputs/verification/<session-id>.md`) and a `fresh-verifier record`
  evidence bundle (`raw-response.txt`, `metadata.json`, `usage.json`,
  `verdict.json`) — only if the fresh-verifier procedure above is
  actually run.

Any of these files that do *not* appear naturally from a real pilot run
must be reported as missing/blocked, not generated to fill the gap — per
this branch's entire operating discipline.
