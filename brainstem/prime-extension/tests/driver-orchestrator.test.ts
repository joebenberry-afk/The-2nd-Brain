/**
 * Tests for the driver-orchestration role resolver + contract module.
 * Pure-function coverage: defaults, env overrides, CSV edge cases, role
 * precedence, substring/case semantics, negatives, contract dedup, and the
 * contract content/word-count guarantees.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_DRIVER_MODELS,
  DEFAULT_WORKER_MODELS,
  DRIVER_CONTRACT_MARKER,
  DRIVER_ORCHESTRATOR_CONTRACT,
  appendDriverContract,
  loadDriverOrchestratorConfig,
  resolveAgentRole,
} from "../src/driver-orchestrator";

// Canonical model id strings (same fixture set as orchestrator-guard.test.ts).
const SOL = "openai-codex/gpt-5.6-sol";
const DRIVER = "deepseek/deepseek-v4-pro";
const LUNA = "openai-codex/gpt-5.6-luna";
const WORKER = "deepseek/deepseek-v4-flash";
const LOCAL = "lemonade/Qwen3.5-9B-GGUF-Q6_K";
const TERRA = "openai-codex/gpt-5.6-terra";
const CLAUDE = "anthropic/claude-sonnet-5";

const HARD = ["gpt-5.6-sol"]; // loadOrchestratorGuardConfig({}).orchestratorModels

describe("loadDriverOrchestratorConfig", () => {
  it("defaults when env is unset/empty", () => {
    expect(loadDriverOrchestratorConfig({})).toEqual({
      driverModels: DEFAULT_DRIVER_MODELS,
      workerModels: DEFAULT_WORKER_MODELS,
    });
    expect(
      loadDriverOrchestratorConfig({ DRIVER_MODELS: "", WORKER_MODELS: "   " }),
    ).toEqual({
      driverModels: DEFAULT_DRIVER_MODELS,
      workerModels: DEFAULT_WORKER_MODELS,
    });
  });


  it("env override replaces the driver list (comma-separated, trimmed, lowercased)", () => {
    const cfg = loadDriverOrchestratorConfig({
      DRIVER_MODELS: " DeepSeek-V4-Pro , gpt-5.6-LUNA ",
      WORKER_MODELS: "deepseek-v4-flash, qwen3.5",
    });
    expect(cfg.driverModels).toEqual(["deepseek-v4-pro", "gpt-5.6-luna"]);
    expect(cfg.workerModels).toEqual(["deepseek-v4-flash", "qwen3.5"]);
  });

  it("CSV edge cases: empty items dropped; all-empty falls back to defaults", () => {
    const cfg = loadDriverOrchestratorConfig({
      DRIVER_MODELS: "deepseek-v4-pro,,,gpt-5.6-luna,",
      WORKER_MODELS: " ,, ",
    });
    expect(cfg.driverModels).toEqual(["deepseek-v4-pro", "gpt-5.6-luna"]);
    expect(cfg.workerModels).toEqual(DEFAULT_WORKER_MODELS);
  });
});

describe("resolveAgentRole — precedence and matching", () => {
  it("precedence: hard_orchestrator > driver > worker > normal", () => {
    const cfg = loadDriverOrchestratorConfig({});
    // hard + driver -> hard
    expect(resolveAgentRole("openai-codex/gpt-5.6-sol", cfg, HARD)).toBe("hard_orchestrator");
    // driver + worker -> driver
    expect(resolveAgentRole("deepseek/deepseek-v4-pro", cfg, HARD)).toBe("driver");
    // worker only -> worker
    expect(resolveAgentRole(WORKER, cfg, HARD)).toBe("worker");
    // nothing matches -> normal
    expect(resolveAgentRole(TERRA, cfg, HARD)).toBe("normal");
  });

  it("driver models resolve by lowercase substring, provider-qualified or bare", () => {
    const cfg = loadDriverOrchestratorConfig({});
    expect(resolveAgentRole(DRIVER, cfg, HARD)).toBe("driver");
    expect(resolveAgentRole("deepseek-v4-pro", cfg, HARD)).toBe("driver");
    expect(resolveAgentRole(LUNA, cfg, HARD)).toBe("driver");
    expect(resolveAgentRole("openai-codex/GPT-5.6-LUNA", cfg, HARD)).toBe("driver"); // case-insensitive
    expect(resolveAgentRole("openai-codex/gpt-6-astra", cfg, HARD)).toBe("driver");
  });

  it("keeps an explicit driver allowlist authoritative for Astra", () => {
    const cfg = loadDriverOrchestratorConfig({ DRIVER_MODELS: "deepseek-v4-pro" });
    expect(resolveAgentRole("openai-codex/gpt-6-astra", cfg, HARD)).toBe("normal");
  });

  it("worker models resolve by lowercase substring, provider-qualified or bare", () => {
    const cfg = loadDriverOrchestratorConfig({});
    expect(resolveAgentRole(WORKER, cfg, HARD)).toBe("worker");
    expect(resolveAgentRole("deepseek-v4-flash", cfg, HARD)).toBe("worker");
    expect(resolveAgentRole(LOCAL, cfg, HARD)).toBe("worker"); // qwen3.5 substring inside lemonade/Qwen3.5-...
  });

  it("negatives: flash is NEVER driver, pro is NEVER hard, substrings do not cross-match", () => {
    const cfg = loadDriverOrchestratorConfig({});
    expect(resolveAgentRole(WORKER, cfg, HARD)).not.toBe("driver");
    expect(resolveAgentRole(DRIVER, cfg, HARD)).not.toBe("hard_orchestrator");
    // "deepseek-v4-pro" is not contained in "deepseek-v4-flash" and vice versa
    expect("deepseek-v4-flash".includes("deepseek-v4-pro")).toBe(false);
    expect("deepseek-v4-pro".includes("deepseek-v4-flash")).toBe(false);
    expect(resolveAgentRole("deepseek/deepseek-v4-flash", cfg, HARD)).not.toBe("driver");
    // a shorter driver substring like "gpt-5.6" must not match terra via the SOL substring
    expect(TERRA.includes("gpt-5.6-sol")).toBe(false);
  });

  it("unknown models and blank/null ids -> normal", () => {
    const cfg = loadDriverOrchestratorConfig({});
    expect(resolveAgentRole(TERRA, cfg, HARD)).toBe("normal");
    expect(resolveAgentRole(CLAUDE, cfg, HARD)).toBe("normal");
    expect(resolveAgentRole(undefined, cfg, HARD)).toBe("normal");
    expect(resolveAgentRole(null, cfg, HARD)).toBe("normal");
    expect(resolveAgentRole("", cfg, HARD)).toBe("normal");
    expect(resolveAgentRole("   ", cfg, HARD)).toBe("normal");
  });

  it("custom hardModels from the guard config take precedence over drivers", () => {
    const cfg = loadDriverOrchestratorConfig({
      DRIVER_MODELS: "gpt-5.6-sol,deepseek-v4-pro",
      WORKER_MODELS: "deepseek-v4-flash",
    });
    // Sol listed as driver too, but the hard list wins
    expect(resolveAgentRole(SOL, cfg, HARD)).toBe("hard_orchestrator");
    expect(resolveAgentRole(DRIVER, cfg, HARD)).toBe("driver");
  });
});

describe("appendDriverContract", () => {
  it("appends the contract once, after the base, with the marker", () => {
    const base = "BASE SYSTEM PROMPT";
    const result = appendDriverContract(base);
    expect(result).toBeDefined();
    expect(result!.startsWith("BASE SYSTEM PROMPT\n\n")).toBe(true);
    expect(result!).toContain(DRIVER_CONTRACT_MARKER);
    // second append on the SAME result is a no-op (dedup by marker)
    expect(appendDriverContract(result)).toBe(result);
  });

  it("marker dedup: base already containing the marker is returned unchanged", () => {
    const base = `BASE\n\n[${DRIVER_CONTRACT_MARKER}] already injected`;
    expect(appendDriverContract(base)).toBe(base);
  });

  it("undefined/empty base -> undefined (never invents a prompt)", () => {
    expect(appendDriverContract(undefined)).toBeUndefined();
    expect(appendDriverContract("")).toBeUndefined();
    expect(appendDriverContract("   ")).toBeUndefined();
  });
});

describe("DRIVER_ORCHESTRATOR_CONTRACT content", () => {
  it("first line carries the marker", () => {
    expect(DRIVER_ORCHESTRATOR_CONTRACT.split("\n")[0]).toContain(DRIVER_CONTRACT_MARKER);
  });

  it("states the required behaviors", () => {
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/execute directly/i); // trivial -> direct
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/delegate the bulk of execution-heavy work/i); // substantial -> delegate
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/at most 2/i); // max concurrency 2
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/never wait for the user/i); // proactive orchestration
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/cheapest competent worker/i); // worker selection
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/do NOT inherit the driver role/i); // anti-recursion
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/must NOT orchestrate/i); // anti-recursion
  });

  it("P3-H: contract carries the STOP-at-completion rule (§15.4)", () => {
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/STOP/i);
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/Requirement Ledger/);
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/material gate/);
    expect(DRIVER_ORCHESTRATOR_CONTRACT).toMatch(/never spawn "one more"/i);
  });

  it("word count <= 230", () => {
    const words = DRIVER_ORCHESTRATOR_CONTRACT.split(/\s+/).filter((w) => w.length > 0);
    expect(words.length).toBeLessThanOrEqual(230);
  });
});
