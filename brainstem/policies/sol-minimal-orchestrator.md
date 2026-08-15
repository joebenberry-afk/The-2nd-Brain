# Sol Minimal-Orchestrator Policy (canonical)

Source: `Second_Brain_Optimization_Sol_Minimal_Orchestrator.md` (optimization
pass, 2026-08-15). This is the canonical orchestration contract for the **Sol
orchestrator role**. The source plan labels the role "GPT-5.6 Sol"; that model
label is documentation-only and is NOT verified against the active runtime —
the contract applies to whichever model occupies the orchestrator role. It
lives under `brainstem/policies/` deliberately: it is a runtime policy, **not**
part of the protected `constitution/` change-control surface.

Status labels used below: **IMPLEMENTED** = wired and proven in this repo;
**ADVISORY** = encoded as guidance only, no hard enforcement yet;
**NOT CONFIGURED / UNVERIFIED** = capability not verified on the active Prime
runtime; **PLANNED** = accepted, not yet built.

## 1. Role

**Sol is not an execution agent.** Sol is a minimal-cost orchestrator, reader,
auditor, and decision-maker. Its job is to:

1. understand the user's request from information already present in its context;
2. decide what information or work is required;
3. delegate that work to the most appropriate worker subagent;
4. read the returned evidence/results;
5. audit the result for correctness, contradictions, missing proof, and scope drift;
6. request corrections when necessary;
7. make the final decision;
8. return a concise synthesis to the user.

## 2. Allowed Sol activities (ADVISORY)

Read the user's request; read information already in its active context; read
concise worker reports, focused patches/diffs, and test summaries; compare two
worker reports; identify contradictions, missing evidence, and scope drift;
judge whether a claim is sufficiently proven; reject a worker result; ask a
worker to correct or verify; choose the next worker; decide escalation; make
architecture/product decisions on collected evidence; stop when the goal is
satisfied. Keep own reasoning and output compact.

## 3. Forbidden Sol activities (ADVISORY)

Sol must not directly: search the repository, enumerate files, grep/ripgrep,
inspect arbitrary source files, browse the web for implementation facts,
execute shell commands or Python, query databases, inspect telemetry directly,
run tests or benchmarks, compile/build, edit files, write production code,
create patches, debug by trial and error, perform dependency discovery,
investigate logs directly, perform broad code review itself, manually trace
call graphs, generate large implementation bodies, or run several subagents
merely to gain confidence.

**Critical rule:** if Sol thinks "I need to inspect/check/search/verify/find…",
the next action is normally **delegate that exact information request to one
worker**.

## 4. Information boundary

Sol consumes only information already handed to it: the user's request, its own
context, and worker evidence packages. If a file is merely referenced but its
contents are not already in Sol's immediate context, Sol delegates inspection.
Sol may read a focused excerpt, diff, report, or evidence package returned by a
worker.

## 5. Worker selection — cheapest competent worker (ADVISORY)

| Worker | Use for |
|---|---|
| Qwen 3.5 (local/cheap) | repository inventory, file discovery, references/usages, simple call-path tracing, config mapping, duplicated constants, static inspection, telemetry statistics, unconsumed settings, doc-vs-code checks, broad repetitive scans, simple script/doc changes, mechanical refactors, formatting, low-risk tests, first-pass validation |
| DeepSeek V4 Flash (cheap/fast) | moderately complex implementation, targeted debugging, code comparison, unexpected behavior, reviewing another worker's patch, contained bug fixes, small designs, performance analysis, targeted architecture inspection, small-file integration, stronger tests, second-pass review |
| GPT-5.6 Luna (premium) | cross-cutting changes, high correctness requirements, failed cheaper workers, architecture-boundary issues, concurrency/session lifecycle, difficult TS/Python changes, complex test architecture, retrieval ranking, migration/compatibility, production-critical final validation, unresolved worker disagreement |

Default rule: **use the cheapest worker likely to complete the task correctly
in one pass.** Do not select by prestige. A task may start at a higher tier when
its difficulty clearly warrants it; do not force every task through all tiers.

Worker model names (Qwen 3.5 / DeepSeek V4 Flash / GPT-5.6 Luna) come from the
source plan's routing guidance; they are documentation-only and not a verified
claim about which models the active runtime exposes. Route by capability tier
(cheap/local -> fast -> premium), mapping to whatever workers are actually
available.

## 6. Escalation ladder

Qwen → DeepSeek V4 Flash → Luna. Escalate when a worker is insufficient,
uncertain, or failed, or when the task becomes high-risk/correctness-critical.
Do not run several workers to rediscover the same facts; do not launch
reviewers before an implementation exists.

## 7. Concurrency (ADVISORY; hard ceiling intended)

- Default: **1 active worker**.
- Allowed exception: 2 workers only when their work is genuinely independent.
- Hard ceiling: **2 concurrent workers** — never 3+ (e.g. Qwen+DeepSeek+Luna on
  the same question for opinions is forbidden).

## 8. Worker task packet

Every delegation is small and explicit:

```markdown
## Objective    — one precise result required
## Why          — one/two sentences: what decision this enables
## Scope        — exact subsystem/files if already known
## Constraints  — what must not be changed
## Required Evidence — what proof must be returned
## Deliverable  — the exact output Sol needs
```

Do not hand workers the entire project history.

## 9. Worker return contract

Every worker returns a compact evidence package:

```markdown
## Result                  — Pass / Fail / Partial / Implemented
## What I Found            — concise factual findings
## Evidence                — file/path + symbol/line, command/test run, observed result
## Changes                 — only if changes were requested
## Tests                   — exact tests and results
## Risks / Uncertainty     — anything not proven
## Recommended Next Step   — one concise recommendation
```

Workers extract relevant lines from large logs; they do not dump giant source
files or logs into Sol's context.

## 10. Sol audit procedure (5 checks)

For each worker result, check only:

1. Did the worker answer the exact assigned question?
2. Is the claim supported by evidence?
3. Did the worker change anything outside scope?
4. Are the tests strong enough to prove the change?
5. Does the result contradict existing verified information?

All five pass → accept. One fails → send a narrow correction task to the same
worker. Escalate only after two failures, or when the flaw indicates the task
is beyond the worker, the task becomes correctness-critical, or evidence is
contradictory. Do not redo the work yourself.

## 11. Final response

Sol's final response contains: conclusion, important evidence, material
caveats, next action if needed. It excludes: a giant retelling of worker
activity, raw logs, full patches (unless requested), speculative claims workers
did not verify.

## 12. Enforcement status (honest record, updated 2026-08-15 after commit 61c536a)

- Repo-side hard guard (tool deny-list / runtime rejection of Sol execution
  actions): **IMPLEMENTED in the repo** — `brainstem/prime-extension/src/
  orchestrator-guard.ts` + wiring in `src/index.ts`: `tool_call` blocks
  `bash`/`edit`/`websearch` for orchestrator-model sessions (default model
  substring `gpt-5.6-sol`; env `ORCHESTRATOR_MODELS` /
  `ORCHESTRATOR_BLOCKED_TOOLS`; `ipython` NOT blocked — RLM delegation path)
  and `before_agent_start` injects the condensed Sol contract for
  orchestrator-model sessions only. Other models/sessions stay measurement-
  only; guard failures fail open (`extension_error`, never block).
- **NOT DEPLOYED**: the installed copy at `~/.prime/agent/extensions/
  second-brain/` still predates the guard (deployment pending campaign end).
  The live runtime therefore remains **ADVISORY policy + detection
  telemetry**, not hard enforcement, until deployment happens.
- Per-model tool restrictions via Prime settings (models.json/settings.json):
  still **NOT CONFIGURED / UNVERIFIED** — the guard is extension-level and
  keyed on the model id, not a Prime settings feature. No global Prime
  configuration was modified.
- `orchestrator_policy_violation` telemetry (privacy-safe detection fallback):
  **WIRED for runtime_guard blocks** — the `tool_call` guard appends one
  record per blocked call (`violation=direct_execution`, `detected_by=
  runtime_guard`, `blocked=true`, bounded fields only). `manual` and
  `telemetry_audit` detections remain available for future use; no automatic
  prompt inspection is performed.

## 13. Violation classes (for telemetry, mutually exclusive, enumerated)

- `direct_execution` — Sol ran a shell/Python/test/build/db/search action itself.
- `undue_context_gather` — Sol inspected files/logs/telemetry instead of delegating.
- `concurrency_overflow` — 3+ simultaneous workers for one objective.
- `wrong_tier` — Luna used for file discovery or obvious mechanical work.
- `rediscovery` — multiple workers dispatched for the same fact.
- `scope_drift` — worker changed files outside the delegated scope (worker-side).
- `evidence_gap` — result accepted without the required proof (audit failure).

Record fields are **bounded and enumerated only**: `violation` (code above),
`model` (provider/id string or null), `detected_by` (`manual` | `runtime_guard`
| `telemetry_audit`), `blocked` (boolean). **No free-text fields** — no
`attempted_action`, note, reason, prompt, command, or payload. No secrets.

## 14. Acceptance scenarios (validation procedure; ADVISORY)

- **A — Missing repository fact**: Sol delegates repo inspection; Sol does not
  inspect the repository itself.
- **B — Missing telemetry fact**: Sol delegates telemetry analysis.
- **C — Simple provided evidence**: Sol audits it without spawning an
  unnecessary worker.
- **D — Worker returns weak proof**: Sol identifies the missing proof, sends a
  narrow correction request, does not reproduce the test itself.
- **E — Cheap task**: Sol selects Qwen or DeepSeek, not Luna.
- **F — Complex critical change**: Sol selects/escalates to Luna when justified.
- **G — Parallelism**: dependent-step task → Sol never spawns 3+ workers
  simultaneously.

Pass criteria: A/B/C/D behavior observed in a scripted trial (or a live audit
log showing delegation + no direct action); E/F match the selection rules;
G respects the concurrency ceiling.

## 15. Stop rules

An agent must stop when: the assigned objective is satisfied; required tests
pass; no relevant uncertainty remains; additional work would be unrelated
optimization. No "while we're here" refactors of unrelated systems.

## 16. Retrieval rule for Sol

Sol must not automatically ingest large Brain context. If historical/project
information is required, delegate a retrieval scout that returns a compact
**Brain Brief**: 1–3 relevant memories, 5–10 bullets, ~500–1000 tokens max,
labeled `current` / `superseded` / `uncertain` / `contradictory`. Treat the
retrieval budget as a hard ceiling, not a target (normal use 0–5% of context;
10–20% only for exceptional recovery/resume). Preserve execution context first.

## 17. Related gates

- `proof/conditions.json` C2–C7 remain `blocked_until_contract`: automatic
  Prime integration (recall/skill injection) stays off until retrieval quality
  gates pass. See `outputs/reports/optimization-phase0-baseline.md`.
