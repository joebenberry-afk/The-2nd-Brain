/**
 * Model-keyed minimal-orchestrator guard (pure decision logic).
 *
 * Implements the enforcement half of the Sol minimal-orchestrator policy
 * (`brainstem/policies/sol-minimal-orchestrator.md`): when the ACTIVE model
 * is the orchestrator (Sol), execution tools are blocked so the model can
 * only delegate and read returned results. When the active model is NOT the
 * orchestrator, nothing is ever blocked.
 *
 * Design rules:
 *  - PURE and side-effect-free: no I/O, no imports with side effects, no
 *    randomness. Every branch is unit-testable and deterministic.
 *  - Env-overridable defaults in the style of `src/config.ts`: read the
 *    environment at call time so tests can manipulate it.
 *  - `ipython` is deliberately NOT blocked: in Prime Agent, subagent
 *    delegation (`rlm(...)`) runs through the IPython kernel, and the policy
 *    requires the orchestrator to KEEP the delegation mechanism.
 *
 * Enforcement is wired by the extension host (`tool_call` event returns
 * `{ block: true, reason }`); this module only DECIDES. It has no knowledge
 * of the extension runtime and performs no side effects.
 */

/** Default model-id substrings identifying the orchestrator role (Sol). */
export const DEFAULT_ORCHESTRATOR_MODELS = ["gpt-5.6-sol"];

/** Default tool names forbidden for orchestrator models. ipython stays allowed (delegation path). */
export const DEFAULT_BLOCKED_TOOLS = ["bash", "edit", "websearch"];

/** Environment variable names consumed by the guard. */
export const ORCHESTRATOR_MODELS_ENV = "ORCHESTRATOR_MODELS";
export const ORCHESTRATOR_BLOCKED_TOOLS_ENV = "ORCHESTRATOR_BLOCKED_TOOLS";

/** Resolved guard configuration. */
export interface OrchestratorGuardConfig {
  /** Lowercased model-id substrings; a model id containing any of these is the orchestrator. */
  orchestratorModels: string[];
  /** Lowercased tool names that the orchestrator must not execute directly. */
  blockedTools: string[];
}

/** Decision for one (model, tool) pair. `reason` is for the tool-result error text only — never persisted. */
export interface OrchestratorPolicyDecision {
  block: boolean;
  reason?: string;
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
 * Load guard configuration from the environment (defaults when unset).
 * Accepts an explicit env record for deterministic tests; defaults to
 * `process.env` so the wired extension needs no argument.
 */
export function loadOrchestratorGuardConfig(
  env: Record<string, string | undefined> = process.env,
): OrchestratorGuardConfig {
  return {
    orchestratorModels: parseCsv(env[ORCHESTRATOR_MODELS_ENV], DEFAULT_ORCHESTRATOR_MODELS),
    blockedTools: parseCsv(env[ORCHESTRATOR_BLOCKED_TOOLS_ENV], DEFAULT_BLOCKED_TOOLS),
  };
}

/**
 * True when `modelId` identifies the orchestrator role: the lowercased model
 * id contains any configured orchestrator substring. Undefined/empty ids
 * never match.
 */
export function isOrchestratorModel(
  modelId: string | undefined,
  config: OrchestratorGuardConfig,
): boolean {
  if (modelId === undefined || modelId === null || modelId.trim() === "") {
    return false;
  }
  const id = modelId.toLowerCase();
  return config.orchestratorModels.some((substring) => id.includes(substring));
}

/**
 * Decide whether a tool call by `modelId` must be blocked.
 *
 * Never blocks when the model is not the orchestrator (allow). For the
 * orchestrator, blocks only tools in the configured blocked list; everything
 * else — including `ipython` (delegation path) — is allowed.
 */
export function orchestratorPolicyFor(
  modelId: string | undefined,
  toolName: string | undefined,
  config: OrchestratorGuardConfig,
): OrchestratorPolicyDecision {
  if (!isOrchestratorModel(modelId, config)) {
    return { block: false };
  }
  const tool = (toolName ?? "").trim().toLowerCase();
  if (tool !== "" && config.blockedTools.includes(tool)) {
    return {
      block: true,
      reason:
        `Sol minimal-orchestrator policy: "${tool}" is blocked for orchestrator model "${modelId}". ` +
        `Delegate the action to a worker and read the returned results instead.`,
    };
  }
  return { block: false };
}

/**
 * Telemetry record for a blocked orchestrator action.
 *
 * Shape follows `brainstem/telemetry/SCHEMA.md` (v2) kind
 * `orchestrator_policy_violation`: BOUNDED, ENUMERATED FIELDS ONLY —
 * `violation`, `model`, `detected_by`, `blocked`. The schema forbids
 * free-text fields, so `toolName` and `reason` are accepted for call-site
 * symmetry with `orchestratorPolicyFor` but intentionally NOT persisted.
 *
 * `session` is a placeholder (empty string); the wiring layer fills the
 * session stem from the Prime session manager.
 */
export interface OrchestratorPolicyBlockRecord {
  v: 2;
  ts: string;
  kind: "orchestrator_policy_violation";
  session: string;
  violation: "direct_execution";
  model: string | null;
  detected_by: "runtime_guard";
  blocked: true;
}

export function buildPolicyBlockRecord(
  modelId: string | undefined,
  _toolName: string,
  _reason: string | undefined,
  nowIso: string,
): OrchestratorPolicyBlockRecord {
  return {
    v: 2,
    ts: nowIso,
    kind: "orchestrator_policy_violation",
    session: "",
    violation: "direct_execution",
    model: modelId === undefined || modelId === null || modelId.trim() === "" ? null : modelId,
    detected_by: "runtime_guard",
    blocked: true,
  };
}
