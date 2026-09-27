# Evaluation methodology audit

Read-only investigation. No repository files changed, no suites/builds/formatters run, no live model campaign launched. Existing campaigns are evidence about OMP 18.3.1 + `deepseek/deepseek-flash`, low thinking, **not** evidence that transfers to the owner's OpenAI coding agents. All proposed live experiments below use **`openai-codex/gpt-6-astra`, medium thinking**, through the existing subscription; no DeepSeek or OpenRouter. Proposed cost estimates are tokens and latency, not dollars.

## Top findings

### 1. The correctness oracle has demonstrated false positives and false negatives; repair it before interpreting success rates. **HIGH**

Evidence: `scripts/v3_value_suite.py:196-202` only requires case-insensitive regex-group presence. It does not check semantic polarity, completeness, behavioral outcome, or source support. The 986-line test module tests that matcher mechanically (`tests/test_v3_value_suite.py:37-65`); its authored-task check verifies counts/IDs/nonempty groups, not truth (`:618-629`).

I executed the real matcher, without launching a model. Both deliberately wrong answers passed:

- M01: “Never clear PYTHONHOME or UV_INTERNAL__PYTHONHOME; SRE stdlib corruption cannot happen.”
- M07: “SECOND_BRAIN_HOME: the daemon sees all env changes; never use a daemon-socket.”

Specific failures in `outputs/reports/v3-jit/g3-live-2/runs.json` (identify rows by `label`):

- **M07 has at least four clear false negatives among six answers.** Native R0/R1 and JIT R0/R1 explain that the daemon captured its environment at process startup and prescribe a dedicated `--daemon-socket`, but fail the enumerated phrase group. Native R1 says “resolves SECOND_BRAIN_HOME once at its own startup … exported value never reaches it”; JIT R1 says “env … is captured once when the daemon itself is spawned.” These are the requested semantics. Reported M07 correctness is 0/3 in both arms. Human semantic adjudication is necessary; expanding the regex synonym list is not a principled repair.
- **M01 is incompletely specified, not an impossible task.** The check requires `UV_INTERNAL__PYTHONHOME` but not `PYTHONPATH` (`tasks.jsonl:1`). `scripts/brainctl.py:11-12` clears all three. Answers repeating the two-variable environment guidance fail; an answer omitting PYTHONPATH can pass. In `g3-live-2`, native is 0/3 and JIT 1/3; the successful JIT answer actually names the third variable. Do not claim universal failure: `g3-live-full` has a native M01 success.
- **M10 mixes the external IDE protocol with this adapter's implemented subset.** The task asks for full hook result shapes and expects `permissionOverrides` or `overwrite` (`tasks.jsonl:10`). The visible adapter source explicitly returns `{}` for PostInvocation/Stop and does not install PreToolUse (`src/second_brain/adapters/antigravity.py:24-39`). Answers accurately describing that implementation fail the protocol question. This is not proof that those answers fully satisfy the prompt; it is proof that the asserted native source anchor is ambiguous/misleading. M10's alternatives also permit omission of some requested fields. Separate “what the external protocol permits” from “what our adapter currently returns,” and provide the actual protocol source to both arms.

**Impact:** archived aggregate memory scores are 17/30 native versus 22/30 JIT in `g3-live-2`, and 20/30 versus 19/30 in `g3-live-full`. Those are regex scores, not reliable coding-correctness rates. In the latter campaign, the one-point aggregate regression and per-task regressions help determine FAIL. Fix grading on frozen outputs before spending more model calls.

### 2. The suite is a directional screening rule, not a significance test; ten tasks give unstable power. **HIGH for computations; MED for extrapolation**

`paired_deltas` takes each arm's median over reps, then a task delta (`scripts/v3_value_suite.py:238-269`); `bootstrap_ci` resamples those ten task deltas (`:279-293`). `evaluate_pass_rule` ignores the confidence interval and passes memory if the point-estimate token **or** tool-call delta is negative (`:379-399`). “Non-inferior” means candidate point accuracy >= control, not a statistical non-inferiority test (`:383-385`, `:1703-1712`). Thus there is **no controlled alpha or formal 80%-power claim for its current PASS/FAIL rule**: a one-token negative median can pass. Bootstrap intervals are explicitly only reported by plan §12 (`V3x_Just_In_Time_Memory_Plan.md:771-788`).

Computed from the two complete three-repetition `runs.json` files, native versus JIT:

| Quantity | g3-live-2 | g3-live-full |
|---|---:|---:|
| SD of ten raw per-task median token deltas | 66,671 | 103,410 |
| Median within task/arm coefficient of variation over reps | 36.4% | 42.0% |
| Maximum such CV | 108.2% | 100.1% |
| SD of task log median ratios | 0.357 | 0.603 |
| SD of task differences in mean log cost | 0.412 | 0.588 |
| Estimated 30%-reduction power, n=10 tasks/r=3, two-sided paired t model | **68.2%** | **40.3%** |
| Reduction detectable with 80% power under that model | **33.7%** | **44.4%** |

Method: for each task, compute mean(log logical tokens) in each arm and subtract; tasks are the independent units, **not 30 unrelated trials**. Estimate `Var(D_i) = tau² + W/r`, where W is the average sum of the two within-task log variances. Estimated `(tau²,W)` is `(0.0141,0.4672)` for live-2 and `(0.1292,0.6513)` for full. Simulate noncentral-t power at two-sided alpha .05, 100,000 draws at n=10; sample-size search uses 50,000 draws, fixed seeds. These are planning estimates under independent-task/log-normal assumptions, not empirical causal guarantees; only ten tasks estimate variance, and several share one record.

**Required task counts to detect a 30% log-scale reduction with 80% power:**

| Reps per arm/task | live-2 variance | full variance |
|---|---:|---:|
| 1 | 32 tasks | 51 tasks |
| 2 | 18 | 31 |
| 3 | **13** | **24** |
| 5 | 9 | 19 |

Keeping ten tasks requires approximately five reps/arm in the lower-variance campaign. In the higher-variance estimate, the between-task floor leaves even infinite repetitions at approximately 79.8% power: effectively on the boundary, not a robust plan. **Buy new tasks, not twenty reruns of the same trivia.** A conservative usable design is **24–32 independent tasks ×3 reps/arm**, then re-estimate variance on the actual OpenAI model before claiming the planned power.

If retaining a median-of-log-ratios estimand instead, a normal-density asymptotic approximation gives 80%-power detectable reductions of 32.8%/48.8%, and about 13/36 tasks at three reps for a 30% reduction. This is a sensitivity calculation, **not exact power for the existing percentile-bootstrap/raw-delta gate**. The choice of estimand matters.

Correctness is even less resolved: every “family” in both manifests is just the individual task ID, so each family has three observations and accuracy moves in 33-point steps. Requiring all point estimates to be nondecreasing is not proof of non-inferiority and gets fragile as the task count increases. Even 30 independent zero-regression observations only bound regression probability above at 9.5% (one-sided 95%); 59 are needed to bound it below 5%. Repeated observations on ten tasks are weaker than 30 independent tasks.

### 3. These tasks predominantly measure repo-fact recall, and their selection has already been tuned to memory delivery. **HIGH**

Evidence: `outputs/reports/v3-agent-experience/value/tasks.jsonl:1-10` are ten short-answer questions about this Brain repository; none asks for an actual code change, passing behavior, investigation artifact, or completed workflow. M05/M08/M10 share `mem-79d7c4fd9876`, leaving eight distinct target record IDs, and three of ten tasks concern one Antigravity contract. M02 asks the almost universal “numeric migration order” rule. M04's note says an earlier task was replaced because delivery never occurred; M05's note says another was replaced because the host docs contradicted the memory. That is development-set selection, not an untouched held-out sample.

Eight of ten no-benefit tasks are self-contained echo/arithmetic/translation/formatting/explanation questions (`:11-18`). N09 runs a trivial shell expression; N10 is a real locator task declared “no benefit” because **the current memory lacks the location** (`:20`). A better locator record can make N10 beneficial. This label is not an inherent property of the user's task.

The plan calls for orientation, locator use, gotchas, recovery, supersession, cross-project knowledge, compaction/resume, and distractors (`V3x_Just_In_Time_Memory_Plan.md:790-803`); the authored set does not exercise that end-to-end breadth. The model is one cheap/weak-model configuration, and the harness disables other skills and rules (`scripts/v3_value_suite.py:1252-1271`). Its seed randomizes scheduling (`:2179-2183`); it is not passed as a model sampling seed. Correct isolation is valuable, but “same seed” does not mean deterministic/pair-matched model trajectories.

**Impact [INFERENCE]:** current evidence can locate delivery/grading defects and compare eager versus JIT overhead. It cannot establish usefulness for every coding agent, realistic coding work, or the owner's OpenAI subscription workflow.

### 4. Weighted-token accounting changes the size of apparent savings, not the complete-campaign verdicts. **HIGH**

Logical tokens `L=I+R+W+O` are useful as **context/work volume**, but not a complete objective. I is uncached input, R cache reads, W cache writes, O output. Existing native/JIT complete arms have 85.4–87.9% of L in cache reads. Counting cached tokens equally to output can badly mismatch latency/resource pressure; measuring only I is also wrong because identical prompts can have different cache splits (`tests/test_v3_value_suite.py:387-398`).

For the owner's subscription, no verified conversion from tokens/cache hits to quota or money is available. Keep the **vector** `(I,R,W,O,visible/generated reasoning when reported, wall time, requests, correctness)` and report L. For sensitivity, compute normalized resource proxies:

- `C4 = I + 0.1 R + W + 4 O`
- `C8 = I + 0.1 R + W + 8 O`
- cold-cache sensitivity: `I + R + W + 8 O`.

The discounts/weights are **[DESIGN] scenarios**, not asserted OpenAI subscription billing or latency coefficients. Report both C4/C8 rather than selecting whichever passes. Do not add `reasoningTokens` again if already included in output. Ultimately calibrate latency weights on actual OpenAI runs, or simply promote on tokens **and** latency rather than an invented exchange rate.

Recomputed below using the original median-over-reps then median-over-task-deltas aggregation. Negative delta favors the candidate. Correctness, family, missing-metric, and zero-addition gates are unchanged.

| Campaign; comparison | Memory ΔL | Memory ΔC4 | Memory ΔC8 | No-benefit ΔL / ΔC8 | Recomputed verdict, all weightings |
|---|---:|---:|---:|---:|---|
| live-2; native→JIT | -9,434.5 | -903.7 | -1,749.7 | 0 / 0 | **FAIL**: one negative-case addition |
| full; native→JIT | -323.5 | -1,428.6 | -1,726.6 | -12.5 / -100 | **FAIL**: correctness/family gates |
| full; brief→JIT | -17,932.5 | -9,677.2 | -10,207.2 | -480 / -434.1 | **PASS** under current rules |
| full; native→brief | +8,379 | +9,540.9 | +10,525 | +463 / +270.6 | **FAIL** |

For the same native→JIT memory runs, **total** logical-token savings are 3.85% in live-2 versus 30.41% in full; total C8 savings are 6.61% versus 21.21%. Geometric reductions from task median L ratios are 18.08% versus 8.74%. These answer different questions; neither “median delta / median baseline” nor cherry-picking the aggregate supports a universal “30% cheaper” claim. In full, JIT median memory wall time is actually **15.25s versus native 13.66s**, despite lower total tokens; mean memory time falls from 19.23s to 17.85s. In live-2, medians are 11.44s versus 12.23s.

Recomputed 20,000-bootstrap, seed-716 memory ΔC8 intervals: live-2 `[-13,434,+838.9]`; full native→JIT `[-8,828.2,+1,224]`; full brief→JIT `[-30,827.6,-4,578.2]`. The native comparisons remain inconclusive on this statistic; the eager-brief comparison is materially more decisive. Archived L intervals use a different seed/2,000 iterations and also cross zero for both native→JIT comparisons.

Other folders: `smoke` has one memory and one no-benefit task per arm, so it is not an efficacy sample; native→JIT remains FAIL, and C8 also makes its no-benefit token subgate fail (+115.2) despite ΔL=0, illustrating cache-split sensitivity. `g3-live-r1` retains error rows with unknown usage and remains **NOT_QUALIFIED**, not zero-cost. All four prep-eval summary folders have zero live rows and remain NOT_QUALIFIED. `g3-live` has 144 rows but no summary/manifest in the inspected folder; do not silently pool an unqualified partial campaign with the complete ones.

### 5. Zero additions and zero statistical slack are different requirements; the present gate confounds them. **HIGH**

The plan explicitly requires zero Brain-authored additions in every no-benefit request (`V3x_Just_In_Time_Memory_Plan.md:773-786`); code also checks no exposures/recovery (`scripts/v3_value_suite.py:1715-1722`). This is an appropriate deterministic **abstention contract for deliberately irrelevant triggers**, and zero private/cross-project disclosures should remain absolute. It is **not a general net-value test**:

- Any always-on orientation/tool-discovery text is disqualified regardless of downstream savings; frozen brief necessarily fails this structural condition.
- N10's label forbids a genuinely useful new locator because it was negative only relative to the old corpus.
- live-2's sole final blocker is `VG-N05-v3-jit-R1`: the agent elected to run bash for a sum-of-squares answer; JIT exposed `mem-6d592dd0c627`, 291 bytes/~73 estimated tokens. The final answer is correct and all aggregate point gates pass. Whether this environment advice was useful is not established by the label; the request-level failure is real, but it does not prove net harm.
- Zero slack on noisy measured tokens rejects harmless variation, while median zero can hide expensive outliers. It simultaneously overconstrains common overhead and underprotects tail behavior.

Replace the universal no-addition value gate with two separate reports: (a) deterministic privacy/abstention contracts on frozen negative observations; (b) deployed-mixture net tokens/latency and bounded harm, with predeclared margins. Keep genuine negative controls; do not relabel post-hoc to manufacture success.

### 6. The measurement stack is larger than the decision it currently resolves; valuable controls are mixed with obsolete experiment platforms. **HIGH for inventory; MED for deletion recommendations**

Measured line counts: value suite **2,232**, its tests **986**, matched-arms **1,524**, retrieval eval **389**, E01 latency **754**, E02 semantic **1,435**: **6,334 script lines, 7,320 including this one test file**.

- E01 measures legacy per-turn Python spawn/batched/helper variants (`scripts/v3_e01_latency.py:1-20,51-75`), not the compiled in-process JIT adapter's main decision.
- E02 implements dense/hybrid encoders, memory/network probes, and mirrored lexical/production-tail logic (`scripts/v3_e02_semantic.py:8-25,375-609`), not evidence that a delivered record helps complete code work.
- Retrieval eval calls legacy `autoinject.BrainLifecycle.prepare_injection` (`scripts/v3_retrieval_eval.py:179-203`). CI's “retrieval gates” seed/reindex legacy memory and run those dev/held-out cases on every push, with four accepted misses (`.github/workflows/ci.yml:38-64`). CI does run new core/trigger/outcome tests, but it does **not** include `tests/test_v3_value_suite.py` in its explicitly enumerated test list (`:31-37`). This is not a claim that the new core is untested; it is a mismatch between the value-harness importance and CI coverage.
- Five promotion arms, prior-training manifests, historical eager pinning, native backend qualification, and score snapshots are mandated (`V3x_Just_In_Time_Memory_Plan.md:739-788`), before a cheap oracle has shown that the corpus can solve the task. Native training even requires `cost_total` (`scripts/v3_value_suite.py:1097-1115`), unnecessary as an availability gate for the subscription objective.

Keep frozen source/corpus identity, isolated runs, randomized order, actual request accounting, child-usage accounting, unknowns/failures, and a real baseline. Those prevent genuine confounds. Stop treating every historical harness or optional scoring-control prerequisite as necessary to decide the next mechanism.

## Breakthrough candidates

### A. Oracle-first causal ladder, not another all-mechanism campaign

**Concrete change:** isolate whether memory content, retrieval, timing, or packaging creates value before implementing new delivery machinery.

Exact arms, tested only as needed:

1. **N — native:** same OpenAI host/tools/source/policies, Brain/native memory off.
2. **O — oracle:** N plus one **sufficient, existing, source-supported record** at prompt time. Maximum 160 tokens including source pointer; if it does not fit, label it insufficient rather than silently rewriting it into the solution. Human chooses relevance on a development set. Do not author from held-out solutions.
3. **S — selector-at-start:** same bytes/budget as O, but selected from the frozen corpus by the proposed actual prompt-time selector. O–S measures selection loss.
4. **T — oracle-timed:** O's exact record, held until the first observation the actual JIT trigger would match. If no observation matches, deliver nothing. O–T diagnoses timing/coverage loss.
5. **J — current JIT:** frozen actual selector, timing, and current first-sentence renderer. T–J mixes selection/rendering; if it matters, add one diagnostic **T80**, same oracle/timing but actual 80-token rendering, to isolate packaging. Do not run all six arms across every task.

**Change of kind:** obtains an upper bound on *this corpus's achievable help* before optimizing trigger engines, ranking, learning loops, or semantic retrieval. Not a universal upper bound on all possible memory.

**Expected effect [INFERENCE]:** avoids full campaigns when the record lacks the needed procedure or the task is already trivial; explains which subsystem merits work. **Effort S** for N/O, M for replay/timing arms. **Risk:** oracle leakage, inappropriate hint construction, or hand-selected friendly tasks. Freeze corpus and rubric first. **Obsoletes/defer:** mandatory five-arm discovery campaigns and scored/native-memory prerequisites before content value is demonstrated.

**Cheapest confirming experiment:** rescore the existing M07 answers and inspect whether each M10 delivery contains the answer-bearing fields (zero new model tokens), then the 72-run pilot below. If even O cannot help at all, improve content/task targeting before touching delivery. If O works but T does not, tool-result-only JIT is the wrong access surface for that family.

### B. Replay real work to choose opportunities, then spend live calls only on causal continuations

**Concrete change:** select **50 real sessions**, stratified across at least three projects and two task kinds per project; manually label **100 decision boundaries: 60 plausible memory opportunities +40 distractors**, blind to candidate delivery. Replay frozen trigger selection in scratch state, preserving cwd/project, compaction epochs, dedup, actual paths/commands/errors. Report eligible-opportunity coverage, useful-before-action rate, answer-bearing coverage of the rendered snippet, false exposures, and first possible delivery position. Use native/no-Brain transcripts to avoid treating Brain-induced actions as an untreated baseline.

**Change of kind:** optimizes the opportunity distribution actually encountered rather than word-matching a memory-question set. Offline replay can prove “would have fired” and bound wasted bytes; it **cannot prove the agent would have used it or saved the later tool calls**.

**Expected effect [INFERENCE]:** 0 new model tokens for the replay, and fewer paid/quota-consuming tests of dead mechanisms. **Effort M. Risk:** telemetry may lack original result text/user intent; redact and mark unavailable, never infer absent observations as negative examples. **Obsoletes:** retrieving target IDs as a substitute for outcome value; broad semantic/proxy campaigns before coverage is established. **Cheapest kill test:** if the correct record cannot be delivered before the native agent already found its source, a post-result trigger cannot save that search; move the pointer earlier or remove it.

### C. Minimal evaluation protocol

This is a proposed replacement protocol, not an executed campaign.

**Model/provider:** `openai-codex/gpt-6-astra`, medium thinking, same OMP version/tools/policy in every arm. Record concrete resolved model ID, not just a moving alias. A later transfer check may use `openai-codex/gpt-5.5`, also through subscription, only after the first model shows value. No other provider is required.

**Tasks:** actual bounded coding outcomes across three repositories. Six families, with two development tasks per family for the pilot and four fresh held-out tasks per family for confirmation:

1. Locate the right implementation and perform a small behavior change.
2. Reproduce/fix an environment/tooling failure and complete the blocked command.
3. Apply a source-supported constraint to a change without violating it.
4. Prefer a current decision over a superseded, plausible one.
5. Resume a bounded coding task after compaction with the invariant intact.
6. Reuse a genuinely shared procedure/locator across projects without leaking private project content.

Negatives are repository work with irrelevant-but-overlapping paths/commands, already-solved problems, known facts stated in the prompt, and privacy/scope traps—not French translation. Determine benefit labels from source-supported opportunity annotation before running candidate arms; allow some naturally no-help tasks in the positive population and report them.

**Scoring:** executable end-state assertions and hidden behavior checks for code tasks, exact file/change invariants for locators/constraints, blinded human adjudication of uncertain semantic answers and all arm disagreements. An LLM judge, if later used, must also be an allowed OpenAI subscription model and separately calibrated; it is not necessary for the initial 12 tasks. Keep regex only for truly syntactic output contracts. No post-hoc “contains the expected words” success definition.

**Stage 0 — no-model sanity:** grade frozen old outputs; freeze new tasks/corpus/rubric; replay 100 boundaries; verify oracle contains sufficient supported content. **0 new agent tokens**.

**Stage 1 — oracle screen:** 12 development memory tasks ×2 reps ×N/O =48 runs; 6 negative tasks ×2 reps ×N/O =24 runs; **72 total**. Use it as screening/variance calibration, not a universal efficacy claim. Continue when the oracle shows materially useful task-level improvements without a critical correctness/privacy failure. Stop a family only for clearly useless/insufficient content or a one-sided interval excluding the desired improvement; an inconclusive noisy point estimate is not a kill result.

**Stage 2 — mechanism diagnosis:** on the **12 development tasks**, run only the needed S/T/J ablation, two reps =**24 additional runs per added arm**, reusing the recorded N/O development baselines descriptively. No inference on the holdout from this tuning.

**Stage 3 — confirmation:** freeze one winner and compare N versus candidate on **24 fresh memory tasks ×3 reps =144 runs**, plus **12 fresh negatives ×2 reps =48 runs**, **192 total**. This targets ~80% power for a 30% reduction under the higher observed log-variance paired-mean model; actual OpenAI pilot variance determines whether 24 is enough. If a median estimand is retained, provision **36 memory tasks ×3 reps** instead (216 memory +48 negative =264 total). Do not claim 80% power based on the wrong estimand.

**Primary analysis:** predeclare mean log resource ratio across independent tasks; report geometric ratio + task-cluster confidence interval. Also report aggregate L, C4/C8 sensitivities, wall-time median/p95, tool calls, requests, correctness, and expensive failures. Charge failed/capped runs in totals; never drop them. Cost per correctly completed task is a useful secondary summary, not a replacement for absolute accuracy. Distinguish demonstrable improvement (CI excludes 1) from the target of 30% savings (point ratio <=.70); proving “at least 30%” requires the upper bound <=.70 and more evidence.

**Quality/safety rule:** zero privacy/host-control breaches; adjudicate every coding regression. Report a predeclared non-inferiority margin with a task-cluster interval, but do not pretend 24 tasks proves a 5-point margin. If quality remains uncertain, the result is inconclusive or a scoped deployment candidate—not universal promotion. For no-benefit efficiency, use a predeclared practical margin such as +2% aggregate L and +5% latency as **[DESIGN]**, alongside a separate zero-exposure contract for explicitly irrelevant frozen observations. Report tails and negative-case harmful actions.

**Token/latency estimates [INFERENCE, planning only]:** using historical averages of ~120k L and ~19s per memory run; ~12k L and ~4s per negative run:

| Stage | Forecast logical tokens | Historical-throughput sequential time |
|---|---:|---:|
| 72-run oracle pilot | ~6.05M | ~16.8 min |
| Each 24-run diagnostic arm | ~2.88M | ~7.6 min |
| 192-run confirmation | ~17.86M | ~48.8 min |
| Median-estimand 264-run alternative | ~26.50M | ~71.6 min |

These are arithmetic forecasts from a different, cheaper model and shorter tasks, **not predictions of OpenAI throughput**. Calibrate on the first four development task pairs (included in Stage 1), then replace both estimates. Use a predeclared **300k logical-token /5-minute per-run cap**, counting cap hits as failures; Stage 1's hard logical-token envelope is 21.6M and the 192-run stage's is 57.6M. If representative tasks routinely need more, revise scope/cap **before** confirmation, not by discarding failures. Local preprocessing/replay latency and human grading effort should be recorded separately. Monetary estimates are deliberately omitted for the subscription objective.

**Change of kind:** measures completed work with a falsifiable causal ladder and one final pair, not simultaneous optional machinery. **Effort M. Risk:** small task population still limits generalization. **Obsoletes:** current trivia as the main promotion benchmark and point-estimate “all family rates nondecrease” as statistical proof. **Cheapest confirmation:** Stage 0+N/O only; build no new ranker until that test says there is value to retrieve.

## Kill list

1. **Stop calling regex score “correctness” without qualification.** Replace semantic checks with behavior or blinded rubric grading. Keep the old outputs for rescore, not new live runs (`v3_value_suite.py:196-202`; demonstrated opposite answers pass).
2. **Retire current tasks from held-out efficacy claims.** They remain cheap smoke/dev fixtures; their notes explicitly disclose task-selection adaptation and repeated target IDs (`tasks.jsonl:4-5,8,10`).
3. **Remove the universal zero-additions clause from the net-value promotion verdict.** Retain it for specifically frozen irrelevant-observation/privacy contracts. It otherwise bans startup guidance and turns corpus-relative N10 into a permanent product restriction (`plan:784`; `suite:1715-1722`).
4. **Stop using a negative median OR fewer tool calls as sufficient value proof.** A tool-call reduction can coexist with more token/latency cost, and no CI is consulted (`suite:379-399`). Predeclare the resource estimand and quality criterion.
5. **Remove `cost_total` as a prerequisite for subscription-model/native-memory qualification.** Preserve available money accounting as optional metadata; require measured token/latency components instead (`suite:1108-1115`).
6. **Remove the cheap-model/low-thinking default from new campaign entrypoints.** Require an explicit allowed model/provider profile (`suite:1857-1860`). Historical data stays historical.
7. **Archive E01's old runtime-arm platform and E02's dense/hybrid exploration as historical experiments once their legacy callers are retired.** Do not expand them to validate current JIT utility. Together **2,189 lines**; deleting them before an archive/caller check is not recommended. Their original decisions were legitimate, but they are not live prerequisites for the next memory surface.
8. **Reduce matched-arms to the used capture/isolation/usage helpers, then delete the old legacy/Lean campaign CLI after auditing callers.** Its 1,524 lines contain a separate experiment platform (`:1-58`), while the value suite dynamically imports it (`v3_value_suite.py:114-121`). Do not duplicate those helpers during cutover.
9. **Stop advertising legacy retrieval CI as the end-to-end Brain-value gate.** Keep deterministic core safety/regression tests; move frozen S2 cases to a historical job, and add grading/statistics contract tests to the active value harness when it is simplified (`ci.yml:31-64`).
10. **Defer scored-selection/native-memory/eager-arm qualification ceremony until a content oracle wins.** A strong native-memory comparison is valuable before broad promotion, not a prerequisite for deciding whether a record contains useful information. Keep source/corpus isolation and request evidence; those are not ceremony.

No blanket line-deletion estimate is warranted without caller review. The clear historical experiment archive candidate is 2,189 lines; the broader 6,334-line script inventory should shrink by reusing a small runner, not by compromising trustworthy accounting.

## Open questions

- What is the real distribution of coding opportunities across the owner's projects/hosts, and how many have a sufficient, current record **before** the agent resolves the issue? Trivia campaigns cannot settle this; offline session annotation can.
- Does subscription quota weight cached input or output differently, and do the exposed usage fields include reasoning? Until documented/measured, C4/C8 are sensitivity scenarios, not billing truth.
- What are actual within-/between-task variances for `openai-codex/gpt-6-astra` at the chosen thinking level? Historical power estimates cannot settle model transfer.
- Does oracle help come from genuinely nonlocal prior knowledge or from duplicating facts the existing agent policy already supplies? Need source-supported annotation and N/O comparison.
- What correctness-regression margin is acceptable for the real workflow? A small token pilot cannot establish universal non-inferiority across all agents/projects.
- Can all relevant native-memory controls be exercised through each target host? This is a host-specific promotion comparison, not a blocker to the oracle experiment.

### Reproduction/evidence artifacts

Data: `outputs/reports/v3-jit/{g3-live-2,g3-live-full,smoke}/runs.json`, corresponding `summary.json`/`manifest.json`; all other summary folders inspected for qualification/row counts. No live records or derived state rebuilt.

Executed, with scratch writes only under OS temp:

```bash
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe C:/Users/assas/AppData/Local/Temp/brain_eval_methodology.py
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe C:/Users/assas/AppData/Local/Temp/brain_eval_power.py
```

The first script computes original/weighted task medians, 20,000-draw bootstrap intervals, usage/latency totals, variance components and file line counts; output is adjacent `brain_eval_methodology.json`. The second reproduces small-sample simulated power/sample requirements and the real matcher false-positive demonstrations; output is adjacent `brain_eval_power.json`. Python import bytecode writes were disabled. Smoke evidence consists of those executed computations/matcher calls; no repository test suite or live model experiment was run.
