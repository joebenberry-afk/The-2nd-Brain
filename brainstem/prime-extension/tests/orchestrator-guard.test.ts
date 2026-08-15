/**
 * Tests for the Sol minimal-orchestrator guard decision module.
 * Pure-function coverage: defaults, env overrides, decision matrix,
 * record shape (SCHEMA.md v2), determinism, and edge cases.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_BLOCKED_TOOLS,
  DEFAULT_ORCHESTRATOR_MODELS,
  buildPolicyBlockRecord,
  isOrchestratorModel,
  loadOrchestratorGuardConfig,
  orchestratorPolicyFor,
} from "../src/orchestrator-guard";

const SOL = "openai-codex/gpt-5.6-sol";
const SOL_BARE = "gpt-5.6-sol";
const WORKER = "deepseek/deepseek-v4-flash";
const LOCAL = "lemonade/Qwen3.5-9B-GGUF-Q6_K";

describe("loadOrchestratorGuardConfig", () => {
  it("defaults when env is unset/empty", () => {
    expect(loadOrchestratorGuardConfig({})).toEqual({
      orchestratorModels: DEFAULT_ORCHESTRATOR_MODELS,
      blockedTools: DEFAULT_BLOCKED_TOOLS,
    });
    expect(loadOrchestratorGuardConfig({ ORCHESTRATOR_MODELS: "", ORCHESTRATOR_BLOCKED_TOOLS: "   " })).toEqual({
      orchestratorModels: DEFAULT_ORCHESTRATOR_MODELS,
      blockedTools: DEFAULT_BLOCKED_TOOLS,
    });
  });

  it("defaults match the policy contract: bash/edit/websearch blocked, ipython NOT listed", () => {
    expect(DEFAULT_BLOCKED_TOOLS).toEqual(["bash", "edit", "websearch"]);
    expect(DEFAULT_BLOCKED_TOOLS).not.toContain("ipython");
    expect(DEFAULT_ORCHESTRATOR_MODELS).toEqual(["gpt-5.6-sol"]);
  });

  it("env override replaces the model list (comma-separated, trimmed, lowercased)", () => {
    const cfg = loadOrchestratorGuardConfig({
      ORCHESTRATOR_MODELS: "DeepSeek-V4-Flash, qwen3.5 ",
    });
    expect(cfg.orchestratorModels).toEqual(["deepseek-v4-flash", "qwen3.5"]);
    expect(cfg.orchestratorModels).not.toContain("gpt-5.6-sol");
  });

  it("env override replaces the blocked-tool list", () => {
    const cfg = loadOrchestratorGuardConfig({
      ORCHESTRATOR_BLOCKED_TOOLS: "bash, ipython",
    });
    expect(cfg.blockedTools).toEqual(["bash", "ipython"]);
    expect(cfg.blockedTools).not.toContain("edit");
  });
});

describe("isOrchestratorModel", () => {
  const cfg = loadOrchestratorGuardConfig({});

  it("matches provider-qualified and bare Sol ids by substring", () => {
    expect(isOrchestratorModel(SOL, cfg)).toBe(true);
    expect(isOrchestratorModel(SOL_BARE, cfg)).toBe(true);
    expect(isOrchestratorModel("openai-codex/GPT-5.6-SOL", cfg)).toBe(true); // case-insensitive
  });

  it("does not match other models or undefined/empty ids", () => {
    expect(isOrchestratorModel(WORKER, cfg)).toBe(false);
    expect(isOrchestratorModel(LOCAL, cfg)).toBe(false);
    expect(isOrchestratorModel("openai-codex/gpt-5.6-terra", cfg)).toBe(false); // substring must be exact
    expect(isOrchestratorModel(undefined, cfg)).toBe(false);
    expect(isOrchestratorModel("", cfg)).toBe(false);
    expect(isOrchestratorModel("   ", cfg)).toBe(false);
  });
});

describe("orchestratorPolicyFor — decision matrix", () => {
  const cfg = loadOrchestratorGuardConfig({});

  it("orchestrator model + blocked tool -> block with reason", () => {
    for (const tool of DEFAULT_BLOCKED_TOOLS) {
      const decision = orchestratorPolicyFor(SOL, tool, cfg);
      expect(decision.block).toBe(true);
      expect(decision.reason).toContain("Sol minimal-orchestrator policy");
    }
    expect(orchestratorPolicyFor(SOL, "BASH", cfg).block).toBe(true); // tool case-insensitive
    expect(orchestratorPolicyFor(SOL, "  edit  ", cfg).block).toBe(true); // trimmed
  });

  it("orchestrator model + ipython -> allow (delegation path)", () => {
    expect(orchestratorPolicyFor(SOL, "ipython", cfg)).toEqual({ block: false });
    expect(orchestratorPolicyFor(SOL, "Ipython", cfg).block).toBe(false);
  });

  it("orchestrator model + other tools -> allow", () => {
    for (const tool of ["agent_message", "agent_observe", "rlm", "goal"]) {
      expect(orchestratorPolicyFor(SOL, tool, cfg).block).toBe(false);
    }
  });

  it("non-orchestrator model + any tool -> never blocked", () => {
    for (const tool of [...DEFAULT_BLOCKED_TOOLS, "ipython", "agent_message"]) {
      expect(orchestratorPolicyFor(WORKER, tool, cfg).block).toBe(false);
      expect(orchestratorPolicyFor(LOCAL, tool, cfg).block).toBe(false);
      expect(orchestratorPolicyFor(undefined, tool, cfg).block).toBe(false);
    }
  });

  it("env override changes which tools/models the matrix blocks", () => {
    const overridden = loadOrchestratorGuardConfig({
      ORCHESTRATOR_MODELS: "deepseek-v4-flash",
      ORCHESTRATOR_BLOCKED_TOOLS: "bash,ipython",
    });
    // deepseek is now the orchestrator: bash and ipython blocked, edit allowed
    expect(orchestratorPolicyFor(WORKER, "bash", overridden).block).toBe(true);
    expect(orchestratorPolicyFor(WORKER, "ipython", overridden).block).toBe(true);
    expect(orchestratorPolicyFor(WORKER, "edit", overridden).block).toBe(false);
    // Sol is no longer the orchestrator under the override
    expect(orchestratorPolicyFor(SOL, "bash", overridden).block).toBe(false);
  });

  it("is deterministic: identical inputs produce identical outputs", () => {
    const a = orchestratorPolicyFor(SOL, "bash", cfg);
    const b = orchestratorPolicyFor(SOL, "bash", cfg);
    expect(a).toEqual(b);
  });
});

describe("buildPolicyBlockRecord — SCHEMA.md v2 shape", () => {
  it("emits the orchestrator_policy_violation kind with bounded enumerated fields", () => {
    const record = buildPolicyBlockRecord(SOL, "bash", "delegate instead", "2026-08-15T09:00:00.000Z");
    expect(record).toEqual({
      v: 2,
      ts: "2026-08-15T09:00:00.000Z",
      kind: "orchestrator_policy_violation",
      session: "",
      violation: "direct_execution",
      model: SOL,
      detected_by: "runtime_guard",
      blocked: true,
    });
    // No free-text fields (SCHEMA.md Phase 1 addition): tool/reason never persisted.
    expect(Object.keys(record).sort()).toEqual(
      ["blocked", "detected_by", "kind", "model", "session", "ts", "v", "violation"].sort(),
    );
  });

  it("maps missing model to null and passes nowIso through", () => {
    const record = buildPolicyBlockRecord(undefined, "bash", undefined, "2026-08-15T09:01:00.000Z");
    expect(record.model).toBeNull();
    expect(record.ts).toBe("2026-08-15T09:01:00.000Z");
    expect(record.blocked).toBe(true);
    expect(record.detected_by).toBe("runtime_guard");
    expect(record.violation).toBe("direct_execution");
  });
});
