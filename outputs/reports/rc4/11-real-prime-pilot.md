# 11 — Real Prime Pilot (RC4, single genuine run)

Status: RC4_REAL_PRIME_PILOT_COMPLETE — RAW EVIDENCE READY FOR AUDIT

This is **one** genuine Prime runtime pilot, not the full token campaign. It
exists to capture real, first-time evidence of RC4's Prime lifecycle wiring
(VMem compaction bookkeeping, RTD, `context` event shape, real tool catalog)
before any further campaign work. No PASS/PROVEN status is claimed here.

## Branch / HEAD

- Worktree: `C:/Users/assas/Documents/The-Second-Brain`
- Branch: `brain/v1-rc4-genuine-proof`
- HEAD before and after the pilot (unchanged): `666633de78f192e2b3c7fe71d4ea577f60e153c2`
  ("docs: freeze rc4 runtime implementation checkpoint")
- `git status --short` before the pilot: clean.
- `git status --short` after the pilot: `M tests/test_ledger.py` only
  (`config/context.toml` was touched for the pilot's [vmem]/[rtd] toggles and
  reverted to its original content immediately after evidence capture — the
  working tree diff on that file is now empty).

## Pre-run setup (real findings, not assumptions)

1. **The Prime daemon's global extension copy was stale.** Prime discovers
   extensions from `agentDir/extensions/` (source:
   `packages/coding-agent/src/core/extensions/loader.ts`,
   `discoverAndLoadExtensions` -> global `agentDir/extensions` dir), which on
   this machine is `C:/Users/assas/.prime/agent/extensions/second-brain/` — a
   **plain copy**, not a symlink into this repo. `diff -rq` against
   `brainstem/prime-extension/src` showed `config.ts`, `index.ts`,
   `sensors.ts` differed and `vmem.ts` was entirely **missing** from the
   installed copy (pre-R3/R6). This means Prime was **not** loading the RC4
   extension before this pilot's setup step.
2. Fix applied: copied `config.ts`, `index.ts`, `sensors.ts`, `vmem.ts` from
   `brainstem/prime-extension/src` (RC4 HEAD) onto the installed copy
   byte-for-byte; re-`diff -rq` confirmed the two trees now match (the only
   remaining `Only in installed: types` line is expected — `types/prime.d.ts`
   already matched). Cleared `%TEMP%/jiti` (jiti's TS-compile cache) to force
   a fresh transpile.
3. Confirmed via the Prime daemon worker's own process environment
   (`printenv` inside a `%%bash` cell run under this daemon session):
   `SECOND_BRAIN_HOME=C:\Users\assas\Documents\The-Second-Brain`,
   `SECOND_BRAIN_OBSERVABILITY` unset (not disabling), and 669 pre-existing
   files already under `telemetry/agent-performance/` confirming the
   extension has a working telemetry sink in this daemon.
4. `config/context.toml` already had `[vmem]` and `[rtd]` sections
   (both `enabled = false` by default, matching "safe by default"). Set
   `[vmem].enabled = true` and `[rtd].enabled = true` for the pilot only;
   reverted both to `false` immediately after raw evidence capture (verified
   `git diff config/context.toml` is empty afterward).

## Model / session

- Provider/model: `anthropic` / `claude-sonnet-5` (matches the recovery
  plan's "Primary implementation/test model: Claude Sonnet 5").
- Real Prime session id (from the session's own transcript `session` record):
  `01a01b25-3465-7762-82ba-1f56d57cf6ce`.
- RLM child id: `sub-90e122cd`, session name `rc4-pilot-worker`, parent
  session `01a01b1f-3ef5-73ab-addf-f467ca374e64`, `rlmDepth: 1`.
- This was spawned as a real RLM child (`await rlm(...)`), i.e. a genuine,
  separate Prime Agent session under the same daemon and the same
  freshly-synced extension — not the orchestrating (parent) session itself.

## Task performed

Added `test_load_retention_config_defaults_and_fallback` to
`tests/test_ledger.py`, covering a real, previously-untested gap in
`second_brain.ledger.load_retention_config` (absent config -> defaults;
malformed TOML -> falls back to defaults instead of raising; valid partial
override merges only recognized numeric/bool keys and ignores unknown/
wrong-typed ones). `git diff --stat`: `tests/test_ledger.py | 39
+++++++++++++++++++++++++++++++++++++++` (39 insertions, 1 file). Verified
independently by the parent after the child's report:
`pytest tests/test_ledger.py -k retention -v` -> `1 passed`. The child also
reported a full-suite run (`1012 passed`) and a clean `ruff check`; the
parent did not independently re-run the full suite (out of scope for a
single-change pilot) but did re-verify the specific new test.

## Raw evidence paths

- Real Prime session transcript (host-native, 313102 bytes, 62 records):
  `C:/Users/assas/.prime/agent/session-artifacts/01a01b1f-3ef5-73ab-addf-f467ca374e64/sub-90e122cd/01a01b25-3465-7762-82ba-1f56d57cf6ce.jsonl`
- Second Brain telemetry JSONL (brain-native, 47996 bytes, 195 records):
  `C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/01a01b25-3465-7762-82ba-1f56d57cf6ce.jsonl`
- Per-session ledger SQLite (88 real events, 1 segment, 0 `session_vmem` rows):
  `C:/Users/assas/Documents/The-Second-Brain/state/sessions/6ffbb297f6bb391a437f245b61ee7a4fcf97a7c271ab06a370632d721dcb3034/ledger.sqlite`
  (internal id = sha256 of the host session id, per `ledger.py`
  `internal_session_id`)
- `rlm-subagent.json` admission record (parent-side):
  `C:/Users/assas/.prime/agent/session-artifacts/01a01b1f-3ef5-73ab-addf-f467ca374e64/sub-90e122cd/rlm-subagent.json`
- Manifest entry: `outputs/reports/rc4/raw/manifest.jsonl`,
  `evidence_id: rc4-r10-real-prime-pilot`.

No synthetic files were generated. No `usage.json`, run IDs, or event files
were hand-written; every number below is read directly from the two JSONL
files and the SQLite ledger above.

## Primary questions — answers from raw evidence

### 1. Exact runtime shape of `event.messages` in Prime's `context` hook

`brainstem/prime-extension/src/index.ts` registers `context` directly (not
through the generic `wire()` mapper) specifically because, per its own
comment, *"no live Prime session has ever captured the real message shape"*.
`sensors.context()` does `Array.isArray(messages) ? messages.length : 0` and
telemetry only ever stores the resulting integer under `messages`.

This pilot confirms **`event.messages` is a real Array** — the 20 captured
`context` telemetry records show a monotonically increasing count
(`2, 5, 8, 11, ..., 45`) that tracks turn advancement, then **drops to `33`
immediately after the real compaction event** (compaction fired at
`17:55:54.513Z`, last pre-compaction count was `45` at `17:55:33.702Z`, first
post-compaction count was `33` at `17:55:55.063Z`) — proof the array shrank
because of the real compaction, not a coincidence or a reset-to-zero bug.

What this pilot **could not** capture: the per-element shape (role/content
keys, tool-call/tool-result block structure) of the array's members, because
RC4's own `sensors.context()` deliberately discards everything except
`.length` (to avoid guessing at/depending on an unverified shape). Answering
"what does one `event.messages[i]` object actually look like" requires a
follow-up instrumentation change that logs (a redacted/sha'd version of) one
element's key set — explicitly out of scope for this pilot per the run
instructions ("do not implement VMem context replacement ... unless the
captured message/tool shapes make the safe implementation unambiguous" —
they do not yet).

### 2. Exact real tool names from `getAllTools()` / `getActiveTools()`

Captured once at `session_start` via the new R6 `prime_tool_surface` record:

```json
{"kind": "prime_tool_surface", "all_tools_count": 1, "active_tools_count": 1,
 "all_tools": ["ipython"], "active_tools": ["ipython"]}
```

In this harness shape (an RLM/IPython-orchestrated Prime subagent), Prime's
**entire real tool surface is a single tool named `"ipython"`** — there is no
separate `"bash"` tool; shell commands run as `%%bash` cells *inside* the
`ipython` tool. Every one of the 31 real `tool_call`/`tool_result` telemetry
pairs in this session used `"tool": "ipython"` — confirmed independently from
both the telemetry JSONL and the raw Prime transcript's `toolName` fields.

### 3. Do the new VMem compact-prep / hot-context records fire during a genuine Prime lifecycle?

**Yes, both fired**, at the correct real lifecycle points:

- `vmem_compact_prep` at `17:55:37.546Z` (inside `session_before_compact`,
  which itself logged `branch_entries: 51`), payload
  `{"evicted_at_compaction": 0, "pinned_preserved": 0}`.
- `vmem_hot_context` at `17:55:55.089Z` (right after `session_compact`),
  payload `{"resident_count": 0, "evicted_count": 0, "resident_tokens": 0}`.
- The per-session ledger's `session_vmem` table exists (real schema) but has
  **0 rows** for this session.

All real events, but an **all-zero payload** — nothing was pinned/tracked in
VMem's working set during this session, so compact-prep/hot-context ran
against an empty state. This is honest evidence of firing, not of a
populated/exercised working set; a follow-up pilot that deliberately pins
something (if/when a real caller of that API exists) would be needed to
observe non-zero VMem bookkeeping.

### 4. Does existing RTD really intercept an actual eligible `tool_result`, preserve it, reduce it, and remain recoverable?

**No — RTD fired zero times this session, despite `[rtd].enabled = true`.**
One real tool result was 70811 bytes (the `pytest -vv` full-suite run,
comfortably over the 8000-char `threshold_chars`), i.e. large-enough to be
size-eligible. But `rtdEligibility()` (`brainstem/prime-extension/src/rtd.ts`)
gates on `whitelist_tools` (default/config `["bash"]`) matched **case-
insensitively against the literal tool name** — and the real tool name in
this harness is `"ipython"`, not `"bash"`. `"ipython" !== "bash"` on every one
of the 31 tool results, so eligibility short-circuits to `"tool"` before the
size check ever runs. All 31 telemetry `tool_result` records have the plain
`{tool, id, is_error, output_bytes}` shape with no distillation/reduction
marker of any kind. **This is a real, exact finding**: RTD as configured
(`whitelist_tools: ["bash"]`) is currently unreachable in any harness shape
where the real tool is named `"ipython"` rather than `"bash"` — it is not a
bug in the size/reduction logic itself (untested by this pilot), it is a
tool-name mismatch that prevents the eligibility gate from ever passing.

### 5. Does AutoInject still behave correctly after the RC4 changes?

**Yes.** Real `before_agent_start` -> `brain_retrieval_attempt` (10
candidates) -> `brain_packet_delivered` (4 items selected, 747 tokens,
`packet_id: pkt-a3b929ca8bddf54c`) -> `autoinject_shadow_decision` chain, with
`decision: "INJECT"`, `mode: "active"`, `model_visible: true`,
`result_patch: true`, `handler_returned_message: true`. The delivered memory
ids (`mem-99df66e3c8f6`, `mem-bb634354ec69`, `mem-b67de5057f76`,
`mem-f745bcb2eff2`) match real Brain memory content, not placeholders.

### 6. Does the session continue correctly after compaction?

**Yes.** Real chain in both the transcript and telemetry:
`session_before_compact` (`branch_entries: 51`) -> `compaction` transcript
record with a real generated summary -> `session_compact`
(`from_extension: false`) -> a **second** `turn_start`/`tool_call`/
`tool_result`/`turn_end` cycle -> a **second** `agent_end` (`messages: 6`).
The per-session ledger's `segments` table independently confirms this:
`seg-1`, `started_reason: "compact"`, `start_seq: 78`, `active: 1`. The child
also verified `git status --short` / `git log -1` were identical before and
after compaction (real continuity check, not asserted).

### 7. What exact token/cache usage does Prime itself report?

Real per-turn `assistant_usage` telemetry (20 turns, sourced from
`provider_request_meta`/`provider_response_meta`/`assistant_usage`, which
mirror actual Anthropic API request/response metadata — not estimated):

| metric | value |
|---|---|
| turns | 20 |
| input_tokens (sum) | 39 |
| output_tokens (sum) | 8519 |
| cache_read_tokens (sum) | 924834 |
| cache_write_tokens (sum) | 89186 |
| total_tokens (sum) | 1042764 (all four columns) |
| cost_total (sum) | $0.4932 |

Per-turn `turn_end` records additionally carry a real `context_usage`
(`used`/`total`/`percent` against a 1,000,000-token context window for this
model/session), e.g. first turn: `{"used": 19222, "total": 1000000,
"percent": 1.9222}`.

## Anomalies

- The global Prime extension install was stale before this pilot (see
  "Pre-run setup" above) — recorded and fixed, not hidden.
- VMem's compact-prep/hot-context events fired but carried all-zero payloads
  (nothing pinned/tracked) — reported as-is, not treated as a failure or a
  pass.
- RTD did not fire despite being enabled and a real eligible-by-size result
  existing, because of the `"bash"` vs `"ipython"` tool-name mismatch — this
  is the pilot's most actionable finding for future RTD work.
- The `context` event's per-message shape remains unobserved by design (RC4
  intentionally never serializes it); only the array length was ever
  captured.

## Explicitly not done in this pilot

- No VMem context replacement or dynamic tool activation was implemented —
  the captured message/tool shapes are informative (real `Array`, real
  single-tool `["ipython"]` catalog) but not yet unambiguous enough to safely
  drive a message-level replacement or a `setActiveTools()` call.
- No PROVEN/PASS status is claimed.
- No full token campaign was started.
