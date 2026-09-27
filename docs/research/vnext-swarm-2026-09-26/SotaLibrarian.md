# State of the art: portable memory and context engineering for coding agents

Research question: Which 2025–2026 mechanisms can make a local, file-based, cross-agent Brain reduce total agent tokens while preserving or improving coding correctness—not merely improve conversational recall?

Scope and applicability: Read `docs/research/v3-just-in-time-memory-proposal.md` §2 and `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md` §1 before researching. This report adds evidence and corrects interpretations rather than repeating their survey. Research is read-only; no model runs, package installations, repository changes, or test suites were performed. Official living documentation was accessed on 2026-09-26. Paper versions are identified where consequential. The supplied environment establishes OMP 18.3.1 on Windows, but not installed versions of Claude Code, Codex, Cursor, Letta, Mem0, or LangMem: upstream behavior below is not a claim about installed support.

Evidence labels: **[DOC]** official documented behavior; **[IMPL]** upstream implementation, not a stable public contract; **[OBS]** author-reported measurements, not reproduced here; **[INFERENCE]** engineering conclusion or proposed experiment. HIGH confidence means high confidence in the cited finding, not that its magnitude transfers to this Brain. All proposed agent experiments use **OMP + `openai-codex/gpt-5.5`**, fixed reasoning settings and host version. No DeepSeek experiments or OpenRouter are proposed. Published third-party results using those systems remain historical evidence, not experiment recommendations. Tokens and latency—not API dollars—are the owner's decision metrics.

## Top findings

### 1. The closest coding benchmark shows an oracle opportunity, not a solved retrieval problem

**Claim — HIGH:** Correctly selected compact experience can reduce coding tokens, but autonomous access can hurt, and token savings need not reduce latency.

**[OBS]** [SWE-ContextBench v3, 2026-05-06, Table 3](https://arxiv.org/html/2602.08316v3#S3.T3) expands the benchmark to **1,100 experience tasks + 376 related tasks, 51 repositories, 9 languages**. Under **GPT-5.3 Codex in Codex**, oracle summaries change:

- Resolution: **22.60% → 23.94%**.
- Mean tokens: **858,252.71 → 718,919.86**.
- Tool calls: **28.91 → 27.41**.
- Runtime: **349.41 → 362.39 seconds**—worse despite fewer tokens.

The corresponding Claude Code/Sonnet 4.5 result is **19.68% → 23.40% resolved**, **1,701,548.05 → 1,352,829.76 tokens**, and **344.47 → 280.62 seconds**. These are model-and-harness-specific results, not universal memory multipliers.

**[OBS]** On its **99-task Lite** subset, [v3 Table 4](https://arxiv.org/html/2602.08316v3#S3.T4) reports baseline **26.26%** resolved, free full-context reuse **26.26%**, free summary reuse **22.22%**, oracle full-context **27.27%**, oracle summary **34.34%**. Free access is not reliable selection.

**New qualification:** [v1 §3.4–3.5](https://arxiv.org/html/2602.08316v1#S3.SS4) called oracle summaries fastest/cheapest, at **356.95 s / $0.77**. [v3 §3.3.2/Table 4](https://arxiv.org/html/2602.08316v3#S3.SS3.SSS2) instead assigns lowest runtime/cost to oracle **full context**, **5.95 min / $0.77**, and oracle summaries **6.66 min / $0.85**, versus baseline **6.37 min / $0.79**. Do not mix versions or preserve the blanket claim that oracle summaries always minimize every cost dimension.

**Impact for the Brain [INFERENCE]:** Before changing retrieval engines, establish whether the best existing record, delivered before the first plan, actually helps. If the oracle card fails, selector tuning cannot rescue the content. If oracle helps but ordinary recall fails, discovery/selection—not storage—is the bottleneck. Existing weak/cheap-model campaigns supplied by the parent cannot establish transfer to the selected OpenAI subscription model.

### 2. Curated procedures have stronger new evidence than generic memory, but skills are not automatically token-saving

**Claim — HIGH for reported results; MED for transfer:** Package high-value procedures as a few discoverable skills. Do not equate auto-generated prose with learned expertise.

**[OBS]** [SkillsBench v4, 2026-06-14, §§4–5/Table 2](https://arxiv.org/html/2602.12670v4#S5.T2) evaluates **87 tasks, 8 domains, 18 model–harness configurations**, with a **three-trial frame per condition**, producing **9,396 selected public result files**. Curated skills raise reported task-macro pass rate **33.9% → 50.5%**. Codex/GPT-5.5 rises **46.8% → 66.5%**. Its **16 software-engineering tasks** improve **37.6% → 49.2%** averaged over configurations. **13/87 tasks regress**. These are the current v4 numbers, not the earlier 84/86-task, +16.2-point summaries circulating online.

**[OBS]** [SkillsBench v4 Appendix L, Table 15](https://arxiv.org/html/2602.12670v4#A12.T15) reports Codex/GPT-5.5 mean tokens **3,222K → 3,227K** with skills: the large correctness gain is **not a token reduction**. OpenHands/GPT-5.5 is **1,197K → 1,267K**. Token direction varies by stack.

**[OBS]** [v4 §5.1.1 / Appendix D.6](https://arxiv.org/html/2602.12670v4#A4.SS6) reports self-generated skills below the no-skills baseline by **8.1 points** for Claude Code/Opus 4.7, **11.3 points** for Codex/GPT-5.5, and **11.5 points** for Gemini CLI/Gemini 3.1 Pro. This condition creates skills before solving; it is not the same as distilling a verified successful past trajectory. It nevertheless kills the assumption that asking an agent to invent a skill is sufficient.

**[DOC]** The [Agent Skills specification, Progressive disclosure](https://agentskills.io/specification#progressive-disclosure) loads names/descriptions at startup, approximately **100 tokens per skill**, the full instructions only on activation, recommended **<5,000 tokens**, and resources on demand. Converting every fact into a skill recreates a startup tax. The useful unit is a small procedure family, not one SKILL.md per record.

**Caveat [OBS/INFERENCE]:** SkillsBench's [construction section](https://arxiv.org/html/2602.12670v4#S3) rejects low-signal tasks without measurable condition separation. Its curated task/skill distribution therefore should not be treated as a representative forecast for everyday coding. Its task-macro score can include verifier rewards between 0 and 1; [Table 16](https://arxiv.org/html/2602.12670v4#A12.T16) separately reports fully solved trial proportions. Retain strict functional completion as the Brain's correctness gate.

### 3. Native agents are already converging on Markdown, progressive recall, and background consolidation

**Claim — HIGH for mechanisms; MED for product implication:** The Brain's differentiator cannot simply be “files plus automatic notes.” It should provide portable, verified knowledge the current host cannot already derive or remember.

**[DOC]** [Claude Code memory](https://code.claude.com/docs/en/memory#auto-memory) maintains a machine-local repository memory directory with a small `MEMORY.md` index and topic files; the first **200 lines or 25KB** of the index load at session start, topic files load on demand. Current docs describe four note types: user, feedback, project, reference. They explicitly tell the agent to skip information derivable from code/git and what CLAUDE.md already says.

**[DOC/IMPL]** [Codex memories docs](https://developers.openai.com/codex/memories) describe background extraction from eligible idle chats, secret redaction, chat-level read/write controls, and an **off-by-default** `features.memories` flag. The [upstream pipeline README on main](https://github.com/openai/codex/blob/main/codex-rs/memories/README.md) describes **two phases**: per-rollout extraction to SQLite, then serialized global consolidation into Markdown, rollout summaries, and skills. This is implementation evidence accessed today, not a pinned installed release.

**[DOC]** Current [Letta MemFS](https://docs.letta.com/concepts/memfs/index.md) is a **git-backed Markdown/YAML memory filesystem**. `system/` content stays resident; other files are read on demand; the tree is resident. Current MemFS has **no semantic/vector index by default**, and agent-owned skills live in the same repository. [Dreaming](https://docs.letta.com/configuration/memory/index.md) uses background subagents after configured steps or compaction; optional agent review is another model pass, not human approval.

**Impact [INFERENCE]:** Compile one canonical Brain store into native discovery surfaces instead of shipping a competing memory runtime everywhere. Preserve the owner's cross-host/cross-machine knowledge, evidence, supersession, and private sharing. Do not blindly write into Codex's generated memory workspace: official docs call those files generated state, not the primary manual control surface. Prefer supported instructions/skills and an explicit candidate-import boundary.

### 4. “More instructions” is a measured failure mode, not just a token-budget concern

**Claim — HIGH:** Native rules can improve discoverability while still harming efficiency if they impose generic work or repeat the repository.

**[OBS]** [Evaluating AGENTS.md v1, 2026-02-12, §§4.1–4.3](https://arxiv.org/html/2602.11988v1#S4) studies **300 SWE-bench Lite tasks** and **138 AGENTbench tasks from 12 repositories**, four model configurations, sampled once per task/configuration. LLM-generated context files reduce performance in **5/8 settings**, add **2.45 / 3.92 steps** on the two datasets, and raise reported inference cost **20% / 23%**. GPT-5.2 reasoning tokens rise **22% on SWE-bench Lite / 14% on AGENTbench**; GPT-5.1 mini rises **14% / 10%**. The agents generally follow the instructions—the failure is not simply ignoring the file.

Developer-written files outperform generated ones and can help correctness, but also add work. Codebase overview sections do not meaningfully reduce steps to first interaction with a gold-patch file. Removing the original documentation changes the result: generated context files then improve performance **2.7% on average** in the tested subset. [Source, §4.2](https://arxiv.org/html/2602.11988v1#S4.SS2).

**Impact [INFERENCE]:** Use native instruction files for a minimal routing contract and genuinely non-obvious constraints. Do not export the whole Brain as always-on AGENTS.md/CLAUDE.md. A rule that causes one useful recall can be worth more than hundreds of correct but irrelevant facts; this needs an ablation against the same wording with an empty memory store.

### 5. The useful memory is often a verified procedure or a conditional negative lesson

**Claim — HIGH for paper measurements; MED for transfer:** Store the action-changing lesson, its applicability boundary, and evidence—not the narrative of the session.

**[OBS]** [ReasoningBank v1, 2025-09-29, Table 2](https://arxiv.org/html/2509.25140v1#S4.T2) on **500 SWE-bench Verified tasks** reports Gemini 2.5 Flash **34.2% → 38.8%** resolution and **30.3 → 27.5 steps**; Gemini 2.5 Pro **54.0% → 57.4%**, **21.1 → 19.8 steps**. The system extracts title/description/content from self-judged successes **and failures**, retrieves with embeddings, and appends items. Default retrieval is the memories from **one similar experience**, not a large knowledge dump. These are step savings; full lifecycle token savings were not established by that table.

**[OBS]** Its [failure ablation, §5.2/Figure 7](https://arxiv.org/html/2509.25140v1#S5.SS2) is on **WebArena-Shopping**, not coding: ReasoningBank success-only **46.5% → 49.7%** when failure lessons are included, while adding failures to AWM reduces **44.4% → 42.2%**. Negative memory means a distilled prevention rule, not appending failed transcripts.

**[IMPL]** Codex's [memory extraction prompt](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/stage_one_system.md) explicitly favors proven workflows, failure shields, exact paths/commands, task maps, and decision triggers. It prefers a no-op over low-signal notes, treats raw rollouts as immutable evidence, and disallows inventing verification. This is an unusually close implementation reference for the Brain's capture policy, not evidence of a measured gain.

### 6. Several premises in the existing research need tightening

**Claim — HIGH:** Four commonly repeated numbers support narrower conclusions than the current shorthand suggests.

1. **Letta 74.0% is not proof that plain grep-only memory beats libraries.** The [August 2025 original report](https://www.letta.com/blog/benchmarking-ai-agent-memory/) says files were automatically parsed and **embedded**, exposes semantic `search_files`, and **forces GPT-4o-mini to search before answering**. The comparison is against Mem0's reported **68.5%** graph score, not a controlled replacement of only the storage layer. Correct `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md:25–27` accordingly. Current MemFS being file-only by default does not retroactively change the 2025 experiment.
2. **Agent KB's disagreement gate is not helpful/harmful counters.** [Agent KB v5 §3.3](https://arxiv.org/html/2507.06229v5#S3.SS3) accepts refinements when embedding cosine similarity between old/new plans is **≥0.8**, using all-MiniLM-L6-v2. The suppression rule in `docs/research/v3-just-in-time-memory-proposal.md:63–64` is a new heuristic, not a replication of that gate. Read-following-delivery is not demonstrated causal helpfulness.
3. **ACE is not a proof that deterministic outcome scoring works.** [ACE v1 §3](https://arxiv.org/html/2510.04618v1#S3) uses a Generator/Reflector/Curator, model feedback, localized deltas, counter updates, and embedding-based deduplication. Its **+17.1-point AppWorld aggregate** is not a coding-repository result and does not isolate counters. With weak feedback, its FiNER online score **70.7 → 67.3** worsens [Table 2](https://arxiv.org/html/2510.04618v1#S4.T2).
4. **Sleep-time's ~5× is not a general coding speedup.** [Sleep-time Compute v1](https://arxiv.org/html/2504.13171v1#S6) gets that headline on modified math tasks. Its coding case is **33 PRs**, evaluates **changed-file F1**, not functional correctness, and reports up to roughly **1.5× fewer test-time tokens at low budgets**; test-time-only can win at high budgets. Total accounting must include the earlier compute.

### 7. Current code structure is better treated as a queryable index than as prose memory

**Claim — HIGH for APIs/mechanisms; MED for Brain savings:** Reuse code intelligence for definitions and references; reserve learned memory for decisions, traps, and hard-won routes that cannot be cheaply reconstructed.

**[DOC]** [Aider's repo map](https://aider.chat/docs/repomap.html) selects relevant symbol definitions/signatures using dependency-graph ranking; default `--map-tokens` is **1K**, with dynamic expansion. It is supplied with change requests. This is a bounded structural context product, not accumulated episodic memory. The documentation is not an isolated correctness/token ablation.

**[OBS]** [LocAgent](https://arxiv.org/abs/2503.09089) parses file/class/function and import/invocation/inheritance graphs. The reported **92.7% file-level accuracy**, approximately **86% cost reduction**, and **12% Pass@10 improvement** involve its experimental configuration, including a fine-tuned Qwen-2.5-Coder-32B result—not “add a graph to OMP and obtain these gains.”

**[OBS]** A newer [Agent Retrieval Bench, 2026-07-27](https://arxiv.org/abs/2607.24882) supplies **427 samples across 25 repositories**: **345 positive**, **50 natural no-gold**, **32 wrong-repository controls**. RepoMap gives the best reported context yield at an **8K-token budget**, while different embeddings win MRR and Recall@20. Agent trajectories miss every gold file on **27–35%** of samples. Thresholds calibrated on wrong-repository controls do not improve natural no-gold selective success. This is direct evidence against declaring either embeddings or fixed abstention thresholds universally superior; it is retrieval evidence, not an end-to-end patch correctness result.

**Impact [INFERENCE]:** A current symbol locator plus one evidenced “start here, not there” lesson is a more defensible first investment than an LLM-authored full-repository summary or conversational knowledge graph.

### 8. Cache economics and token efficiency are different objectives

**Claim — HIGH:** Preserve stable prefixes, but do not call a system token-efficient merely because more of its input is cached or cheaper.

**[DOC]** [OpenAI caching docs](https://developers.openai.com/api/docs/guides/prompt-caching.md) state that changes prevent reuse **after the first changed prefix position**, not necessarily the entire cache. They also show `input_tokens` already contains cached/read and cache-write subsets. A provider-neutral accounting adapter must avoid adding those subsets twice. The input fields used in OMP's normalized usage must be inspected before carrying the earlier campaign's formula to another provider.

**[DOC]** Anthropic's [context editing docs](https://platform.claude.com/docs/en/build-with-claude/context-editing#context-editing-and-prompt-caching) explicitly say tool-result clearing invalidates cached prefixes when clearing occurs. It can still be worthwhile, but it is not cache-free deletion.

**Impact [INFERENCE]:** For the subscription provider, record logical tokens, uncached/cached/write decomposition, output/reasoning where exposed, number of turns, and wall time. Cache-hit percentage alone is not success: a wasteful long session can have an excellent hit rate. Do not retrofit current list pricing onto earlier campaigns or treat API pricing as the owner's marginal subscription bill.

### Coverage ledger: what the requested systems actually do

The following supplements the ranked findings. A lack of an isolated measurement means **none was established in the primary sources checked**, not that none exists anywhere.

| System / applicable source | Mechanism actually evidenced | What was measured; transfer assessment |
|---|---|---|
| **Claude Code CLAUDE.md hierarchy** — [current official docs](https://code.claude.com/docs/en/memory#how-claude-md-files-load) **[DOC]** | Managed/user/project/local guidance; ancestors at launch; subdirectory guidance on reads; concatenation rather than strict file override. `@` imports eagerly expand, up to **four hops**. `.claude/rules` can be path-scoped. Docs recommend **under 200 lines** per CLAUDE.md. | No isolated memory-value benchmark on this page. Useful delivery substrate, not a validated content policy. Importing a large Brain file is not progressive disclosure. New AGENTS.md support is version-sensitive: current docs name **v2.1.277**, with some broader support fixed by **v2.1.281**; older installs need the documented CLAUDE.md import route. |
| **Claude Code auto memory** — [official docs](https://code.claude.com/docs/en/memory#auto-memory) **[DOC]** | Agent writes notes during work; index + topic files; **200 lines / 25KB** startup cap; machine-local, shared across worktrees of one repository; configurable directory. | No causal token/correctness result established. Native baseline must be measured with this feature explicitly on/off. Main-conversation auto memory is not generally loaded into ordinary subagents; forks are an exception per current docs. |
| **Anthropic memory tool** — [API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) **[DOC]** | `{"type":"memory_20250818","name":"memory"}`; model requests client-side operations under `/memories`; application owns storage and path restrictions. Current docs say Claude checks the directory before a task. Not the same feature as Claude Code auto memory. | [2025-09-29 announcement](https://claude.com/blog/context-management) **[OBS]**: internal agentic-search performance **+39%** with memory + context editing, **+29%** editing alone. Sample size and coding-memory isolation not supplied. |
[…70ln elided…]
- **Why grounded:** Letta's filesystem experiment enforced initial search; native skills advertise applicability; SWE-ContextBench separates oracle from free recall. [Letta](https://www.letta.com/blog/benchmarking-ai-agent-memory/), [Skills spec](https://agentskills.io/specification), [SWE-ContextBench](https://arxiv.org/html/2602.08316v3#S3.SS3).
- **Expected effect:** [INFERENCE] More coverage on tasks with no ordinary tool use and fewer initial search loops where useful memory exists. Unknown net tokens: the additional round trip can lose on easy tasks.
- **Effort / risk:** **S–M**. Risk: agents over-call it, ignore it, or anchor on a plausible wrong card.
- **Obsoletes if proven:** The absolute “no resident tool schema” assumption in `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md:40–42,117–119`, and tool-result-only delivery as the universal default. Does not require a new retrieval database.
- **Cheapest confirm/kill experiment:** Same routing text with empty store versus one oracle card versus existing bounded recall on the pilot. Kill if oracle adds no value; fix invocation before ranking if oracle helps but recall is not called. Only then compare schema/tool cost against CLI cost.

### B2. Turn experience into a few verified procedural packages, not more flat facts

- **Concrete change:** Curate a handful of high-leverage procedures from successful prior sessions: preconditions, shortest known route, exact canonical paths/commands, expected observations, a stop condition, and evidence. Store the canonical procedure once; generate SKILL.md/resource views for supporting hosts. Include a deterministic script only where it embodies an already proven repeated operation and normal permissions allow execution.
- **Change of kind:** The agent reuses an algorithm or workflow, not just an assertion. Dynamic Cheatsheet's Python solver is the clean example of eliminating a whole reasoning problem rather than summarizing it.
- **Why grounded:** [Dynamic Cheatsheet, stronger empty-memory control and code reuse](https://arxiv.org/html/2504.07952v1#S3.T1); [ReasoningBank coding results](https://arxiv.org/html/2509.25140v1#S4.T2); [SkillsBench](https://arxiv.org/html/2602.12670v4#S5).
- **Expected effect:** [INFERENCE] Higher correctness and reduced rediscovery on recurring procedures; no guaranteed total-token reduction. SkillsBench's GPT-5.5 token results specifically require measuring this, not assuming it.
- **Effort / risk:** **M**. Risk: overfitted skills, stale commands, catalog overhead, a procedure displacing a better default route.
- **Obsoletes if proven:** Treating every durable observation as a same-shaped short fact; title-only promotion as sufficient packaging; whole-transcript injection. Existing procedure records can remain canonical.
- **Cheapest confirm/kill experiment:** Manually curate **three** procedures using only prior verified episodes; test held-out related tasks against factual-card and native controls. No auto-curation engine first. Reject any procedure whose actual use adds work without correctness or token benefit.

### B3. Add conditional negative memory: known dead ends plus a safe alternative

- **Concrete change:** Capture “under these preconditions, avoid route X because evidence Y; use route Z; re-check if condition W changes.” Distinguish failed attempts from rejected requirements or mere opinions. Examples for this repo would be environment-specific launch traps or searching the wrong historical subsystem, but each candidate needs its existing evidence.
- **Change of kind:** Memory prevents expensive actions before they happen, rather than repairing an error afterward or preserving an answer.
- **Why grounded:** [ReasoningBank failure ablation](https://arxiv.org/html/2509.25140v1#S5.SS2) improves **46.5 → 49.7** only with appropriate failure distillation; naively adding failures to AWM worsens results.
- **Expected effect:** [INFERENCE] Avoided repeated failed runs and search branches; the benefit should appear in negative-route incidence, not just record reads.
- **Effort / risk:** **S** for a few records. Risk: permanent “never” rules survive after the underlying condition changes.
- **Obsoletes if proven:** Capture policies that record only successes; error-only delivery when the trap is knowable earlier; generic cautionary rules with no applicability boundary.
- **Cheapest confirm/kill experiment:** A few real, evidenced traps with near-miss tasks where the prohibition should **not** apply. Score both avoided traps and false prohibitions. Keep the false-prohibition cases in the no-benefit set.

### B4. Make memory reads proof-carrying and revision-aware

- **Concrete change:** On selection, check the locator/evidence revision and return a bounded current source excerpt or a current symbol location beside the claim. If the recorded evidence changed, do not silently repeat the old conclusion: expose the drift and the evidence to inspect. A changed hash means “revalidation needed,” not “the claim is false.” Never execute a recorded command merely because a memory requested it.
- **Change of kind:** Memory becomes a shortcut to current evidence instead of a second competing source of truth. The read contract, not an occasional doctor sweep, prevents blind reuse of stale information.
- **Why grounded:** The corpus already plans evidence and stale checking in `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md` §3.1/3.3. [Graphiti](https://arxiv.org/html/2501.13956v1#S2.SS2.SSS3) supplies temporal provenance concepts; [SWE-ContextBench Appendix A.4](https://arxiv.org/html/2602.08316v3#A1.SS4) demonstrates that experience pools can retain incorrect or partial solutions. No inspected paper establishes a quantified gain for this exact verification-on-read design.
- **Expected effect:** [INFERENCE] Better correctness under code/version drift; additional local I/O and sometimes more prompt tokens. This is a trust/utility hypothesis, not a free token optimization.
- **Effort / risk:** **M**. Risk: overly broad file hashes invalidate useful records; evidence exists but does not actually entail the claim; unavailable cross-machine paths.
- **Obsoletes if proven:** Trusting static grade labels as current validation, and returning stale cached answers merely because they were once tested. Retains canonical history and supersession.
- **Cheapest confirm/kill experiment:** In scratch snapshots, deliberately change a cited path, symbol, behavior, and an irrelevant neighboring line. Check which memory claims remain usable, which correctly abstain, and whether the consuming agent follows current evidence. Local selector checks can run without any model; the downstream usefulness test uses the common OpenAI arm.

### B5. Split “what the code is” from “what experience taught us”

- **Concrete change:** Use existing host LSP/symbol search or a source-derived map for current definitions, references, and test locations. Keep Brain records for cross-repository routes, decisions, environment constraints, and unusual search pivots. Return small task-specific symbol/evidence slices rather than a whole repo map at startup.
- **Change of kind:** Most location knowledge becomes refreshable code intelligence instead of an LLM-maintained prose copy of code.
- **Why grounded:** [Aider repo map](https://aider.chat/docs/repomap.html), [LSP definition/reference contract](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/), and [Agent Retrieval Bench](https://arxiv.org/abs/2607.24882). These do not establish a Brain-specific percentage.
- **Expected effect:** [INFERENCE] Fewer stale locators and fewer exploratory reads; potentially zero capture-model cost for mechanically derivable facts.
- **Effort / risk:** **S** if the host already exposes navigation, **M–L** for a new integration. Risk: unsupported languages/generated code, stale server state, or duplicated indexing systems.
- **Obsoletes if proven:** Routine “function X is in file Y” memories, repeated repository-wide summary generation, and a second graph/index when a working one already exists.
- **Cheapest confirm/kill experiment:** On the same localization tasks, compare native tools, a static memory locator, and a current symbol locator under equal context budgets. Include symbol movement and cross-project cases. Only add infrastructure after existing surfaces demonstrably miss needed information.

### B6. Capture a tested lesson at the natural handoff; treat auto-authorship as candidate production

- **Concrete change:** At a natural completion/compaction handoff, the agent may emit one concise delta: what materially changes a future route, where it was verified, and when it applies. No useful lesson means no write. Import equivalent native notes as candidates rather than maintaining multiple independently authoritative copies. Prefer the active agent's available context before designing a paid background re-reader of every full transcript.
- **Change of kind:** Learning is an ordinary completion artifact with minimal ceremony, not an extra manually administered memory task. The gate concerns evidence and usefulness, not whether a model can produce fluent notes.
- **Why grounded:** [Codex extraction prompt](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/stage_one_system.md), [LangMem background/hot-path distinction](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/#writing-memories), and [SkillsBench self-generation failure](https://arxiv.org/html/2602.12670v4#A4.SS6).
- **Expected effect:** [INFERENCE] More usable candidate procedures with less interruption; not established that the extra note tokens amortize. Candidate count alone is not success.
- **Effort / risk:** **S–M**. Risk: self-congratulation, inferred preferences, secret retention, and accidental promotion of a plausible but unverified workaround.
- **Obsoletes if proven:** High-ceremony note capture, always-summarize sessions, and acceptance based on fluent prose or final-message confidence.
- **Cheapest confirm/kill experiment:** Blindly audit notes from existing completed sessions against their recorded tool evidence, then test only accepted lessons on later held-out tasks. Compare with human-curated notes and no note. Include all authoring tokens in the eventual end-to-end accounting.

### B7. Learn selection only after measuring an oracle gap and natural abstention

- **Concrete change:** Build a query-to-relevant-record evaluation set including real no-benefit queries, stale near-matches, and wrong-project controls. Compare current deterministic/lexical selection with a small hybrid or semantic ranker only where lexical retrieval misses. Keep eligibility/privacy/currentness deterministic; do not let a relevance score override those constraints.
- **Change of kind:** Selection is trained or tuned against downstream usefulness/abstention rather than optimizing delivery frequency or interpreting a later file read as proof of benefit.
- **Why grounded:** [SWE-ContextBench oracle/free gap](https://arxiv.org/html/2602.08316v3#S3.SS3), [Agent Retrieval Bench natural-no-gold calibration failure](https://arxiv.org/abs/2607.24882), [Agent KB hybrid design](https://arxiv.org/html/2507.06229v5#S3.SS3).
- **Expected effect:** [INFERENCE] Better paraphrase recall without obligatory broad injection; potential inference/index overhead. No evidence establishes a universal learned-selector win over specific deterministic triggers.
- **Effort / risk:** **M**. Risk: training on near-duplicate evaluation prompts, false confidence on irrelevant queries, and optimizing proxy metrics.
- **Obsoletes if proven:** Hand-adding ever more path/command triggers for semantic questions; calling heuristic counters “outcomes”; fixed top-k retrieval without an abstention evaluation.
- **Cheapest confirm/kill experiment:** First perform frozen-store retrieval evaluation without a live model. Only candidate selectors that improve held-out relevant-card discovery while preserving natural no-gold abstention enter the common OpenAI downstream pilot. If an oracle card does not improve the task, stop selector work for that task family.

## Kill list

1. **Kill the claim that more memory machinery is the breakthrough.** Native Codex already does two-phase extraction/consolidation and current Letta uses git-backed Markdown. Keep the Brain's portable evidence/scope/currentness value rather than cloning another agent runtime. [Codex](https://github.com/openai/codex/blob/main/codex-rs/memories/README.md), [Letta](https://docs.letta.com/concepts/memfs/index.md). **[INFERENCE, HIGH]**
2. **Stop indiscriminate exports into always-on instruction files.** Generated repository instructions caused additional reasoning and exploration without reliable correctness benefit. Use minimal routing and non-obvious constraints, not an alternative README. [AGENTS.md study](https://arxiv.org/html/2602.11988v1#S4.SS3). **[OBS/INFERENCE, HIGH]**
3. **Stop treating zero tool-schema overhead as an inviolable product requirement.** It is a cost term, not the objective. A tool that is actually invoked can beat a nominally free CLI that is never called; the latter comparison is still to be measured. Relevant local assumption: `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md:117–119`; primary mechanism evidence: [Letta initial-search rule](https://www.letta.com/blog/benchmarking-ai-agent-memory/). **[INFERENCE, MED]**
4. **Stop calling “read after delivery” or “command eventually exited zero” causal helpfulness.** Those are behavioral signals; they can reward redundant reads or irrelevant advice. Neither ACE nor Agent KB validates the proposed deterministic scoring equivalence. Local mismatch: `docs/research/v3-just-in-time-memory-proposal.md:55–64`; [Agent KB gate](https://arxiv.org/html/2507.06229v5#S3.SS3), [ACE feedback](https://arxiv.org/html/2510.04618v1#S3.SS1). **[INFERENCE, HIGH]**
5. **Stop automatic whole-corpus rewrites and low-signal transcript summaries.** Keep localized changes, provenance, no-op capture, and explicit revalidation. ACE's collapse example and Codex's minimum-signal gate support this, though not every rewrite is necessarily harmful. [ACE](https://arxiv.org/html/2510.04618v1#S2.SS2), [Codex](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/stage_one_system.md). **[OBS/INFERENCE, HIGH]**
6. **Do not add a graph database, vector service, sleep agent, or prompt optimizer solely because a conversational benchmark advertises a large percentage.** Mem0's full-context baseline remains more accurate; graph adds context; Zep's gains concern temporal conversation QA; sleep-time's coding metric is file F1. These are design clues, not dependency justification for this local stdlib-oriented product. [Mem0 Table 2](https://arxiv.org/html/2504.19413v1#S4.T2), [Zep Table 2](https://arxiv.org/html/2501.13956v1#S4.T2), [Sleep-time §6](https://arxiv.org/html/2504.13171v1#S6). **[INFERENCE, HIGH]**
7. **Stop promising that skills or compact summaries necessarily save tokens.** Codex/GPT-5.5 SkillsBench tokens are essentially unchanged; SWE-ContextBench's oracle Codex tokens decline while latency rises; free summaries reduce correctness. Require both value and cost measurements. [SkillsBench Table 15](https://arxiv.org/html/2602.12670v4#A12.T15), [SWE-ContextBench Tables 3–4](https://arxiv.org/html/2602.08316v3#S3.T3). **[OBS, HIGH]**
8. **Stop cross-paper leaderboard comparisons without implementation parity.** Letta's forced iterative search, Mem0's extracted facts, LangMem's top-10, and other systems' top-3/top-15 are not one-variable substitutions. SWE-ContextBench [Appendix A.2](https://arxiv.org/html/2602.08316v3#A1.SS2) even supplies an explicit always-recall instruction for its Supermemory arm. **[OBS/INFERENCE, HIGH]**
9. **Stop using published API dollar savings as the owner's success criterion.** Keep the pricing comparison as background; optimize the chosen subscription agent's correctness, tokens, latency, and usable throughput. Preserve cache decomposition without double counting. [OpenAI accounting guide](https://developers.openai.com/api/docs/guides/prompt-caching.md). **[DOC + owner constraint, HIGH]**
10. **Retire or correct the four overbroad literature summaries before building on them:** Letta “plain filesystem,” Agent KB gate = deterministic harmful counters, sleep-time 5× = coding, and version-mixed SWE-ContextBench efficiency claims. Exact corrections and sources are in findings 1 and 6. This research did not edit those documents.

## Open questions

1. **Does early access to the best existing Brain record improve the chosen OpenAI model?** Published oracle effects vary substantially by model/harness; the supplied earlier cheap-model campaigns do not answer this. Smallest resolution: frozen-corpus oracle-card pilot on `openai-codex/gpt-5.5` with native and empty-store routing controls.
2. **What is the actual invocation cost/benefit of one native recall tool or skill in OMP?** Native skills/AGENTS.md semantics belong to hosts, not model providers. None of the inspected external sources proves OMP's selected model will discover and use the proposed surface. Smallest resolution: observe actual first-prompt recall, no-tool answers, latency, and token totals in the bounded pilot.
3. **How much unique knowledge survives a native-memory/code-intelligence baseline?** Official Claude/Codex/Letta mechanisms overlap substantially, but installed host versions and native memory contents were outside this external-research assignment. The Brain's cross-host/cross-machine and evidence gaps may remain valuable; their size is not quantified here.
4. **Can verification-on-read pay for itself under realistic drift?** No directly applicable controlled result was established for the exact local revision/evidence gate proposed here. Need unchanged, irrelevant-change, semantic-change, missing-source, and cross-machine cases—not just a stale-file hash test.
5. **Can natural no-benefit queries be rejected reliably?** Agent Retrieval Bench specifically shows counterfactual calibration failing to transfer to natural no-gold cases. The Brain needs genuine daily-work negatives, not merely unrelated trivia or wrong-project names.
6. **How durable and general are self-authored procedural lessons?** SkillsBench's self-generated-before-solving failures do not refute verified post-task distillation; ReasoningBank's results do not prove unrestricted self-promotion is safe. Need temporally separated task families with evidence review and construction-token accounting.
7. **How representative are the benchmark deltas?** SWE-ContextBench v3 admits noisy task/experience validation, SkillsBench selects for measurable skill separation, several papers use one sample or do not establish repeated coding trials, and conversational studies report retrieval rather than agent lifecycle tokens. These limitations rule out importing a headline percentage as a forecast.
8. **What are Cursor's current memory semantics on the owner's installed build?** Its historical 1.0 behavior is verified, but the old memory docs redirected and current rules docs do not settle all memory defaults/privacy/support. Resolve against the exact installed release before building a memory-specific adapter.
9. **How does OMP normalize the selected provider's usage fields?** OpenAI documents cached/write counts as subsets of input tokens. The earlier aggregate formula must be checked against host normalization before using it to compare providers or determine a token win. No OMP usage implementation was audited in this external-literature assignment.

Bottom line [INFERENCE]: Preserve the file-based canonical store. The strongest next change is not “more memory”; it is **reliably reaching a few verified, action-changing procedures or locators at the start of the right task, through the host's familiar discovery surfaces, while staying silent and cheap elsewhere**. Treat an oracle/content test, a selector/invocation test, and a lifecycle token/correctness test as separate gates. No inspected primary source proves that any single memory architecture already meets the Brain's full local, cross-agent, fewer-tokens-and-higher-correctness objective.


[Showing lines 1-115 and 186-278 of 278; 70 middle lines (21.8KB) elided. Read artifact://307 for full output]