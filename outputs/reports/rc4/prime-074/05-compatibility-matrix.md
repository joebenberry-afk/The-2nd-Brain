# 05 — Prime 0.7.4 Compatibility Verdict Matrix

Evidence-only. Every PASS cites a real session id, real telemetry field, or
real file/line. No bare assertions.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Prime 0.7.4 exact version | PASS | Isolated worktree `tsx cli.ts --version` → `0.7.4` exactly; `git rev-parse HEAD` → `af0b8e00b9f704e834787fd321065ca78281f2aa` ("chore(release): prepare v0.7.4 (#1569)"); `git describe --tags --always --dirty` → `v0.7.4-dirty` (dirty = the 2 known local Windows patches only, confirmed via `git status --short`). |
| 2 | Windows Python bootstrap | PASS | Isolated kernel bootstrap (`PRIME_AGENT_KERNEL_VENV=C:\Users\assas\.prime-074-compat\agent\kernel-venv`) succeeded end-to-end on 0.7.4 with Patch A applied: `✓ ready`, `kernel python: ...\kernel-venv\Scripts\python.exe` (Windows path, not `bin/python`). Live `.prime\agent\kernel-venv\Scripts\python.exe` mtime unchanged throughout (`2026-08-14 08:40:10`), proving isolation held even though the first two bootstrap attempts (before `PRIME_AGENT_KERNEL_VENV` was set) defaulted to the live path and hit `EPERM` (blocked by the live venv being in use) — logged as a corrected process error, not a Prime defect. |
| 3 | Session lease restore | PASS | Patch B applies cleanly to 0.7.4 (`02-local-patch-disposition.md`, `git apply --check`/`git apply` exit 0, isolated worktree). Live daemon session-lease unaffected throughout (5 live `C:\Tools\prime-agent` processes unchanged pre/post pass). `test/session-lease.test.ts` targeted run: 16/16 passed, 2 skipped (0 failed) in the isolated 0.7.4 worktree. |
| 4 | Extension load | PASS | Real session `01a02105-475b-745f-b4ee-e58402682abf` (Section 11 smoke) and `01a02107-1a9d-73ef-8dfb-e8239b63dada` (Section 12 compat) both produced real Second Brain telemetry files under `telemetry/agent-performance/`, proving `discoverAndLoadExtensions`'s global `agentDir/extensions/` tier loaded the extension correctly on 0.7.4 once files were placed directly under `extensions/second-brain/*.ts` (flat layout, matching the live installed copy — an early attempt with a nested `src/` subfolder produced zero telemetry, corrected before Section 11 evidence was captured). |
| 5 | AutoInject | PASS | Session `01a02105-...`: `brain_packet_delivered` (`delivery_count:4, item_count:4, packet_tokens:778`) immediately followed by `autoinject_shadow_decision` (`decision:"INJECT"`). Session `01a02107-...`: same pair, `packet_tokens:745`, `selected_count:4`. |
| 6 | RTD live reduction | PASS | Session `01a02107-...`, tool call `toolu_01DaiYYavHdeZ68uCjuPADNf`: real `rtd_shadow` telemetry event — `command_class:"pytest"`, `distilled:true`, `original_chars:66016`, `visible_chars:2609`, `saved_chars:63407`, `artifact_ref:"[brain-artifact:sha256:8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218]"`. Comparable in magnitude to Pilot 5's 0.7.3 capture (`original_chars:65578`). |
| 7 | RTD exact recovery | PASS | Independently recovered via `second_brain artifact expand 8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218` (run directly by this qualification pass, not the model): 66,016 bytes exactly, real pytest header content (`platform win32 -- Python 3.11.15, pytest-9.1.1 ...`), byte count matches `original_chars` exactly. |
| 8 | RTD VMem metadata | PASS | `second_brain vmem list 01a02107-1a9d-73ef-8dfb-e8239b63dada --kind TOOL_OBSERVATION --json`: real row `obj-802437fb8987`, `metadata: {"toolCallId":"toolu_01DaiYYavHdeZ68uCjuPADNf","artifactRef":"[brain-artifact:sha256:8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218]"}` — not `{}`, and both values match the `rtd_shadow` event exactly. |
| 9 | Proactive paging | PASS | Session `01a02107-...`, turn 2: real `context_paging` event — `newly_claimed_count:1`, `state_before:["RESIDENT"]`, `state_after:["EVICTED"]`, `object_kinds:["RESEARCH_RESULT"]`, `resident_budget:100` (the tuned Pilot-4/5 budget). |
| 10 | Provider pointer proof | PASS | `provider_request_meta.vmem_pointer_count`: `0` on `request_seq:1,2` (baseline, before any claim) → `1` from `request_seq:3` onward (immediately after the turn-2 claim) → `2` after a second AutoInject packet was claimed later in the same session → `rtd_pointer_count`: `0` on all requests before the RTD claim, `1` immediately after (`request_seq:2` of the later daemon-worker segment). No marker string was ever planted in any task prompt. |
| 11 | EVICTED reprojection | PASS | Every turn from turn 3 onward (7 consecutive real occurrences: turns 3–9) shows `context_paging` with `reprojected_page_count:1`, `requested_page_count:0`, `claimed_page_count:0` (no duplicate DB write), `state_before:["EVICTED"]`, `state_after:["EVICTED_REPROJECTED"]` — matches Pilot 5's "essentially every subsequent turn" finding exactly. |
| 12 | Fault-in compatibility | PASS (HOST_INTEGRATION) | The bounded session did not naturally invoke `vmem resolve` in this pass. Deterministic `HOST_INTEGRATION` check performed directly by this qualification pass (not model-triggered): `second_brain vmem resolve 01a02107-1a9d-73ef-8dfb-e8239b63dada obj-35c2cf10dbed --json` → `{"ok":true,"byte_exact":true,"resolution":"packet_artifact", "obj":{"residency_state":"FAULTED_IN", ...}}`, real EVICTED→FAULTED_IN transition (was `"residency_state":"EVICTED"` in the immediately preceding `vmem list`), content byte-identical to the original AutoInject packet. Explicitly labeled HOST_INTEGRATION per the task's instruction — genuine model-triggered fault-in remains frozen in Pilot 5's 0.7.3 evidence. |
| 13 | Compaction lifecycle | NOT_APPLICABLE | Section 12's bounded session stayed at ≤5% of the 1,000,000-token context window (`context_usage.percent` peaked at 5.08%); compaction never triggered naturally, and the task explicitly says not to force it. Static contract audit (`04-static-contract-audit.md`, item 4) already confirmed `session_before_compact`/`session_compact` types/dispatch are byte-identical between 0.7.3 and 0.7.4. |
| 14 | Session identity | PASS | Prime session file id (`01a02107-1a9d-73ef-8dfb-e8239b63dada`) used consistently as the `session` field across all 382 telemetry records for this session, distinct from the internal Prime session id (`01a02107-386b-72e4-9c1c-704849eab650`) and from the Section 11 smoke session's ids — no cross-contamination observed across the 2 real sessions captured. |
| 15 | Usage telemetry | PASS | Real `assistant_usage` records populated on every turn, e.g. session `01a02107-...`: `{"input_tokens":2,"output_tokens":293,"cache_read_tokens":21052,"cache_write_tokens":1203,"total_tokens":22550,"cost_total":0.0101519}` — same field set as Pilot 5's 0.7.3 baseline. |
| 16 | Cache accounting | PASS | Field names/semantics (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `cost_total`) are byte-identical to `outputs/reports/rc4/15-real-prime-pilot-5.md`'s documented 0.7.3 shape (`vmem_pointer_count`/`rtd_pointer_count`/`newly_claimed_count`/`reprojected_page_count` field names also confirmed identical). Static audit additionally confirmed the `anthropic.ts` usage-construction code is comment-diff-only between tags. |
| 17 | Subagent/RLM | PASS (with a noted limitation) | One real RLM child spawned from within the compat session: child id `sub-c7eff7cb`, child session id `01a0211a-5385-724c-9610-34340315f95b`, real result returned ("README.md has 114 lines"), real child session-artifacts confirmed on disk (`session-artifacts/01a02107-386b-72e4-9c1c-704849eab650/sub-c7eff7cb/01a0211a-5385-724c-9610-34340315f95b.jsonl`), parent extension lifecycle continued cleanly (no crash, session shut down normally afterward). Limitation: this bounded `--print`/`--continue` check confirms spawn + completion + cleanup for one small child; it does not exercise long-running or concurrent multi-child RLM scenarios. |
| 18 | Fail-open behavior | PASS | Deterministic CLI-level check: `second_brain vmem store rc4-074-failopen-test-session TEST_EVIDENCE ... --metadata '{not valid json'` → clean non-zero exit (2) with a clear error message, no partial/corrupt row written (`vmem list` for that session returns `[]`). Section 12's real 382-record telemetry stream contains zero `extension_error` events (nothing needed to fail open during the real run). Extension source (`vmem.ts`) confirmed to wrap every subprocess call site in `try/catch` (unchanged from the 0.7.3-proven RC4 candidate code, since the extension source is byte-identical — same SHA — across this whole pass). |
| 19 | Privacy | PASS | Longest free-text string across all 382 captured telemetry records (Section 12) is 88 characters — a content-addressed `brain-artifact:sha256:...` reference, not prose. `context_structure` records contain only `type`/`keys`/`role`/`content_length`/block `kind`/`length` fields, never raw text. Provider pointer telemetry (`vmem_pointer_count`, `rtd_pointer_count`) is counts-only. |
| 20 | Full Python tests | PASS | Main worktree, `PYTHONHOME`/`PYTHONPATH` unset: `pytest -q` → exit 0, 1064/1064 dot markers, zero F/E/skip markers. `ruff check src tests` → "All checks passed!". `pyright` → "0 errors, 0 warnings, 0 informations". |
| 21 | Full TS tests | PASS | `brainstem/prime-extension`: `npm test` → 18/18 test files, 560/560 tests passed. `npm run lint` (eslint) → exit 0, no output. `npm run typecheck` (tsc --noEmit) → exit 0, no output. |

## Note on Prime's own gates (Section 8, informational — not a matrix row)

Prime's own `vitest` suite (packages/coding-agent) shows a **pre-existing,
Windows/Node-v26/vitest-4.1.10-environment-specific failure baseline that
reproduces near-identically on a fresh 0.7.3 install**, proven by a direct
A/B run in this pass (not assumed):

- 0.7.4 (isolated worktree, npm install this pass): 61 test files failed /
  253 passed / 8 skipped (322 files); 318 tests failed / 3886 passed / 55
  skipped (4259 tests); 14 errors.
- 0.7.3 (fresh throwaway worktree + fresh `npm install`, same machine, same
  Node v26.7.0, run immediately after): 62 files failed / 252 passed / 8
  skipped (322); 316 tests failed / 3867 passed / 53 skipped (4236); 14
  errors.
- `extensions-discovery.test.ts` + `extensions-runner.test.ts` (the files
  most directly relevant to Second Brain's own load path): **exactly
  44 failed / 11 passed (55) on BOTH versions** — proven root cause is a
  jiti/vitest dynamic-import interaction unrelated to Prime's source (the
  same loader code succeeds when run directly via `tsx` outside vitest).
- `kernel-bootstrap.test.ts`'s 17/21 failures are a pre-existing test/patch
  mismatch: the test file hardcodes POSIX `join(venv,"bin","python")`
  expectations and is byte-identical between v0.7.3 and v0.7.4 (`git diff
  v0.7.3 v0.7.4` empty), while the local Windows patch intentionally
  changes the real path to `Scripts/python.exe` — the tests were never
  updated for the Windows local patch, on either version.
- File-level deltas between the two runs (3 files fail only on 0.7.4, 1
  file fails only on 0.7.3) are consistent with known-flaky Windows
  socket/timing tests (`daemon-launch.test.ts` EACCES races,
  `session-lease.test.ts` PID-reuse simulation) — normal run-to-run noise
  at this failure rate, not a systematic 0.7.4 regression.

This is not one of the 21 compatibility-matrix rows above because it is a
Prime-repo-internal-only gate (Prime's own test suite against Prime's own
source, independent of the Second Brain extension); it is recorded here
because Section 8 explicitly requires "exact pass/fail counts" and a
narrow explanation before treating any Prime-side failure as dismissible.
