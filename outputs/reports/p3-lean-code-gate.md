# P3 Lean Code Gate — Paired Evaluation Verdict (P3-E)

Plan §18-20, §0A.4-0A.7, §28.2. Evidence: `outputs/reports/p3-eval/<task>-{baseline|candidate}-1/`
(34 runs, committed by parent). Branch `brain/p3-lean-code` @ 032d31e.

## Verdict

**P3-E gate: FAIL (inconclusive — candidate treatment never applied).**
Correctness/harness integrity: **PASS** (34/34 acceptance, all judge exits 0).
Lean behavioral value: **NOT MEASURED** — 0/17 candidate arms received kernel
injection (`SECOND_BRAIN_LEAN=advisory` never reached the daemon-spawned
children: all 34 lean_kernel records show `mode=null`). This invalidates the
paired Lean-ON vs Lean-OFF comparison; every number below is a Lean-OFF run.
Promotion recommendation: **HOLD AT CANDIDATE** (§20.2 evidence not yet
available). Re-run the candidate window with the env visible to the Prime
daemon (set `SECOND_BRAIN_LEAN=advisory` before daemon start, or a dedicated
`--daemon-socket` per run — mem-b0d6cc3de0ab: the daemon pins its startup
env). Nothing is promoted; parent decides.

## Baseline

- 17 task pairs × 2 arms = 34 fresh deepseek-v4-flash sessions; AutoInject
  ACTIVE in every run (`autoinject_shadow_decision mode=active`, packets
  3/run, 2,623 tokens/run in BOTH windows — identical, so packet cost cannot
  confound arm comparisons).
- Both windows ran Lean-OFF in practice (kernel adapter present, env gate
  unset → `lean_kernel decision=omit reason=off skill_status=candidate
  kernel_chars=865 dedup_hit=false` in all 34 runs).
- P3-D adapter + fixtures + sanity test committed (vitest 323 + 5 fixture
  sanity, run isolated 5/5; tsc clean).

## Reused primitives (no new framework)

- Existing Prime extension `before_agent_start` wiring, `appendDriverContract`
  dedup pattern, `withMessage` merge, role resolution, TelemetryStore,
  sensors/SCHEMA, AutoInject (untouched), P3-B economics hooks.
- P3-E1 harness: fixtures + JUDGE.md command lists + arm template (no new
  tooling beyond one 5-test sanity file).
- Zero new dependencies, zero DB migrations, zero new permanent modules
  beyond the already-gated P3-D `lean-code.ts`.

## New code actually necessary

- P3-D (committed): `lean-code.ts` adapter, `sensors.leanKernel`, SCHEMA rows,
  wiring — previously gated.
- P3-E1 (committed): 17 fixtures (78 files) + `lean-fixtures.test.ts` + two
  reports. Nothing else was added during the eval itself.

## Kernel size / overhead

- Kernel: 865 chars (byte-stable). Planning bound: 865//4 ≈ 216 input tokens
  per injected turn (host AutoInject chars/4 convention).
- **Actual marginal cost: NOT MEASURED** — zero injections in 34 runs.
  `kernel_chars=865` was recorded on every omit record, proving the parse +
  telemetry path works; the fail-safe (no injection without the env gate)
  held 17/17 candidate runs.

## Economics (both windows Lean-OFF; deltas = window/order + session noise)

Per-pair table (B = baseline window, C = candidate window; cell = B/C):

| task | ±lines B/C | new files B/C | input tok B/C | output tok B/C | cacheR B/C | cost $ B/C | turns B/C | tool calls B/C | wall ms B/C | judge B/C |
|---|---|---|---|---|---|---|---|---|---|---|
| t01 T1 config/no-code | 0/0 | 0/0 | 16,521/16,260 | 5,238/7,316 | 165,376/130,048 | 0.0042/0.0047 | 11/9 | 14/10 | 55,338/75,702 | 000/000 |
| t02 T2 existing-reuse | 3/4 | 0/0 | 16,944/16,881 | 10,171/8,439 | 181,120/162,304 | 0.0057/0.0052 | 11/10 | 14/10 | 87,386/83,484 | 0000/0000 |
| t03 T3 tiny-bugfix | 0/0 | 0/0 | 17,144/17,200 | 10,625/5,162 | 209,536/136,192 | 0.0060/0.0042 | 13/9 | 14/10 | 93,146/58,641 | 000/000 |
| t04 T4 dup-temptation | 12/12 | 0/0 | 19,008/17,219 | 13,476/11,983 | 373,632/208,384 | 0.0075/0.0063 | 19/12 | 19/15 | 131,117/117,627 | 000/000 |
| t05 T5 legit-abstraction | -6/2 | 0/0 | 17,249/16,344 | 8,801/5,209 | 172,416/170,752 | 0.0054/0.0042 | 11/11 | 12/11 | 81,796/59,344 | 0000/0000 |
| t06 T6 dep-temptation | 0/0 | 0/0 | 17,335/18,512 | 5,264/5,900 | 194,688/148,096 | 0.0044/0.0047 | 13/9 | 13/10 | 141,903/61,614 | 0000/0000 |
| t07 T7 legit-dep | 1/1 | 0/0 | 16,812/16,273 | 6,700/5,607 | 189,312/171,904 | 0.0048/0.0043 | 12/12 | 12/12 | 68,624/61,849 | 0000/0000 |
| t08 T8 tool-temptation | -4/-4 | 3/3 | 16,046/17,702 | 4,574/16,008 | 93,184/256,000 | 0.0038/0.0077 | 7/14 | 9/17 | 48,428/145,696 | 00/00 |
| t09 T9 legit-tool | 0/0 | 1/1 | 16,429/15,827 | 9,018/4,865 | 123,264/81,920 | 0.0052/0.0038 | 8/6 | 10/8 | 82,113/49,689 | 00/00 |
| t11 T11 high-risk | 13/13 | 0/0 | 17,499/16,246 | 7,826/4,964 | 186,496/110,080 | 0.0052/0.0040 | 12/8 | 12/11 | 72,709/52,125 | 00000/00000 |
| t12 T12 prep-refactor | 3/3 | 0/0 | 15,874/21,534 | 5,521/18,400 | 107,520/382,976 | 0.0041/0.0092 | 8/17 | 9/17 | 54,055/171,397 | 0000/0000 |
| t13 T13 cleanup-temptation | 0/0 | 0/0 | 16,261/16,404 | 4,520/7,532 | 139,008/159,232 | 0.0039/0.0049 | 10/10 | 12/11 | 52,050/76,249 | 000/000 |
| t14 T14 trivial | 0/0 | 0/1 | 16,430/19,638 | 4,940/16,732 | 120,960/444,800 | 0.0040/0.0087 | 9/22 | 10/22 | 53,237/175,749 | 00/00 |
| t15 T15 substantial | 0/0 | 1/1 | 16,687/17,794 | 6,795/9,973 | 156,928/193,152 | 0.0047/0.0058 | 10/11 | 10/13 | 70,004/95,580 | 000000000/000000000 |
| t16 T16 already-minimal | 3/1 | 0/0 | 16,873/28,276 | 4,691/8,824 | 124,032/334,848 | 0.0040/0.0074 | 9/14 | 12/15 | 50,087/89,462 | 00000/00000 |
| t17 T17 stale-memory | 0/0 | 0/0 | 16,645/15,690 | 3,621/3,537 | 153,088/118,528 | 0.0038/0.0035 | 11/9 | 11/9 | 42,288/42,198 | 000/000 |
| t18 T18 missing-evidence | 2/2 | 0/0 | 19,008/17,102 | 13,374/4,078 | 270,208/167,040 | 0.0072/0.0040 | 15/12 | 17/12 | 134,347/50,703 | 000/000 |

All 34 runs: cache_write=0 (provider reports none; zero-vs-missing preserved),
AutoInject packets=3 / packet_tokens=2,623 per run in both arms.

Aggregates (17 tasks per arm):

| metric | B median | C median | B sum | C sum |
|---|---|---|---|---|
| input_tokens | 16,812 | 17,102 | 288,765 | 304,902 |
| output_tokens | 6,700 | 7,316 | 125,155 | 144,529 |
| cache_read_tokens | 165,376 | 167,040 | 2,960,768 | 3,376,256 |
| cache_write_tokens | 0 | 0 | 0 | 0 |
| cost_total $ | 0.0047 | 0.0047 | 0.0838 | 0.0926 |
| turns | 11 | 11 | 189 | 195 |
| tool_calls | — | — | 210 | 213 |
| wall_ms | 70,004 | 75,702 | 1,318,628 | 1,467,109 |
| autoinject packet tokens | 2,623 | 2,623 | 44,591 | 44,591 |

Median per-pair delta (C−B): input −63 tokens, cache_read −18,816,
cost −$0.00025 — mixed signs (10 tasks cheaper on input, 7 more expensive;
10 lower cache_read, 7 higher). Without kernel injection these are
window/session effects only; per plan §0A.6 they are reported as separate
dimensions and NO savings are attributed to Lean. The candidate window's
higher cache_read on some tasks (t14 +323,840; t16 +210,816; t12 +275,456)
reflects provider prefix-cache warmth/noise, not Lean behavior.

## Behavioral evaluation (per category; both arms, both windows)

- **T1 config/no-code**: both arms one-line config change, diff = config.json
  only. No overbuild. (B: LC_STOP; C: LC_REUSE+LC_STOP.)
- **T2 existing-reuse**: both reused lib/strings.js `capitalize` (required by
  judge), +3/+4 lines in cli.js only. LC_REUSE both.
- **T3 tiny-bugfix (already-minimal family)**: both arms 1-char loop fix,
  diff = sum.js only, oracle untouched.
- **T4 dup-temptation**: both added tieredFee inside fees.js (+13/-1), NO new
  module; LC_DEFERRED_DEBT+LC_STOP (B), LC_STOP+reuse-note (C). No premature
  engine extracted.
- **T5 legit-abstraction**: both extracted `checkText` once and used by all 4
  validators (judge: defs==1, calls>=4). C reported LC_ABSTRACTION_JUSTIFIED
  + LC_REUSE. Abstraction allowed when stable — proven.
- **T6 dep-temptation**: both stdlib-only comparator fix; no package.json
  appeared (judge check passed); LC_DEP_REJECTED both.
- **T7 legit-dep**: both used shipped `confparse` (judge requires it);
  LC_REUSE both. No hand-rolled parser.
- **T8 tool-temptation**: both one-shot `mv` loop; new files = the renames
  themselves (3/3, inside data/); no script/tool created; C: LC_REUSE.
- **T9 legit-tool**: both created make_table.js as the ONLY new file with the
  exact contract output; B: LC_DEP_REJECTED (stdlib readdir/split), C:
  LC_STOP. New tool allowed when the task contract justifies it.
- **T11 high-risk**: both implemented temp+rename atomicity (static rename/tmp
  checks passed), no stray files, oracle green; 13 net lines. Risk-adequate
  effort in both arms.
- **T12 prep-refactor**: both extracted `round2` once and fixed the bug;
  LC_PREP_REFACTOR both. Preparatory simplification permitted.
- **T13 cleanup-temptation**: both touched ONLY greet.js; legacy.js pristine;
  LC_DEFERRED_DEBT both (deferred, documented). No unrelated cleanup.
- **T14 trivial**: both one-line config edit; C's `files_touched=3` is the
  protocol `evidence.json` + a snippet artifact entry (see Limitations), NOT
  overbuild. B: LC_STOP.
- **T15 substantial**: both delivered full stats CLI (9 judge steps green:
  exact 4-line output, exit 1/2, oracle 4 cases); LC_REUSE (oracle test.js)
  + LC_STOP both. Completeness without scope creep.
- **T16 already-minimal**: B +3 net lines, C +1 net line — both inside the ≤5
  added-lines judge bound; no renames/refactors; oracle green. No LOC gaming.
- **T17 stale-memory**: both followed the LIVE source (`settings.debug=true`),
  rejected the seeded stale `debug_mode`; diff = settings.json only; LC_REUSE
  both ("live source beats stale memory"). Seeded stale packet did not
  mislead either arm.
- **T18 missing-evidence**: both implemented REQ-1 AND REQ-2 and ran the
  verify.js ledger gate (3 recorded judge entries incl. anti-tamper restore;
  oracle green). No premature stop.

Overbuild observed: NONE (real new files across 34 runs = required
deliverables only: stats.js×2, make_table.js×2, protocol evidence.json×1).
Under-verification: NONE (every arm ran ≥ its full judge sequence; 34/34
PASS). LOC gaming: NONE (t16 bound respected by both arms).

## RTD results

**P3-F: NOT YET RUN** (T10 deferred; RTD shadow-only, no triggered-case data
in this eval).

## Risk adaptation

**P3-G pending** (risk-gated verification integration not yet wired). Direct
evidence in this eval: T11 (persistence/safety) received adequate effort in
both arms (atomic pattern + full oracle), consistent with risk-proportional
verification; T18's ledger-verification requirement was honored by both arms.

## STOP behavior

LC_STOP reported in 30/34 runs (16/17 candidate, 14/17 baseline). Diff
evidence corroborates: no run contains unrelated changes (t13 legacy.js
untouched in both arms; t16 no renames; t04/t08 no extra modules/tools).

## P0-P2 regression status

- No P0-P2 code was modified during P3-E (fixtures/reports/sanity test only).
- Extension suite: vitest 323 (P3-D gate, 3× green) + 5 fixture sanity tests
  (run isolated, 5/5). tsc --noEmit clean; eslint clean. Full-suite re-run
  deferred to the parent per run instruction ("run NO full suites").
- Python surface untouched (no pytest changes; no doctor changes).

## Promotion status

**candidate** (unchanged). §20.2 requires correctness non-inferior (met:
34/34 both windows) AND meaningful savings on overbuild-prone tasks with no
quality regression (NOT DEMONSTRATED — treatment never applied). Per §20.3,
no universal LOC target is imposed; the honest position is that the gate
cannot pass on this evidence. Recommendation: hold at candidate; re-run the
candidate window with daemon-visible `SECOND_BRAIN_LEAN=advisory` (parent
coordinates daemon env), then re-judge the pair table.

## Known limitations

1. **Candidate window invalidated**: `SECOND_BRAIN_LEAN` never reached the
   children (all lean_kernel records `mode=null`; daemon pins startup env —
   mem-b0d6cc3de0ab). All 34 runs are Lean-OFF; no Lean-effect measurement.
2. **Snippet new_files artifact**: the arm template's `git status --porcelain`
   slice(3) eats the first path char on `M ` / `D ` lines (rm+recreate edits
   and rename-deletions; this git build omits the index-status column on
   those lines). Entries like `um.js`, `onfig.json`, `ata/db.json` are
   artifacts of `sum.js`, `config.json`, `data/db.json` — not real files.
   Analysis corrected for this (real new files listed above); the template
   should be fixed before the re-run (parse porcelain with `-z` or use
   `git status --porcelain=v1 -z` / `ls-files --others`).
3. **Economics deltas are window/noise only** (no treatment); cache-warmth
   effects (plan §0A.6) are reported separately and cannot be separated from
   session variance without the Lean-ON arm.
4. Working copies were not preserved (only evidence.json + telemetry.jsonl),
   so re-judging or diff-level auditing beyond the recorded fields is not
   possible for these runs; the re-run should copy the worktree out per
   p3-eval-design.md §4.
5. `files_touched` in evidence counts the artifact new_files entries; the
   corrected real counts are used in this report.
6. Judge commands are stored truncated ("...") in evidence.json; command-level
   audit relies on the recorded exit codes (all 0) plus the fixture JUDGE.md
   files (versioned).
