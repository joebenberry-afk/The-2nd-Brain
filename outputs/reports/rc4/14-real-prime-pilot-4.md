# 14 — Real Prime Pilot 4 (RC4, single genuine run — proactive paging repair verification)

Status: RC4_REAL_PRIME_PILOT4_COMPLETE — RAW EVIDENCE READY FOR EXTERNAL AUDIT

This is the **fourth** genuine Prime runtime pilot, the first to run against
the proactive-paging-repair candidate (`brain/v1-rc4-proactive-paging-repair`)
and directly test whether the two Pilot 3 defects (RTD multi-line `%%bash`,
late/compaction-coupled eviction) are actually fixed under real runtime
conditions. The main objective — proactive paging *before* compaction — is
proven genuinely, with real telemetry. RTD firing and byte-exact recovery
are also proven genuinely. Genuine model-triggered fault-in did not occur
this run (honest negative). A new, real, exact defect was discovered
during independent evidence inspection and is reported, not fixed.

## Branch / HEAD

- Candidate: `brain/v1-rc4-proactive-paging-repair` @
  `28a88c341a6cc1d87ad497a70c557c04d09d4cc2` (confirmed exact match before
  starting; unchanged after). Local == origin confirmed. Pilot 1-3 evidence
  files confirmed present/untouched. `brain/v1-rc4-genuine-proof` confirmed
  unaffected at `1c8b78ce97d419edf92662ef92f31ec2b9826bac`.
- Prime build: `v0.7.3-dirty` (frozen baseline, not upgraded).
- Pilot workload ran in a disposable worktree/branch (`rc4-pilot4-disposable`),
  both deleted after the run.

## Pre-run setup

Re-synced the global Prime extension from this exact HEAD; verified the
installed copy contains the RTD approved-prelude grammar
(`APPROVED_BASH_PRELUDE_LINES`), the proactive-paging bridges
(`runVmemListPrePageSync`, `runVmemClaimPagesSync`/`claim_pages`), and the
real-hostSessionId pointer template (confirmed the rendered line uses
`${opts.hostSessionId}`, not the literal `<session_id>` placeholder — that
placeholder now appears only in a doc comment, never in rendered output).
Cleared `%TEMP%/jiti`. Enabled in the MAIN worktree's `config/context.toml`:
`[rtd] enabled=true`, `[vmem] enabled=true budget_tokens=50`,
`[vmem_admission] enabled=true`, `[context_structure] enabled=true`,
`[context_paging] enabled=true pin_recent_messages=4
resident_token_budget=100 max_pages_per_context_event=3`.

## Model / session

- `anthropic` / `claude-sonnet-5`.
- Real Prime session id: `01a01edb-1c05-736f-a8b8-905cbdfb38cb`.
- RLM child id: `sub-d033902f`, session name `rc4-pilot4-worker`.
- **Anomaly**: the child's kernel actually started in the MAIN worktree
  cwd rather than the disposable worktree; it self-corrected via `%cd`
  early on and confirmed clean/correct HEAD/branch afterward — no impact
  on evidence validity.

## Workload

Real CLI UX fix: `second_brain vmem list --state <bad>` / `--kind <bad>`
previously silently returned an empty list (indistinguishable from "no
matching objects"); now validates against the real `ResidencyState`/
`SessionObjectKind` enums and fails clearly (exit 2, stderr listing valid
values). A real `%%bash` cell matching Pilot 3's exact breaking pattern
(`unset PYTHONHOME` / `unset PYTHONPATH` / canonical pytest invocation) was
run early. The child discovered and correctly worked around a real
environment quirk: the shared `.venv`'s editable `second_brain` install
always resolves to the MAIN worktree's `src` regardless of cwd, so its
disposable-worktree code edit needed an explicit `PYTHONPATH` override to
be exercised by subprocess-invoked CLI calls (including its own
`test_cli.py`-style tests).

## Raw evidence paths

- Prime transcript (local only, 433,106 B, 143 records):
  `C:/Users/assas/.prime/agent/session-artifacts/01a01b1f-3ef5-73ab-addf-f467ca374e64/sub-d033902f/01a01edb-1c05-736f-a8b8-905cbdfb38cb.jsonl`
- Second Brain telemetry (local only, 1,037,234 B, 575 records):
  `C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/01a01edb-1c05-736f-a8b8-905cbdfb38cb.jsonl`
- Per-session ledger (local only):
  `C:/Users/assas/Documents/The-Second-Brain/state/sessions/dd7a0c0a5ad7fae8cd1fa3309e7e16918e19aa91500b360dbeaebeacf108952c/ledger.sqlite`
- Sanitized bundle (committed): `outputs/reports/rc4/raw/pilot-04/pilot-04-evidence-bundle.json`
  (privacy-verified: max free-text field across 575 telemetry records is an
  88-char content-addressed artifact handle string, not prompt/tool text)
- Disposable workload diff (committed, not applied): `outputs/reports/rc4/raw/pilot-04/pilot-workload.diff`

## Success criteria — evidence-based results

### AutoInject exact preservation — **PROVEN**

Real `brain_packet_delivered` (4 items, 745 tokens) → `autoinject_shadow_decision`
(`decision: INJECT`, `packet_sha256:
e1eab477abef9cf8e200bce6efd012da4e2060f27c873ce4b033aa2746ec8cd5`). The
per-session ledger's `session_vmem` row for `obj-c07f5b7caa68` (RESEARCH_RESULT)
has `metadata_json` containing `packetArtifactRef`/`packetSha256` that
**matches the telemetry field exactly** — real, verified preservation, not
a manual insertion.

### RTD fired — **PROVEN** (repair confirmed working)

Real `%%bash` cell: `unset PYTHONHOME` / `unset PYTHONPATH` /
`"<venv-python>" -m pytest -vv` — exactly Pilot 3's breaking pattern. Real
`rtd_shadow` telemetry: `command_class: "pytest"`, `distilled: true`,
`original_chars: 65578`, `visible_chars: 2609`, `saved_chars: 62969`,
`artifact_ref: [brain-artifact:sha256:81cbbeadc0...]`. The child
independently confirmed the model-visible tool_result was a real
`[SECOND_BRAIN_RTD]`-substituted block (quoted its exact header verbatim).
**This directly confirms the RTD multi-line `%%bash` repair works under
real runtime conditions.**

### RTD byte-exact recovery — **PROVEN**

Independently recovered by the **parent** (not the child, per the plan's
"supported deterministic recovery mechanism" check) via
`second_brain artifact expand 81cbbeadc0f33987f44a4dee8a3b0b27c392138e5a179e9b4a5e3203c8948603`:
recovered exactly 65,578 bytes, recomputed sha256 =
`81cbbeadc0f33987f44a4dee8a3b0b27c392138e5a179e9b4a5e3203c8948603` — an
**exact match** to the original raw output's hash. The recovered content is
genuine pytest output (verified head/tail), including Prime's own
65,536-char ipython-tool truncation marker, faithfully preserved verbatim.

### VMem admission — **PROVEN** (2 real objects)

`obj-c07f5b7caa68` (RESEARCH_RESULT, AutoInject) and `obj-737affd6d8a2`
(TOOL_OBSERVATION, RTD) — both real, both content-addressed, confirmed via
the per-session ledger.

### Proactive page claim / context paged / tokens reduced — **PROVEN** (the pilot's main objective)

Real `context_paging` telemetry record, fired at `2026-08-20T11:08:04.827Z`
— **only ~13 seconds after session start, and before any compaction ever
occurred** (no `session_before_compact`/`session_compact` event exists
anywhere in this session):

```json
{
  "paged_count": 1, "candidate_count": 1, "eligible_count": 1,
  "pressure_estimated_tokens": 802, "resident_budget": 100,
  "requested_page_count": 1, "claimed_page_count": 1,
  "estimated_tokens_before": 802, "estimated_tokens_after": 128,
  "estimated_tokens_removed": 674,
  "object_kinds": ["RESEARCH_RESULT"],
  "state_before": ["RESIDENT"], "state_after": ["EVICTED"]
}
```

`PROACTIVE_PAGE_CLAIM = 1 > 0`. `CONTEXT_PAGED_COUNT = 1 > 0`.
`PAGING_ESTIMATED_TOKENS_AFTER (128) < PAGING_ESTIMATED_TOKENS_BEFORE (802)`.
The per-session ledger independently confirms `obj-c07f5b7caa68`'s
`residency_state` is `EVICTED`. The `provider_request_meta` record for the
same turn (2ms later) confirms the paging patch was applied to the actual
outgoing provider request. **This is the first genuine, real proof that
VMem eviction can happen independently of Prime's own compaction boundary
— exactly the defect Pilot 3 found and this repair branch was built to
fix, now confirmed working under live runtime conditions.**

### A new, real, exact defect discovered (not fixed this pass)

Only 1 of 2 admitted VMem objects (the AutoInject one) was ever a paging
candidate. The RTD `TOOL_OBSERVATION` object (`obj-737affd6d8a2`) has
`metadata_json: "{}"` — **empty**. Reading
`brainstem/prime-extension/src/index.ts` directly: the RTD admission call
site (`vmemAdmit(session, "TOOL_OBSERVATION", "rtd_artifact", {...})`) is
invoked with only 4 arguments — the 5th `metadata` parameter (which the
AutoInject admission call site DOES pass) is never provided. Since
`context-paging.ts`'s `byToolCallId` correlation map reads ONLY
`obj.metadata.toolCallId`/`artifactRef` (no fallback to the object's
`content` JSON, unlike `vmem.py`'s `resolve_object` which DOES fall back),
an RTD-backed object can **structurally never become a paging candidate**
— it stayed `RESIDENT` for the entire session. This precisely explains why
only the AutoInject object was ever claimed. Fault-in via `vmem resolve`
would still work fine for this object (that path's content-fallback covers
it) — this is specifically a **paging-eligibility gap**, not a
recoverability gap. **Not fixed this pass**, per Pilot 4's evidence-only
discipline; collected and reported for a future narrow repair pass.

### Genuine model-triggered fault-in — **NOT PROVEN** (honest negative)

`REAL_FAULT_IN = 0`. The child never invoked `vmem resolve` (0 occurrences
in the transcript) and reported never seeing a `[SECOND_BRAIN_VMEM]`
pointer anywhere in its own context (verified via its own grep of its raw
session log). Cross-checked by the parent: the paging patch is applied to
the live provider-request payload (and, structurally, to Prime's live
in-memory context used to build subsequent requests) but is **not**
reflected back into Prime's own persisted `custom_message` transcript log
— the two original session-start custom messages are still recorded there
at their full original lengths, with no separate "paged" version ever
logged as its own transcript entry. Whether the model itself ever visually
noticed the pointer in a live turn could not be independently confirmed
from available evidence; the child simply never had cause to re-examine
that early portion of context during its real work. Reported honestly as
`REAL_FAULT_IN = 0 — NOT PROVEN`, not forced or fabricated.

### Compaction — did not occur (by choice, per plan guidance)

The child checked `compact.status()` (~7% kernel token usage) and
correctly chose not to force compaction, per the plan's explicit "do not
force it" guidance. `COMPACTION_CONTINUATION` is N/A this run.

### Task correctness — **PROVEN**

Independently re-verified by the parent (not just the child's report):
directly invoked the disposable worktree's own fixed CLI
(`PYTHONPATH`-overridden) — `vmem list ... --state NOT_A_STATE` → exit 2,
correct error message and valid-value list. `ruff check` on both changed
files → clean.

### Actual provider usage — captured, no savings claim

63 real provider turns: `input_tokens=125`, `output_tokens=22153`,
`cache_read_tokens=2865387`, `cache_write_tokens=83161`,
`cost_total=$1.0028` — sourced from `BRAIN_TELEMETRY assistant_usage`
mirroring real Anthropic responses. Kept explicitly separate from the VMem
local estimated-token figures above (802→128, a local deterministic
estimate only). No OFF control exists yet; no savings claim is made.

## Summary against the stated success criteria

| Criterion | Result |
|---|---|
| AUTOINJECT_EXACT_PRESERVATION | **true** |
| RTD_FIRED | **true** |
| RTD_BYTE_EXACT_RECOVERY | **true** |
| VMEM_REAL_ADMISSION > 0 | **true** (2) |
| PROACTIVE_PAGE_CLAIM > 0 | **true** (1) |
| CONTEXT_PAGED_COUNT > 0 | **true** (1) |
| PAGING_ESTIMATED_TOKENS_AFTER < BEFORE | **true** (128 < 802) |
| REAL_FAULT_IN > 0 | **false** (0) |
| FAULT_IN_EXACT_RECOVERY | N/A (no fault-in occurred) |
| TASK_CORRECT | **true** |
| COMPACTION_CONTINUATION | N/A (compaction did not occur, by choice) |

Pilot 4's main objective — genuine proactive paging before compaction — is
proven. RTD firing and byte-exact recovery are proven. Genuine
model-triggered fault-in did not occur and is reported as an honest
negative, alongside a newly discovered, exact, real defect (RTD admission
metadata gap) that explains a related limitation and was deliberately left
unfixed this pass.

## Anomalies

- Child's kernel started in the wrong cwd (main worktree instead of
  disposable worktree); self-corrected, no evidence-validity impact.
- Shared `.venv` editable install always resolves Python code from the
  MAIN worktree regardless of cwd; the child correctly discovered and
  worked around this via `PYTHONPATH` override; documented for future
  pilots.
- New defect discovered: RTD-backed VMem admissions never attach
  `metadata.toolCallId`/`artifactRef`, making them structurally ineligible
  for proactive paging (though still fully fault-in-recoverable via the
  content-fallback path). Not fixed this pass.

## Explicitly not done in this pilot

- The newly discovered defect was not fixed.
- No further pilot was started.
- No Brain-OFF/Brain-ON benchmark was started.
- Prime was not upgraded.
- No PROVEN/PASS status beyond the specific, evidence-backed criteria
  table above.
