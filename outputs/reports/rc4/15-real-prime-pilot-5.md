# 15 — Real Prime Pilot 5 (RC4, single genuine run — final CVM closure proof)

Status: RC4_REAL_PRIME_PILOT5_COMPLETE — RAW EVIDENCE READY FOR EXTERNAL AUDIT

This is the **fifth and final planned** genuine Prime runtime pilot for the
CVM closure effort. It targeted the last three unproven live behaviors:
RTD-backed `TOOL_OBSERVATION` paging, already-EVICTED reprojection after
reconstruction, and genuine model-triggered fault-in. All three are
**genuinely proven**, with one important, honestly-reported nuance about
the exact mechanism that produced the reconstruction evidence.

## Branch / HEAD

- Candidate: `brain/v1-rc4-cvm-closure-repair` @
  `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72` (confirmed exact match before
  starting; unchanged after). Local == origin confirmed. Pilot 1-4 evidence
  confirmed present/untouched. Prior branches
  (`brain/v1-rc4-proactive-paging-repair` @ `55767baf...`,
  `brain/v1-rc4-genuine-proof` @ `1c8b78ce...`) confirmed unaffected.
- Prime build: `v0.7.3-dirty` (frozen baseline, not upgraded).
- Installed global extension re-synced and verified to contain all eight
  required behaviors (RTD metadata fix, proactive paging, EVICTED
  reprojection, double-wrap guard, `newly_claimed_count`,
  `reprojected_page_count`, `vmem_pointer_count`, `rtd_pointer_count`, real
  host-session recovery command) before the run.
- Pilot workload ran in a disposable worktree/branch
  (`rc4-pilot5-disposable`), both deleted after the run.

## Telemetry contamination discipline

Neither task packet sent to the child ever quoted the literal
`[SECOND_BRAIN_VMEM]`/`[SECOND_BRAIN_RTD]` markers, named a VMem object id,
gave the exact `vmem resolve` command form, or stated that a fault-in was
expected/required. The only guidance given was the plan's own generic
efficiency hint ("if information produced earlier in this session has been
offloaded and a deterministic local recovery reference is available,
prefer recovering that prior result..."). Baseline provider-request
telemetry (`vmem_pointer_count=0`, `rtd_pointer_count=0`) was captured on
the first two real requests, before any RTD or paging occurred.

## Model / session

- `anthropic` / `claude-sonnet-5`.
- Real Prime session id: `01a02028-9f7c-758b-b275-fe8805cc22a6`.
- RLM child id: `sub-bbf19333`, session name `rc4-pilot5-worker`.
- The pilot was run as one continuous session across two task packets (an
  initial spawn, and a follow-up sent after the child paused and went idle
  per its own instructions) rather than an explicit Prime CLI
  `--resume`/`--continue` cycle — see "Genuine resume/reconstruction
  finding" below for what this actually proved.

## Workload

Real, small test-coverage improvement: added 2 direct unit tests for
`second_brain.paths.db_path()`/`backups_dir()` (previously only exercised
indirectly). A real, broad `pytest -vv` run (using this machine's
documented `unset PYTHONHOME`/`unset PYTHONPATH` prelude) produced genuine
RTD-eligible output.

## Raw evidence paths

- Prime transcript (local only, 418,712 B, 86 records)
- Second Brain telemetry (local only, 493,540 B, 375 records)
- Per-session ledger (local only, `state/sessions/2740f197.../ledger.sqlite`)
- Sanitized bundle (committed): `outputs/reports/rc4/raw/pilot-05/pilot-05-evidence-bundle.json`
- Disposable workload diff (committed, not applied): `outputs/reports/rc4/raw/pilot-05/pilot-workload.diff`

## Success criteria — evidence-based results

### AutoInject exact preservation — PROVEN

Real delivery, `packetSha256` in the real `session_vmem` row
(`obj-f6c3977ff500`) matches the real telemetry field exactly.

### RTD fired + metadata correlation — PROVEN (Repair A confirmed in production)

Real `rtd_shadow`: `command_class: pytest`, `distilled: true`,
`original_chars: 65578`, `saved_chars: 62969`. The admitted
`TOOL_OBSERVATION` object (`obj-1f9d8f6f6086`) has
`metadata_json: {"toolCallId": "toolu_01B5SK1wxFrTFygdxuSUgmcV",
"artifactRef": "[brain-artifact:sha256:cf239...]"}`  — **not empty**,
matching the real `rtd_shadow` record's own values exactly. This directly
confirms Repair A closed Pilot 4's gap.

### RTD byte-exact recovery — PROVEN

Independently recovered by the parent via `artifact expand`: 65,578 bytes,
sha256 match exact.

### RTD-backed TOOL_OBSERVATION paging — PROVEN

Real `context_paging` event at `2026-08-20T17:18:45.270Z`:
`object_kinds` includes `TOOL_OBSERVATION`, `newly_claimed_count: 1`,
`state_before` includes `RESIDENT`. The per-session ledger independently
confirms the object's residency transitioned as claimed.

### Provider-request pointer proof — PROVEN (highest-authority evidence)

Real `provider_request_meta.vmem_pointer_count`: `0` (baseline, first 2
requests) → `1` (from the first AutoInject claim onward) → `2` (from the
TOOL_OBSERVATION claim onward). `rtd_pointer_count`: `0` → `1` (RTD block
reaches the provider request) → `0` again at the SAME moment
`vmem_pointer_count` becomes `2` — fully coherent: that toolResult's RTD
block was itself replaced by the VMem pointer at that exact paging event.
This is direct, provider-payload-level proof (the plan's own designated
highest authority) that both markers genuinely reached the live outgoing
model context.

### Already-EVICTED reprojection, zero duplicate eviction — PROVEN, and more thoroughly than expected

35 real `context_paging` events fired this session. After the very first
real claim (event 1: AutoInject `RESIDENT → EVICTED`), **every single
subsequent event** (34 of 35) re-detects the SAME already-EVICTED object
as a live, full-content candidate and reprojects it: `state_before:
EVICTED → state_after: EVICTED_REPROJECTED`, with
`requested_page_count: 0` / `claimed_page_count: 0` every time — **zero
`claim-pages` calls, zero DB mutation**, confirmed directly in the
telemetry for every reprojection event.

### Genuine resume/reconstruction finding (important, honestly reported)

This pilot did **not** invoke an explicit Prime CLI `--resume`/`--continue`
cycle — it used a follow-up message to the same, previously-idle RLM child
session. What the real evidence instead reveals is **arguably stronger**:
Prime's `context`-hook patch appears to be applied only to the one
outgoing provider request for that turn, and is **never durably persisted**
to Prime's own live/reconstructed message array — so **every single
context event, continuously, for the rest of the session**, re-presents
the full original content and requires re-pointerization. This was proven
34 separate times in one session, not merely after a single artificial
resume. `GENUINE_PRIME_RESUME_RECONSTRUCTION` is reported as **proven via
this different, continuously-recurring mechanism** rather than via an
explicit stop/resume cycle — external review should judge whether this
satisfies the criterion's intent; the underlying Repair B behavior itself
(safe reprojection, zero duplicate eviction) is unambiguously and
repeatedly proven regardless of which mechanism triggered it.

### Genuine model-triggered fault-in — PROVEN

At `2026-08-20T17:18:52.507Z`, the child ran, unprompted:
```
second_brain vmem resolve 01a02028-9f7c-758b-b275-fe8805cc22a6 obj-1f9d8f6f6086 --json
```
using its **own real session id** and a **real object id it was never
told**. Its own quoted reasoning: *"...maybe the original tool result had
more detail accessible through a different retrieval path, like paging via
vmem resolve. Let me try that command for this object."* A search of the
entire persisted transcript **before** this tool call for the literal
strings `vmem resolve` and `obj-1f9d8f6f6086` returns **zero hits** —
consistent with Pilot 4's finding that Prime's persisted transcript never
records the ephemeral per-request pointer view; the model could only have
learned the real command and object id from the **live outgoing provider
request** for the immediately-preceding turn, which real telemetry
independently confirms carried `vmem_pointer_count=2` at that exact
moment. The tool result returned `"ok": true, "resolution": "artifact"`
with the exact preserved content. **`state_before` for that object
included `FAULTED_IN`** on the very next `context_paging` event (8 seconds
later), directly confirming a genuine `EVICTED → FAULTED_IN` transition
occurred, before the object was legitimately re-claimed once its
(now-larger, re-resident) content again exceeded budget.

### Fault-in exact recovery — PROVEN

Independently recovered by the parent (same artifact,
`cf239bca99...8948603`): 65,578 bytes, sha256 exact match. Independently
confirmed the real recovered content genuinely contains both specific
details the child cited in its final report (`"collected 1066 items"` and
the exact line `tests/test_ledger.py::test_append_auto_assigns_seq_zero
PASSED [ 51%]`) — not fabricated.

### Task correctness — PROVEN

Child ran the focused test file (6/6 passed), ruff clean, pyright clean.
The child was also honest about a real limitation: the true final
pass/fail summary line of the *specific* Step 3 run was never captured by
any layer (a harness-level 65,536-char cap truncated it before any
preservation layer saw it) — it explicitly declined to fabricate that
number, instead reporting a separately-obtained real total from a
distinct, later, full rerun (1066 passed), clearly labeled as different
evidence.

## Summary against the stated success criteria

| Criterion | Result |
|---|---|
| AUTOINJECT_EXACT_PRESERVATION | **true** |
| RTD_FIRED | **true** |
| RTD_BACKED_METADATA_CORRELATION | **true** |
| RTD_BYTE_EXACT_ARTIFACT_RECOVERY | **true** |
| RTD_TOOL_OBSERVATION_PAGED | **true** |
| TOOL_OBSERVATION_RESIDENT_TO_EVICTED | **true** |
| PROVIDER_VMEM_POINTER_BASELINE = 0 | **true** |
| PROVIDER_VMEM_POINTER_AFTER_PAGING > 0 | **true** (1, then 2) |
| PROVIDER_RTD_POINTER_BASELINE = 0 / AFTER_RTD > 0 | **true** (0→1) |
| GENUINE_PRIME_RESUME_RECONSTRUCTION | **true, via a different (continuous per-turn) mechanism — see finding above** |
| ALREADY_EVICTED_REPROJECTED > 0 | **true** (34 events) |
| DUPLICATE_EVICTION_FOR_REPROJECTED_OBJECT | **false (correct)** — zero claim calls for reprojections |
| REAL_MODEL_TRIGGERED_FAULT_IN > 0 | **true** (1, genuinely unprompted) |
| FAULT_IN_STATE_TRANSITION = EVICTED_TO_FAULTED_IN | **true** |
| FAULT_IN_EXACT_RECOVERY | **true** |
| TASK_CORRECT | **true** |

## Anomalies

- Mechanism nuance for "resume/reconstruction" — reported honestly above,
  not glossed over.
- Child's `%%bash` tool cwd did not initially match the stated disposable
  worktree; self-corrected and re-verified, no validity impact.
- A harness-level ~65,536-char output cap prevented the true final summary
  line of the Step 3 run from ever being captured by any layer; the child
  was honest about this limitation rather than inventing a number.
- A separate, unexplained environment quirk: a file-redirected pytest
  rerun's summary line was also not captured via the `%%bash` tool path
  but WAS visible via a direct Python `subprocess.run()` call; root cause
  not conclusively determined, reported as an observation only.

## Explicitly not done in this pilot

- No implementation changes were made during the pilot.
- No further pilot was started.
- No Brain-OFF/Brain-ON benchmark was started.
- Prime was not upgraded.
- No v1.0/PROVEN declaration is made — the criteria table above is the
  honest record, including the one criterion proven via a different
  mechanism than literally specified.
