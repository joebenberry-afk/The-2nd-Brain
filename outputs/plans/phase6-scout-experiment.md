# Phase 6 — Scout: baseline vs Scout experiment protocol (plan §102)

Acceptance requires comparing baseline vs Scout before any promotion. Scout
stays tool-only (never auto-triggered) in this phase.

## Tasks (ground truth known to the lead, not given to participants)

- T1 (localization): "Where does the Prime observability extension append the
  rtd_shadow record, and what function decides the trigger?"
  Ground truth: brainstem/prime-extension/src/index.ts (tool_result handler,
  rtd wiring) + src/rtd.ts shouldDistill.
- T2 (localization+context): "Which Python module validates requirement status
  values, and where is the material-unverified gate computed?"
  Ground truth: src/second_brain/working_set.py (REQUIREMENT_STATUSES +
  check_requirements).

## Protocol (each task, both arms; fresh flash sessions)

1. BASELINE arm: fresh prime-agent print session (tools ipython,bash, cwd=repo)
   with ONLY the task text. The session solves it; the lead records: wall
   time, tool calls, tool-result bytes, context peak, answer vs ground truth
   (correct/partial/wrong).
2. SCOUT arm: `brainctl scout run <repo> --task <text>` fills an Evidence Map in an
   isolated session (its trajectory never enters the lead context); then a
   fresh session receives the SAME task + the map file path (Tier-2 style).
   Same measurements.
3. Metrics source: telemetry/agent-performance JSONL via
   `brainctl telemetry report` + per-session record analysis (deterministic
   script); wall time measured by the orchestrator; correctness judged against
   ground truth.

## Promotion rule

Promote Scout to advisory (default suggestion in later phases) only if:
- T1+T2 scout-arm success >= baseline-arm success, AND
- scout-arm tool calls or tokens meaningfully lower, AND
- lead-context pollution measurably lower (map only, not the trajectory).
Anything else: keep Scout manual-only and record why.

## Outputs

- Evidence maps: outputs/evidence-maps/<slug>.md
- Experiment ledger: outputs/reports/milestone-06-scout.md (tables per arm)
