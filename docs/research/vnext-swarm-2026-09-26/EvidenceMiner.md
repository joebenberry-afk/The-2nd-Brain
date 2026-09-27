# EvidenceMiner — live value-suite forensic analysis

## Top findings

1. **The main observed delivery defect is loss of the answer, not excessive delivery size: the 77-token Antigravity snippet spends its entire budget saying where the contract lives and omits every requested field.** The delivered text is exactly: `Brain memory (advisory): Antigravity hook contract (authoritative, from installed app bundles): The current official Antigravity hook contract is embedded in Antigravity IDE bundles: out/main.js and out/jetskiAgent/main.js contain the exa/hooks_pb protobuf descriptor (base64 Lo("...")). [mem-79d7c4fd9876]`. The record's following sentences contain the actual camelCase fields, Stop arguments and return shapes (`records/mem-79d7c4fd9876.md:26`). M05/M08/M10 receive the same 306 bytes irrespective of their three different questions. In `g3-live-2`, all nine of these task/rep combinations get that item, but M10 is still 0/3; M08-R2 takes **23 tools / 530,450 logical tokens**, finally retrieving the full record from the Brain home. This is a sufficient-information failure. **Confidence HIGH.** Evidence: `outputs/reports/v3-jit/g3-live-2/raw/VG-M10-v3-jit-R0.jsonl:290-461`; request 3 in that run's request capture; `.../VG-M08-v3-jit-R2.jsonl:1005-4271`; computations C1–C3 below.

2. **The premise “M01/M07/M10 fail in all arms” is not literally true, and the three failure mechanisms are different.** `g3-live-full`: M01 native **1/3**, M07 native **1/3**; `g3-live-2`: M01 JIT **1/3**. M07 frequently gives the correct daemon explanation/private-socket remedy but fails the exact phrase-group regex; M01 is pulled toward the already-present host guidance `PYTHONHOME/PYTHONPATH` while the task demands historical `UV_INTERNAL__PYTHONHOME`; M10 is a real omission of protocol capabilities, reinforced by current adapter docs calling their deliberately restricted implementation the “official result contracts.” Current code says PostInvocation/Stop/PreToolUse return `{}`, while the record describes what the IDE protocol permits. **Confidence HIGH.** Evidence: task file lines 1,7,10; scorer `scripts/v3_value_suite.py:196-209`; `src/second_brain/adapters/antigravity.py:24-39`; detailed quotations below.

3. **Most claimed JIT gains cannot be attributed to supplied memory.** In `g3-live-2`, expected-memory deliveries occur on **11/30 memory runs**: M02 twice, M05/M08/M10 three times each. M06's only delivery is **the unrelated Python-launch gotcha `mem-6d592dd0c627`**, not the fan-out record. M09 receives **zero** Brain bytes in every rep. Thus the headline M06 median reduction **351,015→156,486** and M09 correctness **1/3→3/3** are not evidence that those memories worked. M06-R0/R1 and all M09 runs succeed/fail through native repository hunting. **Confidence HIGH on non-exposure; LOW on causal performance conclusions.** Evidence: `g3-live-2/runs.json`, labels `VG-M06-v3-jit-R0/R1/R2`, `VG-M09-v3-jit-R0/R1/R2`, fields `brain.per_memory`, `deliveries.expected`, `request_capture`; C1.

4. **Expensive exploration, not the final answer or a 77-token insertion, dominates the useful opportunity.** In the second campaign's native memory runs, **87.78%** of logical tokens are cache reads, **1.63%** outputs. Repeated fixed host context is approximately **42.1%** of logical tokens; accumulated task evidence is most of the rest. The first request already costs approximately **8.8K input tokens** before task work. M06/M09 routinely issue 14–34 and 21–25 tools respectively, often retrieving historical reports, currentness sweeps and removed-policy paths. A sufficient 40–80-token answer capsule at the user-message boundary has a measured-input-calibrated oracle budget around **9K logical tokens, zero tools**, versus 351K/368K native medians. This is a change in number of reasoning rounds, not merely prompt compression. **Confidence HIGH on anatomy; oracle is [INFERENCE], not a tested saving.** Evidence: raw provider usage/messages, per-task table and C1/C2/C4.

5. **The evidence cannot yet establish stable per-task speedups.** With three rep-pairs, even three deltas with the same sign give minimum two-sided exact sign-test **p=.25**. In `g3-live-2`, M05 is consistently worse in logical tokens and M07 consistently cheaper; all other per-task logical bootstrap intervals cross zero. In `g3-live-full`, M08 is consistently worse and M09 consistently cheaper, then both change direction in the second campaign. Across ten task-level differences-of-arm-medians, JIT's bootstrap median delta is **−323.5 [−48,322,+966.5]** in full and **−9,434.5 [−28,536,+4,969.5]** in second. These are suggestive observations, not proof. **Confidence HIGH.** C1, seeded 20,000-resample percentile bootstrap; methods below.

### Scope, campaign integrity and interpretation

All analysis was read-only; no repository modifications, rebuilding, testing suites or new live model campaigns. Scratch computations live under the OS temp directory. The historical model was `deepseek/deepseek-flash`, thinking low (`g3-live-full/resume.json:29-32`). These are weak/cheap-model observations whose transfer to the owner's chosen `openai-codex` provider is unproven. Proposed experiments below use **`openai-codex/gpt-5.5`**, never DeepSeek/OpenRouter; subscription tokens and latency, not USD, are their economic outcomes.

| Campaign | Rows/status | What it contributes |
|---|---:|---|
| `g3-live-full` | 180 ok: 60 native / 60 brief / 60 JIT | Complete 3-rep comparison. Memory correctness 20/30 native, 18/30 brief, 19/30 JIT. |
| `g3-live-2` | 120 ok: 60 native / 60 JIT | Complete second 3-rep comparison. Memory correctness 17/30→22/30, subject to rubric defects. |
| `g3-live` | 144 ok: 49 native / 48 brief / 47 JIT | Incomplete uneven replication: supporting trace evidence only, not a complete 3-rep trial. No memory run has identical usage to its same-label full-campaign run; run directories differ. |
| `g3-live-r1` | 60 errors | Not performance evidence: 40 candidate rows have `KeyError: 'agent_sessions'`; native rows have zero model requests/unknown usage and CLI failure. Unknown tokens are **not zero-cost runs**. |
| legacy `value/campaign` | 120 ok | Memory 20/30→28/30; median task logical delta −1,394, CI [−34,517,+14,908]. |
| legacy `value/campaign2` | 120 ok | Memory 20/30→27/30; median task logical delta −3,900, CI [−41,709.5,+22,726]. |

Sources: each campaign's `runs.json`; C1; `g3-live-r1/runs.json` first candidate row and native `VG-M02-native-R0`; `summary.json` cross-checks. Both complete JIT campaigns are labelled FAIL. In second, class-level memory/no-benefit gates and family non-inferiority pass; the failing field is `no_benefit_zero_additions:false`. Specifically `VG-N05-v3-jit-R1` receives the 291-byte Python gotcha. This is **not** a finding that every memory task became worse.

### Per-task table: actual behavior, sufficient knowledge, timing and oracle

Numbers use `g3-live-2` unless stated. `N→J` is the difference between each arm's three-rep median, **not** median of rep-paired differences. Oracle assumptions: preserve the observed host/input, add an 80-token sufficient capsule and a 100-token answer; immediate acceptance, no independent re-verification. Prompt oracle = first-request input+cache+180. First-result oracle = observed first-request total + second-request input/cache +180, so it retains the actual first tool-result payload and initially issued batch (normally 1–2 tools). These are optimistic lower-bound **[INFERENCE]** estimates calibrated with measured requests, not achieved results. First-result delivery is unreachable on an unchanged zero-tool trace.

| Task | What native actually did; where tokens went | Single knowledge unit that would help; best moment | Oracle saving: prompt / first result | Observed Brain effect and failure root |
|---|---|---|---|---|
| M01 | 0/0/0 tools; immediately answers from host guidance. Median 9,005 logical; fixed prefix ≈96.7% of aggregate task tokens. | Historical incident names **PYTHONHOME and UV_INTERNAL__PYTHONHOME**, corrupted uv 3.11 stdlib/SRE mismatch; distinguish it from today's venv PYTHONPATH precaution. **Prompt**, before immediate answer. | No meaningful token saving (~9,041 oracle; +36); possible correctness gain. First-result route cannot fire. | 9,005→9,021; correctness 0/3→1/3. No JIT delivery. One JIT run searches natively. Missing historical variable, not generalized model inability. |
| M02 | 4/3/5 tools: find/grep/glob, inspect `src/second_brain/db.py`, migration docs/version ordering. Median 41,239; prefix ≈69.5%. | “Apply numbered migrations in ascending numeric order.” **Prompt**; first result is sufficient if needed. | ~32,252 / 18,756 tokens saved; 9.0K /22.5K total; zero / first 1–2 tools. | 41,239→31,811, both 3/3. Record delivered twice, but only after already reading migration code/docs; mostly redundant rather than demonstrably used. |
| M03 | 0/0/0 tools, answers SQLite issue directly. Median 9,346; prefix ≈93.2%. | Move full DB set aside; drop stale WAL/SHM after restoring copy; same-lineage stale WAL replays/resurrects rows. Here agent already knows enough. **No injection for this question**; before actual restore is a different use case. | Only ~335 tokens under arbitrary shorter-answer oracle; not a meaningful Brain opportunity. No unchanged first-result delivery. | 9,346→9,316, both 3/3; no expected delivery. Generic-known answer should not be presented as strong memory-value evidence. |
| M04 | 5/10/5 tools: find `paths.py`/`doctor.py`, read layout constants/ranges; occasional bad `proj` path and extra searches. Median 68,444; prefix ≈61.8%. | `paths.ensure_layout(home)` creates `skills/approved/{global,domain,project,model}` and `skills/principles`. **Prompt**, or locator at first find result. | ~59,434 /49,729 saved; 9.0K /18.7K total. | 68,444→46,843, both 3/3; zero exposure. Historical record now superseded; observed speed delta is not memory use. |
| M05 | 4/4/2 tools: broad Antigravity grep plus find, then adapter field matches/read. R0 broad result 44,810 serialized chars. Median 41,991; prefix ≈62.2%. | Exact four common keys `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`; annotate protocol vs adapter reading. **Prompt** or first search result, before source hunt. | ~32,972 /17,503 saved; 9.0K /24.5K total. | 41,991→61,358, both 3/3; all three logical deltas positive. Delivered locator-only sentence contains none of the requested keys; agent continues field searches. |
| M06 | 21/34/14 tools: broad worker/fan-out grep/find; reads currentness sweep, historical harness refinement, tries removed `config/orchestration.toml`, follows policy/report trails. R0's three largest results ≈53K/42K/30K serialized chars. Median 351,015; prefix ≈33.0%. | **Historical amendment §12.2:** adaptive fan-out, conservative default, config/env maximum, hard resource ceiling, telemetry; label as historical because Brain orchestration was removed. **Prompt** with exact historical source. | ~341,991 /330,376 saved; 9.0K /20.6K total. | 351,015→156,486, correctness 1/3→3/3. No target delivery; only R2 unrelated Python gotcha. Native failures omit telemetry after long provenance hunts. Do not reactivate obsolete policy to win this question. |
| M07 | 5/5/10 tools: home/daemon grep, extension README and integration runner; R2 also searches suite/socket setup. R0's largest result ≈80K serialized chars. Median 74,180; prefix ≈55.4%. | Shared daemon keeps startup environment; changing client `SECOND_BRAIN_HOME` does not retarget it; create dedicated `--daemon-socket` per integration run. **Prompt**, not only a launch-command trigger. | ~65,160 /52,085 saved; 9.0K /22.1K total. | 74,180→38,709; rubric 0/3→0/3. No target delivery. Many correct explanations rejected on phrasing; one native answer also omits exact socket flag. |
| M08 | 5/16/14 tools: adapter docstring/Stop branch/tests, then searches historical decisions/contract descriptors; first native R0 only four model rounds, others much longer. Median 128,346; prefix ≈41.3%. | `stopHookArgs={executionNum,terminationReason,error,fullyIdle}`; **host protocol may return `{decision,reason}`; this Brain adapter deliberately returns `{}`**. **Prompt**, with distinction included. | ~119,355 /109,351 saved; 9.0K /19.0K total. | Median 128,346→103,193, yet rep-paired median is **+59,873**, and full-campaign marginal delta is **+135,444**. 3/3 rubric passes each arm are not reliable semantic correctness. Locator-only delivery can initiate contract reconciliation and full-record hunting. |
| M09 | 25/21/22 tools: amendment/orchestrator greps, redesign/currentness/removal mandates, change-control, changelog and harness refinement. R0 largest results ≈59K/33K/16K chars. Median 368,226; prefix ≈32.0%. | Historical amendment §31 item 3 permits trivial deterministic driver work, substantial work delegated when advantageous; **not current Brain orchestration policy**. **Prompt**, with temporal scope and source. | ~359,219 /347,811 saved; 9.0K /20.4K total. | 368,226→430,230; correctness 1/3→3/3. Zero delivery; worsened exploration cannot be delivery-induced. Current-policy vs historical-question ambiguity dominates. |
| M10 | 5/4/3 tools: find/read adapter docstring/implementation/tests; accepts implementation's `{}` subset as protocol. Median 49,275; prefix ≈76.2%. | **Protocol:** invocation hooks `injectSteps:[{ephemeralMessage|userMessage|toolCall}]`; PreToolUse `{decision,reason,overwrite,permissionOverrides}`; Stop `{decision,reason}`. Distinguish optional protocol capability from adapter's deliberately disabled responses. **Prompt**, or at first relevant source result with complete fields. | ~40,260 /27,500 saved; 9.0K /21.8K total. | 49,275→39,834, both 0/3. All JIT reps receive the irrelevant first sentence, never return-shape fields. This is content omission plus source-boundary confusion, not evidence that the model ignored a supplied answer. |

Native trace citations (prefix `outputs/reports/v3-jit/g3-live-2/raw/`): `VG-M01-native-R0.jsonl:105`; M02 `:241-481`; M03 `:535`; M04 `:162-522`; M05 `:160-517`; M06 `:186-4769`; M07 `:300-1155`; M08 `:143-855`; M09 `:102-5657`; M10 `:114-678`. All three reps' tool sequences, results sizes, answers and usage were parsed in C1/C2; scratch details retain the other rep references. Knowledge citations: `records/mem-b67de5057f76.md:29`; `mem-a8d221e64549` delivered text in M02 request 3; `records/mem-29557f93448f.md:35`; `mem-3848b16778bd.md:19`; `mem-79d7c4fd9876.md:26`; `mem-f745bcb2eff2.md:18`; `mem-b0d6cc3de0ab.md:28`; `mem-174b3f5abbba.md:18`.

### Failure quotations and grading defects

**M01 — prior conflict + zero-tool blind spot.** Record: “User-level PYTHONHOME/UV_INTERNAL__PYTHONHOME pointed at a corrupted uv CPython 3.11 tree (since repaired 2026-08-14: uv reinstall restored the stdlib). Shims still sanitize PYTHONHOME defensively; doctor still warns when set.” (`records/mem-b67de5057f76.md:29`). It is now superseded as historical (`:7-12`). Native R0: “Clear `PYTHONHOME` and `PYTHONPATH` … Without that: `AssertionError: SRE module mismatch` on bare startup.” (`g3-live-2/raw/VG-M01-native-R0.jsonl:105`). Its only missing group is `UV_INTERNAL__PYTHONHOME`. The captured initial request already contains AGENTS-style guidance “Always run the project venv Python with `PYTHONHOME` and `PYTHONPATH` removed”; this is a competing, useful current launch instruction, not random forgetting (e.g. `g3-live-2/raw/VG-M05-native-R2/provider-request-11300-1d275747-001.json:1`, system message 2). A correct historical reminder requires an explicit historical/current distinction, not replacing the current safety rule.

**M07 — strong evidence of false negatives.** Record: “A shared prime-agent daemon does not see client env changes like SECOND_BRAIN_HOME. Integration runs need a dedicated --daemon-socket per run; production users must set SECOND_BRAIN_HOME before starting prime-agent.” (`records/mem-b0d6cc3de0ab.md:28`). JIT R0 answers: “A shared prime-agent daemon is bound to the home/env it loaded at its own startup … your exported `SECOND_BRAIN_HOME` never reaches its already-loaded extension. Integration runs must force a fresh, dedicated daemon per run via a private `--daemon-socket` pipe …” (`g3-live-2/raw/VG-M07-v3-jit-R0.jsonl:763`). It is marked false solely because none of the enumerated phrases `startup env`, `startup environment`, `pins its own`, `environment at startup`, `does not see`, etc. appears literally. Native R0 similarly says “read by the daemon/extension process at start … changing the var mid-session cannot retarget it” and prescribes unique `--daemon-socket`; also marked false (`.../VG-M07-native-R0.jsonl:1155`). Native R2 is a mixed case: correct explanation, but says per-run sessions dir/socket without naming dedicated daemon socket; do not classify every failure as a rubric-only defect. The current record's triggers are **launch commands**, not reading the integration runner (`records/mem-b0d6cc3de0ab.md:15-20`), so an explanatory question never triggers it.

**M10 — the answer was never delivered.** Full record: “Results: PreInvocation/PostInvocation {injectSteps:[{ephemeralMessage|userMessage|toolCall}]}, PostToolUse {}, Stop {decision, reason}, PreToolUse {decision, reason, overwrite, permissionOverrides}.” (`records/mem-79d7c4fd9876.md:26`). JIT R0 instead answers “PreInvocation → …; PostInvocation → `{}` (telemetry only). PreToolUse is not installed … returns `{}` … Stop → `{}` …” (`g3-live-2/raw/VG-M10-v3-jit-R0.jsonl:461`). Its missing group is `permissionOverrides|overwrite`. The current adapter really documents these empty responses (`src/second_brain/adapters/antigravity.py:33-39`); that is not evidence the broader host protocol lacks those capabilities. No direct primary installed-IDE descriptor revalidation was performed here: present-day external protocol truth remains an open question.

**M08 exposes false positives as well.** Full-campaign JIT R0 says “Return — `{}`, always” and labels nonempty decision behavior historical, yet passes all groups (`g3-live-full/raw/VG-M08-v3-jit-R0.jsonl:1865`). The regex `reason` already matches **terminationReason**; `decision` matches statements that there is **no decision**. Scorer is unconstrained substring matching (`scripts/v3_value_suite.py:196-202`), not proposition correctness.

**Legacy M10 “3/3” does not prove three clean protocol answers.** `campaign2` candidate R0 gets the **full 1,539-character packet**, including return fields, and ends: “the only field names you have are the advisory memory's … unsupported by current repo evidence; confirm against the installed exa/hooks_pb descriptor before you write results back.” This is scored correct because it repeats all keywords, despite withholding a firm protocol answer (`outputs/reports/v3-agent-experience/value/campaign2/raw/VG-M10-candidate-R0.jsonl:1591`; corresponding `runs.json.brain_custom_messages`). Full delivery did make the missing information available; it also provoked reconciliation instead of a short answer. The desired replacement is a concise **scoped distinction**, not restoration of the whole legacy packet.

**Anchors are keyword coverage, not proof.** `g3-live-2/anchors.json:206-208` claims all ten tasks are covered. `anchor_scan` concatenates the entire repo and entire record corpus, then independently searches each group across those concatenations (`scripts/v3_value_suite.py:773-783`). It does not prove the expected record is current, deliverable, sufficient after snippet compilation, or that one authoritative source entails the answer. M10 and M08 demonstrate the distinction directly.

### Did delivery induce exploration?

- **M02:** useful text, late/redundant. R0 delivers at request 3 only after reading `db.py:1-160` and `docs/components/db-migrations.md`; the agent answers immediately afterwards. Causal contribution cannot be separated from the source just read (`g3-live-2/raw/VG-M02-v3-jit-R0.jsonl:221-302`).
- **M05:** topical but answer-empty. R0 has a larger broad grep result **before delivery** (52,346 serialized chars versus native R0's 44,810). After the adapter read triggers the locator, it performs an additional repo-wide `artifactDir|artifactPath|artifact_dir|ArtifactDir` search (`.../VG-M05-v3-jit-R0.jsonl:156-426`). R0 has the same total 4 tools as native, but an extra model round: native 3 requests vs JIT 4. Thus some cost divergence predates injection; it is wrong to attribute the whole +19,367 to the 306-byte snippet.
- **M06:** delivered Python gotcha in R2 is relevant only to launching Python, not to answering the amendment question. No target memory was delivered in any second-campaign rep. Do not use its correctness delta to justify fan-out retrieval.
- **M08:** strongest temporal evidence for memory-induced exploration, but not randomized causal proof. R2 reads adapter, receives locator, then searches `79d7c4fd9876|hooks_pb`, tries git history in a non-git snapshot, attempts `brainctl recall`, and finally reads `home/records/mem-79d7c4fd9876.md` including a raw read (`.../VG-M08-v3-jit-R2.jsonl:1005,2288,2695,4039,4137,4271`). Final answer correctly separates host fields from this adapter's `{}` behavior. The path is **530,450 tokens/23 tools** versus native paired R2 **128,346/14**. A contentful distinction capsule plausibly replaces the entire loop [INFERENCE].
- **M09:** no Brain delivery at all; neither deterioration nor improvement can be described as delivery-induced. Currentness sweeps state the driver/fan-out memories were retired, and the agent spends many tools reconciling old amendment wording against the orchestrator-removal mandate. This is a provenance/temporal-scope retrieval problem, not JIT overhead.

### Token anatomy and historical cost-weighted comparison

Logical = input + output + cacheRead + cacheWrite (`scripts/v3_value_suite.py:213-235`). **Cache reads are not synonymous with host prompt**: they also include accumulated search results and the agent's previous task context. Nor do logical tokens measure the sum of unique new evidence. The principal gains from short-circuiting a hunt are avoiding later rounds that reread both.

Measured initial native request example has two system contents of **9,997 + 4,698 characters**, tool schemas **18,444 JSON characters**, and user content **563 characters**. Actual first input+cache across memory tasks has median **8,833 tokens** in second. A fixed-prefix approximation of 8,770 tokens/request yields native memory **42.06%** and JIT memory **41.00%** fixed-overhead shares. These are **token estimates**, not exact tokenizer attribution. Exact character accounting of message contents plus tool schemas gives second native system **20.76%**, tool schemas **25.34%**, tool results **53.18%** of that counted material. C1/C2; the provider does not supply a per-role tokenizer breakdown.

| Campaign/arm, memory only | Logical total | Cache-read fraction | Output fraction | Model requests | Tools | Median wall seconds/run |
|---|---:|---:|---:|---:|---:|---:|
| full native | 3,341,292 | 87.03% | 1.40% | 155 | 209 | 13.66 |
| full JIT | 2,325,075 | 85.31% | 1.78% | 138 | 186 | 15.25 |
| full brief | 3,422,455 | 85.96% | 1.65% | 176 | 251 | 18.58 |
| second native | 3,648,587 | 87.78% | 1.63% | 175 | 246 | 12.23 |
| second JIT | 3,508,235 | 88.11% | 1.54% | 164 | 218 | 11.44 |

Historical recorded rates reconstruct as input 0.15/million, output 0.60/million, cached input 0.003/million. For comparison without cent-scale figures, define **input-price-equivalent tokens W = input + 4×output + 0.02×cacheRead**, or directly `provider_usage.cost_total × 1e6 / .15` (zero cache writes in these runs). C2's per-run residual against recorded cost is at rounding scale. These rates describe the historical captured provider only; they are **not a proposed objective for OpenAI subscription use**.

| Task | Second marginal logical delta | Second median rep-paired logical delta [95% bootstrap CI] | Second marginal W delta | Second median rep-paired W delta | Full marginal W delta |
|---|---:|---:|---:|---:|---:|
| M01 | +16 | +16 [−260,+13,019] | +64 | +64 | +224 |
| M02 | −9,428 | −15,059 [−15,077,+18,826] | −2,335 | −2,458 | −2,690 |
| M03 | −30 | +180 [−242,+12,209] | −120 | +720 | +1,000 |
| M04 | −21,601 | −13,129 [−60,379,+5,308] | −11,358 | −11,358 | −6,080 |
| M05 | +19,367 | +19,367 [+14,769,+30,821] | +783 | **−1,611** | +181 |
| M06 | −194,529 | −254,691 [−405,995,+149,171] | −37,648 | −44,478 | −48,686 |
| M07 | −35,471 | −35,471 [−102,832,−11,408] | −9,835 | −6,293 | −4,374 |
| M08 | −25,153 | **+59,873** [−263,216,+402,104] | −3,859 | **+13,848** | +33,385 |
| M09 | +62,004 | +62,004 [−170,168,+450,277] | +1,002 | +1,002 | −1,649 |
| M10 | −9,441 | −9,342 [−25,426,+4,399] | **+1,110** | **+1,254** | +272 |

M10 is cheaper in logical tokens but more expensive in weighted usage in all three rep-pairs. M05's marginal and paired weighted medians disagree; M08's marginal and paired logical medians disagree. The suite's function named `paired_deltas` is **pairing task-level arm medians**, not calculating same-rep deltas (`scripts/v3_value_suite.py:238-271`). Both estimands can be reported, but should not be interchanged.

Campaign-level task-bootstrap median historical cost deltas: full JIT −0.00011006 [−0.000658,+0.000092], second −0.000184155 [−0.001475,+0.000117]; both intervals cross zero. Historical total recorded memory costs are full **0.09484671→0.07578386**, second **0.10316586→0.09606809**. Totals are outlier-sensitive, explaining why full total logical use falls 30.4% while median run latency increases. **Use logical tokens + uncached/new input + output + cache fraction + request count + latency** for the next subscription experiments; retain historical weighted figures only as an anatomy check.

### Variance/statistical method

C1 bootstraps the observed deltas with replacement 20,000 times, seed 7821, percentile 2.5/97.5 bounds, and computes the exact two-sided sign-test binomial tail. For per-task checks it aligns arm rows by `rep`. That gives an auditable contrast, **not common-random-number pairing**: the captures do not establish matched model sampling seeds. For campaign comparisons it follows the suite's task-level difference-of-arm-medians and resamples ten task deltas.

With n=3, a percentile CI that excludes zero can simply reproduce the observed minimum/maximum delta; it does not confer robust 95% causal confidence. Minimum nonzero two-sided sign-test p=.25 before considering ten task comparisons. Treat M05 worsening and M07 shortening in second as consistent-in-this-sample leads; M08/M09 reversals between campaigns demonstrate the danger of promotion on a single median. M06 has very large potential but crossed-zero within-task intervals and no relevant exposure, so cannot currently count as a proven Brain win. Correctness significance is additionally compromised by the semantic rubric errors; do not attach a causal accuracy claim to the raw 17→22 count.

## Breakthrough candidates

### 1. Compile question-sized answer capsules, not first-sentence snippets

- **Concrete change:** split or project the Antigravity record into three sufficient units (common input keys; Stop args plus host/adapter distinction; result shapes plus distinction). Each capsule carries answer-bearing fields, scope/version and a short authoritative locator. Retrieval returns a complete unit or nothing; do not emit a title/introduction that omits the fact.
- **Change of kind:** from “here is a place to investigate” to “here is the missing, scoped proposition, with checkable provenance.” It removes a reasoning/search branch rather than shaving bytes from it.
- **Expected effect:** [INFERENCE] M05/M08/M10 oracle totals near 9K at prompt vs native medians 42K/128K/49K; especially avoid the observed M08 530K reconciliation path. No claim of achieved savings.
- **Effort M; risk:** incorrect protocol version or missing distinction can confidently mislead. Require authoritative installed descriptor/version evidence, not a blanket “memory outranks code” instruction.
- **Obsoletes:** blind first-sentence truncation for fact/procedure payloads, monolithic multifact record with one generic snippet, “delivered expected ID” as sufficient-success criterion.
- **Cheapest confirming/killing experiment:** first deterministic offline check: does each rendered capsule entail its target answer and preserve host-vs-adapter distinction? Then owner-run `openai-codex/gpt-5.5` comparison on M05/M08/M10-like **fresh held-out** questions, same prompt, existing snippet vs sufficient capsule, matched host/source snapshot; score semantic answer and tokens/latency. Kill if a sufficient capsule still causes the same source-reconciliation path.

### 2. Retrieve on the incoming question, with a true zero-match branch

- **Concrete change:** use the incoming user message to select at most one high-confidence sufficient capsule *before the next model call*, without a standing startup brief. Keep tool-result triggers for action-specific hazards. Prompt-time historical/current routing must not re-enable retired policies as standing advice.
- **Change of kind:** covers decisions made before any tool call. Current tool-only design cannot affect the native M01/M03 immediate answers at all.
- **Expected effect:** [INFERENCE] enables correctness correction on historical M01 and removes first-search cost on locator tasks; first-result oracle floors are 18.7–24.5K versus ~9K prompt floors. M03 already succeeds; abstention is the desired behavior.
- **Effort M; risk:** false-positive interruptions and a second broad eager brief. Admission must be about the user's current question, not merely project membership.
- **Obsoletes:** blanket “no prompt-time memory” as a universal rule, and eager all-project brief as the only alternative. Does not obsolete tool-result hazard delivery.
- **Cheapest experiment:** offline exact trace replay to prove zero-tool question coverage and no additions for no-benefit prompts, then small owner-run `openai-codex/gpt-5.5` prompt-vs-first-result capsule ablation. Primary outcomes tokens, latency and semantically correct response; no USD optimization.

### 3. Treat temporal scope and interface boundaries as first-class knowledge

- **Concrete change:** historical amendment records answer historical questions as historical; current product policy is separately named. The Antigravity capsule explicitly separates **IDE protocol capabilities** from **Brain adapter implementation choices**, with one source for each.
- **Change of kind:** preserve the relation between facts rather than forcing a single “current” sentence to answer every question. Eliminates apparent contradictions that trigger searches across removal mandates, historical reports and tests.
- **Expected effect:** [INFERENCE] targets the 351K/368K M06/M09 hunts and M08's contract-reconciliation branch; avoids falsely reviving obsolete Brain orchestration.
- **Effort M; risk:** schema complexity if generalized prematurely. Begin with explicit scoped text in existing record fields, not a temporal database/framework.
- **Obsoletes:** retiring a historically useful fact as if it were never answerable, or serving the retired fact as current policy; ambiguous “official result contract” labels for implementation subsets.
- **Cheapest experiment:** offline rubric plus explicit two-sentence capsules for three historical/current and protocol/implementation distinctions; owner-run `openai-codex/gpt-5.5` on changed phrasings with the same distinction. Kill if it cannot improve answer quality without more exploration.

### 4. Replace keyword victories with semantic and exposure-grounded evidence

- **Concrete change:** correctness must distinguish required positive claims from negations/quoted rejected claims, and accept paraphrases. Track supplied propositions, request index, later tool decisions and answer use—not just memory ID appearances. Qualify answerability against the **rendered capsule**, not whole-corpus regex coverage.
- **Change of kind:** product decisions become based on information that actually changed behavior. M07 false negatives and M08/legacy M10 false positives currently reward/penalize the wrong things.
- **Expected effect:** immediately prevents misclassification of known inspected examples; any product token saving remains [INFERENCE].
- **Effort S/M; risk:** an opaque judge can substitute a new bias. Keep a small explicit adjudicated set including these known positive/negative examples and blind model/arm labels; deterministic schema assertions where possible.
- **Obsoletes:** corpus-wide anchor regex as sufficiency proof, successful-ID-delivery as utility proof, three-rep medians as strong causal evidence.
- **Cheapest experiment:** rescore already captured M07/M08/M10 answers with explicit human-readable semantic criteria, **without any new live agent runs**. Verify unchanged fail/pass examples before spending subscription runs on a new product design.

## Kill list

1. **Stop emitting introductory-only capsules.** Current 306-byte Antigravity injection omits all three tasks' answer-bearing fields (`records/mem-79d7c4fd9876.md:26`; raw request captures). Smaller is not token-efficient if it creates another hunt.
2. **Stop claiming M06/M09 observed deltas are benefits of those memories.** Expected records never arrive in the second campaign; M06's one exposure is the Python gotcha (C1).
3. **Stop treating the eager brief as the obvious rescue for tool-only JIT.** Full campaign brief memory correctness is 18/30 vs native 20/30; median task logical delta **+8,379**, bootstrap [+1,538,+55,206], median latency 18.58s vs 13.66s. A selected question capsule is a different design, not a revived all-project preface.
4. **Stop using `anchors.json`'s `memory_all:true` to assert deliverable knowledge.** Whole-corpus keyword coverage ignores currentness, expected ID, snippet sufficiency and conflicting meaning (`scripts/v3_value_suite.py:764-783`).
5. **Stop scoring arbitrary occurrences of `reason`/`decision` as supported protocol claims and exact daemon wording as understanding.** M08 passes on `terminationReason`/negated decision; M07 fails correct paraphrases (`scripts/v3_value_suite.py:196-202`; quoted streams).
6. **Stop lumping harness errors into cheap model failures.** `g3-live-r1` has no usable performance rows; unknown usage must stay unknown, never zero.
7. **Stop inflating current-policy usefulness with historical trivia tasks.** M06/M09 are explicitly superseded records (`records/mem-f745bcb2eff2.md:7-12`, `mem-174b3f5abbba.md:7-12`). Retain a deliberate historical-question lane, but do not let it define current coding-agent utility or cause retired runtime policy to be promoted.
8. **Stop optimizing proposed experiments for historical DeepSeek monetary rates.** The owner selected `openai-codex` subscription use: measure tokens, latency, requests and correctness. Historical weighted calculations above explain prior evidence, not future priorities.

## Open questions

- Which current installed Antigravity bundle version and descriptor definitively establish the external result schema today? Repository record and adapter-subset conflict is established; external descriptor truth was not revalidated here.
- Will sufficient, scope-aware capsules help `openai-codex/gpt-5.5` (or another chosen available OpenAI model), which may search/answer differently from the captured model? No transfer claim is justified yet.
- How much of M08's extra exploration is specifically caused by seeing the memory locator, rather than stochastic choices and already-present contradictory source labels? The trace supplies a temporal mechanism, but only an ablation can isolate causality.
- How should a historical incident's sanitized variables be phrased as present-day launcher requirements? The M01 task asks both, while its record says the uv corruption was repaired. A current runtime-backed requirement should decide future scoring.
- What fraction of real coding tasks, rather than these ten repository-memory questions, actually need knowledge absent from current repo/host context? This dataset cannot estimate deployment-wide net value.

### Reproducible computation/evidence inventory

No model APIs were called by these scripts. They read captured JSON/JSONL and write summaries only to `%TEMP%/evidence-miner/`.

**C1 — all campaign rows, streams, request contents; task/arm medians, rep-paired deltas, exact sign tests, 20,000-resample CIs:**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe C:/Users/assas/AppData/Local/Temp/evidence_miner.py
```

Outputs: `%TEMP%/evidence-miner/stats.json`, `anatomy.json`, and `<campaign>-traces.txt`. `g3-live-r1`'s null usages are invalid observations; no zero-valued exploratory intermediates from those rows were included in conclusions above.

**C2 — full/second native/JIT/brief tool sequences, result sizes, rate reconstruction, token anatomy:**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe C:/Users/assas/AppData/Local/Temp/evidence_detail.py
```

Outputs: `%TEMP%/evidence-miner/g3-live-full-detail.txt`, `g3-live-2-detail.txt`; console anatomy and weighted comparisons. Fields used for W: `provider_usage.{input,output,cacheRead,cost_total}`; logical uses all four token fields. All memory runs in the two complete campaigns have zero spawned subagent sessions, so the analyzed tool/usage paths are root paths.

**C3 — exact R0 native read-path/final-answer references and no-benefit exposure:**

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe C:/Users/assas/AppData/Local/Temp/evidence_refs.py
```

**C4 — oracle/anatomy derivation:** use C1 `anatomy.json['g3-live-2']`, group labels by task and `native`; each `root_usage` is chronological observed assistant usage. Take median of `(first.input+first.cacheRead+180)` for prompt oracle and `(first.input+first.cacheRead+first.output+second.input+second.cacheRead+180)` for first-result oracle; subtract from the native median logical total. Fixed-prefix share is `(sum(model_requests)*8770)/sum(logical)`. These formulas were executed against the saved output, not inferred from file lengths.
