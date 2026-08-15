# Driver Orchestration Contract (canonical)

Source: Driver-Orchestration campaign (optimization pass, 2026-08-15). This
is the canonical orchestration contract for the **driver role** in the Prime
extension (`brainstem/prime-extension`): a model that runs the agent session
but delegates the bulk of execution-heavy work to worker subagents. It lives
under `brainstem/policies/` deliberately: it is a runtime policy, **not** part
of the protected `constitution/` change-control surface.

Status labels used below: **IMPLEMENTED** = wired and proven in this repo;
**ADVISORY** = encoded as guidance only, no hard enforcement yet;
**NOT CONFIGURED / UNVERIFIED** = capability not verified on the active Prime
runtime; **PLANNED** = accepted, not yet built.

## 1. Role model

Every session's active model is classified into exactly one of four roles on
`before_agent_start` (resolution: `src/driver-orchestrator.ts`
`resolveAgentRole`; precedence hard_orchestrator > driver > worker > normal;
lowercased substring containment, same semantics as the Sol guard):

| Role | Default model substrings | Default source |
|---|---|---|
| `hard_orchestrator` | `gpt-5.6-sol` | `ORCHESTRATOR_MODELS` (existing Sol guard, unchanged) |
| `driver` | `deepseek-v4-pro`, `gpt-5.6-luna` | `DRIVER_MODELS` (new) |
| `worker` | `deepseek-v4-flash`, `qwen3.5` | `WORKER_MODELS` (new) |
| `normal` | anything else (e.g. `anthropic/claude-sonnet-5`, `openai-codex/gpt-5.6-terra`) | — |

Model ids are matched case-insensitively as substrings of the lowercased
`provider/id` serialization (e.g. `deepseek/deepseek-v4-pro`).
`deepseek-v4-pro` and `deepseek-v4-flash` are mutually exclusive substrings.
Blank/null model ids are always `normal`.

## 2. Role behaviors

- **hard_orchestrator (Sol)** — unchanged: strict Sol contract replaces the
  system prompt (`SOL_ORCHESTRATOR_CONTRACT`), `bash`/`edit`/`websearch` are
  blocked by the runtime guard, `ipython` stays available for delegation
  (see `sol-minimal-orchestrator.md`). The driver contract is NEVER applied.
- **driver** — the driver-orchestration contract
  (`DRIVER_ORCHESTRATOR_CONTRACT`, embedded in `src/driver-orchestrator.ts`,
  <= 230 words, marker `second-brain-driver-orchestration-contract`) is
  APPENDED to the full current system prompt (`ctx.getSystemPrompt()` + the
  contract). Never replaces the base prompt. Deduplicated by the marker:
  when the base already contains the marker, no second append happens and
  no prompt patch is returned (unless the recall hook produces one).
- **worker** — measurement-only. Never receives the driver contract. Workers
  do not inherit the driver role and must not orchestrate (anti-recursion).
- **normal** — measurement-only, no contract.

## 3. Contract content (IMPLEMENTED)

The driver contract states, in order: (1) the driver orchestrates substantive
work by default and never waits for the user to explicitly ask for subagents;
(2) TRIVIAL work (one obvious action, tiny edit, typo, loaded-context
question) is executed directly — never spawn workers merely because workers
exist; (3) SUBSTANTIAL work (repo investigation, debugging, unknown root
cause, multi-file implementation, research, nontrivial review) is delegated —
the bulk of execution-heavy work goes to workers, small control-plane actions
stay with the driver, and worker work is never duplicated; (4) concurrency:
parallelize only genuinely independent workstreams, default 1 active worker,
at most 2, never 3+; (5) worker selection prefers the cheapest competent
worker (deepseek-v4-flash or qwen3.5), stronger workers only when required;
(6) every worker spawn gets a narrow objective, scope, constraints, required
evidence, and completion condition; (7) workers do not inherit the driver
role and must not orchestrate; (8) the driver reviews every worker result
(evidence quality, contradictions), prefers one targeted correction over
replacing a worker, and owns final integration and the final answer.

## 4. Configuration (IMPLEMENTED)

Env vars, comma-separated, trimmed/lowercased, empty items dropped; unset or
all-empty falls back to the defaults (read at call time, `process.env` by
default — same style as `orchestrator-guard.ts`):

- `DRIVER_MODELS` — driver-role model-id substrings (default
  `deepseek-v4-pro,gpt-5.6-luna`).
- `WORKER_MODELS` — worker-role model-id substrings (default
  `deepseek-v4-flash,qwen3.5`).

No file-based configuration; no new env vars beyond these two. The existing
concurrency ceiling of the system (`config/skills.toml [router] max_active`,
default 3) is not the driver contract's limit: the CONTRACT enforces a
stricter 1-default / 2-max / never-3+ rule on the driver role itself.

## 5. Enforcement (IMPLEMENTED)

- `src/index.ts` `before_agent_start` handler: role resolution, contract
  append (driver only), recall composition (brief appended AFTER the contract
  in one patch when the default-off recall hook is enabled), telemetry record
  with `role` (always) and `driver_contract_injected` (driver only).
- `src/sensors.ts` `beforeAgentStart`: additive optional `role` /
  `driver_contract_injected` fields (schema v2, snake_case, additive per
  `brainstem/telemetry/SCHEMA.md`).
- Pure decision module `src/driver-orchestrator.ts` with no I/O; unit-tested
  (`tests/driver-orchestrator.test.ts`); wiring tested
  (`tests/wiring.test.ts`).
- The Sol guard (`orchestrator-guard.ts`) is NOT modified; Sol isolation is
  preserved by role precedence (hard_orchestrator wins) and by the handler
  ordering (Sol branch returns before any driver/recall composition).

## 6. Anti-recursion (IMPLEMENTED)

Workers (and normal models) never receive the driver contract, so a spawned
worker cannot itself act as a driver; `ORCHESTRATOR_MODELS`/`DRIVER_MODELS`
defaults are disjoint from `WORKER_MODELS`, and role resolution is
deterministic per model id. Operator overrides that put the same substring in
both lists are possible but discouraged; precedence resolves ties in favor
of the higher role.
