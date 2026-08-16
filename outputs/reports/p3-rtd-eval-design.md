# P3-F — RTD Activation Experiment Design

Plan §11 (RTD activation). Prerequisite PROVEN live: Prime `tool_result`
handlers can replace result content (Phase A probe; SDK `ToolResultEventResult`
— `agent-session.ts` applies `hookResult.content`). Branch `brain/p3-lean-code`
@ de0a647. Baseline: vitest 368, tsc/eslint clean. NO commits, NO deployment —
the live experiment starts after the parent deploys and the user restarts the
daemon with `[rtd] enabled = true` in config/context.toml.

## 1. What is being tested

Eligible large bash results (tool=bash, first command token ∈ {pytest, git,
rg, grep}, text-only, serialized size > threshold_chars) are:

1. preserved byte-exactly through the artifact store
   (`second_brain artifact store --kind rtd_raw --tool bash --session <sid>
   --no-distill`) — sha256 content-addressed, atomic, idempotent;
2. verified recoverable (`artifact expand <sha256>` byte-compared to the raw
   text; handle must equal the TS-computed sha256 of the raw bytes);
3. ONLY THEN replaced in the model-visible tool result by the deterministic
   `[SECOND_BRAIN_RTD]` block (metadata + bounded head/tail + pytest
   failures/summary or generic head/tail + exact reopen instructions).

Any preservation/verification failure → ORIGINAL content unchanged (plan
§11.4 — never trade recoverability for savings). Binary/non-text results are
never distilled (§11.8). Error results are reduced conservatively (longer
tail, exit/error status recorded; §11.7).

## 2. Eligibility / safety matrix

| surface | behavior |
|---|---|
| tool = bash, command ∈ {pytest, git, rg, grep} (first token, case-insensitive), size > threshold | DISTILL (after preservation+verify) |
| tool = bash, other command (ls, npm, node, ...) | untouched (no distill, no record) |
| tool ≠ bash (edit, ipython, websearch, ...) | untouched |
| content contains any non-text block (image/binary) | untouched (never distill) |
| size ≤ threshold_chars | untouched |
| enabled = false | shadow record only (zero substitution) |
| artifact store fails / verify mismatch / no venv | ORIGINAL content unchanged + distilled=false record |
| error result (isError=true) | distilled conservatively (head 15%/tail 85%, error_status=true) |

## 3. Judge protocol (baseline(raw) vs candidate(distilled))

Same task, same repo state, counterbalanced order; AutoInject ACTIVE in both
arms; brain state isolated between arms (existing P3 freeze backup). For each
task the ANALYSIS phase runs these deterministic commands on BOTH arms:

```bash
# 1) task correctness (identical on both arms — must exit 0)
<task-specific verification command from TASK.md>

# 2) RTD trigger + recovery proof (candidate arm):
#    a) telemetry shows rtd_shadow with distilled=true + artifact_ref for the
#       triggered tool_result;
#    b) recovery: extract artifact_ref hash, then
python -m second_brain artifact expand <hash> > recovered.txt
cmp recovered.txt <raw-capture>     # must be byte-identical
#    (the analysis captures the raw result itself BEFORE the model sees it by
#     re-running the same command — see §5.)

# 3) visible-byte reduction (candidate arm only):
#    original_chars vs visible_chars from the rtd_shadow record:
#    require visible_chars <= original_chars * 0.5  (>= 50% reduction, §20.3)

# 4) no hidden failure evidence (candidate arm):
#    if the raw result contains failure markers (pytest FAILED/ERROR,
#    non-zero exit, "fatal:", "error:"), the distilled block MUST contain the
#    corresponding evidence (failure section / tail / error_status=true).
```

Per-triggered-result acceptance:

- correct behavior: judge exit 0 (identical to baseline);
- raw fully recoverable: `artifact expand` byte-identical (compare with the
  independently captured raw);
- visible-byte reduction ≥ 50% on triggered cases;
- no hidden failure evidence (deterministic marker scan above);
- rollback: `[rtd] enabled = false` restores raw results (no redeploy;
  config read per event).

## 4. Representative tasks (large-output, §20.3 targets)

| task | command surface | expected trigger |
|---|---|---|
| T-R1 | `python -m pytest tests/ -v` on a suite with failures | pytest class; failures + summary kept |
| T-R2 | `rg -n "def " src/` across the repo | rg; head/tail + counts |
| T-R3 | `git log -p -n 200` (or `git diff HEAD~50`) | git; head/tail + stat |
| T-R4 | `grep -rn "TODO" .` (with -r over src) | grep; head/tail + counts |
| T-R5 | failing pytest with a long traceback | pytest; error conservative (long tail, failing names) |

Each task: baseline arm sees the RAW result; candidate arm sees the distilled
block. Both arms must produce the same acceptance outcome (e.g., the model
correctly identifies the failing test / the file list / the TODO locations
from the distilled evidence + reopen if needed). The analysis records:
acceptance, rtd_shadow fields, recovery cmp result, reduction %, evidence
markers, economics (input/output/cache_read/cost per arm), reopen usage if
observable.

## 5. Evidence capture

- The analysis captures the RAW result per task independently (re-run the
  command with output to a file) BEFORE judging, so recovery comparison is
  against a trusted copy, not the arm's word.
- Telemetry: `rtd_shadow` extended fields (original_chars, visible_chars,
  saved_chars, artifact_ref, command_class, error_status, distilled) — never
  raw content (plan §11.9).
- Per-run evidence JSON at outputs/reports/p3-rtd-eval/<run-id>/ mirroring the
  P3-E layout (evidence.json + telemetry.jsonl + judge.json).

## 6. Acceptance criteria for the experiment (plan §20.3)

- visible-byte reduction ≥ 50% on triggered cases;
- correctness: no meaningful regression (identical judge exits);
- raw recovery: 100% byte-identical on triggered cases (else FAIL — the
  preservation guarantee is the top invariant);
- no hidden failure evidence on error/failure results;
- marginal economics: report input deltas (distilled arm should be ≤ baseline
  on triggered tasks, within cache-warmth caveats);
- rollback: `enabled=false` restores raw results (verifiable in one run).

## 7. Activation / rollback controls

- Activate: set `[rtd] enabled = true` in config/context.toml (read per
  event — no redeploy needed for the flip itself; the extension code must be
  deployed once by the parent, then the user restarts the daemon).
- Rollback: set `enabled = false` (or remove the key) — substitution stops on
  the next event; no uninstall, no code revert needed.
- Kill-switch safety: any artifact-store failure automatically degrades to
  raw results (fail-open), so a broken store can never hide content.
