# Second Brain v3 — Final R&D Thesis
## Cognitive Efficiency, State Coherence, and Verified-Work Economics

**Status:** Research synthesis / architecture direction — **not an implementation plan**  
**Date:** 2026-09-04  
**Primary harness:** OMP (Oh My Pi)  
**Goal:** Use what v2 already built to make agentic work cheaper, more stateful, less repetitive, and more reliable.

---

# Executive thesis

Second Brain v3 should **not** be defined by feature count.

V2 already established most of the important adaptive substrate: trusted/earned memory, Retrieval Intelligence 2.0, Brainstem, causal learning, engrams/action reuse, governed self-improvement, and a universal harness-control-plane direction.

The best v3 identity is a **cognitive-efficiency and state-coherence overhaul**:

> **Second Brain v3 should make intelligence cheaper.**

The question changes from:

> What can the Brain remember, retrieve, and coordinate?

to:

> **What is the cheapest path to a verified successful result, and how much paid cognition is actually necessary?**

That means optimizing more than raw tokens. The real cost includes:

- reasoning/thinking tokens;
- normal input/output tokens;
- prompt-cache misses;
- tool calls;
- noisy repository exploration;
- subagent coordination;
- latency;
- retries and rework;
- verification;
- provider/subscription quota;
- failure recovery.

A major conclusion from this research is that **model switching should not be the first v3 lever**. Initially, keep the active model stable and dynamically manage its reasoning effort. Escalate to another model only as a late fallback.

The desired pattern is:

```text
cheap baseline cognition
        ↓
state / retrieval / tools / tests
        ↓
is meaningful uncertainty still unresolved?
        ├─ no  → continue cheaply
        └─ yes
             ↓
      raise next reasoning episode
             OR
      spawn one bounded same-model
      high-reasoning specialist
             ↓
      compact evidence/decision receipt
             ↓
      parent resumes cheap baseline
```

This creates **temporary high-reasoning islands inside a mostly low-reasoning workflow**.

---

# 1. What v3 should overhaul

A major version can be justified by deep changes to existing mechanisms rather than dozens of new features.

The strongest v3 research directions are:

1. **Dynamic cognitive scheduling** — treat reasoning effort as a resource.
2. **State-first execution** — validated mutable state replaces replaying growing transcript/reasoning history.
3. **High-reasoning islands** — expensive cognition is localized to rare hard decisions.
4. **Proof-before-thought** — tests, tools, hashes, state and deterministic checks resolve uncertainty before buying more reasoning.
5. **Cognition amortization** — repeated reasoning compiles into engrams, procedures, skills, action caches or deterministic mechanisms.
6. **Reasoning receipts** — carry portable verified decision state, not raw chain-of-thought.
7. **Context coherence** — stable refs/version hashes and deltas replace full-state rebroadcast to workers.
8. **Root-goal accounting** — the parent and all descendants are charged to one task budget.
9. **Cache-aware cognition** — an effort change is only a saving if it does not destroy more cache value than it saves.
10. **Verified-work economics** — optimize cost per verified successful task, not token count alone.

---

# 2. OMP Auto Thinking: what it actually does

OMP's current source defines the canonical thinking ladder as:

```text
minimal
low
medium
high
xhigh
max
```

Its UI metadata describes these approximately as:

```text
minimal ≈ 1k reasoning tokens
low     ≈ 2k
medium  ≈ 8k
high    ≈ 16k
xhigh   ≈ 32k
max     ≈ highest supported tier
```

These are approximate OMP descriptions, not guaranteed provider budgets.

Most importantly, OMP `auto` is **per user turn**. The session resolves `auto` into a concrete effort each turn.

OMP's current classifier describes:

- **low** — trivial/mechanical/direct factual work;
- **medium** — localized change or straightforward bug;
- **high** — multi-file/debugging/moderate design;
- **xhigh** — concurrency, cross-system reasoning, ambiguity, risky refactors, hard root cause;
- **max** — xhigh plus exceptional conditions such as irreversibility, possible data loss, missing reproduction, or live cutover correctness.

OMP explicitly tells the classifier to choose the **lower** tier when uncertain.

Sources:

- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/thinking.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/prompts/system/auto-thinking-difficulty.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/provider-compat-reference.md

So v3 should **not duplicate OMP Auto Thinking**.

OMP can answer:

> "How hard does the user's request look initially?"

Second Brain can answer the more valuable runtime question:

> **"Given everything we have learned during execution, how much unresolved cognition remains now?"**

---

# 3. Cognitive Governor / Cognitive DVFS

Working research name: **Cognitive Governor**.

The CPU analogy is useful: a processor should not run every workload at maximum power. A reasoning model should not spend maximum inference effort on every tool result, lookup, test run, or obvious edit.

## Initial effort

Use OMP Auto as the default initial prior.

Examples:

```text
"Find where this timeout is configured."
→ low

"Explain this local function."
→ low/medium

"Find the timeout and audit whether it can silently break recovery."
→ medium/high

"Audit concurrent state recovery and prove it is race-safe."
→ high/xhigh
```

## Runtime re-evaluation

The original sentence cannot reveal everything. During a task, Second Brain may discover:

- conflicting implementations;
- failed tests;
- hidden concurrency;
- migration or data-loss implications;
- stale state;
- cross-harness disagreement;
- ambiguous requirements;
- failed prior attempts.

Reasoning should therefore be reconsidered at meaningful **cognitive episode boundaries**:

- major tool result;
- test failure;
- contradiction discovered;
- hypothesis count increases;
- scope expands;
- risk/irreversibility rises;
- prior fix fails;
- verification begins;
- worker returns uncertainty or conflicting evidence.

This is not changing effort halfway through one inference. Agentic work is normally:

```text
model → tool → model → tool → model
```

The Governor changes effort for a **later model call / episode**.

---

# 4. Cognitive hysteresis: avoid effort thrashing

A bad design would do:

```text
low → medium → low → high → medium → low
```

after every tiny event.

That can cause cache churn, inconsistent behavior and control complexity.

A better design is episode-level hysteresis:

```text
start low
    ↓
evidence crosses escalation threshold
    ↓
enter medium episode
    ↓
remain medium while same uncertainty is active
    ↓
hard isolated decision appears
    ↓
high specialist or higher parent call
    ↓
decision settles
    ↓
return parent to cheap baseline
```

Higher effort should be **earned by new evidence**.

De-escalation should happen after the difficult reasoning episode settles.

---

# 5. Cognitive debt: a stronger signal than "confidence"

A useful v3 concept is **cognitive debt**:

> How much unresolved reasoning remains before the task can safely be considered understood or verified?

Possible structural signals:

- unresolved requirements;
- multiple live hypotheses;
- contradictions;
- failed prior attempts;
- failed/missing tests;
- low evidence coverage;
- unknown root cause;
- unresolved dependencies;
- stale state;
- high change risk;
- irreversibility;
- cross-component scope;
- missing reproduction;
- worker disagreement;
- verification gaps.

Do **not** primarily ask the model:

> "How confident are you?"

Research cautions against treating verbal confidence as correctness. RiskEval found models often fail to adapt decisions appropriately under changed error penalties, and a 2026 study found reported confidence can track commitment more strongly than actual correctness.

Sources:

- https://arxiv.org/abs/2601.07767
- https://arxiv.org/abs/2606.29490
- https://arxiv.org/abs/2310.01798

Model self-confidence may be one weak feature. External/structural evidence should dominate.

---

# 6. High-reasoning islands

This is one of the strongest v3 ideas from our discussion.

Instead of:

```text
parent agent = high effort for the whole task
```

use:

```text
parent = low/medium
       ↓
hard localized decision appears
       ↓
same-model high/xhigh specialist
       ↓
compact decision + evidence + uncertainty
       ↓
parent resumes low/medium
```

Most coding sessions contain large amounts of low-cognitive work:

- locating files;
- running tests;
- applying obvious edits;
- checking hashes;
- reading status;
- gathering versions;
- executing known procedures.

Only a subset needs deep cognition:

- subtle concurrency;
- architecture boundaries;
- migration safety;
- contradictory evidence;
- non-local root causes;
- release-critical decisions.

High-reasoning islands localize expensive thinking to those moments.

---

# 7. OMP already exposes the control surface

The final scan found that OMP extensions currently expose:

```text
getThinkingLevel()
setThinkingLevel()
```

OMP's task/subagent executor also supports per-spawn coarse effort:

```text
lo
med
hi
```

and maps it onto the selected model's actual supported effort ladder.

OMP additionally supports a task `maxEffort` ceiling.

This matters because `hi` means:

> highest effort supported by the target model

which can be `max`.

Sources:

- https://github.com/can1357/oh-my-pi/blob/main/docs/extensions.md
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/extensibility/extensions/loader.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/thinking.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/task/executor.ts

Therefore the v3 concept can likely be built **with OMP rather than by replacing/forking OMP**.

A high-reasoning island should conceptually prefer something like:

```text
effort = hi
ceiling = xhigh
```

for normal deep reasoning.

`max` should remain exceptional and evidence-triggered.

---

# 8. Avoid duplicate classifier tax

OMP Auto Thinking already runs a TINY/smol classifier by default, with optional small local models.

Source:

- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/tiny/models.ts

Second Brain should not add another LLM classification call every turn just to decide how much thinking to buy.

That would mean:

> spending model compute to decide whether to spend model compute.

Better split:

### OMP
Initial prompt difficulty.

### Second Brain
Deterministic runtime re-evaluation from state, tests, contradictions, risk and evidence.

Only add a learned Second Brain classifier later if experiments prove its own cost produces net savings.

---

# 9. Parent escalation vs specialist spawn

Multi-agent research strongly argues against "spawn whenever hard."

Google Research evaluated 180 agent configurations and found:

- large gains on parallelizable tasks;
- **39–70% performance degradation** for multi-agent approaches on strict sequential planning tasks;
- increasing coordination tax on tool-heavy tasks;
- independent multi-agent error amplification;
- centralized coordination giving better error containment than independent swarms.

Source:

- https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/

So v3 should distinguish:

## A. Sequential reasoning tightly coupled to parent state

Prefer:

```text
raise the next parent call's effort
```

No reacquisition/handoff tax.

## B. Deep but cleanly separable reasoning pocket

Prefer:

```text
one bounded same-model high-effort specialist
```

Give it only the evidence necessary for that question.

## C. Consequential decision where independence matters

Prefer:

```text
fresh-context focused verifier
```

The point is independence from the parent's assumptions, not merely more tokens.

A useful rule:

> **Escalate within the parent when cognition is sequential; isolate when the hard question is separable; use independent verification when correlated reasoning is the risk.**

---

# 10. More thinking is not always better

The v3 case for dynamic effort is strengthened by multiple studies.

*When More Thinking Hurts* reports diminishing marginal returns at high reasoning budgets and cases where extended reasoning abandons previously correct answers. Optimal thinking length varied with task difficulty.

NeurIPS 2025's *Does Thinking More Always Help?* also found an improve-then-decline pattern under extended reasoning and showed parallel shorter paths could beat a single extended path under equal budget in its experiments.

ICML 2025's *Do NOT Think That Much for 2+3=?* studies wasteful overthinking on easy tasks.

Sources:

- https://aclanthology.org/2026.findings-acl.1199/
- https://arxiv.org/abs/2604.10739
- https://proceedings.neurips.cc/paper_files/paper/2025/hash/fc067ac218430c409d6f65403328f740-Abstract-Conference.html
- https://proceedings.mlr.press/v267/chen25bx.html

V3 therefore needs a **cognitive stop rule**.

Stop increasing effort when:

- requirements are satisfied;
- evidence coverage is sufficient;
- tests prove the relevant behavior;
- contradictions are resolved;
- material uncertainty is gone.

High/max is more compute, not guaranteed correctness.

---

# 11. Adaptive compute research supports the Governor

The 2026 paper *Adaptive Test-Time Compute Allocation for Reasoning LLMs via Constrained Policy Optimization* formalizes inference as maximizing expected accuracy subject to a compute budget and reports better matched-budget performance than uniform/heuristic allocation in its evaluated math tasks.

Source:

- https://arxiv.org/abs/2604.14853

The general lesson is strong:

> **Uniform reasoning allocation is inefficient.**

Second Brain can eventually do better than an input-only classifier because it observes the real task trajectory:

```text
task signature
+ current effort
+ tool results
+ tests
+ contradictions
+ failures
+ evidence coverage
+ final verification
+ total cost
```

V2's causal/prediction-error machinery is already a good foundation for learning these policies.

---

# 12. Proof before thought

A major final synthesis:

Before paying for deeper reasoning, Brainstem should ask:

> **Can a cheap deterministic observation settle this uncertainty?**

Examples:

```text
Does it compile?
→ compile

Did behavior regress?
→ test

Does the file/call site exist?
→ filesystem/index/AST/rg

Did state change?
→ hash / DB query

Are two artifacts identical?
→ content hash

Is migration recovery safe?
→ isolated migration/restore experiment
```

Classic self-correction research found that asking models to reconsider without external feedback can fail or even degrade performance.

Source:

- https://arxiv.org/abs/2310.01798

So:

> **Do not buy reasoning tokens to answer something a deterministic probe can settle.**

---

# 13. Reasoning and tool budgets should be scheduled together

Thinking is only one inference-time resource.

*Budget-Aware Tool-Use Enables Effective Agent Scaling* reports that simply allowing more tool calls does not automatically improve agent performance and argues for joint token/tool budget awareness.

Source:

- https://arxiv.org/abs/2511.17006

Anthropic has also introduced task budgets for supported API models that span a full agentic loop—thinking, tool calls/results and output—while effort controls depth per step.

Source:

- https://platform.claude.com/docs/en/build-with-claude/task-budgets

Second Brain can generalize the principle independently of provider:

```text
reasoning-effort ceiling
token budget
tool-call budget
wall-clock budget
worker-concurrency budget
scope
verification requirement
exact deliverable
```

A high-reasoning specialist should be a **bounded resource envelope**, not a second open-ended session.

---

# 14. Can we offload paid thinking?

## What cannot be offloaded

We cannot ask a provider model to internally perform thousands of hidden reasoning tokens and somehow have those exact tokens executed somewhere else for free.

For OpenAI API reasoning models, hidden reasoning tokens count toward output usage and are billed as output tokens.

Source:

- https://help.openai.com/en/articles/4936856-w

## What can be offloaded

We can remove the need for those tokens.

### 1. Deterministic cognition

Move work into:

- SQLite;
- hashes;
- state machines;
- AST/index queries;
- validators;
- tests;
- schemas;
- policy rules;
- provenance/freshness checks.

### 2. Exploration isolation

Broad repository search can be isolated from the main solver context.

FastContext reports up to 60% main-agent token reduction in its evaluated coding setups by using a specialized repository explorer.

- https://arxiv.org/abs/2606.14066

Microsoft's Terminus-4B reports up to roughly 30% main-agent token reduction on evaluated software tasks by offloading terminal execution to a specialized small model.

- https://www.microsoft.com/en-us/research/publication/terminus-4b-can-a-smaller-model-replace-frontier-llms-at-agentic-execution-tasks/

These are research signals, not guarantees for our workload. OMP already has task/scout capabilities, so Second Brain should use harness capabilities rather than create a competing agent framework.

### 3. State

Do not force the model to reconstruct task state from transcript history.

### 4. Procedural reuse

If a recurring problem already has a verified procedure/engram/skill, do not reason from scratch.

### 5. Provider-native continuity

When the same provider/model supports preserving reasoning state, reuse it.

### 6. Brain-native decision receipts

Across harness/provider boundaries, transfer the verified decision state and unresolved uncertainty, not the full reasoning history.

The useful definition is:

> **Thinking offload = remove work from paid cognition, not relocate private chain-of-thought.**

---

# 15. State-first runtime

SKILL.state is highly aligned with Second Brain.

It replaces append-only long-horizon conversational history with:

```text
immutable skill specification
+
explicit mutable execution state
+
latest observation
```

Intermediate reasoning is discarded after a validated state update. The paper reports improved accuracy and substantially reduced cumulative token use in its evaluated settings.

Source:

- https://arxiv.org/abs/2608.26263

This suggests a major v3 overhaul:

```text
transcript = task state
```

should evolve toward:

```text
validated structured state = task state
transcript = evidence/history/archive
```

Second Brain already has:

- Active State Capsule;
- Requirement Ledger;
- session/event ledger;
- VMem;
- artifacts;
- handoff packets;
- decisions;
- context paging.

V3 should investigate whether Active State can become a near-sufficient representation for continuation.

That would make compaction much safer: checkpoint authoritative state and preserve exact recovery refs instead of repeatedly summarizing a giant transcript.

---

# 16. Reasoning receipts

A v3 **Reasoning Receipt** should not contain raw/private chain-of-thought.

It should contain the portable result needed to avoid rediscovering the decision:

```text
decision
assumptions
evidence refs + hashes
requirements satisfied
tests run
remaining uncertainty
brief rejected alternatives when useful
invalidation conditions
next action
state/version identity
```

## Same provider/model

Use provider-native continuity where supported.

Gemini uses thought signatures/state for reasoning continuity:

- https://ai.google.dev/gemini-api/docs/thought-signatures

OpenAI Responses provides persisted conversation/reasoning-state and prompt-cache mechanisms:

- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create

## Cross-harness/provider

Provider-private reasoning is not portable.

The Brain Receipt becomes the shared representation.

So continuity becomes:

```text
provider-native opaque cognition
+
portable verified Brain receipt
```

without depending on transcript dumping or chain-of-thought extraction.

---

# 17. Context coherence instead of rebroadcast

Workers repeatedly receiving the same policy, project state, decisions and artifacts creates token waste and stale copies.

The preprint *Token Coherence* maps this problem to cache-coherence ideas and proposes versioning/lazy invalidation instead of repeated full-state broadcast. Its very large simulated savings should be treated as experimental, but the core concept is relevant.

Source:

- https://arxiv.org/abs/2603.15183

A good v3 direction is:

```text
one canonical object
+
version/hash
+
worker-held ref
+
delta/invalidation on change
```

rather than:

```text
send complete shared state again
```

That fits Second Brain's existing content-addressed artifacts, packet hashes, VMem, and worker packets.

Worker context can increasingly behave like copy-on-write:

```text
shared immutable refs
+
small task delta
+
explicit invalidations
+
fault-in only when needed
```

---

# 18. Cognition compiler: reason once, then amortize it

This may be v3's deepest long-term idea.

Novel problem:

```text
deep reasoning is justified
```

Repeated problem class:

```text
paying for the same reasoning again is waste
```

Desired progression:

```text
expensive reasoning
        ↓
verified experience
        ↓
generalizable strategy
        ↓
reusable skill / engram
        ↓
low-effort or deterministic execution
```

V2 already has most ingredients:

- earned memory;
- causal learning;
- workflow engrams;
- action cache;
- model culture;
- governed promotion;
- skill lifecycle.

Relevant research:

### ReasoningBank
Distills strategies from successes and failures rather than storing only raw trajectories.

- https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/
- https://arxiv.org/abs/2509.25140

### ProcMEM
Transforms recurring experience into executable skills with activation, execution and termination conditions.

- https://arxiv.org/abs/2602.01869

### SkillGen
Treats a generated skill as an intervention and compares the same instances with/without the skill to detect both repairs and regressions.

- https://www.microsoft.com/en-us/research/publication/skillgen-verified-inference-time-agent-skill-synthesis/

This suggests a stronger engram question for v3:

> **Does this reusable cognition measurably reduce verified task cost without reducing correctness?**

A successful v3 should gradually move common workflows:

```text
high → medium → low → procedure → deterministic replay
```

as evidence accumulates.

---

# 19. Compact decision artifacts, not verbose rationale

Chain of Draft reports that concise intermediate reasoning matched or exceeded verbose CoT on its evaluated benchmarks while using far fewer visible tokens.

Source:

- https://arxiv.org/abs/2502.18600

This is not direct proof about hidden provider reasoning, but it strongly supports:

> Worker returns, reasoning receipts, handoffs and state updates should carry minimum sufficient information—not essays.

The Brain's durable state should become more structured as it matures.

---

# 20. Parallel reasoning: exceptional fallback

There are cases where several short independent paths are better than one extremely long path.

NeurIPS 2025's test-time scaling study reported parallel independent reasoning outperforming extended single-path reasoning under matched budgets in its experiments.

Reliability-Aware Adaptive Self-Consistency also reports strong cost reductions versus fixed sampling on some benchmarks.

Sources:

- https://proceedings.neurips.cc/paper_files/paper/2025/hash/fc067ac218430c409d6f65403328f740-Abstract-Conference.html
- https://arxiv.org/abs/2601.02970

V3 should use this only when:

- decision consequences are high;
- one reasoning path remains materially uncertain;
- independence is valuable;
- external evidence cannot cheaply settle it;
- expected benefit exceeds coordination cost.

Do not turn hard questions into default multi-agent debate.

---

# 21. Provider-aware cache economics

OMP provides one normalized effort abstraction, but providers implement it differently.

OMP currently maps its canonical effort levels onto mechanisms such as:

- OpenAI reasoning effort;
- Anthropic adaptive effort;
- Google thinking levels/budgets.

Source:

- https://github.com/can1357/oh-my-pi/blob/main/docs/provider-compat-reference.md

But effort transitions can have different cache consequences.

Anthropic currently documents that changing top-level effort can invalidate prompt caching on models without per-message effort support; supported per-message effort can preserve cache.

- https://platform.claude.com/docs/en/build-with-claude/effort

OpenAI GPT-5.6+ exposes explicit prompt-cache controls/breakpoints, while newer OpenAI interfaces are adding stronger mid-conversation reasoning configuration.

- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/docs/guides/latest-model

Gemini recommends common content at the beginning and similar prefixes close together for implicit cache hits.

- https://ai.google.dev/gemini-api/docs/caching/

Therefore:

```text
reasoning savings
-
cache loss
-
transition overhead
```

is the real value of an effort change.

This reinforces the existing PREFIX/TAIL direction and the IDEA_LEDGER decision against unnecessary dynamic schema churn.

---

# 22. Same-model-first escalation ladder

The refined v3 ladder should be:

```text
0. deterministic/no-model mechanism
        ↓
1. active model at low effort
        ↓
2. same model at medium
        ↓
3. bounded same-model high/xhigh specialist
        ↓
4. fresh independent verifier / limited parallel reasoning
        ↓
5. stronger/different model only as exceptional fallback
```

Why delay model switching:

- fewer cache disruptions;
- simpler provider/auth/quota behavior;
- easier measurement;
- less harness-specific logic;
- OMP already provides good effort controls;
- separates "model quality" from "reasoning allocation."

Model routing can remain a future Brainstem capability without defining early v3.

---

# 23. Execution difficulty ≠ decision difficulty

A huge mechanical edit may be low cognitive difficulty:

```text
500 files changed by deterministic transformation
→ low-thinking execution + tests
```

A two-line recovery lock change may be extremely high cognitive difficulty:

```text
2 lines
→ concurrency proof + high reasoning + targeted verification
```

So v3 should not route primarily on:

- prompt length;
- diff size;
- file count;
- number of tool calls.

Those measure work volume, not necessarily unresolved cognition.

Brainstem should separately estimate:

```text
execution volume
```

and:

```text
decision difficulty / cognitive debt
```

---

# 24. Conceptual v3 cognitive loop

This is a research model, **not an implementation plan**.

```text
TASK ARRIVES
    ↓
Can deterministic state/rules/reuse answer?
    ├─ yes → no model
    └─ no
         ↓
Use OMP Auto as initial effort prior
         ↓
MODEL / TOOL EPISODE
         ↓
Update validated task state
         ↓
Measure cognitive debt
    ├─ low → remain/de-escalate
    └─ high
         ↓
Can a cheap tool/test settle uncertainty?
    ├─ yes → collect proof
    └─ no
         ↓
Is reasoning sequentially coupled to parent?
    ├─ yes → raise next parent effort
    └─ no
         ↓
Is it a separable hard pocket?
    ├─ yes → bounded same-model high island
    └─ no
         ↓
Does consequential uncertainty require independence?
    ├─ yes → fresh verifier
    └─ no → continue parent
         ↓
Evidence sufficient?
    ├─ yes → STOP THINKING / settle
    └─ no → one justified escalation step
```

The key rule:

> **Effort is earned by unresolved evidence, not permanently assigned at session start.**

---

# 25. Verified-task economics

The wrong target is:

```text
minimize tokens
```

because a cheap wrong run creates retries.

The wrong target is also:

```text
maximize accuracy at any cost
```

A better target:

> **Minimize expected total cost per verified successful task subject to risk constraints.**

Conceptually:

```text
C_verified =
    paid reasoning
  + uncached input
  + output
  + tool cost
  + coordination cost
  + latency
  + cache-break cost
  + retry/rework
  + verification
  + recovery
```

Optimize against:

```text
verified success
requirements satisfied
risk constraints satisfied
```

This also works when marginal dollar pricing is not visible. Excessive cognition can still consume quota, wall time, credits or scarce subscription capacity.

---

# 26. Root-goal accounting

A parent can appear cheap while its children consume the real budget.

V3 should account at the task-tree level:

```text
root task
├── parent
├── explorer
├── high-reasoning specialist
└── verifier
```

Aggregate:

- all reasoning/output tokens;
- input/cache cost;
- tool calls;
- wall time;
- workers;
- retries;
- final verified outcome.

This prevents false economics such as:

> "The driver only used 2k tokens"

while children used 80k.

The current IDEA_LEDGER's interest in descendant/root-goal accounting is therefore strongly justified.

---

# 27. Bounded specialist contract

A high-reasoning island should resemble a process resource group:

```text
OBJECTIVE
one exact hard question

EVIDENCE
only relevant refs

SCOPE
bounded files/subsystem

EFFORT
hi

EFFORT CEILING
high/xhigh unless exceptional conditions justify max

TOOL BUDGET
bounded

REQUEST/TURN BUDGET
bounded

WALL CLOCK
bounded

RETURN
decision
evidence
uncertainty
invalidation conditions
next action
```

The specialist should return a **receipt**, not its transcript.

The parent should not inherit every failed hypothesis, tool log, or raw search result.

---

# 28. Broad exploration should sometimes be isolated

Repository exploration is a strong offload candidate because it is verbose and can pollute solver context.

But the rule should not be:

> search always gets a subagent.

A direct one-file lookup is cheaper inline.

A broad exploration may deserve isolation when:

```text
expected context pollution > handoff/coordination cost
```

This threshold can eventually be learned from telemetry.

OMP's existing task/scout capabilities are the preferred execution mechanism rather than creating a separate Second Brain swarm subsystem.

---

# 29. Aggressively seek zero-model paths

The best reasoning optimization is not:

```text
high → medium
```

It is:

```text
model call → no model call
```

Potential zero-model operations:

- project identity;
- trust/refusal gates;
- content hashes;
- task lifecycle;
- cache validation;
- budget accounting;
- exact artifact reuse;
- freshness invalidation;
- capability checks;
- schema validation;
- deterministic routing constraints;
- compaction coverage proof;
- dependency invalidation;
- known action-cache replay.

This keeps the Brain's OS-kernel analogy honest.

> The control layer should not consume premium intelligence just to administer itself.

---

# 30. Learn effort curves, not model prestige

Eventually Second Brain can learn empirically:

```text
task family: repo lookup
low      → 99% verified, 1.0x cost
medium   → 99% verified, 2.4x
high     → 99% verified, 6.8x
```

Choose low.

Another:

```text
task family: concurrency root cause
low      → 48% verified
medium   → 72%
high     → 91%
xhigh    → 92%
```

Choose high.

The relevant question becomes:

> **What is the marginal verified value of the next effort tier for this task family?**

Not:

> "Which tier is smartest?"

---

# 31. Learn from outcomes, not prompt labels

A static classifier may say:

```text
"audit" → high
```

but runtime outcomes are better evidence.

Example:

```text
initial low
clean tool evidence
targeted tests pass
requirements covered
→ low was sufficient
```

versus:

```text
initial low
3 contradictory call paths
2 failed fixes
no reproduction
→ low was insufficient
```

V2's causal/prediction-error learning can naturally feed future effort policies.

Do not create a separate learning stack.

---

# 32. Govern the cognition policy

V3 should not let one successful cheap run lower effort globally.

Nor should one failure permanently promote every similar task to xhigh.

Reasoning policies should inherit v2 governance:

- evidence count;
- scope;
- freshness;
- contradiction handling;
- counterexamples;
- shadow evaluation;
- rollback;
- causal/economic comparison.

A cheaper policy is only good if verified outcomes hold.

---

# 33. Anti-goals

V3 should **not**:

- build a swarm OS;
- make model switching the headline;
- create a second reasoning-memory DB;
- store raw chain-of-thought as canonical memory;
- add another LLM classifier to every event;
- assume high/max is always better;
- let verbal confidence control escalation;
- dynamically churn stable tool/system prefixes without measured value;
- make every broad operation a subagent;
- optimize tokens while ignoring retries/rework;
- defer known v2 release-blocking bugs just to call them v3 improvements;
- revive vector fallback or dynamic tool-schema churn without new evidence;
- create a literal BrainFS for aesthetics.

---

# 34. Research experiments before v3 design lock

These are validation questions, not an implementation sequence.

## Effort sweep

Run representative real Second Brain coding tasks at:

```text
low / medium / high / xhigh
```

Measure verified success, reasoning/output tokens, tools, latency, retries and cache hits.

Question:

> Where does each task family's marginal value flatten?

## OMP Auto vs runtime-aware escalation

Compare:

```text
OMP Auto only
```

with:

```text
OMP Auto + evidence-triggered Brain escalation
```

Question:

> Does runtime knowledge improve verified-task economics without thrashing?

## Parent escalation vs high-reasoning island

For matched hard questions compare:

```text
raise parent
```

against:

```text
same-model high specialist + compact receipt
```

Measure total root-task cost, context pollution, cache behavior, correctness and latency.

## High-island ceiling

Compare unrestricted `hi` versus `hi` with high/xhigh ceilings.

Question:

> How often does unrestricted `hi` spend a top tier without verified benefit?

## Duplicate classifier tax

Measure OMP Auto classification overhead.

Question:

> Does Second Brain need any additional model classifier at all?

## State-first runtime

Compare:

```text
append-only transcript
```

with:

```text
validated active state + latest observation + faultable history
```

Measure cumulative tokens, resume quality and compaction loss.

## Search isolation

Compare inline broad repo exploration with bounded explorer returns.

Question:

> At what exploration size does isolation become cheaper?

## Reasoning receipt continuity

Test:

```text
OMP restart
OMP → Claude
Claude → OMP
same-provider continuation
```

Measure repeated investigation avoided.

## Cognition compiler

For recurring task classes compare fresh reasoning every time versus verified engram/skill/action reuse.

Measure cost across repeated uses, not just first-run success.

## Cache-aware effort

Measure provider cache hits when changing effort versus spawning a compact specialist.

## Structural escalation signals

Ablate:

- contradictions;
- failed tests;
- failed attempts;
- unresolved requirements;
- risk/irreversibility;
- evidence coverage.

Question:

> Which signals actually predict benefit from higher effort?

---

# 35. Metrics v3 should care about

## Correctness
- verified task success;
- requirements satisfied;
- regression rate;
- false-completion rate;
- recovery correctness.

## Cognition
- reasoning tokens;
- effort-tier distribution;
- escalations;
- unnecessary escalations;
- high/max usage;
- high-island count.

## Context
- model-visible tokens;
- cumulative task context;
- cached input;
- cache-hit rate;
- bytes/tokens faulted in;
- state-vs-transcript ratio.

## Coordination
- child count;
- root-task aggregate tokens;
- reacquisition cost;
- handoff size;
- duplicated context;
- coordination/wait latency.

## Tools
- tool calls;
- tool-result bytes exposed to parent;
- deterministic resolutions;
- unnecessary exploration.

## Learning
- repeated reasoning avoided;
- engram/skill reuse;
- action-cache hits;
- cost reduction after repeated uses;
- regressions from learned procedures.

## Economics
- API cost where visible;
- subscription/quota usage where visible;
- latency;
- retries;
- rework;
- cost per verified successful task.

---

# 36. High-confidence v3 directions

## Same-model Cognitive Governor
**Confidence: very high**

OMP already provides effort controls. Adaptive-compute and overthinking research strongly support variable effort.

## Temporary high-reasoning islands
**Confidence: high**

Especially when the question is cleanly separable and tightly budgeted.

## State-first long-horizon execution
**Confidence: very high**

Strong fit with current Second Brain primitives and SKILL.state.

## Reasoning receipts
**Confidence: high**

Good portable continuity mechanism without chain-of-thought dependence.

## Cognition compiler / reasoning amortization
**Confidence: high as a direction**

Strong fit with v2 engrams and external ReasoningBank/ProcMEM/SkillGen work.

## Proof-before-thought
**Confidence: very high**

External evidence often resolves uncertainty more cheaply and reliably than additional reflection.

## Root-goal accounting
**Confidence: very high**

Essential to prevent hidden subagent cost.

## Cache-aware effort scheduling
**Confidence: very high**

Provider behavior directly makes this necessary.

## Structural cognitive-debt signals
**Confidence: high research direction**

Likely better than verbal confidence; exact weighting needs data.

## Context coherence / delta-based worker state
**Confidence: high conceptually**

Specific MESI-like implementation remains experimental.

---

# 37. Watchlist, not design commitments

- limited parallel reasoning;
- optional local/small execution specialists;
- learned effort allocator after enough real telemetry;
- provider-specific mid-conversation effort APIs;
- stronger-model routing as a late fallback;
- MESI-style artifact coherence specifics.

---

# 38. The most important synthesis: REUSE → OBSERVE → THINK

V3 can organize cognitive work into three increasingly expensive layers.

## 1. REUSE

```text
Have we already paid to solve this?
```

Use:

- memory;
- state;
- engram;
- skill;
- action cache;
- artifact;
- prior evidence.

## 2. OBSERVE

```text
Can cheap evidence settle the remaining uncertainty?
```

Use:

- tools;
- tests;
- indexes;
- hashes;
- deterministic policy;
- focused search.

## 3. THINK

```text
What decision genuinely still requires model intelligence?
```

Then allocate only as much effort as necessary:

```text
low → medium → bounded high island → exceptional verification
```

This is better than the common pattern:

```text
THINK → SEARCH → THINK MORE → SPAWN → THINK AGAIN
```

The v3 order should be:

> **REUSE → OBSERVE → THINK**

---

# 39. What successful v3 behavior looks like

## Simple lookup

```text
User: Find where X is configured.

Brain:
- resolve project deterministically
- OMP Auto selects low
- one targeted search
- answer
- no irrelevant memory
- no worker
- no deep reasoning
```

## Search + audit

```text
User: Find X and audit whether it can corrupt recovery.

Brain:
- starts medium
- targeted exploration
- discovers concurrent writer
- cognitive debt rises
- one same-model high specialist gets exact relevant refs
- specialist returns proof/uncertainty
- targeted reproduction settles the issue
- parent resumes low/medium
```

## Recurring workflow

```text
User: Perform workflow Y.

Brain:
- recognizes verified engram
- validates preconditions
- executes procedural/cached route
- verifies postconditions
- little or no novel model reasoning
```

The trajectory is:

> **Spend deep cognition only where novelty and unresolved uncertainty demand it. Reuse everything else.**

---

# 40. Final v3 identity

If v1 established the reliable substrate and v2 established adaptive memory/Brainstem learning, v3 should establish **adaptive cognition**.

A concise definition:

> **Second Brain v3 is the cognitive-efficiency overhaul: a state-first, evidence-driven runtime that dynamically allocates reasoning effort, isolates rare high-reasoning work, preserves cache and decision continuity, and compiles repeated verified cognition into cheaper reusable mechanisms.**

Core rules:

> **Higher reasoning is earned by unresolved evidence.**

> **Reason once when necessary; verify it; then try not to pay for the same reasoning again.**

> **State is working memory; transcripts and large artifacts are recoverable evidence, not default context.**

> **Spawn cognition only when isolation, parallelism, or independence is worth the coordination tax.**

> **Optimize cost per verified successful task.**

That gives v3 a genuine major-version identity without feature bloat.

---

# Source index

## OMP
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/thinking.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/prompts/system/auto-thinking-difficulty.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/provider-compat-reference.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/extensions.md
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/extensibility/extensions/loader.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/task/executor.ts
- https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/tiny/models.ts

## Provider reasoning / cost / caching
- https://help.openai.com/en/articles/4936856-w
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://platform.claude.com/docs/en/build-with-claude/effort
- https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking
- https://platform.claude.com/docs/en/build-with-claude/task-budgets
- https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- https://ai.google.dev/gemini-api/docs/thought-signatures
- https://ai.google.dev/gemini-api/docs/caching/

## Adaptive reasoning / overthinking
- https://arxiv.org/abs/2604.14853
- https://arxiv.org/abs/2604.10739
- https://aclanthology.org/2026.findings-acl.1199/
- https://proceedings.neurips.cc/paper_files/paper/2025/hash/fc067ac218430c409d6f65403328f740-Abstract-Conference.html
- https://proceedings.mlr.press/v267/chen25bx.html
- https://arxiv.org/abs/2601.02970
- https://arxiv.org/abs/2502.18600

## Agent / tool economics
- https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/
- https://arxiv.org/abs/2511.17006
- https://www.microsoft.com/en-us/research/publication/terminus-4b-can-a-smaller-model-replace-frontier-llms-at-agentic-execution-tasks/
- https://arxiv.org/abs/2606.14066

## State / coherence
- https://arxiv.org/abs/2608.26263
- https://arxiv.org/abs/2603.15183

## Memory / cognition amortization
- https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/
- https://arxiv.org/abs/2509.25140
- https://arxiv.org/abs/2602.01869
- https://www.microsoft.com/en-us/research/publication/skillgen-verified-inference-time-agent-skill-synthesis/

## Confidence / self-correction caution
- https://arxiv.org/abs/2310.01798
- https://arxiv.org/abs/2601.07767
- https://arxiv.org/abs/2606.29490

---

## Bottom line

**V3 does not need more AI everywhere.**

It should make Second Brain better at deciding:

```text
when AI is unnecessary,
when light thinking is enough,
when evidence is cheaper than thought,
when one deep reasoning island is justified,
when state can replace history,
and when yesterday's expensive cognition can become tomorrow's cheap mechanism.
```

That is the direction with the strongest combination of:

- direct leverage of what v2 already built;
- direct leverage of OMP's current capabilities;
- token/cost efficiency;
- local-first design;
- provider portability;
- measurable correctness;
- and a credible path toward Second Brain behaving like an actual Agent OS rather than another memory plugin.
