/**
 * Driver-orchestration role resolution + contract (pure decision logic).
 *
 * Implements the Driver Orchestration Contract (canonical policy:
 * `brainstem/policies/driver-orchestration.md`): the active model is
 * classified into one of four roles — `hard_orchestrator` (Sol, guarded by
 * `orchestrator-guard.ts`), `driver` (deepseek-v4-pro, gpt-5.6-luna,
 * gpt-6-astra by default), `worker` (deepseek-v4-flash, qwen3.5), or `normal`
 * (everything else). Only the DRIVER role receives the driver contract as a
 * systemPrompt addendum on `before_agent_start`; workers and normal models
 * never get it, and the hard orchestrator keeps its existing strict Sol
 * contract untouched.
 *
 * Design rules (mirror `src/orchestrator-guard.ts`):
 *  - PURE and side-effect-free: no I/O, no imports with side effects, no
 *    randomness. Every branch is unit-testable and deterministic.
 *  - Env-overridable defaults in the style of `src/config.ts`: read the
 *    environment at call time so tests can manipulate it.
 *  - Substring matching is deliberately identical to the Sol guard
 *    (`id.toLowerCase().includes(substring)`): `deepseek-v4-pro` never
 *    matches `deepseek-v4-flash` and vice versa, while bare ids such as
 *    `qwen3.5` match provider-qualified ids like `lemonade/Qwen3.5-9B-GGUF-Q6_K`
 *    case-insensitively.
 *
 * The contract itself is embedded here so the installed extension copy stays
 * self-contained (same pattern as `SOL_ORCHESTRATOR_CONTRACT` in index.ts).
 */

/** Agent roles resolved from the active model id. */
export type AgentRole = "hard_orchestrator" | "driver" | "worker" | "normal";

/** Default model-id substrings identifying the DRIVER role (campaign orchestrators). */
export const DEFAULT_DRIVER_MODELS = [
  "deepseek-v4-pro",
  "gpt-5.6-luna",
  "gpt-6-astra",
  "deepseek-flash",
];

/** Default model-id substrings identifying the WORKER role (never get the driver contract). */
export const DEFAULT_WORKER_MODELS = ["deepseek-v4-flash", "qwen3.5"];

/** Environment variable names consumed by the driver-orchestrator config. */
export const DRIVER_MODELS_ENV = "DRIVER_MODELS";
export const WORKER_MODELS_ENV = "WORKER_MODELS";

/** Resolved driver-orchestrator configuration. */
export interface DriverOrchestratorConfig {
  /** Lowercased model-id substrings; a model id containing any of these is the driver. */
  driverModels: string[];
  /** Lowercased model-id substrings; a model id containing any of these is a worker. */
  workerModels: string[];
}

/**
 * Parse a comma-separated env list into trimmed, lowercased, non-empty items.
 * Empty/unset input falls back to `fallback` (a defensive copy).
 */
function parseCsv(raw: string | undefined, fallback: readonly string[]): string[] {
  if (raw === undefined || raw.trim() === "") {
    return [...fallback];
  }
  const items = raw
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter((item) => item.length > 0);
  return items.length > 0 ? items : [...fallback];
}

/**
 * Load driver-orchestrator configuration from the environment (defaults when
 * unset). Accepts an explicit env record for deterministic tests; defaults to
 * `process.env` so the wired extension needs no argument.
 */
export function loadDriverOrchestratorConfig(
  env: Record<string, string | undefined> = process.env,
): DriverOrchestratorConfig {
  return {
    driverModels: parseCsv(env[DRIVER_MODELS_ENV], DEFAULT_DRIVER_MODELS),
    workerModels: parseCsv(env[WORKER_MODELS_ENV], DEFAULT_WORKER_MODELS),
  };
}

/**
 * Resolve the agent role for a model id. Lowercased substring containment
 * (same semantics as `orchestrator-guard.isOrchestratorModel`). Precedence:
 * HARD_ORCHESTRATOR > DRIVER > WORKER > NORMAL. Null/undefined/blank ids are
 * always `normal`.
 *
 * `hardModels` is the Sol-guard model substring list (from
 * `loadOrchestratorGuardConfig().orchestratorModels`), so the hard
 * orchestrator role is decided by the SAME configuration as the guard.
 */
export function resolveAgentRole(
  modelId: string | null | undefined,
  cfg: DriverOrchestratorConfig,
  hardModels: string[],
): AgentRole {
  if (modelId === undefined || modelId === null || modelId.trim() === "") {
    return "normal";
  }
  const id = modelId.toLowerCase();
  if (hardModels.some((substring) => id.includes(substring.toLowerCase()))) {
    return "hard_orchestrator";
  }
  if (cfg.driverModels.some((substring) => id.includes(substring))) {
    return "driver";
  }
  if (cfg.workerModels.some((substring) => id.includes(substring))) {
    return "worker";
  }
  return "normal";
}

/** Marker string that identifies the driver contract inside a system prompt. */
export const DRIVER_CONTRACT_MARKER = "second-brain-driver-orchestration-contract";

/**
 * The driver-orchestration contract, appended to the FULL current system
 * prompt for DRIVER-role sessions only (never replaces the base prompt).
 * The first line carries DRIVER_CONTRACT_MARKER so `appendDriverContract`
 * can deduplicate. Word count is capped at 230 (verified by tests).
 */
export const DRIVER_ORCHESTRATOR_CONTRACT = `[${DRIVER_CONTRACT_MARKER}] You are the DRIVER of an RLM-capable agent system. ORCHESTRATE substantive work by default; never wait for the user to explicitly ask for subagents.

TRIVIAL work (one obvious action, a tiny edit, a typo, or a question answerable from your loaded context) -> execute directly. Never spawn workers merely because workers exist.

SUBSTANTIAL work (repository investigation, debugging, unknown root cause, multi-file implementation, research, nontrivial review) -> delegate the bulk of execution-heavy work to workers. Small control-plane actions stay yours. Do not duplicate worker work.

CONCURRENCY: parallelize only genuinely independent workstreams; default 1 active worker, at most 2, NEVER 3+.

WORKER SELECTION: prefer the cheapest competent worker (deepseek-v4-flash or qwen3.5); use a stronger worker only when required.

WORKER TASK PACKET: every spawn gets a narrow objective, scope, constraints, required evidence, and a completion condition. Workers do NOT inherit the driver role and must NOT orchestrate.

REVIEW: audit every worker result for evidence quality and contradictions; prefer one targeted correction over replacing a worker; own final integration and the final answer.

STOP: once worker evidence and the Requirement Ledger prove completion with no material gate remaining or a legitimate blocker, invoke the bounded Brain STOP decision with the current session/task identity; decision=stop is terminal — never spawn "one more" verifier, worker, or substantive tool without a risk/evidence reason.`;

/**
 * Append the driver contract to a base system prompt. Returns undefined when
 * the base is undefined/empty (never invent a prompt), and returns the base
 * UNCHANGED when it already contains DRIVER_CONTRACT_MARKER (dedup). Otherwise
 * returns `${base}\n\n${contract}` — an APPEND, never a replace.
 */
export function appendDriverContract(base: string | undefined): string | undefined {
  if (base === undefined || base.trim() === "") return undefined;
  if (base.includes(DRIVER_CONTRACT_MARKER)) return base;
  return `${base}

${DRIVER_ORCHESTRATOR_CONTRACT}`;
}
