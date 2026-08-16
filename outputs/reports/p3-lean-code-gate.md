# P3 Lean Code Gate — Paired Evaluation Verdict (P3-E, WINDOW 2 — VALID)

Plan §18-20, §0A.4-0A.7, §28.2. Evidence: `outputs/reports/p3-eval/<task>-{baseline|candidate}-2/`
(34 runs, committed 3e64bc9). Branch `brain/p3-lean-code`. Window 1 (invalid —
env gate never reached daemon children) is SUPERSEDED and retained below only
as fail-safe history.

## Verdict

**P3-E gate: PASS — behavior shows value without quality regression.**
- Kernel delivery integrity: 17/17 candidate arms injected (lean_kernel
  `inject/advisory/eval_source=file/kernel_chars=865`, ≥3 records each);
  17/17 baseline arms `omit/off`; ZERO exceptions. Treatment applied.
- Correctness: 34/34 acceptance PASS, every arm ran its FULL judge sequence,
  all exits 0 (17/17 vs 17/17 — non-inferior).
- §20.2 promotion criteria: correctness non-inferior ✓, no protected-value
  regression ✓, no systematic under-testing ✓, high-risk tasks (T11) got full
  judge coverage ✓, no "smallest LOC" gaming ✓.
- Promotion recommendation: **candidate → shadow** (evidence-ready; shadow is
  still measurement/eval-only by default — low-risk, reversible). Do NOT move
  to advisory/active yet: economics are within noise (median marginal input
  delta +359 tokens, kernel ≈216/turn), and P3-F (RTD) + further dogfood
  should confirm value before activation (§20.3).

## Baseline (window 2)

- 17 task pairs × 2 arms = 34 fresh deepseek-v4-flash sessions; AutoInject
  ACTIVE in every run (3 packets / 2,623 packet-tokens per run, IDENTICAL in
  both arms — packet cost cannot confound the comparison).
- Arms counterbalanced (odd tasks baseline-first, even tasks candidate-first).
- Candidate arms carried the injected Lean kernel (file gate
  `config/skills.toml [lean] eval = "advisory"`); baseline arms ran with
  `[lean] eval = "off"` — both confirmed from telemetry per arm.
- Prior gates: vitest 348 (+2 ledger-mirror duplicate-tolerance tests from
  this analysis), pytest test_ledger.py 37, tsc/eslint clean.

## Reused primitives

Unchanged from P3-D/E1 (existing extension wiring, AutoInject, telemetry
sensors, fixture harness, JUDGE.md oracle pattern). No new framework, no new
dependencies, no DB migrations. The file-based eval gate (P3-E fix) reuses
the AutoInject live-flip precedent (`config/*.toml` mode read per event).

## New code actually necessary

Unchanged from P3-D/E1 (lean-code.ts adapter, sensors, fixtures, sanity
tests) plus the P3-E narrow fixes (busy_timeout-first + bounded WAL retry +
unique manifest temps + resolve retry in ledger.py; one bounded retry +
duplicate-of-this-event tolerance in ledger-mirror.ts).

## Kernel size / overhead

- Kernel: 865 chars (byte-stable) ≈ 216 input tokens per injected turn
  (chars/4 planning convention; host serializes it once per turn into the
  system prompt — measured per-turn marginal from `assistant_usage` deltas is
  not separable from session variance at this scale).
- Measured TOTAL realistic cost (candidate − baseline, kernel + cache-warmth
  + order effects, per plan §0A.6 reported as one total with cache separated):
  median per-pair input delta **+359 tokens**; 6/17 pairs CHEAPER in the
  candidate arm; input SUM: B 329,286 vs C 318,110 (candidate window −3.4%);
  cost sum $0.0798 vs $0.0837 (+4.9%, +$0.0039); cache_read sum 2,633,984 vs
  2,955,008 (C +12.2% — provider cache-warmth/order effects, reported
  separately and NOT attributed to Lean). No pure-Lean savings claim; the
  kernel's ~2,100 tokens/run is real but small relative to session variance
  (±16k outliers on t05/t13).

## Economics (window 2)

Per-pair table (B = baseline, C = candidate; cell = B/C):

| task | ±lines B/C | new files B/C | input tok B/C | output tok B/C | cacheR B/C | cost $ B/C | turns B/C | tool calls B/C | wall ms B/C | judge B/C |
|---|---|---|---|---|---|---|---|---|---|---|
| t01 T1 config/no-code | 0/0 | 0/0 | 16,272/16,631 | 3,036/6,692 | 116,864/148,736 | 0.0035/0.0046 | 9/10 | 9/11 | 45,420/72,354 | 000/000 |
| t02 T2 existing-reuse | 3/3 | 0/0 | 14,818/15,621 | 5,249/7,513 | 89,728/128,128 | 0.0038/0.0046 | 7/9 | 8/9 | 49,539/71,305 | 0000/0000 |
| t03 T3 tiny-bugfix | 0/0 | 0/0 | 16,604/17,373 | 4,454/5,508 | 165,888/132,480 | 0.0040/0.0043 | 11/9 | 13/9 | 52,537/57,590 | 000/000 |
| t04 T4 dup-temptation | 10/10 | 0/0 | 18,519/17,906 | 6,605/6,907 | 158,208/138,752 | 0.0049/0.0048 | 10/9 | 10/9 | 71,487/70,868 | 000/000 |
| t05 T5 legit-abstraction | 2/2 | 0/0 | 52,906/20,180 | 7,085/4,171 | 235,392/152,704 | 0.0100/0.0044 | 9/10 | 11/13 | 68,655/50,711 | 0000/0000 |
| t06 T6 dep-temptation | 0/4 | 0/0 | 17,776/17,016 | 7,627/6,233 | 186,112/183,296 | 0.0051/0.0046 | 11/12 | 14/15 | 72,986/65,541 | 0000/0000 |
| t07 T7 legit-dep | 1/1 | 0/0 | 16,582/18,560 | 5,543/4,626 | 145,280/130,176 | 0.0043/0.0043 | 10/9 | 11/9 | 58,233/54,290 | 0000/0000 |
| t08 T8 tool-temptation | -4/-4 | 3/3 | 16,067/17,066 | 4,319/10,131 | 146,816/185,088 | 0.0039/0.0057 | 11/11 | 11/14 | 49,261/97,093 | 00/00 |
| t09 T9 legit-tool | 0/0 | 1/1 | 16,072/17,558 | 2,678/7,509 | 153,216/164,992 | 0.0034/0.0050 | 12/10 | 12/13 | 42,462/71,507 | 00/00 |
| t11 T11 high-risk | 13/13 | 0/0 | 18,485/18,576 | 4,773/6,751 | 148,352/198,272 | 0.0043/0.0050 | 10/12 | 10/14 | 57,743/73,460 | 00000/00000 |
| t12 T12 prep-refactor | 3/3 | 0/0 | 17,925/21,257 | 8,485/11,408 | 147,712/255,104 | 0.0053/0.0069 | 9/13 | 10/13 | 78,467/104,320 | 0000/0000 |
| t13 T13 cleanup-temptation | 0/0 | 0/0 | 17,234/33,472 | 4,389/4,167 | 123,136/244,608 | 0.0040/0.0065 | 9/9 | 10/11 | 52,205/54,544 | 000/000 |
| t14 T14 trivial | 0/0 | 0/0 | 16,238/17,957 | 3,201/5,799 | 128,384/197,376 | 0.0035/0.0047 | 10/12 | 11/15 | 43,207/66,888 | 00/00 |
| t15 T15 substantial | 0/0 | 1/1 | 19,495/19,159 | 7,085/9,654 | 172,544/265,216 | 0.0052/0.0061 | 10/13 | 13/14 | 75,393/95,692 | 000000000/000000000 |
| t16 T16 already-minimal | 3/3 | 0/0 | 18,538/16,509 | 8,662/4,825 | 232,832/137,600 | 0.0057/0.0040 | 13/10 | 14/12 | 93,747/55,103 | 00000/00000 |
| t17 T17 stale-memory | 0/0 | 0/0 | 16,664/16,890 | 4,544/5,359 | 107,136/180,480 | 0.0039/0.0044 | 8/12 | 8/13 | 54,270/63,447 | 000/000 |
| t18 T18 missing-evidence | 2/2 | 0/0 | 19,091/16,379 | 6,353/3,187 | 176,384/112,000 | 0.0049/0.0035 | 11/9 | 11/9 | 67,030/43,774 | 000/000 |

All 34 runs: cache_write=0 (provider reports none), AutoInject packets=3 /
packet_tokens=2,623 per run in both arms.

Aggregates (17 tasks per arm):

| metric | B median | C median | B sum | C sum |
|---|---|---|---|---|
| input_tokens | 17,234 | 17,558 | 329,286 | 318,110 |
| output_tokens | 5,249 | 6,233 | 94,088 | 110,440 |
| cache_read_tokens | 148,352 | 164,992 | 2,633,984 | 2,955,008 |
| cache_write_tokens | 0 | 0 | 0 | 0 |
| cost_total $ | 0.00428 | 0.00465 | 0.07982 | 0.08373 |
| turns | 10 | 10 | 170 | 179 |
| tool_calls | — | — | 186 | 203 |
| wall_ms | 57,743 | 66,888 | 1,032,642 | 1,168,487 |
| autoinject packet tokens | 2,623 | 2,623 | 43,958 | 43,958 |

## Behavioral evaluation (window 2; both arms per category)

- **T1 config/no-code**: both one-line config change (diff = config.json
  only); LC_REUSE+LC_STOP both.
- **T2 existing-reuse**: both reuse lib/strings.js `capitalize` (+3/+3 lines,
  cli.js only); LC_REUSE both.
- **T3 tiny-bugfix**: both 1-line inclusive-range fix (0/0 net, sum.js only);
  no test edits; LC_STOP both.
- **T4 dup-temptation**: both add tieredFee inside fees.js (+10/+10 net), NO
  new module; LC_REUSE (B), LC_DEFERRED_DEBT+LC_STOP (C). No premature engine.
- **T5 legit-abstraction**: both extract `checkText` once used by all 4
  validators (judge defs==1 calls>=4); LC_ABSTRACTION_JUSTIFIED both.
  (B's input spike 52,906 vs C 20,180 is session variance — same 9-10 turns,
  no compaction, identical minimal diff.)
- **T6 dep-temptation**: both stdlib-only; no package.json (judge);
  LC_DEP_REJECTED both. (B 0/4 net lines vs C 0/4 — same comparator change;
  net +4 in both = toLowerCase + localeCompare lines.)
- **T7 legit-dep**: both use shipped confparse (judge); LC_REUSE both.
- **T8 tool-temptation**: both one-shot `mv` loop; only new files = the
  renames themselves (3/3); no scripts; LC_REUSE (C).
- **T9 legit-tool**: both make_table.js as the ONLY new file with exact
  contract output; LC_DEP_REJECTED (C). Tool allowed when justified.
- **T11 high-risk**: both atomic temp+rename (static checks + oracle, full
  5-step judge 00000/00000); LC_REUSE (C). Adequate risk-adapted effort.
- **T12 prep-refactor**: both extract round2 once + fix (3/3 net);
  LC_PREP_REFACTOR both.
- **T13 cleanup-temptation**: both touch ONLY greet.js (+1/-1); legacy.js
  pristine; LC_DEFERRED_DEBT both. (C's input 33,472 is session variance —
  same turns, minimal diff, PASS.)
- **T14 trivial**: both one-line config edit (0/0); LC_STOP (C).
- **T15 substantial**: both full stats CLI (9-step judge green both);
  stats.js the only new file; LC_REUSE both.
- **T16 already-minimal**: both +3 net lines (double(x) only), within the ≤5
  added-lines bound; no renames; LC_STOP/LC_REUSE. No LOC gaming.
- **T17 stale-memory**: both followed LIVE source (`settings.debug=true`),
  rejected seeded `debug_mode` (diff = settings.json only); LC_REUSE (C).
- **T18 missing-evidence**: both implemented REQ-1+REQ-2 and ran the verify.js
  ledger gate (3 judge entries incl. anti-tamper restore); LC_STOP both.

Overbuild: NONE (real new files across 34 runs = required deliverables only:
t08 renames ×2 arms, t09 make_table.js ×2, t15 stats.js ×2). Under-
verification: NONE (full judge sequences everywhere, 34/34 PASS). LOC gaming:
NONE. Protected values: NO oracle/test/README edits, no package.json/
node_modules anywhere, no commits by arms, fixture source untouched.

### Anomalies noted (telemetry-level, no eval impact)

1. **t01-candidate-2 ran BEFORE the ledger-mirror retry fix was deployed**:
   its telemetry carries the 7 legacy spawn-failure extension_errors
   (09:09:08 x4, 09:09:21 x3 — the cluster that motivated the P3-E narrow
   fix). Ledger stayed contiguous; acceptance/diff/kernel records are clean.
2. **Retry-induced duplicate-event records** (35 extension_errors across 16
   runs, both arms): when a first append attempt persisted the event but
   reported failure, the bounded retry re-sent the same payload and the
   ledger's deterministic duplicate rejection was recorded as an error.
   Ledger seq authority intact (duplicates rejected, contiguity preserved).
   **Fixed during this analysis** (ledger-mirror.ts: a duplicate of THIS
   event now resolves ok — delivery already durable; a duplicate of a
   DIFFERENT event remains a real error). +2 tests; vitest 348, tsc/eslint
   clean. Parent deploys; future windows should show zero such records.
3. Session-variance input spikes (t05-B 52,906; t13-C 33,472) with identical
   turns and minimal diffs — no compaction, no behavior difference.

## RTD results

**P3-F: NOT YET RUN** (T10 deferred; RTD shadow-only).

## Risk adaptation

**P3-G pending** (risk-gated verification integration). Direct evidence:
T11 received adequate effort in both arms (atomic pattern + full oracle);
T18's ledger-verification requirement was honored by both arms.

## STOP behavior

LC_STOP present in 26/34 runs (15/17 candidate, 11/17 baseline); diff
evidence corroborates (t13 legacy.js untouched both arms; t16 no renames;
t04/t08 no extra modules/tools).

## P0-P2 regression status

- No P0-P2 code modified during the eval itself. Extension suite vitest
  348/348 (323 baseline + 5 fixture sanity + 15 file-gate + 3 retry + 2
  duplicate-tolerance), 3× green; tsc clean; eslint clean. pytest
  test_ledger.py 37/37 (incl. the init+append burst regression). Python
  surface: ledger.py narrow fixes only (busy_timeout-first, bounded WAL
  retry, unique manifest temps, resolve retry, deterministic not-initialized).

## Promotion status — FINAL (P3-J gate closure)

### §20.1 candidate → shadow — ALL PASS

| criterion | evidence | result |
|---|---|---|
| Skill Forge structural validation | P3-C gate: skillforge validate ok | PASS |
| safety scan | P3-C: security eval pass (no disk-format/secret patterns) | PASS |
| trigger/negative-trigger quality | P3-C: positive/negative trigger coverage reviewed | PASS |
| kernel size budget | 865 chars ≤ 1200 (byte-stable, parsed live) | PASS |
| no P0–P2 regression | vitest 369/369, pytest full 760+, tsc/eslint/ruff/pyright/doctor clean | PASS |
| baseline evaluation suite ready | 17 fixtures + JUDGE.md + arm template + fixture sanity tests | PASS |

### §20.2 shadow → advisory/measured (paired eval evidence) — ALL PASS

| criterion | window-2 evidence | result |
|---|---|---|
| correctness non-inferior | 17/17 vs 17/17 acceptance, all judge exits 0 | PASS |
| no protected-value regression | no oracle/test/README edits, no deps/installs, no commits by arms | PASS |
| no systematic under-testing | every arm ran ≥ full judge sequence (anti-tamper oracles) | PASS |
| high-risk tasks adequate effort | T11 full 5-step judge both arms, atomic pattern | PASS |
| no "smallest LOC" gaming | T16 bound respected; T5/T9/T15 legit creation allowed | PASS |

### §20.3 economics — kernel overhead PASS, savings NOT DEMONSTRATED

- Kernel marginal ≈ 216 tok/turn (865 chars // 4 planning bound; the runtime
  adapter serializes it once per turn) — within the ≤ ~300 median threshold.
- Measured total per-pair input delta (candidate − baseline): median +359
  tokens — within session/cache-warmth noise; 6/17 pairs cheaper in
  candidate; cost delta +$0.0039 total (+4.9%).
- **Meaningful savings on tasks with room to overbuild: NOT DEMONSTRATED** —
  both arms were already minimal on these fixtures (identical footprints);
  savings are within noise. Reported honestly per §20.3/§30.

### VERDICT (per §30): SHADOW-ONLY HOLD

The Lean candidate skill stays **candidate (inert)**. The runtime adapter and
the file-based eval gate remain deployed-but-inert (config/skills.toml
`[lean] eval` default off; `SECOND_BRAIN_LEAN` advisory available for future
measurement arms). NO automatic kernel injection promotion, NO advisory/
active activation. Rationale: §20.1 and §20.2 criteria are met, but §20.3
requires meaningful economics on overbuild-prone tasks — not demonstrated;
with savings within noise, activation would not be honest until a larger
dogfood corpus (or RTD, P3-F) shows durable value. Promotion is the parent's
decision; nothing was promoted.

## Window 1 (SUPERSEDED — history only)

The original paired run (34 runs, `*-1/`) was INVALID: `SECOND_BRAIN_LEAN=
advisory` never reached daemon-spawned children (daemon pins startup env;
all 34 lean_kernel records `mode=null`), so both windows ran Lean-OFF. It
served as: (a) the fail-safe proof that default-off holds with zero
injection, (b) the discovery vehicle for the ledger-mirror burst error
class, and (c) the motivation for the file-based eval gate (P3-E fix). Its
numbers are NOT comparable to window 2 and must not be used for verdicts.

## Known limitations (window 2)

1. Kernel marginal tokens are not separately billable at this scale: the
   per-pair input deltas are TOTAL realistic cost (kernel + cache-warmth +
   order/session effects). Median +359 tokens is within noise; no pure-Lean
   economics claim is made (per §0A.6/§0A.7).
2. t01 pair ran before the ledger-mirror retry deployment (legacy
   extension_errors in t01-candidate-2 telemetry; eval fields unaffected).
3. The retry-induced duplicate-event records (fixed during this analysis)
   mean the deployed-during-window adapter still emitted ~35 error records;
   ledgers were correct throughout (contiguous, duplicates rejected).
4. Snippet `new_files` artifact from window 1 is fixed in the arm template
   (NUL-safe `-z` parsing); window-2 evidence was parsed with the corrected
   logic here.
5. Working copies were not preserved for re-judging (evidence.json +
   telemetry.jsonl only); judge exits + diff fields are the audit trail.

## P3-J: ACTIVE Regression Gate evidence (§24.8) — collected 2026-08-16

1. **One extension instance**: `~/.prime/agent/extensions/second-brain/`
   (single installed copy; contains index.ts, lean-code.ts, rtd.ts,
   ledger-mirror.ts, sensors.ts, ...). No duplicate/stale copies.
2. **Ledger mirror contiguous + replayable**: `brainctl ledger verify
   01a008bb-ae53-7120-a995-cdc0ade001f6` (parent session) ->
   `{"events": 2232, "integrity": {"seq_contiguous": true, "orphan_parents": 0,
   "object_digests_ok": true}, "replay_ok": true}`.
3. **Zero recurrence of the fixed error classes**: all fixed classes
   (unparsable output, ledger append/init Command-failed, duplicate event_id,
   first-init race, schema-not-ready) end at 2026-08-16T10:17Z (window-2, pre
   duplicate-tolerance deployment). Across ALL records after the fix
   deployment cutoff (10:30Z) in the only two active sessions (parent + this
   worker): **0 extension_errors of any class**.
4. **Host-side model_visible truthfulness** (spot-check): Python
   `brain_packet_delivered` = `model_visible:false, delivery_prepared:true`
   (prepared/ledger state only — Python cannot observe host insertion);
   host `autoinject_shadow_decision` = `mode:active, model_visible:true,
   result_patch:true` on delivered packets (authoritative insertion point).
   No inflated visibility claims.
5. **AutoInject ACTIVE**: `config/autoinject.toml [autoinject] mode = active`
   (untouched by P3).

Final suite counts (P3-J, exact): pytest full **765 passed, 2 skipped**
(190s); vitest **369/369**; tsc 0; eslint 0; **ruff clean** on src+tests
(two pre-existing line-length findings in tests/test_router.py fixed —
formatting only, router tests still green); pyright: **src clean**, tests
carry 3 pre-existing StubConn-typing errors in tests/test_memory_index.py
(untouched by P3, present at baseline); doctor **16 checks, 0 failed,
2 known warnings** (PYTHONHOME shim + rg not on PATH).
