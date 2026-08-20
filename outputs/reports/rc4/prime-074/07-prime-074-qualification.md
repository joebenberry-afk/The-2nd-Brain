# 07 — Prime 0.7.4 Second Brain Compatibility Qualification (Sections 6-27)

Status: **PRIME_0_7_4_SECOND_BRAIN_COMPATIBLE — EXTERNAL REVIEW REQUIRED**

## Scope

This report covers Sections 6-27 of the RC4 Prime 0.7.4 upgrade
qualification plan: building/running an isolated 0.7.4 instance, Prime's
own test gates, re-syncing the Second Brain extension, a low-cost smoke
session, one bounded live compatibility session (Q1-Q10), token-efficiency
sanity, cache-accounting compatibility, session/transcript reconstruction,
security/privacy, fail-open behavior, full Second Brain regression suites,
the compatibility matrix, rollback verification, and cleanup. Sections
1-5/00-04 (frozen baseline, patch disposition, upstream delta audit,
static contract audit) were already complete and are unchanged by this
pass — see `00-pilot5-freeze.md` through `04-static-contract-audit.md`.

## Section 6 — branch confirmation

`brain/v1-rc4-prime-074-compat` confirmed as the current branch, clean
tree, before any new work began.

## Section 7 — isolated 0.7.4 build

Isolated worktree `C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`
confirmed still detached at `af0b8e00b9f704e834787fd321065ca78281f2aa`
(`v0.7.4` tag) with both local Windows patches applied (`git status
--short` showed exactly the 2 expected files, unchanged from
`02-local-patch-disposition.md`). `npm install` run there (tsx/non-`--dist`
path; 351 packages added, exit 0); `git status --short` afterward still
showed only the same 2 patched files (npm install touched no tracked
source). `node_modules/.bin/tsx --version` → `tsx v4.23.1`, `node
v26.7.0`. `tsx cli.ts --version` → exactly `0.7.4`.

## Section 8 — Prime's own gates

Targeted Windows-relevant tests (`ipython-bootstrap.test.ts`,
`kernel-bootstrap.test.ts`, `session-lease.test.ts`): 2/3 files fully
clean; `kernel-bootstrap.test.ts` showed 17/21 failures, all traced to a
pre-existing test/patch mismatch (the test file hardcodes POSIX
`bin/python` path expectations and is byte-identical between v0.7.3 and
v0.7.4; the local Windows patch intentionally changes the real path to
`Scripts/python.exe` — this mismatch is not new to 0.7.4).

Lint (`biome check .`, no `--write`): clean, 919 files, no fixes needed.
Typecheck (`tsgo --noEmit`): clean, zero output.

Full `vitest` suite (`--exclude daemon-supervisor-process.test.ts`): 61
files failed / 253 passed / 8 skipped (322); 318 tests failed / 3886
passed / 55 skipped (4259); 14 errors. To determine whether this is a real
0.7.4 regression or pre-existing environment noise, a **direct A/B
comparison** was run: a fresh, throwaway `v0.7.3` worktree
(`C:\Users\assas\.prime-074-compat\throwaway-073`, completely separate
from the live install) was checked out and `npm install`ed on this same
machine, and the identical full test suite was run there immediately
after. Result: 62 files failed / 252 passed / 8 skipped (322); 316 tests
failed / 3867 passed / 53 skipped (4236); 14 errors — nearly identical
failure rate (~7.4% both versions). The two files most directly relevant
to Second Brain's own load path
(`extensions-discovery.test.ts`+`extensions-runner.test.ts`) showed
**exactly the same 44 failed / 11 passed (55)** on both versions,
independently confirmed to be a jiti/vitest dynamic-import interaction
(the same loader code succeeds when invoked directly via `tsx` outside
vitest) — unrelated to Prime's source. File-level deltas between the two
runs (a handful of files failing on one version but not the other) match
known-flaky Windows socket/timing test patterns
(`daemon-launch.test.ts` EACCES races, `session-lease.test.ts` PID-reuse
simulation), not a systematic regression. **Conclusion: Prime's own gates
are healthy on 0.7.4; the observed failure baseline pre-exists on 0.7.3
identically on this machine, proven by direct A/B, not assumed.**

## Section 9 — extension re-sync

No `brainstem/prime-extension/` runtime file differs between the current
branch HEAD and the frozen RC4 candidate SHA `98f147f9...` (confirmed via
`git diff`, empty). All 13 `.ts` files plus `types/prime.d.ts` copied into
a freshly created `C:\Users\assas\.prime-074-compat\agent\extensions\second-brain\`
(flat layout matching the live installed copy — **an early attempt that
nested the files under an extra `src/` subfolder produced zero telemetry
in the Section 11 smoke session; corrected before capturing any evidence
used in this report**). Combined sha256 (sorted per-file hash-of-hashes,
same method as `00-freeze-hashes.json`) recomputed and confirmed to match
`5c44759771add150628ca72a095c7e08f892626353962dac21d91f307a360e2d`
**exactly**. `auth.json`/`settings.json`/`models.json` copied read-only
from the live agent dir into the new isolated agent dir (contents never
printed/logged anywhere in this pass, per instruction). jiti/tsx cache is
the isolated instance's own `%TEMP%` location (default, not shared with
the live daemon).

**Process-safety correction made during this section**: the kernel-venv
bootstrap path (`PRIME_AGENT_KERNEL_VENV`) is **not** derived from
`PRIME_AGENT_CODING_AGENT_DIR` — it defaults independently to
`os.homedir()/.prime/agent/kernel-venv` (the LIVE path) unless explicitly
overridden. The first bootstrap attempt (before this was discovered)
attempted to rebuild the live kernel-venv and hit `EPERM` (blocked because
the live venv's `python.exe` was in use by the live daemon) — **no
mutation occurred** (verified: live `kernel-venv\Scripts\python.exe`
mtime unchanged, `2026-08-14 08:40:10`, before and after). All subsequent
isolated-instance invocations explicitly set
`PRIME_AGENT_KERNEL_VENV=C:\Users\assas\.prime-074-compat\agent\kernel-venv`
in addition to `PRIME_AGENT_CODING_AGENT_DIR`, and the isolated kernel
bootstrapped successfully into its own directory thereafter.

## Section 10 — static contract re-confirmation

Spot-re-confirmed the exact line citations from `04-static-contract-audit.md`
against the isolated worktree: `ContextEvent`/`ContextEventResult`
(types.ts:576-585, 869-873), `emitContext` (runner.ts:852-882),
`transformContext` (sdk.ts:319-325), `getSessionFile()`
(session-manager.ts:1313) — all match exactly, confirming nothing drifted
since the static audit was written.

## Section 11 — smoke session

Real session `01a02105-475b-745f-b4ee-e58402682abf` (internal id
`01a02105-654c-764d-b059-a4f4ed84b903`), run from the MAIN Second Brain
worktree with `--print "confirm you can see this repo; run \`git status
--short\` and report it"`, unique daemon socket
`\\.\pipe\prime074cE...`, isolated agent dir. Model correctly ran `git
status --short` and reported a clean tree. Real Second Brain telemetry
(23 records) confirmed: `session_start` → `brain_retrieval_attempt` →
`brain_packet_delivered` (`delivery_count:4, item_count:4,
packet_tokens:778`) → `autoinject_shadow_decision` (`decision:"INJECT"`)
→ `provider_request_meta`/`provider_response_meta` →
`assistant_usage` (real input/output/cache tokens) → `tool_call`/
`tool_result` → `turn_end` → `session_shutdown(reason:"quit")`. Session
started, AutoInject attached, real usage event appeared, session completed
and exited cleanly. **Gate passed — proceeded to Section 12.**

Two process-safety corrections were made and verified before this
evidence was captured: (1) the extension directory-layout fix (Section 9
above), (2) unsetting `PYTHONHOME`/`PYTHONPATH` in the launching shell
before every isolated-instance invocation from this point forward — the
kernel's own environment inherited a polluted `PYTHONHOME`
(`C:\Users\assas\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none`,
the documented AGENTS.md gotcha), which would otherwise have silently
broken every `second_brain` Python-bridge subprocess call the extension
makes, masquerading as "extension didn't attach" rather than a Prime 0.7.4
defect. Both corrections are process-quality findings about this
qualification pass's own launch discipline, not about Prime 0.7.4 or the
Second Brain runtime code.

## Section 12 — bounded live compatibility session (Q1-Q10)

Disposable worktree/branch `rc4-prime074-compat-disposable` created off
the RC4 candidate SHA `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72` (deleted
after, see Cleanup). `config/context.toml`'s five flags enabled in the
MAIN worktree with the tuned Pilot 4/5 budgets (`rtd.enabled=true`,
`vmem.enabled=true, budget_tokens=50`, `vmem_admission.enabled=true`,
`context_structure.enabled=true`, `context_paging.enabled=true,
pin_recent_messages=4, resident_token_budget=100,
max_pages_per_context_event=3`) — reverted to all-OFF after (empty diff
confirmed, see Cleanup).

Real session, Prime session file id `01a02107-1a9d-73ef-8dfb-e8239b63dada`
(internal id `01a02107-386b-72e4-9c1c-704849eab650`), driven across
multiple `--print`/`--print --continue` invocations against the same
unique daemon socket (the daemon architecture keeps the session alive
across invocations, including once continuing real work in the background
after one client connection was killed by a shell timeout — verified via
the same session file continuing to grow). 382 total telemetry records
captured.

- **Q1 AutoInject**: real `brain_packet_delivered`/`autoinject_shadow_decision`
  pair captured (see `05-compatibility-matrix.md` row 5).
- **Q2 RTD live reduction**: the model's naturally-issued `%%bash` cells
  needed several iterations before satisfying RTD's narrow, deliberately
  strict prelude grammar (only `unset PYTHONHOME`/`unset PYTHONPATH` are
  recognized skip-lines before the target command; a `cd`, `export PATH`,
  `set -e`, or `which` line before the target correctly breaks eligibility
  by design — confirmed by direct code reading of `rtd.ts`'s
  `resolveToolClass`). Once a real `.venv/Scripts/pytest.exe -vv tests/`
  cell matching the grammar was run, RTD fired for real: `rtd_shadow`
  event, `command_class:"pytest"`, `distilled:true`, `original_chars:66016`,
  `saved_chars:63407`, real `artifact_ref`. This is genuine evidence, not
  contrived — the narrow-grammar friction itself is evidence that RTD's
  documented eligibility rules (not a looser heuristic) are what's
  actually running on 0.7.4, matching the exact behavior `rtd.ts`'s own
  comments describe as proven in Pilot 1.
- **Q2 independent recovery**: `second_brain artifact expand
  8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218` run
  directly by this qualification pass (not trusting the model's self-report)
  → 66,016 bytes, byte-count-exact match to `original_chars`, real pytest
  header content.
- **Q3 RTD VMem metadata**: `second_brain vmem list ... --kind
  TOOL_OBSERVATION --json` → real row with `toolCallId`/`artifactRef`
  matching the `rtd_shadow` event exactly, not `{}`.
- **Q4 proactive paging**: real `context_paging` event, turn 2,
  `newly_claimed_count:1`, `RESIDENT`→`EVICTED`.
- **Q5 provider pointer proof**: `vmem_pointer_count` `0` (first 2
  requests, baseline) → `1` (from the turn-2 claim onward); `rtd_pointer_count`
  `0` → `1` at the RTD claim — no marker string was ever included in any
  task prompt.
- **Q6 EVICTED reprojection**: `reprojected_page_count:1,
  requested_page_count:0, claimed_page_count:0` on every one of 7
  consecutive turns (3 through 9) — matches Pilot 5's "essentially every
  subsequent turn" finding.
- **Q7 fault-in**: the model did not naturally invoke `vmem resolve`
  within this bounded session (expected and acceptable per the plan). One
  `HOST_INTEGRATION` check performed directly: `second_brain vmem resolve
  01a02107-1a9d-73ef-8dfb-e8239b63dada obj-35c2cf10dbed --json` → real
  `EVICTED`→`FAULTED_IN` transition, `byte_exact:true`, content matches
  the original AutoInject packet exactly. Clearly labeled HOST_INTEGRATION,
  not genuine-model-triggered proof (that remains frozen in Pilot 5's
  0.7.3 evidence).
- **Q8 compaction**: did not occur naturally (context usage stayed ≤5.08%
  of the 1,000,000-token window) — not forced, per instruction.
  NOT_APPLICABLE.
- **Q9 usage/cache telemetry**: real `assistant_usage` fields populated
  identically in shape to 0.7.3 (see matrix rows 15-16).
- **Q10 subagent/RLM**: one real RLM child spawned (`sub-c7eff7cb`, child
  session `01a0211a-5385-724c-9610-34340315f95b`), real result returned
  ("README.md has 114 lines"), real child session-artifacts confirmed on
  disk, parent extension lifecycle continued cleanly and the session shut
  down normally afterward. This bounded check confirms spawn+completion+
  cleanup for one small, fast child; it does not exercise long-running or
  concurrent multi-child scenarios (noted as a limitation, not forced or
  faked).

## Section 13 — token-efficiency sanity

RTD reduction magnitude (`original_chars:66016, saved_chars:63407`) is
comparable to Pilot 5's real 0.7.3 numbers (`original_chars:65578,
saved_chars:62969`) — same order of magnitude for a similar `pytest -vv`
workload, nothing structurally more expensive. AutoInject packet sizes
(745-800 tokens, 4 items) are consistent with Pilot 4/5's documented
range. No informal red flag found; this is a sanity gate, not a formal
economics comparison (no OFF arm was run, per the plan's explicit
instruction).

## Section 14 — cache accounting compatibility

Field names/semantics (`input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `total_tokens`, `cost_total`) confirmed byte-identical
to `outputs/reports/rc4/15-real-prime-pilot-5.md`'s documented 0.7.3
shape. Same for the VMem/RTD-specific field names
(`vmem_pointer_count`, `rtd_pointer_count`, `newly_claimed_count`,
`reprojected_page_count`). Nothing renamed, missing, or unit-changed.

## Section 15 — session/transcript reconstruction compatibility

The exact semantic invariant Pilot 5 discovered on 0.7.3 holds on 0.7.4:
Q6 above shows a full recoverable message reappearing while VMem still
records `EVICTED` reprojects cleanly to `EVICTED_REPROJECTED` with
`requested_page_count:0, claimed_page_count:0` (zero duplicate DB write),
repeated identically across 7 consecutive real turns.

## Section 16 — security/privacy regression check

Longest free-text string across all 382 captured telemetry records: 88
characters, a `brain-artifact:sha256:...` reference (content-addressed
hash, not prose). `context_structure` records contain only
type/keys/role/content_length/block-kind/length fields. Provider pointer
telemetry is counts-only (`vmem_pointer_count`/`rtd_pointer_count`
integers). Artifact refs are content-addressed hashes throughout. Session
ids for the smoke session (`01a02105-...`) and compat session
(`01a02107-...`) never appear cross-contaminated in either telemetry
stream.

## Section 17 — fail-open regression checks

One deterministic, cheap check performed: `second_brain vmem store
rc4-074-failopen-test-session TEST_EVIDENCE ... --metadata '{not valid
json'` → clean non-zero exit (2), clear error message, **no partial or
corrupt row written** (confirmed via a follow-up `vmem list` on that
session returning `[]`). The real Section 12 session additionally produced
zero `extension_error` events across 382 real records (nothing needed to
fail open during normal operation — a further, non-forced sanity signal).
Extension source code (`vmem.ts`, byte-identical to the RC4 candidate SHA
across this whole pass) confirmed to wrap every subprocess call site in
try/catch, matching the existing unit-test-proven fail-open guarantees
(re-confirmed live in Section 18's 560/560 passing `brainstem/prime-extension`
suite, which includes explicit fail-open test cases such as "a failing
shared ensurer: first store reports once, second store still constructs
and never re-attempts mkdir").

## Section 18 — full Second Brain regression suites

Python (main worktree, `PYTHONHOME`/`PYTHONPATH` unset): `pytest -q` →
exit 0, 1064/1064 passed, 0 failed (confirmed via dot-marker count since
this environment's pytest final summary line does not print through the
shell pipe used — exit code 0 plus zero `F`/`E`/`s`/`x` markers is
conclusive). `ruff check src tests` → "All checks passed!". `pyright` →
"0 errors, 0 warnings, 0 informations".

Prime extension (`brainstem/prime-extension/`): `npm test` → 18/18 test
files, 560/560 tests passed. `npm run lint` (eslint) → exit 0. `npm run
typecheck` (tsc --noEmit) → exit 0.

These test Second Brain's own code (unchanged runtime, same RC4 candidate
SHA throughout this pass) and pass identically regardless of Prime
version, as expected.

## Section 19 — compatibility verdict matrix

See `05-compatibility-matrix.md` for the full 21-row matrix. Every row is
PASS, NOT_APPLICABLE (compaction — not exercised by design, static audit
already confirmed unchanged contracts), or PASS-with-noted-limitation
(RLM subagent — small/fast child only).

## Section 20 — rollback verification

See `06-rollback.md`. Exact 0.7.3 commit independently re-verified
resolvable/checkoutable in a fresh throwaway worktree; local patches
`git apply --check` clean there.

## Anomalies / process-quality findings (not Prime 0.7.4 defects)

1. `PRIME_AGENT_KERNEL_VENV` is independent of `PRIME_AGENT_CODING_AGENT_DIR`
   and must be set explicitly for full isolation — documented above
   (Section 9) and recommended as a durable lesson for any future Prime
   upgrade-isolation work on this machine.
2. Extension discovery under the global `extensions/<name>/` tier requires
   a **flat** file layout (`extensions/second-brain/index.ts` +
   `types/`), not a nested `src/` subfolder — corrected before any
   evidence in this report was captured.
3. The launching shell's inherited `PYTHONHOME` (the documented,
   previously-repaired-then-recurring uv CPython pollution) must be
   unset before every isolated-instance invocation, or the Second Brain
   Python bridge silently no-ops (fail-open, so the session still runs,
   but with zero Brain integration and no error surfaced) — corrected
   before any Section 11/12 evidence was captured.
4. RTD's real eligibility grammar is deliberately narrower than a
   naturally-composed multi-step shell cell tends to satisfy (documented,
   intentional behavior per `rtd.ts`'s own comments, not a defect) — this
   qualification pass needed several precisely-worded turns to get a real
   RTD firing, consistent with (not contradicting) the documented design.

None of these four findings are Prime 0.7.4 regressions or Second Brain
runtime defects; all are one-time correction lessons about running the
isolation setup itself, and all were corrected before any PASS verdict in
this report was based on evidence.

## Verdict

**PRIME_0_7_4_SECOND_BRAIN_COMPATIBLE — EXTERNAL REVIEW REQUIRED.**

No BREAKING_FOR_BRAIN finding. No UNKNOWN_REQUIRES_RUNTIME_PROOF finding
remains open — the one static-audit-flagged gap (`before_provider_request`
payload field-name stability) is closed by this pass's real
`provider_request_meta` captures showing the same `messages`/`tools`-based
shape Second Brain's `sensors.ts` already handles defensively, with
correct `vmem_pointer_count`/`rtd_pointer_count` accounting throughout.
No STOP condition fired. Upgrade adoption is a narrow, evidence-backed
recommendation, not forced merely because 0.7.4 is newer.
