# P3-E Paired Evaluation — Harness Design (P3-E1)

Branch `brain/p3-lean-code` @ 032d31e. Plan §18 (evaluation design), §19
(metrics), §20 (promotion), §0A.4–0A.7 (experimental control), §16.3 (LC
decision codes). Baseline known: vitest 323 (extension suite; +5 fixture
sanity tests in `tests/lean-fixtures.test.ts`).

## 1. Arms (plan §0A.4)

| arm | composition |
|---|---|
| BASELINE | P0–P2 + ACTIVE AutoInject + P3-B/C/D instrumentation, Lean influence OFF (skill is candidate; `SECOND_BRAIN_LEAN` unset) |
| CANDIDATE | identical, Lean influence ON via the P3-D eval mode: parent sets `SECOND_BRAIN_LEAN=advisory` at spawn → kernel injected for driver/worker sessions even while the skill is candidate |

AutoInject is NOT the experimental variable: it is ACTIVE in both arms.
Arms are blinded (identical prompt template; the env difference is invisible).

## 2. Fixture inventory (plan §18.2; T10 deferred to P3-F — RTD-specific)

`brainstem/prime-extension/tests/fixtures/lean-code-tasks/` — 17 inert,
self-contained, pure-Node (no deps, no network) project-shaped fixtures.
Every fixture ships TASK.md (TASK PROMPT / ACCEPTANCE / BASELINE HINT) and
JUDGE.md (deterministic commands). Validated: every fixture FAILS its judge
unmodified (real task gap) and PASSES with the reference minimal solution.

| fixture | category | what the judge pins |
|---|---|---|
| t01-config-reuse | T1 config/no-code | debug via config only; diff = config.json only |
| t02-existing-reuse | T2 existing function reuse | `title` CLI must require lib/strings.js |
| t03-tiny-bugfix | T3 tiny bug fix | inclusive range fix; diff = sum.js only |
| t04-duplication-temptation | T4 no premature abstraction | tieredFee added; NO new files/modules |
| t05-legit-abstraction | T5 abstraction is allowed | shared `checkText` defined once, called ≥4× |
| t06-dep-temptation | T6 no new dependency | stdlib sort; no package.json appears |
| t07-legit-dep | T7 dependency accepted when justified | load.js must use shipped `confparse` |
| t08-tool-temptation | T8 no new tool | renames via one-shot; no new files outside data/ |
| t09-legit-tool | T9 new tool justified | make_table.js = ONLY new file, output exact |
| t11-high-risk | T11 persistence/safety | atomic temp+rename; no stray files; oracle passes |
| t12-prep-refactor | T12 preparatory refactor allowed | shared `round2` once; bug fixed |
| t13-cleanup-temptation | T13 unrelated cleanup deferred | diff = greet.js only (legacy.js untouched) |
| t14-trivial | T14 trivial task | diff = config.json only |
| t15-substantial | T15 substantial independent task | full stats CLI: exact output, exit codes 1/2, oracle |
| t16-already-minimal | T16 already-minimal | total added lines ≤ 5; no renames |
| t17-stale-memory | T17 live source beats stale memory | settings `debug:true`; no `debug_mode`; diff = settings.json |
| t18-missing-evidence | T18 ledger verification step | pristine verify.js passes (REQ-1 AND REQ-2) |

## 3. Judge strategy (deterministic, identical for both arms)

- Commands are bash (git-bash) + node + git ONLY (verified on this machine).
- Run from the ARM COPY root, which the protocol git-initializes with a
  baseline commit BEFORE the arm starts (`git init -b main` + commit), so
  `git diff`/`git status` measure exactly the arm's footprint.
- Anti-tamper rule (step 0 in every JUDGE.md): restore the pristine oracle
  (test.js / verify.js) from the FIXTURE SOURCE before judging — an arm can
  never pass by editing its own tests. Fixtures ship COMPLETE oracles
  (acceptance tests for the new feature already present, failing at
  baseline), so "add tests" is never required of the arm.
- Every command must exit 0; any non-zero = acceptance FAIL. Analysis
  records each command's exit code + tail output into judge.json.
- All 17 judges were validated both ways: unmodified fixture FAILS (real
  gap), reference minimal solution PASSES.

## 4. Run protocol (per task pair)

Per task, the parent runs ONE baseline arm and ONE candidate arm (both fresh
`deepseek/deepseek-v4-flash` children — fresh context per arm is a genuine
requirement, plan §18.1 "same model class"). RLM depth is capped at 1 on
this daemon (mem-d2f7df353130): ARM SESSIONS CANNOT SPAWN THEIR OWN WORKERS.
T15 therefore measures "substantial work completed thoroughly with
verification" rather than depth-2 delegation; orchestration fan-out stays a
parent-side decision (plan §12.2).

1. **Prepare** — copy the fixture to a disposable path
   `<TEMP>/p3-eval/<run-id>/work`, `git init -b main` + baseline commit.
   Copy `TASK.md`'s TASK PROMPT section verbatim into the arm prompt
   (ACCEPTANCE/BASELINE HINT never reach the arm; the BASELINE HINT is
   analysis-only).
2. **Arm run** — parent spawns a fresh v4-flash child with the arm template
   (outputs/reports/p3-eval-arm-template.md), substituting `<SLUG>`,
   `<COPY_PATH>`, `<SESSION_ID>`, and the env gate (candidate arm:
   `SECOND_BRAIN_LEAN=advisory`; baseline: unset). The arm writes
   `<work>/evidence.json` (economics + judge exits + diff + LC codes).
3. **Capture before restore** — analysis copies OUT, BEFORE any Brain
   restore: `<work>/evidence.json`, the arm's telemetry file
   (`telemetry/agent-performance/<SESSION_ID>.jsonl` → per-run dir), the arm
   report, and the working copy (for re-judging). Telemetry is derived data
   and may be reverted by the restore; evidence must leave first.
4. **Brain-state isolation (plan §0A.5/§18.1.1)** — between arms of a pair,
   the parent restores the Brain from the P3 freeze backup
   `backups/backup-20260816-060200-676435` (full DB file set; per
   mem-29557f93448f the restore must move the DB file set aside, drop stale
   `-wal`/`-shm` sidecars after the copy, and verify the restored sha256).
   Identical memory/index/config/project state for both arms; baseline
   writeback can never leak into the candidate arm.
5. **Judge** — analysis runs JUDGE.md on the arm copy (step 0 restores the
   oracle), records exits + outputs to `<run-id>/judge.json`.
6. **Ordering counterbalance (plan §0A.6)** — pairs alternate:
   odd-numbered tasks (t01, t03, …) run BASELINE-first, even-numbered tasks
   (t02, t04, …) run CANDIDATE-first. Record the order per run in
   manifest.json.

## 5. Evidence layout

`outputs/reports/p3-eval/<run-id>/`:

| file | producer | content |
|---|---|---|
| manifest.json | parent/analysis | task slug, arms order, session ids, timestamps, brain-backup id |
| evidence.json | arm (template §4) | economics sums, judge exits, diff stat, LC codes, acceptance |
| telemetry.jsonl | copied | raw arm telemetry (copied BEFORE restore) |
| judge.json | analysis | per-command exit codes + tails |
| arm-report.md | arm | the arm's return-contract report |
| diff-stat.txt | analysis | `git diff --numstat` + porcelain of the copy |

## 6. Evidence JSON schema (arm-written)

```json
{
  "run_id": "t03-baseline-01",
  "task": "t03-tiny-bugfix",
  "arm": "baseline | candidate",
  "session": "<session id>",
  "economics": {
    "assistant_usage_rows": 12, "input_tokens": 104789, "output_tokens": 79273,
    "cache_read_tokens": 12306816, "cache_write_tokens": 0, "total_tokens": 12490878,
    "cost_total": 0.071326,
    "autoinject_packets": 2, "autoinject_packet_tokens": 995,
    "tool_calls": {"bash": 4, "ipython": 9, "edit": 2},
    "turns": 8, "wall_ms": 420000
  },
  "judge": [{"command": "node test.js", "exit": 0}],
  "diff": {"changed_files": ["sum.js"], "added_lines": 1, "deleted_lines": 1, "new_files": []},
  "files_touched": 1,
  "lc_decisions": ["LC_REUSE"],
  "acceptance": "PASS"
}
```

The arm template contains ONE deterministic node snippet that computes the
economics + diff object from the arm's telemetry file and git, so every arm
produces identical-shaped evidence. AutoInject packet tokens are ALWAYS
separate from Lean cost (plan §0A.7).

## 7. Metrics mapping (plan §19)

- Correctness/safety (§19.1): judge exit codes; material requirements verified
  = t18 verify.js; security/integrity = t11 atomicity checks.
- Code surface (§19.2): git diff --numstat/--name-only + porcelain (files,
  LOC, new files/deps/tools/abstractions) — from the copy, mechanically.
- Economics (§19.3): evidence.json (input/output/cacheRead/cacheWrite/total/
  cost, turns, tool calls, wall time). Compactions, if any, from telemetry
  kind `session_compact`.
- Exploration (§19.4): telemetry `context` message counts, `tool_call`
  volumes, `provider_request_meta` system_prefix_sha epochs — no new
  instrumentation.
- Orchestration (§19.5): depth-1 constraint documented; fan-out width is 0
  for arms by design (arms are workers); parent-side orchestration costs are
  out of the paired scope and noted in the report.
- Maintainability (§19.6): independent verifier (analysis) qualitative pass
  on each candidate diff (understandable patch, no clever compression, no
  unjustified abstraction, no unrelated cleanup).

## 8. Economics reporting rules (plan §0A.6/§0A.7/§18.1.2)

- Report logical/input tokens, cache-read, cache-write, billed cost as
  SEPARATE dimensions; never claim Lean savings from a warm provider cache
  (ordering is counterbalanced to expose this).
- TOTAL realistic cost (Prime + ACTIVE AutoInject + Lean) and MARGINAL Lean
  delta (candidate − baseline) both reported; AutoInject packet tokens
  reported separately and never attributed to Lean.
- Lean kernel marginal tokens come from `assistant_usage` deltas between
  arms; the chars//4 estimate (865 → ~216 tokens) is only the planning bound.

## 9. LC decision codes (plan §16.3 — self-reported ONLY when material)

`LC_REUSE`, `LC_NEW_TOOL_JUSTIFIED`, `LC_DEP_REJECTED`, `LC_DEP_ACCEPTED`,
`LC_PREP_REFACTOR`, `LC_ABSTRACTION_JUSTIFIED`, `LC_DEFERRED_DEBT`, `LC_STOP`.
The analysis corroborates each code against the mechanical diff signals
(new files/deps/abstractions, stop-shaped diffs) — no code is judged on
self-report alone.

## 10. Promotion mapping (plan §20.2/§20.3)

- correctness non-inferior: candidate judge pass rate == baseline, no
  protected-value regression, no systematic under-testing (oracles are
  fixture-owned and tamper-proof);
- temptation tasks (T4/T6/T8/T13): zero unnecessary new
  dependencies/tools/cleanup (judge shape checks);
- already-minimal (T16): no forced complexity reduction (≤5 added lines);
- high-risk (T11): adequate effort (atomic pattern + oracle);
- kernel overhead: median marginal ≤ ~300 input tokens from live deltas;
- if token savings are within noise but overbuilding is materially reduced
  without quality loss, report that honestly (plan §20.3).

## 11. Dogfood/simplification decisions (this harness)

- No new framework: fixtures are plain Node files; judges are bash+node+git
  command lists; the only "tooling" added is one 5-test sanity file
  (`tests/lean-fixtures.test.ts`).
- Oracles ship WITH fixtures (complete acceptance tests, failing at
  baseline) so arms never write tests and anti-tamper is one copy command.
- No per-fixture judge scripts: JUDGE.md IS the executable spec (numbered
  commands); validated mechanically against references.
- T17 seeds the stale memory INSIDE the task prompt (marked advisory) — a
  stand-in for an AutoInject packet — so the real Brain stays untouched and
  isolation is preserved.
- T10 omitted per parent instruction (RTD-specific → P3-F).
