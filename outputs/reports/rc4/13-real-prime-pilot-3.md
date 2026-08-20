# 13 — Real Prime Pilot 3 (RC4, single genuine run — full CVM loop attempt)

Status: RC4_REAL_PRIME_PILOT3_COMPLETE — RAW EVIDENCE READY FOR EXTERNAL AUDIT

This is the **third** genuine Prime runtime pilot, the first to enable all
five capability flags simultaneously and attempt the full live loop: real
content → durable preservation → VMem admission → eviction → model-context
replacement → deterministic fault-in → successful continued task. Several
success criteria were met genuinely; several were **not** met, and are
reported honestly as negative results with exact root causes, per the run's
own instruction ("do not fabricate or force evidence").

## Branch / HEAD

- Candidate: `brain/v1-rc4-genuine-proof` @ `23bb08e72af97e5aa0b45ae78faf120f969ac0b4`
  (confirmed exact match before starting; unchanged after).
- Pilot workload ran in a disposable worktree/branch
  (`rc4-pilot3-disposable`), both git-untracked/deleted after the run — the
  main branch was never touched by workload edits.
- Only `config/context.toml` (five pilot-only flags, in the MAIN worktree)
  was intentionally changed and reverted (verified empty diff after
  revert).

## Pre-run setup

Re-synced the global Prime extension from this exact HEAD, cleared
`%TEMP%/jiti`, created the disposable worktree, and enabled in
`config/context.toml`: `[rtd] enabled=true`, `[vmem] enabled=true
budget_tokens=50`, `[vmem_admission] enabled=true`, `[context_structure]
enabled=true`, `[context_paging] enabled=true pin_recent_messages=4
resident_token_budget=100 max_pages_per_context_event=3` (smaller pin
window and budget than pilot-2-prep's defaults, deliberately, to give
paging its best real chance).

## Model / session

- `anthropic` / `claude-sonnet-5`.
- Real Prime session id: `01a01dc9-3f2b-732d-af0b-c60d9e817a8d`.
- RLM child id: `sub-3ccbf732`, session name `rc4-pilot3-worker` (fresh
  child).
- **Anomaly**: the child's session ended without sending its planned final
  report (its last tool_call — a follow-up pytest re-run — never received a
  matching tool_result in the transcript). This did not prevent evidence
  capture: the parent independently reconstructed every finding below
  directly from the real session transcript, telemetry JSONL, and
  per-session ledger SQLite, per this campaign's established practice of
  never trusting only the child's self-report.

## Workload

Added `TestTokenEstimateAndBasePriority` (5 real unit tests) to
`tests/test_vmem.py` in the disposable worktree, covering
`second_brain.vmem`'s previously-only-indirectly-tested pure helpers
`_estimate_tokens`/`_compute_base_priority`. Ran a real full-suite verbose
pytest (`"<venv-python>" -m pytest -vv`, preceded by `unset PYTHONHOME` /
`unset PYTHONPATH` per this machine's documented workaround), triggered one
real compaction via the `compact` skill, and continued with 12 further real
context/turn cycles afterward (including a second full pytest run, 1044
passed, and ruff/pyright checks, all succeeding post-compaction).

## Raw evidence paths

- Prime transcript (local only, 331,668 B, 85 records):
  `C:/Users/assas/.prime/agent/session-artifacts/01a01b1f-3ef5-73ab-addf-f467ca374e64/sub-3ccbf732/01a01dc9-3f2b-732d-af0b-c60d9e817a8d.jsonl`
- Second Brain telemetry (local only, 373,544 B, 359 records):
  `C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/01a01dc9-3f2b-732d-af0b-c60d9e817a8d.jsonl`
- Per-session ledger (local only):
  `C:/Users/assas/Documents/The-Second-Brain/state/sessions/937539e04f255b22ab0387a662e1e51391f609ddfdc94c8235f1fe063f83f5ec/ledger.sqlite`
- Sanitized bundle (committed): `outputs/reports/rc4/raw/pilot-03/pilot-03-evidence-bundle.json`
  (privacy-verified: max free-text field across 359 records is a 64-char
  sha256 hex string)
- Disposable workload diff (committed, not applied to the candidate):
  `outputs/reports/rc4/raw/pilot-03/pilot-workload.diff`

## Success criteria — evidence-based results

### 1. Genuine AutoInject — **MET**

Real `before_agent_start` → `brain_retrieval_attempt` (10 candidates) →
`brain_packet_delivered` (4 items, 745 tokens) → `autoinject_shadow_decision`
(`decision: INJECT`, `mode: active`, `model_visible: true`,
`packet_sha256: e1eab477abef9cf8e200bce6efd012da4e2060f27c873ce4b033aa2746ec8cd5`).
The per-session ledger's `session_vmem` table shows a real admitted
`RESEARCH_RESULT` object (`obj-423130bab4bb`) whose `metadata_json` contains
`packetArtifactRef: "[brain-artifact:sha256:e1eab477...]"` and
`packetSha256` **matching the telemetry `packet_sha256` exactly** —
confirming real, verified packet preservation, not a manual insertion.

### 2. Genuine RTD substitution — **NOT MET (exact root cause found, third distinct one this campaign)**

`RTD_FIRED = false`. The real `%%bash` cell was:
```
%%bash
unset PYTHONHOME
unset PYTHONPATH
"C:\Users\assas\Documents\The-Second-Brain\.venv\Scripts\python.exe" -m pytest -vv
```
`resolveToolClass` (the canonical resolver added specifically to fix this)
only ever reads the **first** non-empty line after the `%%bash` header as
"the command" — it extracted `unset PYTHONHOME` (first token `unset`), not
the actual pytest invocation two lines later, so RTD eligibility never even
reached the real target command. This is a **third distinct, exact root
cause** across the three real pilots run this campaign: pilot 2 found a
tool-name mismatch (fixed); the safety pass found a python-path-vs-literal
command-prefix mismatch for single-statement cells (fixed); pilot 3 found
that the resolver never scans past the first statement of a **multi-
statement** `%%bash` cell — a realistic, even `AGENTS.md`-documented
pattern on this machine. Not a security concern (an eligibility/coverage
gap, not an unsafe over-broad classification) but a real, reproducible
limitation. The eligible-by-size result (67,161 bytes per telemetry) passed
through completely unreduced; 0 of 38 real `tool_result` records show any
RTD marker. `RTD_BYTE_EXACT_RECOVERY = N/A` (nothing to recover — RTD never
substituted anything).

### 3. Real context paging — **NOT MET (exact structural cause found)**

`CONTEXT_PAGED_COUNT = 0` (0 real `context_paging` telemetry events, 0
`extension_error` events — the pager evaluated cleanly and found nothing
eligible, it did not fail). Root cause, precisely reconstructed:

- VMem eviction only ever happens via `prepare_compaction()`, which fires
  at the SAME real compaction event that also causes Prime's own host-level
  context summarization (confirmed: `vmem_compact_prep` reports
  `evicted_at_compaction: 2`, exactly matching the 2 admitted objects).
- The real post-compaction `context_structure` record (count=34, the very
  first context event after compaction) shows `event.messages[0]` is
  `role: compactionSummary`, and the ONLY `role: custom` element remaining
  is at index 33. Cross-referenced against the raw local transcript's own
  `custom_message` records, that surviving element's `customType` is
  `"ipython_state"` (the post-compaction kernel-state notice) — **not**
  `"brain.autoinject.packet"`. The original AutoInject custom message,
  which was admitted into VMem pre-compaction, does not appear anywhere in
  the post-compaction `event.messages` array at all.
- Since AutoInject fires exactly once, at session start, it is structurally
  always among the OLDEST content in the conversation by the time any
  compaction occurs — and real Prime compaction appears to fold/drop
  session-start-era custom messages entirely rather than retaining them
  verbatim for a later paging pass to find.
- No `TOOL_OBSERVATION` object existed this session (RTD never fired, see
  above), so there was no second, independent candidate class to test
  either.

This is a genuine, structurally-important negative finding this pilot was
specifically designed to surface: **as currently wired, AutoInject-class
paging may rarely or never get a real opportunity to fire**, because the
one event that makes a VMem object EVICTED (compaction) is the same event
that tends to remove the corresponding live message from context entirely.
Overall context size DID shrink at the compaction boundary (46→28-style
reduction pattern, here 58→34 context.messages count) — but that reduction
is attributable to Prime's own compaction, not to this campaign's pager
(`paged_count` was 0 throughout). `CONTEXT_SIZE_AFTER < CONTEXT_SIZE_BEFORE`
is therefore reported as **N/A for paging specifically** (true for
compaction generally, not demonstrated for paging).

### 4. Genuine fault-in — **NOT MET (honestly, as expected given #3)**

`REAL_FAULT_IN = 0`. `second_brain vmem resolve` was never invoked (0
occurrences in the transcript) — consistent with paging never firing (no
`[SECOND_BRAIN_VMEM]` pointer was ever presented to the agent) and
consistent with the run's own instruction not to force/fake a fault-in
call absent a genuine trigger. `FAULT_IN_EXACT_RECOVERY = N/A`.

### 5. Genuine compaction + continuation — **MET**

Real `session_before_compact` (`branch_entries: 64`) → compaction
transcript record → real `session_compact` (`from_extension: false`) → 12
further real `context`/`turn`/`tool_call` cycles over ~8 minutes,
including a second full pytest run (1044 passed) and clean ruff/pyright
checks, all succeeding post-compaction. Ledger `segments` table confirms
`seg-1`, `started_reason: compact`. `COMPACTION_CONTINUATION = true` — only
1 `agent_end`/segment exists (vs. 2 in pilots 1-2) because the RLM child
session terminated before a clean second wrap-up, but genuine, sustained
post-compaction continuation is amply evidenced by the 12 further real
cycles that DID complete successfully.

### 6. Task correctness — **MET**

Real, small, genuine improvement (5 new unit tests for previously
under-tested pure helpers). Independently re-verified by the parent after
the run: `pytest tests/test_vmem.py -k TestTokenEstimateAndBasePriority` →
6 passed (5 new + 1 pre-existing under the same filter); `ruff check
tests/test_vmem.py` → clean. The child had also independently verified a
full-suite run (1044 passed) and clean ruff/pyright both before and after
compaction. `TASK_CORRECT = true`. No regression from missing paged
information, since nothing was ever paged this run.

### 7. Actual provider usage — captured, no savings claim

38 real provider turns: `input_tokens=75`, `output_tokens=11018`,
`cache_read_tokens=1667509`, `cache_write_tokens=95197`,
`cost_total=$0.6818` — sourced from `BRAIN_TELEMETRY assistant_usage`
mirroring real Anthropic responses. This is a Brain-ON pilot with no
matched OFF control; no savings claim is made.

## Summary against the stated success criteria

| Criterion | Result |
|---|---|
| RTD_FIRED | **false** |
| RTD_BYTE_EXACT_RECOVERY | N/A (RTD never fired) |
| VMEM_REAL_ADMISSION > 0 | **true** (2) |
| VMEM_REAL_EVICTION > 0 | **true** (2) |
| CONTEXT_PAGED_COUNT > 0 | **false** (0) |
| CONTEXT_SIZE_AFTER < CONTEXT_SIZE_BEFORE (paging-attributable) | N/A (paged_count=0; compaction itself did shrink context, but that is not this campaign's pager) |
| REAL_FAULT_IN > 0 | **false** (0) |
| FAULT_IN_EXACT_RECOVERY | N/A |
| COMPACTION_CONTINUATION | **true** |
| TASK_CORRECT | **true** |

Pilot 3 is **not** fully successful against the stated criteria — this is
reported honestly, with exact, reproducible root causes for both negative
results, rather than forced or fabricated to look complete.

## Anomalies

- The RLM child session ended before sending its planned final report;
  all findings above were independently reconstructed by the parent from
  raw transcript/telemetry/ledger evidence, per established practice.
- A leftover disposable worktree directory briefly resisted deletion
  (Windows file lock); git had already fully untracked the worktree and
  deleted its branch before this, so the main candidate branch was never
  at risk. Directory removal succeeded shortly after (once the RLM child
  process was deleted).
- Two genuine, exact, actionable defects were newly discovered and are
  explicitly NOT fixed in this pilot, per instructions ("do not fix
  discovered defects during the same run"): (1) `resolveToolClass` does
  not scan past the first statement of a multi-statement `%%bash` cell;
  (2) AutoInject-class paging may have little to no real opportunity to
  fire given how VMem eviction is coupled to compaction and how
  compaction appears to drop session-start-era custom messages.

## Explicitly not done in this pilot

- No fixes were applied for either newly-discovered defect.
- No further pilot was started.
- No Brain-OFF/Brain-ON benchmark was started.
- No PROVEN/PASS status is claimed; the criteria table above is the honest
  record.
