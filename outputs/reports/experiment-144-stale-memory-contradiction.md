# Experiment 4 (§144) — Stale Memory Contradiction

Date: 2026-08-14. Intentional stale memory (per the experiment spec): the
claim "the skill security detector flags any occurrence of the word
'format' in a skill" was TRUE before the experiment-3 detector fix and is
FALSE after it — a genuine stale claim, not a fabricated one.

## Flow actually run

1. Created memory `mem-f21a28b715f1` ("Skill security detector flags
   'format' anywhere") grade OBSERVED, curated to current.
2. Ran the contradicting REAL task first, against the repo (ground truth):
   `skillforge.security_review` on a skill containing "ruff format" ->
   passed=True. REPO WINS.
3. Reconsolidation: retrieval recorded (retrieval 2); activation recorded
   as `contradicted` (activation 2); heat set COLD.
4. Semantic update: curated labile + HISTORICAL, then superseded ->
   `mem-f21a28b715f1` v2 with the corrected body, change note and sources.
5. History: v1 and v2 both preserved (memory/semantic/...md and
   ...__v2.md); v2 is current.

## Expected vs actual (§144)

| Expected | Actual |
|---|---|
| repo wins | yes (security_review passed=True before any memory was consulted) |
| memory marked labile | yes (status=labile, grade=HISTORICAL) |
| reconsolidation event | yes (retrieval + activation=contradicted, heat COLD) |
| semantic update | yes (v2 supersedes with corrected claim) |
| history preserved | yes (v1 + v2 on disk) |

## Honest note

The memory was created already-stale (the detector fix landed in
experiment 3, minutes earlier). That is exactly the experiment's intent:
introduce a stale memory and prove the contradiction path, on a claim whose
staleness is real rather than invented.
