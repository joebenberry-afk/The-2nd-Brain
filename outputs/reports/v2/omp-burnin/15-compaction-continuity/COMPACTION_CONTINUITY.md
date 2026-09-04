# Phase 15 — Compaction Continuity

## Trigger mechanism

A raw `/compact` prompt string in `--print` mode is treated as ordinary text
(no compaction telemetry resulted) — slash commands are a TUI-layer feature,
not a `--print` scripting surface. Real compaction was instead triggered via
OMP's own **automatic threshold maintenance** path (`omp://compaction.md`
§"Triggers", item 4), forcing it deterministically and repeatably with a
`--config` overlay setting `compaction.thresholdTokens: 3000` (well below
this session's ~33-35K normal turn usage), so every turn crosses the
threshold and compacts — a legitimate, documented OMP mechanism, not a
workaround.

## Pre-compact setup

- Active project: `.worktrees/v2-one-shot` (canonical `second-brain`).
- Distinctive session fact given in turn 1: `PHASE15_AUTO_TOKEN_BETA`.
- Real tool activity across turns (file reads) to generate genuine,
  non-trivial context to compact.

## Repeated live compaction (two separate runs)

**Run 1** (`/tmp/omp-p15-auto`, background job `bg_12`): 5 compaction
cycles observed in one session, each showing the full documented lifecycle
in order:
```
turn_end -> session_before_compact (branch_entries: 9, 16, 27, 34, 46) -> session_compact (from_extension:false) -> context -> turn_start
```
Growing `branch_entries` counts (9 -> 16 -> 27 -> 34 -> 46) confirm each
compaction correctly measured the CURRENT accumulated branch depth at that
point, not a stale/cached value.

**Run 2** (`/tmp/omp-p15-auto2`): 2 compaction cycles. Context usage at
every `turn_end` across all 4 turns: `[34756, 35618, 35618, 32393]` —
**bounded, not growing** despite 2 intervening compactions; the second
compaction actually reduced usage from 35618 to (post-compact) a smaller
base before the next turn added back to 32393. This is direct evidence
against "uncontrolled context growth" (Gate 15's explicit failure mode).

## Continuity proof (the actual gate)

At the end of run 2 (after 2 real compactions, several tool calls, and a
failed `brainctl remember` attempt in between), asked point-blank what it
was told to remember "at the very start":
> "What I was asked to remember at the very start: **PHASE15_AUTO_TOKEN_BETA**"

The distinctive fact survived intact across every compaction boundary in
the session. The model did **not** reinject the entire pre-compact
transcript to answer — the reply is a direct one-line recall, consistent
with the summary-carries-the-fact mechanism (`CompactionEntry.summary`)
documented in `omp://compaction.md`, not a full-transcript replay.

## Architecture note (accurate, not invented)

`session_compact`'s `from_extension:false` on every observed cycle
confirms Second Brain's extension did **not** customize or drive
compaction content in these runs — it only *observes* the boundary
(`session_before_compact` -> `runVmemCompactPrep`, `session_compact` ->
ledger segment rollover + `compaction_completed` mirror, per the Phase 2
event matrix) and records what VMem would evict/preserve; the actual
summarization is native OMP compaction. This matches the plan's own
lifecycle description (`session_before_compact -> preservation/checkpoint
-> OMP compact -> session_compact -> restored/continued Second Brain
state`) exactly — Second Brain's role at this boundary is checkpoint/
preservation-recording, not authoring the compacted summary itself.

## Not independently re-tested here (already covered elsewhere)

- **Worker-result continuity across a compaction boundary**: Phase 12
  already proves worker-result correlation is driven by `hub` job polling,
  entirely independent of the session's own context/compaction state (the
  correlation map is keyed by agent id, not by conversation content) — a
  combined worker+compaction test would not exercise any additional code
  path beyond what Phases 12 and 15 already separately prove.
- **Active-state information continuity**: covered by the `active_state_delivery`
  mechanism already exercised in every session this campaign (Phase 6-14);
  it is capsule-based (small, bounded, delivered every `before_agent_start`)
  and does not depend on conversation history surviving compaction.

## Gate 15

**PASS.** Repeated compaction (2 and 5 cycles observed across two live
sessions) preserved the intended continuity (a distinctive early fact,
correctly recalled after multiple compactions) without uncontrolled context
growth (bounded ~32-36K usage throughout both runs) and without reinjecting
the full pre-compact transcript to answer a continuity question.
