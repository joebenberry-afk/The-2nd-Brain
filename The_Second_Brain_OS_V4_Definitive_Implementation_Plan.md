# The Second Brain OS v4
## Definitive Architecture & Implementation Plan
### Brainstem + Neuroplastic Memory + Causal Learning + Metacognitive Control

**Status:** Pre-implementation master specification  
**Date:** 2026-08-13  
**Primary executor:** DeepSeek / Luna / Prime Agent  
**Primary platform first:** Windows + Prime Agent  
**Secondary compatibility targets:** Codex, Claude Code, future Agent Skills-compatible harnesses  
**Canonical project display name:** **The Second Brain**  
**Canonical project folder:** `%USERPROFILE%\Documents\The-Second-Brain`

---

# 0. READ THIS FIRST

This file is the definitive implementation plan.

Do **not** implement the older Second Brain plans independently.

This document supersedes and merges the useful mechanisms from:

1. `Second_Brain_OS_Master_Implementation_Plan.md`
2. `Second_Brain_Brainstem_Research_and_Architecture.md`
3. `Second_Brain_Neuroplastic_Memory_Architecture.md`
4. the later causal-memory / metacognition / predictive-workflow additions.

Older documents remain valuable as research history, but this plan is the implementation authority.

The system must be built incrementally, measured against a baseline, and promoted through shadow/advisory/active stages.

Do not try to build the entire finished architecture in one pass.

The final system is large.

The first production version must remain understandable, auditable, recoverable, and testable.

---

# 1. WHERE THE PROJECT SHOULD LIVE

Use:

```text
%USERPROFILE%\Documents\The-Second-Brain
```

Example:

```text
C:\Users\<YOUR_USER>\Documents\The-Second-Brain
```

## Why this location

The Second Brain must be:

- independent of any one repository;
- accessible from every future project;
- independent of Prime, Codex, Claude, or another harness;
- easy to back up;
- easy to Git-version;
- easy to reference from global agent instructions;
- outside the `.codex`, `.prime`, `.claude`, or Sparking Zero project trees.

Do **not** place the canonical Brain inside:

```text
Dragon Ball SZ Modding\
.codex\
.prime\
.claude\
a specific project repo\
```

Those environments should point **to** the Brain.

The Brain should not belong to them.

## Why `The-Second-Brain` instead of `The Second Brain`

Windows supports spaces.

PowerShell, Python, Git and modern tools can handle them when paths are quoted.

However, this system will eventually be referenced by:

- shell commands;
- Python;
- TypeScript;
- PowerShell;
- junctions/symlinks;
- Git;
- Agent Skills;
- tool configuration;
- task runners;
- subprocesses;
- external harness adapters.

A path without spaces removes a large class of quoting mistakes.

Use:

```text
The-Second-Brain
```

as the real directory name.

Use:

```text
The Second Brain
```

as the display/project name.

## Environment variable

The implementation must define a single canonical environment abstraction:

```text
SECOND_BRAIN_HOME
```

Default:

```text
%USERPROFILE%\Documents\The-Second-Brain
```

All scripts should resolve the root using:

1. `SECOND_BRAIN_HOME` if set;
2. otherwise the default Documents path;
3. never duplicate the absolute path throughout source code.

---

# 2. WHAT WE ARE BUILDING

The Second Brain OS is not:

- a notes folder;
- a chat archive;
- a giant `AGENTS.md`;
- a generic vector database;
- a giant collection of `SKILL.md` files;
- a Prime-only plugin;
- a replacement for Git;
- a replacement for the repository;
- an autonomous system allowed to rewrite its own rules without evidence.

The system is:

> **A model-independent continual-learning control layer that surrounds coding agents, remembers verified experience, actively manages context, chooses tools and skills adaptively, learns from success/failure, transfers validated experience across projects, and improves future agent performance without retraining the underlying LLM.**

---

# 3. THE FINAL MENTAL MODEL

The completed architecture has these major functional systems.

```text
                          USER
                           │
                           ▼
                    AGENT / HARNESS
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                         BRAINSTEM                          │
│ deterministic control / telemetry / budgets / environment │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                   THALAMUS / SENSORY GATE                 │
│ decide what data is allowed into active working context   │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                        WORKING SET                         │
│ current task / requirements / source / hypotheses         │
└──────────────────────────┬─────────────────────────────────┘
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
┌─────────────────┐ ┌────────────────┐ ┌──────────────────┐
│ HIPPOCAMPUS     │ │ SEMANTIC       │ │ PROCEDURAL       │
│ episodic vault  │ │ CORTEX         │ │ CORTEX           │
│ raw experience  │ │ generalized    │ │ skills/policies  │
└────────┬────────┘ │ knowledge       │ └────────┬─────────┘
         │          └────────┬───────┘          │
         └───────────────────┼──────────────────┘
                             ▼
                    ┌─────────────────┐
                    │ BASAL GANGLIA   │
                    │ sparse routing  │
                    │ skill/tool/mem  │
                    └────────┬────────┘
                             │
                             ▼
                           AGENT
                             │
                             ▼
                           ACTION
                             │
                             ▼
                    ┌─────────────────┐
                    │ CEREBELLUM      │
                    │ workflow        │
                    │ prediction      │
                    └────────┬────────┘
                             │
                             ▼
                  EXPECTED vs ACTUAL OUTCOME
                             │
                             ▼
                    ┌─────────────────┐
                    │ PLASTICITY      │
                    │ ENGINE          │
                    └────────┬────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       ▼                     ▼                     ▼
  CREDIT ASSIGNMENT      REPLAY / SLEEP      RECONSOLIDATION
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             ▼
                       FUTURE POLICY
```

Additional cross-cutting systems:

```text
IMMUNE LAYER
META-MEMORY
KNOWLEDGE FRONTIER
ENVIRONMENT STEWARD
ACCURACY / INTENT VERIFIER
SCOUT / REPO INTELLIGENCE
SKILL FORGE
SKILL GARDENER
```

---

# 4. CORE DESIGN DOCTRINE

The system must follow these principles.

1. **Repository reality outranks Brain memory.**
2. **Experience is written quickly; general rules change slowly.**
3. **Learn hardest from surprise, corrections and verification failures.**
4. **Context is working memory, not long-term storage.**
5. **Raw evidence is preserved outside active context whenever possible.**
6. **Only information with enough decision value should enter the Working Set.**
7. **Exploration and solving may use separate contexts.**
8. **Skills must earn activation.**
9. **Skills must earn continued existence.**
10. **Skill/tool success must not be inferred from mere co-occurrence.**
11. **High-risk work receives independent verification.**
12. **Tests are evidence, not the entire definition of success.**
13. **Automatic policy changes start in shadow mode.**
14. **Deterministic bookkeeping belongs in code, not prompts.**
15. **Reasoning-heavy judgment belongs in skills or isolated agents.**
16. **External skills and memories are untrusted until reviewed.**
17. **Forgetting means moving out of the hot set, not destroying evidence.**
18. **Current knowledge and historical knowledge must remain distinguishable.**
19. **Concision removes waste; it must never remove required detail.**
20. **Measure total verified work, not simply token count.**
21. **Prefer the smallest sufficient mechanism.**
22. **Do not build a sophisticated mechanism before a real metric justifies it.**

---

# 5. PROGRAMMING LANGUAGE / TOOLING POLICY

Use the correct tool for each layer.

## Python

Use for:

- `brainctl`;
- SQLite control database;
- indexes;
- memory metadata;
- curation;
- consolidation;
- replay;
- evaluation runners;
- reports;
- retrieval;
- project registry;
- skill registry;
- reward/utility updates;
- security metadata;
- health checks.

Use standard library first.

Primary Python modules likely needed:

```text
argparse
sqlite3
pathlib
json
hashlib
subprocess
datetime
uuid
tempfile
shutil
logging
tomllib
statistics
collections
dataclasses
```

Add third-party dependencies only when a measured requirement justifies them.

## TypeScript

Use for the Prime Agent extension.

Why:

- Prime extension surface is TypeScript/JavaScript-oriented;
- it needs direct lifecycle interception;
- tool-result handling must be low-latency;
- repeated Python subprocess calls for every tool event would be wasteful.

TypeScript Brainstem code should perform:

- event interception;
- local deterministic signal extraction;
- tool-output artifact storage;
- session read ledger updates;
- context-pressure tracking;
- environment snapshots;
- low-cost routing decisions;
- telemetry event writes.

It should call Python only for higher-level Brain operations when necessary.

## PowerShell

Use for:

- Windows bootstrap;
- backup;
- environment-variable setup;
- junction/symlink creation;
- adapter installation;
- diagnostic wrappers;
- uninstall/rollback.

## Markdown

Canonical human-readable:

- knowledge;
- decisions;
- experiences;
- plans;
- handoffs;
- skill documentation;
- architecture;
- research;
- project state.

## TOML

Use for policy/configuration:

```text
project manifests
Brainstem policies
retrieval policies
verification policies
learning thresholds
```

## JSON / JSONL

Use for:

- deterministic event state;
- telemetry;
- eval cases;
- artifact metadata;
- session state;
- runtime projection metadata.

## SQLite

Use for:

- searchable metadata;
- FTS;
- meta-memory;
- retrieval history;
- policy statistics;
- tool/skill ROI;
- replay queue;
- causal evaluation data;
- task outcomes;
- co-activation;
- memory strength;
- project/model scopes.

SQLite is **not** canonical for important human-readable knowledge.

## Rust

Do not use for initial implementation.

Only consider a Rust helper if profiling later proves a Python/TypeScript bottleneck is materially hurting the system.

---

# 6. CANONICAL DIRECTORY STRUCTURE

Create:

```text
The-Second-Brain/
│
├── README.md
├── AGENTS.md
├── VERSION
├── CHANGELOG.md
├── INDEX.md
├── .gitignore
├── pyproject.toml
│
├── constitution/
│   ├── constitution.md
│   ├── truth-precedence.md
│   ├── learning-boundaries.md
│   ├── security-boundaries.md
│   ├── retention-policy.md
│   └── change-control.md
│
├── config/
│   ├── brain.toml
│   ├── context.toml
│   ├── learning.toml
│   ├── retrieval.toml
│   ├── verification.toml
│   ├── environment.toml
│   ├── skills.toml
│   └── sleep.toml
│
├── brainstem/
│   ├── prime-extension/
│   ├── adapters/
│   ├── policies/
│   ├── telemetry/
│   └── tests/
│
├── memory/
│   ├── episodic/
│   ├── semantic/
│   ├── procedural/
│   ├── meta/
│   └── archive/
│
├── projects/
│   └── <project-id>/
│       ├── overview.md
│       ├── current-state.md
│       ├── architecture.md
│       ├── lexicon.md
│       ├── decisions.md
│       ├── known-issues.md
│       ├── knowledge-gaps.md
│       ├── simplification-debt.md
│       ├── rejected-findings.md
│       ├── roadmap.md
│       ├── references.md
│       └── project.toml
│
├── experiences/
│   ├── successes/
│   ├── failures/
│   ├── incidents/
│   └── experiments/
│
├── decisions/
│   ├── global/
│   └── projects/
│
├── skills/
│   ├── candidates/
│   ├── shadow/
│   ├── staged/
│   ├── approved/
│   │   ├── global/
│   │   ├── domain/
│   │   ├── project/
│   │   └── model/
│   ├── evals/
│   ├── quarantine/
│   ├── retired/
│   └── principles/
│
├── engrams/
│   ├── candidates/
│   ├── shadow/
│   ├── active/
│   └── retired/
│
├── plasticity/
│   ├── prediction-errors/
│   ├── rewards/
│   ├── credit/
│   ├── routing/
│   └── hindsight/
│
├── sleep/
│   ├── replay-queue/
│   ├── consolidation/
│   ├── dreaming/
│   ├── reconsolidation/
│   └── reports/
│
├── frontier/
│   └── projects/
│
├── lexicon/
│   ├── global.md
│   └── projects/
│
├── immune/
│   ├── quarantine/
│   ├── fingerprints/
│   ├── trust/
│   ├── baselines/
│   └── reports/
│
├── outputs/
│   ├── context-capsules/
│   ├── evidence-maps/
│   ├── handoffs/
│   ├── plans/
│   ├── audits/
│   └── reports/
│
├── state/
│   ├── sessions/
│   ├── artifacts/
│   ├── ownership/
│   ├── locks/
│   ├── projections/
│   └── cache/
│
├── telemetry/
│   └── agent-performance/
│
├── db/
│   └── brain.sqlite
│
├── templates/
│
├── scripts/
│   ├── brainctl.py
│   ├── bootstrap.ps1
│   ├── install-adapters.ps1
│   ├── uninstall-adapters.ps1
│   ├── sync-skills.ps1
│   └── doctor.ps1
│
├── src/
│   └── second_brain/
│
└── tests/
```

Do not blindly create every deep subfolder on first boot.

Create major roots.

Create deeper folders on demand.

---

# 7. CANONICAL VS DERIVED DATA

This distinction is mandatory.

## Canonical

Git-versioned and human-readable:

```text
constitution
semantic knowledge
decisions
project state
skills
engram definitions
high-value experiences
policies/config
lexicons
```

## Derived / rebuildable

Do not treat as truth:

```text
SQLite indexes
FTS rows
routing statistics
telemetry rollups
cache
temporary working-set state
artifact summaries
```

## Raw evidence

Preserve but do not inject automatically:

```text
tool output
logs
test output
imported source material
large JSON
session traces
```

---

# 8. DATABASE DESIGN

Use:

```text
db/brain.sqlite
```

Enable:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;
```

WAL improves concurrent reads/writes.

Do not allow SQLite to replace Git/history for canonical knowledge.

---

# 9. MINIMUM SQLITE TABLES

Implement migrations from day one.

Use schema version table:

```sql
CREATE TABLE schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
```

Core tables:

```text
projects
sessions
tasks
task_requirements
tool_events
artifacts
episodes
memories
memory_sources
memory_links
memory_retrievals
skills
skill_activations
skill_evals
tool_utility
skill_utility
routing_policies
policy_trials
predictions
outcomes
prediction_errors
credit_events
replay_queue
model_profiles
environment_events
knowledge_gaps
lexicon_terms
immune_fingerprints
```

---

# 10. PROJECT TABLE

Fields:

```text
id
name
repo_path
git_remote
created_at
last_seen_at
brain_project_path
default_mode
repo_intelligence
verification_policy
active
```

Project identity priority:

1. explicit `.brain/project.toml` ID;
2. Git remote normalized;
3. repo root path hash;
4. manual fallback.

Never identify a project solely by directory name.

---

# 11. SESSION TABLE

Fields:

```text
session_id
project_id
harness
model
started_at
ended_at
mode
initial_head
final_head
initial_dirty
final_dirty
max_context_pressure
total_input_tokens
total_output_tokens
total_tool_calls
total_child_agents
completion_status
verification_level
```

---

# 12. EPISODIC MEMORY

An episode records what happened.

Minimum fields:

```text
episode_id
project_id
session_id
task_id
episode_type
created_at
summary
evidence_refs
prediction_error
salience
status
confidence
scope
```

Types:

```text
success
failure
incident
experiment
correction
surprise
tool-routing
context-efficiency
environment
skill-observation
```

Episodes are fast memory.

Do not merge them automatically.

---

# 13. SEMANTIC MEMORY

Semantic memory represents generalized knowledge.

Each entry must track:

```text
memory_id
title
scope
project/domain/global
status
evidence_grade
current_version
created_at
updated_at
last_verified_at
strength
stability
```

Evidence grades:

```text
OBSERVED
TESTED
VERIFIED
INFERRED
HISTORICAL
REJECTED
```

The agent must never present `INFERRED` as `VERIFIED`.

---

# 14. PROCEDURAL MEMORY

Procedural memory includes:

```text
skills
policies
workflow engrams
tool-routing strategies
verification procedures
```

Each must track:

```text
support_count
trial_count
success_count
failure_count
token_delta
latency_delta
user_correction_delta
verification_delta
scope
model_scope
project_scope
adoption_strength
```

---

# 15. META-MEMORY

Meta-memory is memory **about memory**.

Per memory track:

```text
retrieval_count
successful_retrieval_count
verified_retrieval_count
contradiction_count
distinct_session_support
distinct_project_support
distinct_model_support
last_retrieved_at
last_successful_use_at
avg_token_cost
avg_outcome_delta
negative_transfer_count
```

This is essential.

Similarity does not equal utility.

---

# 16. WORKING SET

Per active task maintain:

```text
state/sessions/<session-id>/
```

Required:

```text
active-state.json
requirements.json
read-ledger.json
tool-ledger.json
routing.json
environment.json
```

Working Set contents should be cheap to reconstruct.

---

# 17. ACTIVE STATE CAPSULE

Schema:

```json
{
  "objective": "",
  "task_mode": "STANDARD",
  "risk": "MEDIUM",
  "constraints": [],
  "confirmed_facts": [],
  "current_hypotheses": [],
  "decisions_this_session": [],
  "files_touched": [],
  "open_questions": [],
  "verification": {},
  "next_action": "",
  "brain_refs": [],
  "artifact_refs": [],
  "updated_at": ""
}
```

Update at meaningful checkpoints, not every token.

---

# 18. REQUIREMENT-TO-EVIDENCE LEDGER

For every substantive engineering task:

```json
[
  {
    "id": "REQ-001",
    "requirement": "...",
    "importance": "critical",
    "evidence": [],
    "status": "unverified"
  }
]
```

Valid statuses:

```text
unverified
partially_verified
verified
not_applicable
blocked
```

A material requirement remaining `unverified` blocks normal completion.

---

# 19. SENSORY GATEWAY

The Sensory Gateway decides whether raw data should reach the LLM.

Core question:

> Does the model need to read this data, or merely know a property of it?

Examples:

```text
Need top churn files
→ compute result

Need failing tests
→ filter failures

Need exact function edit
→ preserve source exactly

Need dependency graph
→ query RepoWise

Need count
→ script it
```

Do not use the LLM as a counting/filtering engine when deterministic computation can produce the answer.

---

# 20. REVERSIBLE TOOL DISTILLATION

When tool output exceeds configured threshold:

1. hash exact output;
2. persist under `state/artifacts/`;
3. classify type;
4. generate deterministic distilled representation;
5. send distilled version to active context;
6. attach recovery handle.

Example:

```text
[brain-artifact:sha256:abc...]
pytest exit=1
141 passed
3 failed

Failures:
...

Full output recoverable with:
/brain-expand abc...
```

Never lose the original.

---

# 21. NEVER LOSSY-COMPRESS THESE BY DEFAULT

- exact changed diff;
- exact compiler error;
- exact stack frame needed for diagnosis;
- exact configuration value involved in failure;
- exact source region being edited;
- hashes/IDs;
- requirement text;
- destructive-operation target.

---

# 22. SCOUT

Scout is an isolated repository explorer.

Use when:

- repository is unfamiliar;
- edit location is uncertain;
- architecture is relevant;
- multiple packages are implicated;
- repeated search cycles occur;
- main context is becoming polluted.

Priority:

```text
RepoWise
→ rg
→ ast-grep
→ direct read
→ isolated subagent reasoning
```

Return only:

```text
Evidence Map
```

---

# 23. EVIDENCE MAP

Required fields:

```text
task
likely edit sites
relevant tests
callers/dependencies
architecture context
hotspot/risk notes
unknowns
recommended next read
source freshness
```

The main agent must not inherit Scout's full search trajectory.

---

# 24. EXPLORATION BUDGET

Brainstem tracks:

```text
search_calls
read_calls
unique_files
repeated_files
uncertainty_reduction
```

If exploration continues without material uncertainty reduction:

```text
strategy switch
```

Do not simply keep grepping.

---

# 25. JIT CONTEXT COMPILER

Inputs:

```text
user task
project
Working Set
semantic memory
episodic memory
decisions
RepoWise
skills
risk
model profile
historical utility
```

Output:

```text
Task Context Capsule
```

Target:

Every line should justify its token cost.

---

# 26. MEMORY RETRIEVAL SCORE

Initial interpretable scoring model:

```text
score =
  relevance
  * trust
  * freshness
  * scope_match
  * historical_utility
  * predicted_decision_value
  * diversity_factor
  / estimated_token_cost
  - negative_transfer_risk
```

Do not overfit numeric weights initially.

Start with normalized categories.

Log all components.

Tune later.

---

# 27. CAUSAL MEMORY SELECTION

For important memories ask:

```text
If this memory were withheld,
would the likely action change?
```

Candidate causal signals:

```text
action shift
localization improvement
verification improvement
error avoidance
tool selection change
decision change
```

Causal evaluation belongs mainly in:

```text
benchmark
sleep/replay
skill/memory evaluation
```

Do not double-run every live task.

---

# 28. CONTEXT VALUE DENSITY

Classify context:

## Tier 1

Must load:

- requirement;
- directly edited source;
- exact relevant test;
- hard project constraint.

## Tier 2

High value:

- matching verified failure;
- relevant decision;
- RepoWise caller/ripple info.

## Tier 3

Conditional:

- related old handoff;
- broad architecture note;
- secondary episode.

## Tier 4

Normally omit:

- unrelated history;
- duplicate summaries;
- old superseded fact;
- generic style text.

---

# 29. THALAMIC LATERAL INHIBITION

Do not retrieve 10 similar notes.

After ranking:

- deduplicate;
- suppress near-duplicates;
- retain diverse evidence;
- surface contradictions explicitly.

Preferred:

```text
1 current fact
1 supporting failure
1 conflicting historical note
```

over:

```text
10 paraphrases of same fact
```

---

# 30. PROJECT LEXICON / SEMANTIC CODEBOOK

Each project maintains:

```text
projects/<id>/lexicon.md
```

Use concise stable names for recurring concepts.

Each term:

```markdown
## Post-end contamination
Definition:
Events emitted after match termination that retain the ended match identity.

Use when:
...

Do not confuse with:
...
```

The purpose is:

- context compression;
- consistent code naming;
- searchability;
- shared vocabulary;
- lower conceptual ambiguity.

Do not create cryptic abbreviations.

---

# 31. CONCEPT COMPILER

During curation, detect repeated verbose concepts.

Candidate:

```text
long recurring description
```

Propose:

```text
short canonical concept
```

Only curator/user approval makes it canonical.

---

# 32. TASK / BOTTLENECK CLASSIFIER

Task modes:

```text
MICRO
STANDARD
DEEP
DEBUG
RESEARCH
REVIEW
ADVISOR
EXECUTOR
HANDOFF
```

Bottleneck classes:

```text
localization
missing-knowledge
context-pressure
tool-output
uncertainty
specification
environment
nondeterminism
verification
complexity
coordination
plan-ambiguity
```

---

# 33. UNCERTAINTY TYPES

Classify uncertainty.

## Epistemic

Missing knowledge.

Response:

```text
retrieve
Scout
research
```

## Specification

Success criteria unclear.

Response:

```text
Requirement Ledger
decisions
intent constraints
```

## Environmental

External state uncertain.

Response:

```text
Environment Steward
snapshot
reproduction
```

## Stochastic

System nondeterministic.

Response:

```text
instrument
repeat
distribution
race/timing analysis
```

Do not respond to all uncertainty by simply loading more context.

---

# 34. METACOGNITIVE MONITOR

Estimate confidence from the trajectory.

Inputs:

```text
failed commands
hypothesis reversals
contradictions
untested requirements
stale source
search depth
repeated reads
verifier disagreement
flaky tests
speculative edits
context pressure
source authority
```

Output:

```text
Epistemic confidence
Execution confidence
Verification confidence
```

Use categories first:

```text
LOW
MEDIUM
HIGH
```

Avoid fake precision.

---

# 35. RISK CONTROLLER

Separate risk from confidence.

Risk signals:

```text
blast radius
centrality
concurrency
persistence
migration
security boundary
public API
data loss
configuration scope
hotspot/bug history
number of files
user-defined criticality
```

Risk:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

---

# 36. VERIFICATION LADDER

## LOW

- targeted test;
- typecheck/compile if relevant;
- diff sanity.

## MEDIUM

- targeted + relevant tests;
- requirement ledger;
- affected-file review;
- simplification check.

## HIGH

- all MEDIUM;
- RepoWise impact/risk context;
- independent Intent Verifier;
- negative/adversarial tests;
- rollback check.

## CRITICAL

- all HIGH;
- explicit human approval for irreversible/destructive boundaries;
- optionally second independent verification.

---

# 37. INTENT VERIFIER

Use a fresh context.

Input only:

```text
original requirement
constraints
final diff
relevant source
validation output
```

Do not provide solver reasoning.

Verifier asks:

1. What does the task require?
2. What does this patch actually do?
3. If I saw only the patch, what task would I infer?
4. Are those aligned?
5. What requirement lacks evidence?
6. Did tests merely satisfy a narrow oracle?
7. Was unrelated scope added?
8. Are failure paths covered?

---

# 38. PATCH BACKWARD RECONSTRUCTION

The independent verifier must first infer the patch's apparent intent **before** reading the original task.

Then compare.

This reduces confirmation bias.

---

# 39. BRAINSTEM CEREBELLUM

The Cerebellum predicts workflow progress.

Example expected path:

```text
architecture query
→ candidate files shrink
→ exact edit location
→ minimal patch
→ tests
→ requirements verified
```

If actual path becomes:

```text
architecture query
→ 12 searches
→ 9 file reads
→ no location
```

Brainstem detects trajectory deviation.

Action:

```text
switch strategy
```

Do not wait until context is exhausted.

---

# 40. WORKFLOW PREDICTION EVENTS

Record:

```text
state
expected_next_state
actual_next_state
prediction_error
```

Examples:

```text
RepoWise expected to localize
test expected to discriminate hypothesis
Lean Build expected to reduce new dependency
verifier expected to approve
```

---

# 41. PREDICTION ERROR

High learning priority when:

```text
agent was confident but wrong
unexpected failure
unexpected success
user correction
verifier rejection
environment surprise
skill false trigger
skill missed trigger
```

Prediction error influences:

```text
episode salience
replay priority
reflection priority
policy update rate
```

---

# 42. OUTCOME / REWARD VECTOR

Do not reduce outcome to one binary.

Track:

```text
verified_success
first_pass_success
intent_alignment
regression
user_correction
revert
token_cost
latency
tool_calls
context_peak
code_complexity
dependency_delta
environment_damage
```

A scalar reward may later be derived.

Raw vector must remain available.

---

# 43. CREDIT ASSIGNMENT

Never do:

```text
task succeeded
→ every active skill +1
```

Credit levels:

```text
direct
contributory
correlated
unknown
```

Direct:

```text
skill produced verified result
```

Contributory:

```text
skill produced evidence used by solver
```

Correlated:

```text
skill happened to be loaded
```

Only strong evidence receives strong utility updates.

---

# 44. LOCAL COUNTERFACTUAL EVAL

During replay/eval:

```text
same starting state
A: intervention present
B: intervention absent
```

Compare:

```text
success
tokens
tools
time
verification
regressions
```

Use for:

```text
skills
important memories
routing policies
Scout
verification policy
```

Do not run on every live task.

---

# 45. HINDSIGHT RELABELING

After a task, compare:

```text
initial bottleneck classification
actual bottleneck discovered
```

If wrong:

record training example.

Example:

```text
predicted: localization
actual: environment drift
```

Update classifier evidence.

---

# 46. EPISODIC VAULT

Write episodes immediately.

Properties:

- immutable;
- source-linked;
- project-scoped;
- no automatic global truth;
- pattern-separated.

Episode file template:

```markdown
---
id:
project:
session:
task:
type:
created_at:
prediction_error:
salience:
evidence_grade:
---

# Situation

# Expected

# Actual

# Actions

# Evidence

# Root cause

# What worked

# What failed

# Reusable lesson

# Trigger signals

# Counter-signals

# Verification

# Related memories
```

---

# 47. MEMORY CONSOLIDATION

Consolidation moves repeated stable structure into Semantic Cortex.

Requirements:

```text
supporting episodes
evidence
scope
contradiction check
interference check
```

A one-off surprising episode remains an episode until validated.

---

# 48. SCHEMA COMPATIBILITY

For new experience:

```text
Does this fit current semantic model?
```

High compatibility:

```text
strengthen existing memory
```

Low compatibility:

```text
create contradiction/reconsolidation event
```

Never silently overwrite.

---

# 49. RECONSOLIDATION

When retrieved memory influences a task:

record activation.

After outcome:

## correct/useful

```text
strengthen
last_verified
utility gain
```

## irrelevant

```text
minor utility decrease
```

## contradicted

```text
mark labile
create review event
```

Review outcomes:

```text
confirm
narrow
split
update
supersede
archive
```

Preserve history.

---

# 50. MEMORY STRENGTH

Track:

```text
verified reuse
spaced reuse
independent sources
cross-session support
cross-project support
cross-model support
staleness
contradictions
redundancy
negative transfer
```

Do not equate retrieval count with truth.

---

# 51. SPACED VERIFIED REUSE

A memory successfully verified over separate sessions should strengthen more than repeated observations in one session.

Track:

```text
distinct_session_support
distinct_project_support
distinct_model_support
```

Global policy requires stronger diversity.

---

# 52. STRATEGIC FORGETTING

States:

```text
HOT
WARM
COLD
ARCHIVED
```

The system may reduce active retrieval priority.

It must not destroy canonical evidence by default.

Protected:

```text
constitution
security
accepted decisions
critical failure immunizations
explicit user preferences
current invariants
```

---

# 53. SLEEP ENGINE

Manual first.

Later scheduled.

Two passes.

## Conservative consolidation

- replay high-priority episodes;
- cluster;
- verify provenance;
- strengthen semantic memory;
- detect contradictions;
- update utility.

## Creative dream pass

Candidate-only:

- cross-project analogies;
- skill ideas;
- experiment ideas;
- concept abstractions;
- workflow engrams.

Dream outputs are never verified facts.

---

# 54. PRIORITIZED REPLAY

Replay priority includes:

```text
prediction error
user correction
verification failure
risk
novelty
reuse potential
uncertainty
cross-project relevance
```

Do not replay newest-only.

Interleave older representative cases.

---

# 55. MEMORY INTERFERENCE TEST

Before changing global/domain semantic rule:

1. run old representative evals;
2. apply candidate;
3. run new cases;
4. compare.

Reject if candidate:

```text
fixes new case
but breaks important old cases
```

---

# 56. SPARSE ROUTING / BASAL GANGLIA

The router chooses a small subset.

Typical:

```text
0-3 specialist skills
1 retrieval packet
minimal tools
```

Do not load all skills.

Routing inputs:

```text
task
bottleneck
risk
model
project
context pressure
tool availability
skill utility
negative transfer
```

---

# 57. SKILL ADOPTION STRENGTH

New skills begin low:

```text
shadow
```

Then:

```text
advisory
```

Then:

```text
active
```

Adoption strength rises with verified utility.

Falls with regressions/false triggers.

---

# 58. WORKFLOW ENGRAMS

Repeated successful sequences become compositional macros.

Example:

```text
unfamiliar-state-bug:
  Scout
  → Evidence Debugger
  → Lean Build
  → Accuracy Gate
```

Engrams do not duplicate underlying skill logic.

They coordinate existing specialists.

---

# 59. INITIAL SKILL SET

Do not expose all globally.

Core candidates:

```text
brain-governor
brain-recall
context-compiler
scout
context-steward
environment-steward
lean-build
simplification-review
evidence-debugger
accuracy-gate
intent-verifier
improvement-radar
improvement-advisor
experience-observer
memory-consolidator
reconsolidation-reviewer
prediction-error-reflector
workflow-engram-builder
skill-forge
skill-verifier
skill-transfer-verifier
skill-gardener
memory-gardener
memory-interference-auditor
semantic-codebook
frontier-planner
immune-reviewer
implementation-planner
brain-curator
brain-handoff
```

Most are Brainstem-scheduled, not permanently model-visible.

---

# 60. SKILL QUALITY

Every skill requires:

```text
purpose
positive triggers
negative triggers
inputs
procedure
tools
safety
verification
output
references
```

Skills must not become textbooks.

Use progressive disclosure.

---

# 61. SKILL FORGE

Pipeline:

```text
episodes
→ pattern
→ candidate
→ trigger eval
→ workflow eval
→ counterfactual eval
→ shadow
→ advisory
→ active
```

Global promotion requires:

```text
multiple sessions
multiple projects where appropriate
preferably multiple models
no unacceptable regressions
```

---

# 62. SKILL GARDENER

Periodically find:

```text
dead skills
overlap
false triggers
never-used skills
negative ROI
duplicate skills
skills too broad
skills too narrow
model-specific quirks
```

Actions:

```text
merge
narrow
demote
hide
retire
```

The skill bank must stay bounded.

---

# 63. MODEL PROFILES

Store model-specific performance.

Example:

```text
models/deepseek/
models/gpt/
models/claude/
```

Track:

```text
preferred context density
skill trigger behavior
planner quality
verification quality
tool tendencies
failure patterns
```

Do not turn one model's quirk into a universal rule.

---

# 64. CROSS-MODEL TRANSFER

Global policy/skill promotion should test portability.

Example:

```text
skill created from DeepSeek episodes
```

Test:

```text
GPT
Claude
```

If it only helps DeepSeek:

```text
model-scoped
```

not global.

---

# 65. TEACHER-STUDENT DISTILLATION

Strong/expensive model:

```text
discover
reason
validate
```

Then distill into:

```text
skill
policy
plan
tests
lexicon
decision
```

Cheaper agent executes.

Measure whether performance transfers.

This is especially useful for DeepSeek/Luna executor workflows.

---

# 66. KNOWLEDGE FRONTIER

Per project track gaps:

```text
importance
uncertainty
information_gain
experiment_cost
dependency
risk
```

Frontier Planner recommends high-information next experiments.

Useful for:

```text
reverse engineering
telemetry
AI behavior discovery
performance optimization
architecture research
```

---

# 67. ACTIVE LEARNING

For a knowledge gap:

1. list competing hypotheses;
2. identify distinguishing observations;
3. choose cheapest high-information experiment;
4. run;
5. update beliefs;
6. capture result.

Do not run random experiments.

---

# 68. IMPROVEMENT RADAR

Lightweight.

Triggers:

```text
user correction
repeated command failure
workaround
new dependency
new abstraction
hot file touched
missing test
skill miss
skill false trigger
tool wasted effort
plan ambiguity
context thrashing
```

Output:

```text
candidate only
```

No full audit automatically.

---

# 69. IMPROVEMENT ADVISOR

Heavy.

Use when:

```text
user requests
milestone
many Radar signals
project health decline
high-risk architecture review
```

Read-only source audit.

Findings require evidence.

---

# 70. PONYTAIL / LEAN BUILD

Before adding structure:

```text
Does it need to exist?
Does it already exist?
Can existing code extend?
Stdlib?
Native platform?
Existing dependency?
Smaller design?
Only then new implementation.
```

Never simplify away:

```text
security
validation
error handling
data safety
concurrency correctness
required compatibility
```

---

# 71. SIMPLIFICATION DEBT

Each project:

```text
simplification-debt.md
```

Track valid deferred simplifications.

Do not repeatedly rediscover them.

---

# 72. CONTEXT GOVERNOR

Context pressure bands begin as configurable defaults:

```text
GREEN
YELLOW
ORANGE
RED
```

Do not hardcode final percentages until Prime telemetry validates them.

Actions scale:

```text
normal
→ restrict broad reads
→ distill/offload
→ checkpoint
→ compact/handoff
```

---

# 73. READ LEDGER

Track:

```text
path
hash
range
purpose
turn
artifact
```

Repeated reads are allowed when needed.

But default to prior compact reference if unchanged and sufficient.

---

# 74. ENVIRONMENT STEWARD

Session start:

```text
cwd
repo
branch
HEAD
dirty state
worktree
language
package manager
lockfiles
tools
RepoWise freshness
children
Brain version
```

During:

```text
dependency installs
processes
temp dirs
worktrees
config mutation
agent spawns
repeated failure
```

Shutdown:

```text
owned process leak
untracked junk
active children
dirty tree
dependency drift
incomplete verification
```

---

# 75. PROCESS OWNERSHIP

Do not use PID alone.

Store when possible:

```text
PID
process start time
executable
ownership token
session ID
```

Never kill ambiguous process ownership.

---

# 76. MULTI-AGENT ISOLATION

Read-only agents:

```text
can share repo
```

Writers:

```text
worktree or explicit ownership
```

Verifier:

```text
fresh/read-only context
```

Curator:

```text
exclusive canonical Brain lease
```

---

# 77. IMMUNE LAYER

External skill/memory/tool:

```text
quarantine
→ provenance
→ hash
→ license
→ static scan
→ semantic review
→ permission review
→ trigger review
→ sandbox eval
→ candidate
```

SkillSpector may be integrated later as one scanner.

Never allow internet → active skill directly.

---

# 78. MEMORY POISONING DEFENSE

Track:

```text
source trust
evidence
verification
scope
freshness
```

External retrieved text cannot become VERIFIED solely because it appears authoritative.

---

# 79. CONSTITUTION

These rules are highly protected:

```text
truth precedence
security
backup
rollback
secret handling
learning boundaries
human approval boundaries
```

Plastic learning does not auto-rewrite Constitution.

Constitution changes require explicit review.

---

# 80. PRIME EXTENSION

Create:

```text
brainstem/prime-extension/
```

Suggested:

```text
index.ts
config.ts
sensors/
controllers/
distill/
telemetry/
tools/
storage/
tests/
```

The extension is the automatic reflex layer.

---

# 81. PRIME EVENT RESPONSIBILITIES

## session_start

- project;
- environment;
- tools;
- RepoWise freshness;
- state recovery;
- telemetry.

## before_agent_start

- task classification;
- uncertainty class;
- risk;
- JIT Context Capsule.

## turn_start

- pressure;
- current state.

## context

- safe offload;
- artifact substitution;
- preserve requirements/state.

## tool_call

- ownership/safety;
- noisy-command detection;
- telemetry.

## tool_result

- exact artifact persist;
- distill if appropriate;
- update evidence.

## turn_end

- workflow progress;
- failed loops;
- prediction event.

## agent_end

- outcome;
- Radar;
- episode salience.

## session_before_compact

- Active State Capsule;
- requirements;
- hypotheses;
- decisions;
- exact resume point.

## session_shutdown

- environment report;
- pending handoff;
- telemetry flush.

---

# 82. PYTHON CONTROL CLI

Implement:

```text
brainctl
```

Commands:

```text
brainctl init
brainctl doctor
brainctl status
brainctl project add
brainctl project list
brainctl project status
brainctl session inspect
brainctl recall
brainctl memory add
brainctl memory inspect
brainctl memory reconsolidate
brainctl memory garden
brainctl capture
brainctl curate
brainctl consolidate
brainctl sleep
brainctl replay
brainctl frontier
brainctl skills list
brainctl skills validate
brainctl skills eval
brainctl skills shadow
brainctl skills promote
brainctl skills retire
brainctl skills sync
brainctl immune scan
brainctl telemetry report
brainctl routing report
brainctl benchmark
brainctl backup
brainctl restore
```

Do not create all commands in milestone 1.

Add as phases require them.

---

# 83. WINDOWS BOOTSTRAP

Create:

```text
scripts/bootstrap.ps1
```

Must:

1. resolve Brain root;
2. refuse unsafe existing non-Brain overwrite;
3. create backup directory;
4. verify Python;
5. verify Git;
6. initialize venv if chosen;
7. initialize Git;
8. create config;
9. initialize SQLite;
10. run doctor;
11. print next steps.

Never silently edit global agent configs in bootstrap v1.

Use separate adapter install step.

---

# 84. GLOBAL AGENT BOOTSTRAP

Global `AGENTS.md` integration stays tiny.

Concept:

```markdown
## The Second Brain

Canonical Brain: `%SECOND_BRAIN_HOME%`.

For substantive work:
- current repo/tests outrank memory;
- use targeted Brain recall;
- do not preload the Brain;
- use Brainstem signals where available;
- preserve durable validated learning.
```

Procedures live elsewhere.

---

# 85. PROJECT MANIFEST

Every managed repo:

```text
.brain/project.toml
```

Minimum:

```toml
schema_version = 1
id = "..."
name = "..."
brain_enabled = true
repository_is_authoritative = true

[performance]
default_mode = "standard"
context_policy = "adaptive"
repo_intelligence = "repowise-preferred"
verification_policy = "risk-adaptive"

[automation]
brainstem = true
improvement_radar = true
experience_observer = true

[tools]
repowise = "auto"
ast_grep = "auto"
sz_tool = "auto"
```

---

# 86. REPOWISE

Use RepoWise for:

```text
architecture
dependencies
centrality
churn
ownership
co-change
hotspots
test impact
decisions
```

Verify freshness.

Do not dump entire RepoWise output into context.

Brain stores durable conclusion, not a copy of the index.

---

# 87. AST-GREP / RG ROUTING

Exact string:

```text
rg
```

Structural code pattern:

```text
ast-grep
```

Architecture/history:

```text
RepoWise
```

Domain fact:

```text
domain tool
```

Do not run all automatically.

---

# 88. SHADOW MODE

New adaptive behavior lifecycle:

```text
IDEA
→ SHADOW
→ MEASURED
→ ADVISORY
→ ACTIVE
→ MONITORED
→ REVISE / RETIRE
```

Shadow mode logs:

```text
would_trigger
reason
expected_action
actual_outcome
hindsight_useful
```

No behavior change.

---

# 89. BRAIN WHY

Implement transparent reasoning about Brainstem interventions.

Command:

```text
/brainwhy
```

Example:

```text
Scout would trigger because:
- 5 search/read cycles
- edit location unresolved
- RepoWise available
- context pressure rising
```

Do not expose chain-of-thought.

Expose deterministic policy signals.

---

# 90. BRAIN STATUS

Compact:

```text
Project
Task mode
Risk
Uncertainty type
Context pressure
Current bottleneck
Active skills
Scout
RepoWise freshness
Requirements verified
Owned processes
Pending captures
Learning mode
```

---

# 91. TELEMETRY

Do not store private chain-of-thought.

Track operational data:

```text
task
model
harness
tokens
tool calls
tool bytes
files read
unique files
rereads
files edited
children
skills
context peak
compactions
failed commands
tests
verification
user corrections
reverts
time
```

---

# 92. BOTTLENECK FINGERPRINTS

Examples:

```text
exploration-heavy
context-thrashing
tool-output-heavy
verification-heavy
environment-drift
overengineering-prone
coordination-conflict
low-signal-audit
```

Use fingerprint as one router input.

---

# 93. KPIs

## Accuracy

```text
verified task success
first-pass success
user correction rate
verifier rejection
regression rate
requirement coverage
```

## Efficiency

```text
tokens / verified task
tool calls / verified task
time / verified task
irrelevant read ratio
reread ratio
```

## Context

```text
peak context
artifact offload amount
compactions
retrieval precision
```

## Simplicity

```text
new dependencies
duplicate implementation
safe code removed
unnecessary abstractions
```

## Skill

```text
trigger precision
trigger recall
success delta
token delta
regression delta
```

---

# 94. PARETO OPTIMIZATION

Do not optimize tokens alone.

Compare:

```text
accuracy
tokens
latency
complexity
```

Select policies on useful Pareto frontier.

High risk may choose higher-cost policy.

---

# 95. BASELINE BENCHMARK BEFORE OPTIMIZATION

Before Brainstem actively changes behavior, collect baseline tasks.

At minimum:

1. tiny known-file fix;
2. unfamiliar repo bug;
3. difficult state bug;
4. noisy logs;
5. over-engineering temptation;
6. architecture audit;
7. detailed handoff plan;
8. multi-agent task;
9. long context task;
10. misleading/incomplete test task;
11. cross-project transfer case;
12. cross-model executor case.

Record all KPIs.

---

# 96. PHASE 0 — PROJECT CREATION

Create folder:

```powershell
$Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain"
New-Item -ItemType Directory -Force -Path $Brain | Out-Null
Set-Location $Brain
git init
```

Set environment variable for current shell:

```powershell
$env:SECOND_BRAIN_HOME = $Brain
```

Persist after implementation is stable:

```powershell
[Environment]::SetEnvironmentVariable(
  "SECOND_BRAIN_HOME",
  $Brain,
  "User"
)
```

Do not persist until bootstrap/doctor passes.

---

# 97. PHASE 1 — FOUNDATION

Implement only:

```text
root
Git
constitution
config
Python package
brainctl init
brainctl doctor
SQLite migration framework
project registry
backup
```

No automatic Brainstem behavior.

Acceptance:

```text
fresh clone/init works
doctor passes
DB migrations idempotent
backup restore works
```

---

# 98. PHASE 2 — OBSERVABILITY

Prime extension in measurement-only mode.

Collect:

```text
session
model
tools
files
tokens
context
environment
RepoWise freshness
commands
tests
children
```

No context mutation.

No auto cleanup.

No auto skill routing.

Run real workload baseline.

Acceptance:

```text
telemetry accurate
overhead low
no behavior changes
```

---

# 99. PHASE 3 — PROJECT INTEGRATION

Implement:

```text
brainctl project add
.brain/project.toml
project Brain directory
minimal AGENTS marker block
project current-state
lexicon seed
RepoWise detection
```

Acceptance:

```text
new repo attaches in one command
existing AGENTS content preserved
rollback works
```

---

# 100. PHASE 4 — WORKING SET / JIT CONTEXT

Implement:

```text
Active State Capsule
Requirement Ledger
JIT Context Compiler
Context Capsule
read ledger
```

Start advisory/shadow.

No aggressive pruning.

Acceptance:

```text
fresh agent resumes task
context capsule relevant
no key requirement lost
```

---

# 101. PHASE 5 — SENSORY GATEWAY / RTD

Start with:

```text
test logs
git log
search results
```

Never compress source edit regions.

Original exact output recoverable.

Acceptance:

```text
hash verified
distillation deterministic
expand returns byte-identical original
```

---

# 102. PHASE 6 — SCOUT

Implement isolated Scout.

Compare baseline vs Scout.

Acceptance metrics:

```text
edit localization
tool calls
tokens
main context size
success
```

Promote to advisory only if beneficial.

---

# 103. PHASE 7 — ACCURACY

Implement:

```text
risk controller
Requirement Ledger enforcement
Intent Verifier
independent fresh context
```

Start HIGH-risk only.

Acceptance:

```text
detect planted requirement/test mismatch
no major false blocking on low-risk tasks
```

---

# 104. PHASE 8 — ENVIRONMENT STEWARD

Measurement first.

Then advisory.

Then safe owned cleanup.

Acceptance:

```text
owned process tracking
PID reuse-safe identity
worktree tracking
dependency mutation reporting
no unrelated process killed
```

---

# 105. PHASE 9 — EPISODIC MEMORY

Implement:

```text
capture
episode files
episode DB rows
salience
prediction-error field
source references
```

No semantic auto-update yet.

Acceptance:

```text
multi-agent-safe unique writes
episode retrieval
provenance
```

---

# 106. PHASE 10 — SEMANTIC MEMORY

Implement:

```text
curator
evidence grades
semantic entries
contradiction handling
current/historical distinction
```

Manual curation first.

Acceptance:

```text
repo contradiction correctly supersedes stale memory
history preserved
```

---

# 107. PHASE 11 — METACOGNITIVE MONITOR

Implement trajectory-based confidence categories.

Shadow mode only.

Compare against:

```text
actual verification result
user correction
```

Tune signals.

Acceptance:

```text
low-confidence trajectories correlate with real problems better than random/basic heuristic
```

---

# 108. PHASE 12 — CEREBELLUM / PREDICTIVE WORKFLOW

Start with simple expected-state templates.

Examples:

```text
Scout should reduce candidate files
test should discriminate hypothesis
verification should close requirements
```

Detect nonprogress.

Advisory only.

Acceptance:

```text
detects planted looping exploration earlier than fixed thresholds alone
```

---

# 109. PHASE 13 — PLASTICITY

Implement:

```text
prediction events
outcomes
prediction errors
utility updates
hindsight relabeling
```

No automatic policy enforcement.

Shadow learning.

Acceptance:

```text
replaying identical telemetry produces deterministic updates
```

---

# 110. PHASE 14 — REPLAY / SLEEP

Manual command:

```text
brainctl sleep
```

Conservative pass only first.

Later add creative dream pass.

Acceptance:

```text
no invented verified facts
all semantic updates provenance-linked
candidate ideas remain candidate
```

---

# 111. PHASE 15 — RECONSOLIDATION / FORGETTING

Implement:

```text
activation tracking
strength
labile state
supersede
hot/warm/cold/archive
```

Forgetting starts advisory only.

Acceptance:

```text
stale memory loses hot priority
critical protected memory does not decay
history still recoverable
```

---

# 112. PHASE 16 — SKILL FORGE

Build:

```text
episode
→ pattern
→ candidate skill
→ eval
→ shadow
```

Do not auto-install.

Acceptance:

```text
candidate has trigger boundaries
workflow eval
regression eval
security review
```

---

# 113. PHASE 17 — SKILL ROUTER

Sparse top-K.

Shadow route first.

Compare:

```text
model natural skill routing
vs Brainstem route
```

Acceptance:

```text
lower trigger noise
no success regression
```

---

# 114. PHASE 18 — CREDIT ASSIGNMENT

Implement:

```text
direct
contributory
correlated
```

Then counterfactual replay for major policy candidates.

Acceptance:

```text
task success does not automatically reward every active skill
```

---

# 115. PHASE 19 — WORKFLOW ENGRAMS

Detect repeated skill sequences.

Candidate-only.

Acceptance:

```text
engram references existing skills
does not duplicate giant logic
```

---

# 116. PHASE 20 — CROSS-MODEL MEMORY

Track model-specific outcomes.

Test transferable skills.

Acceptance:

```text
model-specific failures do not contaminate global policy
```

---

# 117. PHASE 21 — KNOWLEDGE FRONTIER

Implement:

```text
gap registry
hypotheses
experiment cost
information value
dependencies
```

Manual planner first.

Acceptance:

```text
frontier recommends discriminating experiment instead of generic todo
```

---

# 118. PHASE 22 — IMMUNE SYSTEM

Integrate:

```text
quarantine
hash
trust
static scanning
semantic review
permissions
SkillSpector optional
```

Acceptance:

```text
unreviewed third-party skill cannot become active
```

---

# 119. PHASE 23 — POLICY PROMOTION

Only after enough real telemetry.

Lifecycle:

```text
shadow
→ advisory
→ active
```

Every promotion needs:

```text
evidence
baseline comparison
rollback
owner
version
```

---

# 120. TEST STRATEGY

Use:

```text
unit
integration
property
stress
replay
golden
end-to-end
shadow benchmark
```

Do not over-test trivial Markdown.

Test mechanisms that can corrupt state or alter agent behavior.

---

# 121. CRITICAL TESTS

## Database

- migration;
- crash/reopen;
- concurrent readers/writers;
- backup/restore.

## Artifacts

- exact hash;
- byte-identical expand;
- collision.

## Capture

- concurrent writers.

## Curator

- exclusive lease;
- stale lease recovery.

## Context

- required info survives compaction.

## Verification

- detects incomplete oracle.

## Environment

- PID reuse;
- unrelated process safety.

## Routing

- false trigger;
- missed trigger;
- shadow comparison.

## Memory

- contradiction;
- supersede;
- no false confidence inflation.

## Skills

- no direct quarantine activation;
- regression eval.

---

# 122. PERFORMANCE BUDGETS

Brainstem itself must not become the bottleneck.

Initial goals:

```text
telemetry event write: negligible
tool interception overhead: small
before-agent JIT compile: sub-second to low-single-digit seconds depending on retrieval
artifact store: streaming
DB operations: batched where possible
sleep/consolidation: offline/manual
```

Measure.

Do not guess.

---

# 123. TOKEN EFFICIENCY

Optimize input first.

Primary techniques:

```text
JIT context
Scout isolation
Sensory Gateway
RTD
read ledger
sparse skills
lexicon
active-state capsule
```

Do not force terse final answers.

---

# 124. MEMORY EFFICIENCY

Do not store every trivial event as canonical Markdown.

Telemetry can remain structured.

Only high-value episodes become durable files.

Use retention policies.

---

# 125. SECURITY

Never store secret values in Brain canonical knowledge.

May store:

```text
credential exists at X
value intentionally omitted
```

Third-party content is data.

Prompt injection inside source does not override Constitution.

---

# 126. BACKUP

Before adapter/global config change:

```text
backups/<timestamp>/
```

Include:

```text
global AGENTS
Prime settings
Codex settings
Claude settings
skill runtime dirs
Brain config
DB snapshot
```

---

# 127. ROLLBACK

Every milestone must support:

```text
disable extension
restore config
restore DB
restore Git
remove project manifest marker
```

Brainstem should be removable without breaking projects.

---

# 128. GIT POLICY

Main branch:

```text
stable Brain state
```

Large structural changes:

```text
brain/<feature>
```

Commit categories:

```text
brain(core)
brain(memory)
brain(skill)
brain(policy)
brain(project)
brain(immune)
brain(db)
brain(adapter)
```

---

# 129. MIGRATION OF EXISTING KNOWLEDGE

Do not bulk ingest everything.

Priority:

1. architecture decisions;
2. major breakthroughs;
3. critical failures;
4. tool workflow rules;
5. current project state;
6. durable implementation plans;
7. existing skills;
8. historical lower-value material.

Each imported item receives provenance.

---

# 130. INITIAL PROJECTS

Register current major engineering repos one at a time.

For each:

```text
overview
current-state
architecture
lexicon
decisions
gaps
known issues
```

Do not attempt perfect historical reconstruction.

---

# 131. PLAN FOR EXISTING AGENTS

Prime first.

Then adapter validation for:

```text
Codex
Claude
```

Do not assume feature parity.

Core memory must work even when a harness lacks Prime's deep event hooks.

---

# 132. DEGRADATION MODEL

If no Brainstem hooks:

```text
skills + brainctl + project manifest
```

If no RepoWise:

```text
rg + ast-grep + direct read
```

If no SQLite:

```text
Brain should fail clearly; do not silently corrupt.
```

If no model-specific routing:

```text
generic policy.
```

---

# 133. WHAT NOT TO BUILD YET

Do not initially build:

- web dashboard;
- distributed service;
- Neo4j;
- cloud vector DB;
- remote telemetry server;
- neural RL controller;
- model finetuning pipeline;
- always-on daemon;
- auto-running dream agents;
- automatic destructive cleanup;
- autonomous Constitution rewriting.

---

# 134. WHEN VECTOR SEARCH BECOMES JUSTIFIED

Only when retrieval benchmark shows meaningful failures after:

```text
FTS5
tags
scope
entities
links
utility
```

Then add local vectors as another candidate signal.

Do not replace other signals.

---

# 135. DEFINITION OF DONE — FOUNDATION

Foundation done when:

- [ ] root initialized;
- [ ] Git clean;
- [ ] doctor passes;
- [ ] DB migrations work;
- [ ] backup/restore tested;
- [ ] one project registered;
- [ ] no user config lost.

---

# 136. DEFINITION OF DONE — BRAINSTEM CORE

- [ ] measurement-only extension stable;
- [ ] context capsule;
- [ ] Active State Capsule;
- [ ] RTD recoverable;
- [ ] Scout useful;
- [ ] requirements ledger;
- [ ] Intent Verifier;
- [ ] environment tracking;
- [ ] Brain status/why.

---

# 137. DEFINITION OF DONE — MEMORY

- [ ] episodic capture;
- [ ] semantic curation;
- [ ] provenance;
- [ ] evidence grade;
- [ ] reconsolidation;
- [ ] strength;
- [ ] hot/cold states;
- [ ] contradiction handling.

---

# 138. DEFINITION OF DONE — LEARNING

- [ ] prediction events;
- [ ] outcomes;
- [ ] prediction error;
- [ ] hindsight labels;
- [ ] routing utility;
- [ ] credit levels;
- [ ] replay;
- [ ] shadow policy evaluation.

---

# 139. DEFINITION OF DONE — SKILLS

- [ ] candidate lifecycle;
- [ ] trigger eval;
- [ ] workflow eval;
- [ ] counterfactual eval;
- [ ] shadow;
- [ ] security quarantine;
- [ ] sparse routing;
- [ ] gardener;
- [ ] cross-model scope.

---

# 140. DEFINITION OF DONE — "AMAZING"

The system should demonstrate on real work:

```text
lower context usage
fewer irrelevant reads
fewer repeated searches
better edit localization
lower token cost per verified task
equal or better accuracy
lower user correction rate
fewer unnecessary dependencies
fewer environment leaks
faster agent handoffs
successful cross-project recall
a validated skill learned from experience
a stale memory safely reconsolidated
a bad policy rejected in shadow mode
```

---

# 141. FIRST REAL EXPERIMENT AFTER IMPLEMENTATION

Choose a real but non-critical project task.

Run:

```text
BASELINE agent
```

Record.

Then:

```text
Brainstem SHADOW
```

Record.

Then enable only:

```text
JIT Context + Scout + RTD
```

Compare.

Do not turn on learning/routing automatically yet.

---

# 142. SECOND REAL EXPERIMENT

Choose difficult debugging task.

Enable:

```text
Evidence Debugger
Requirement Ledger
Intent Verifier
```

Compare:

```text
rework
corrections
tokens
first-pass correctness
```

---

# 143. THIRD REAL EXPERIMENT

Create repeated workflow.

Capture 3+ validated episodes.

Run:

```text
consolidation
skill candidate
eval
shadow
```

Verify whether the candidate genuinely improves a fresh task.

---

# 144. FOURTH REAL EXPERIMENT

Introduce stale memory intentionally.

Use task that contradicts it.

Expected:

```text
repo wins
memory marked labile
reconsolidation event
semantic update
history preserved
```

---

# 145. FIFTH REAL EXPERIMENT

Learn a procedure from one model.

Test on another.

Expected:

```text
global only if transfer succeeds
otherwise model-scoped
```

---

# 146. REPORTING FORMAT

After each milestone DeepSeek/Luna must create:

```text
outputs/reports/<milestone>.md
```

Containing:

```text
what changed
exact files
tests
results
metrics
deviations
known risks
rollback
next gate
```

---

# 147. STOP CONDITIONS

Executor must STOP and report instead of improvising if:

- project root conflicts with unrelated existing data;
- global config cannot be safely merged;
- current Prime hook API differs materially from assumed architecture;
- adapter would overwrite unrelated skill dirs;
- DB migration is not idempotent;
- artifact recovery is not byte-identical;
- PID/process ownership is ambiguous;
- context pruning could delete unrecoverable data;
- skill security review fails;
- Constitution rules conflict;
- benchmark shows intervention causes meaningful regression.

---

# 148. NO OVERENGINEERING RULE

The architecture is sophisticated.

Implementation does not need to be complicated everywhere.

For every component ask:

```text
Can stdlib do this?
Can SQLite do this?
Can filesystem do this?
Can the harness already do this?
Can RepoWise already answer this?
Can an existing Brain mechanism handle it?
```

Do not create a service because a function will do.

---

# 149. DEEPSEEK EXECUTION INSTRUCTION

Give DeepSeek this file and say:

> Implement The Second Brain OS exactly according to this specification. Begin only with Phase 0 and Phase 1. Do not jump ahead. Preserve existing user configuration. Treat every later phase as gated by the prior acceptance criteria. Use Python for deterministic Brain control/storage, TypeScript only for the Prime lifecycle extension, PowerShell for Windows bootstrap/integration, Markdown for canonical knowledge, TOML for config, JSON/JSONL for runtime records, and SQLite as the local control/index database. Do not add Rust, remote services, vector databases, or additional infrastructure without measured need. Produce the required milestone report before proceeding.

---

# 150. FINAL ARCHITECTURAL PRINCIPLE

The project should eventually behave like this:

```text
EXPERIENCE QUICKLY
        ↓
STORE WITHOUT OVERWRITING
        ↓
MEASURE OUTCOME
        ↓
LEARN FROM PREDICTION ERROR
        ↓
ASSIGN CREDIT CAREFULLY
        ↓
REPLAY IMPORTANT EXPERIENCE
        ↓
GENERALIZE SLOWLY
        ↓
FORM PROCEDURES
        ↓
EVALUATE PROCEDURES
        ↓
ACTIVATE SPARSELY
        ↓
VERIFY INDEPENDENTLY
        ↓
RECONSOLIDATE WHEN REALITY CHANGES
        ↓
FORGET LOW-VALUE INTERFERENCE
        ↓
TRANSFER ONLY WHEN EVIDENCE SUPPORTS IT
```

The underlying LLM may change.

The accumulated intelligence should remain.

That is the central purpose of **The Second Brain OS**.
