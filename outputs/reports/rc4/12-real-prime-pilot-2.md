# 12 — Real Prime Pilot 2 (RC4, single genuine run)

Status: RC4_REAL_PRIME_PILOT2_COMPLETE — RAW EVIDENCE READY FOR AUDIT

This is the **second** genuine Prime runtime pilot, run after pilot-2 prep
(`ce51a85`) added context structural telemetry, VMem admission, and RTD
host-tool normalization — all default-disabled. This pilot enabled all four
new/existing flags for one real run to observe whether they fire correctly
under genuine runtime activity. No PASS/PROVEN status is claimed.

## Branch / HEAD

- Candidate: `brain/v1-rc4-genuine-proof` @ `ce51a8565a126aa594d742b5a8013ec68cd7625e`
  (unchanged before/after this pilot).
- The pilot's actual workload ran in a **disposable worktree/branch**
  (`C:/Users/assas/.prime/agent/pilot-worktrees/rc4-pilot2`, branch
  `rc4-pilot2-disposable`), both created fresh at this HEAD and **deleted**
  after the run — the main branch was never touched by workload edits.
- The only intentional change to the main worktree was `config/context.toml`
  (four pilot-only flags), reverted immediately after evidence capture
  (`git diff config/context.toml` is empty afterward).

## Pre-run setup

1. Re-synced the global Prime extension copy
   (`C:/Users/assas/.prime/agent/extensions/second-brain`) from
   `brainstem/prime-extension/src` at this HEAD — `diff -rq` had again shown
   `config.ts`/`index.ts`/`rtd.ts`/`sensors.ts`/`vmem.ts` all stale (still
   at pilot-1's synced version, missing pilot-2-prep's changes). Cleared
   `%TEMP%/jiti` again.
2. Confirmed `brain/v1-rc4-genuine-proof` clean at the target HEAD.
3. Created the disposable worktree: `git worktree add -B
   rc4-pilot2-disposable <path> ce51a856...`.
4. Enabled in the **main** worktree's `config/context.toml` (config is
   resolved via `SECOND_BRAIN_HOME`, not cwd, so this had to be the main
   worktree regardless of where the child's cwd was):
   `[rtd].enabled=true`, `[vmem].enabled=true` with **`budget_tokens=50`**
   (deliberately tiny, vs. the default 1500, to force real eviction once a
   couple of small objects are admitted), `[vmem_admission].enabled=true`,
   `[context_structure].enabled=true`.

## Model / session

- Provider/model: `anthropic` / `claude-sonnet-5`.
- Real Prime session id: `01a01b52-a354-7028-8b65-e4c9cbf591d9`.
- RLM child id: `sub-54ee0ad7`, session name `rc4-pilot2-worker` (a fresh
  child this time, not reused, so this pilot's evidence is a clean, isolated
  session — deleted after the run per this session's child-hygiene
  practice).

## Workload

The child ran, from the disposable worktree, a real full-suite verbose
pytest run (`"<main-worktree>\.venv\Scripts\python.exe" -m pytest -vv`,
1011 tests, real execution — first attempt hit the known PYTHONHOME
pollution issue, cleared it, reran successfully), several real `git`/`grep`/
`sed` reads, deliberately triggered one real compaction via the `compact`
skill, and did one more real action afterward to prove continuity. It also
found and (in the disposable worktree only, discarded with it) corrected a
2-line documentation drift in `docs/components/artifacts-rtd.md` — reported
here as a finding, not applied to the main branch this pass (kept this
pilot strictly evidence-only).

## Raw evidence paths

- Prime session transcript (330,643 bytes, 64 records):
  `C:/Users/assas/.prime/agent/session-artifacts/01a01b1f-3ef5-73ab-addf-f467ca374e64/sub-54ee0ad7/01a01b52-a354-7028-8b65-e4c9cbf591d9.jsonl`
- Second Brain telemetry (191,909 bytes, 237 records):
  `C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/01a01b52-a354-7028-8b65-e4c9cbf591d9.jsonl`
- Per-session ledger SQLite (real `session_vmem` rows this time):
  `C:/Users/assas/Documents/The-Second-Brain/state/sessions/a1bc2b300fb517748f2b7dbaf6cb6f22c03a3550885bd5b2d688f2e629e6e5a3/ledger.sqlite`
- Sanitized bundle: `outputs/reports/rc4/raw/pilot-02/pilot-02-evidence-bundle.json`
  (privacy-verified: max free-text field across all 237 raw telemetry
  records is a 64-char sha256 hex string).

## Findings

### Observed context message schema (the pilot's primary target)

`context_structure` fired 24 times (once per `context` event), recording
ONLY types/key-names/short tokens/lengths. Aggregated across all 24 records,
the real `event.messages` element schema is:

| role | content_type | keys |
|---|---|---|
| `toolResult` (n=316) | object | content, details, isError, role, timestamp, toolCallId, toolName |
| `assistant` (n=249) | object | api, content, model, provider, responseId, role, stopReason, timestamp, usage |
| `custom` (n=42) | string | content, customType, details, display, role, timestamp |
| `custom` (n=3, variant) | string | content, customType, display, role, timestamp (no `details`) |
| `compactionSummary` (n=3) | undefined | customInstructions, retainedMessageCount, role, summary, timestamp, tokensBefore |

`assistant`/`toolResult` content-array block kinds observed: `text` (338),
`toolCall` (316), `thinking` (194) — no other kinds seen.

This is real, exact, previously-unknown schema information (RC4's own code
comments note "no live Prime session had ever captured the real message
shape" before this campaign). It is sufficient to know the field names
needed for a type-safe `{messages}` patch, but this pilot still did not
implement one (out of scope, per instructions) — a future pass could use
this schema directly rather than guessing.

### Actual tool surface

`getAllTools()`/`getActiveTools()` = `["ipython"]` again (same single-tool
RLM/IPython harness shape as pilot 1).

### AutoInject admission

AutoInject fired identically to pilot 1 (`decision: INJECT`, 4 memory items,
747 tokens, `mode: active`, `model_visible: true`). This delivery was
**admitted into VMem** for the first time — `obj-1678acbbc007`
(`RESEARCH_RESULT`, title `autoinject_delivery`, 16 estimated tokens).
**AutoInject admission count: 1.**

### RTD — eligibility reached, still did not fire; root cause now precise

`[rtd].enabled=true` and Phase C's `resolveToolClass` correctly classified
the real `%%bash` cell (`"<venv-python>" -m pytest -vv`) as canonical class
`bash` — the ipython→bash normalization worked exactly as designed. But
`rtdEligibility`'s `whitelist_commands` check compares only the **first
whitespace-separated token** of the resolved command against
`["pytest","git","rg","grep"]`. The resolved command's first token was the
**quoted python.exe path**, not the literal word `pytest` — this repo's own
`AGENTS.md`-mandated invocation style on this machine (due to a documented
`PYTHONHOME` pollution issue) starts with the interpreter path, not the
word `pytest`. So eligibility resolved to `"command"` (ineligible) before
the size check ever ran, even though the real output was 65,578+ characters
— comfortably over the 8000-char threshold. Three other real commands this
session did start with a literal whitelisted token (`git`, `git`, `grep`)
but their real outputs were 1826 / 128 / 1289 characters — all well under
threshold. **Net: RTD fired 0 times this pilot too, but for a precisely
identified, different, and more specific reason than pilot 1** (pilot 1:
tool-name mismatch, now fixed; pilot 2: command-prefix mismatch against
this project's own venv-python invocation convention, not yet fixed).
0 of 28 real `tool_result` records show any distillation marker; the
biggest (67,161 bytes per telemetry, 65,578 chars per the raw transcript)
passed through completely unreduced.

### VMem — first non-zero admission and a real STORED→RESIDENT→EVICTED cycle

The per-session ledger's `session_vmem` table has **2 real rows** this
pilot (vs. 0 in every prior session):

1. `obj-1678acbbc007` — `RESEARCH_RESULT`, "autoinject_delivery", 16 tokens,
   priority 50.0, **residency_state: EVICTED**.
2. `obj-a6a03cd84875` — `DECISION`, "pre_compaction_checkpoint", 19 tokens,
   priority 100.0, **residency_state: EVICTED**.

Both objects were inserted `RESIDENT` (per `store_object`'s own logic —
confirmed by reading `vmem.py`, not directly observed as an intermediate
telemetry event, since only the final DB state was queried), then
transitioned to `EVICTED` by the real compaction-boundary lifecycle: real
`vmem_compact_prep` telemetry reports `evicted_at_compaction: 2,
pinned_preserved: 0` — an **exact match** to both admitted objects being
evicted, none pinned. The post-compaction `vmem_hot_context` correspondingly
reports `resident_count: 0, evicted_count: 2, resident_tokens: 0`. No
RTD-artifact admission occurred (the third suggested admission point) —
not a silent failure (0 `extension_error` ledger events this session) but
simply never reached, because RTD itself never substituted anything this
pilot (see above). **STORED→RESIDENT→EVICTED was observed for 2 real
objects, naturally, with no manual population.**

### Compaction / continuation

Real `session_before_compact` (`branch_entries: 52`) → transcript
`compaction` record → real `session_compact` (`from_extension: false`) → a
second real turn cycle → second `agent_end` (`messages: 6`). Ledger
`segments` table independently confirms `seg-1`,
`started_reason: "compact"`. The transcript's own `context.messages` count
dropped `46 → 28` exactly at the compaction boundary, then grew `28 → 33`
afterward — real continuation, matching pilot 1's pattern. The child also
independently observed a real RLM-kernel-level token drop
(`compact.status()`: 74052 → 37323) — a different measurement surface,
consistent with the same real event.

### Actual usage telemetry

24 real provider turns: `input_tokens=47`, `output_tokens=10655`,
`cache_read_tokens=1031984`, `cache_write_tokens=100245`,
`cost_total=$0.5637` — sourced from `BRAIN_TELEMETRY assistant_usage`
mirroring real Anthropic responses, same as pilot 1.

## Anomalies

- RTD's root cause is now specific and different from pilot 1's (see
  above) — this project's own mandated pytest invocation style is itself
  what defeats `whitelist_commands`' literal first-token match, independent
  of the tool-name fix already landed.
- A documentation/code drift was found (`docs/components/artifacts-rtd.md`
  claimed RTD substitution was unimplemented; it is implemented and
  config-gated) — corrected only in the now-deleted disposable worktree,
  intentionally **not** ported to the main branch this pass, to keep this
  pilot strictly evidence-only per its STOP instruction. Left for external
  review to action.
- The disposable worktree directory briefly resisted deletion (Windows file
  lock held by the child process); resolved after deleting the RLM child.
  Git had already fully untracked the worktree and deleted its branch
  before this, so `brain/v1-rc4-genuine-proof` was never at risk.
- PYTHONHOME pollution (known machine issue) required clearing inside the
  child's kernel before pytest would run — not new, already documented.

## Explicitly not done in this pilot

- No `{messages}` context replacement was implemented (schema is now known
  well enough to attempt one safely in a future pass, but that is a
  follow-up decision for external review, not this pilot).
- No fix was applied for RTD's command-prefix vs. venv-python-invocation
  mismatch.
- No PROVEN/PASS status is claimed.
- No third pilot, benchmark, or ablation was started.
