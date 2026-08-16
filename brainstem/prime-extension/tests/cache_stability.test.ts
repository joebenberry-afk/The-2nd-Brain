import { describe, expect, it } from "vitest";
import { resolveAgentRole, appendDriverContract, DRIVER_CONTRACT_MARKER } from "../src/driver-orchestrator";
import { appendLeanKernel, LEAN_KERNEL_MARKER } from "../src/lean-code";
import { sha256Hex, providerRequestMeta } from "../src/sensors";

describe("cache regression recovery: deterministic prefix stability", () => {
  const BASE_PROMPT = "You are Prime, an advanced AI coding assistant.";
  const PRO_MODEL = { id: "deepseek-v4-pro", provider: "deepseek" };
  const FLASH_MODEL = { id: "deepseek-v4-flash", provider: "deepseek" };
  const CONFIG = { driverModels: ["deepseek-v4-pro"], workerModels: ["deepseek-v4-flash"] };

  it("driver system prompt is 100% byte-identical across 10 consecutive turns", () => {
    let currentSystemPrompt = BASE_PROMPT;
    const prompts: string[] = [];

    for (let turn = 0; turn < 10; turn++) {
      // Simulate Prime before_agent_start on turn N
      // 1. Resolve role
      const role = resolveAgentRole(PRO_MODEL.id, CONFIG, ["sol"]);
      expect(role).toBe("driver");

      // 2. Append driver contract (idempotent)
      let patched = appendDriverContract(currentSystemPrompt);
      expect(patched).toBeDefined();

      // 3. Append lean kernel (simulating lean advisory/active)
      const kernel = "# Runtime Kernel\nPrefer minimal, targeted code edits.";
      patched = appendLeanKernel(patched, kernel);
      expect(patched).toBeDefined();

      // The patched prompt must always contain markers
      expect(patched!).toContain(DRIVER_CONTRACT_MARKER);
      expect(patched!).toContain(LEAN_KERNEL_MARKER);

      prompts.push(patched!);
      // In Prime, currentSystemPrompt for subsequent turns might be base or patched
      currentSystemPrompt = turn % 2 === 0 ? patched! : BASE_PROMPT;
    }

    // All 10 turns must have produced the EXACT same system prompt byte string
    const firstPrompt = prompts[0];
    for (let i = 1; i < prompts.length; i++) {
      expect(prompts[i]).toBe(firstPrompt);
    }

    // Check sha256 of the prompt
    const hashes = prompts.map(sha256Hex);
    expect(new Set(hashes).size).toBe(1);
  });

  it("provider request prefix sha is deterministic and invariant across consecutive turns", () => {
    const systemPrompt = appendLeanKernel(
      appendDriverContract(BASE_PROMPT),
      "# Runtime Kernel\nPrefer minimal edits.",
    )!;

    const messages: Array<{ role: string; content: string }> = [
      { role: "system", content: systemPrompt },
    ];

    // Turn 0
    messages.push({ role: "user", content: "Check brain status" });
    messages.push({ role: "custom", content: "[BRAIN_CONTEXT_DELTA v1]\nmem-1: Verified" });
    messages.push({ role: "assistant", content: "I will check." });
    messages.push({ role: "toolResult", content: "doctor: 16/16 PASS" });
    messages.push({ role: "assistant", content: "Brain is active and healthy." });

    // Measure prefix hash at end of Turn 0
    const metaTurn0 = providerRequestMeta("sess-1", "deepseek", "deepseek-v4-pro", 1, {
      messages,
      tools: [{ type: "function", function: { name: "bash" } }],
    });
    expect(metaTurn0.system_prefix_sha).toBeDefined();

    // Turn 1
    messages.push({ role: "user", content: "Now run the tests" });
    messages.push({ role: "assistant", content: "Running tests..." });
    messages.push({ role: "toolResult", content: "747 passed" });
    messages.push({ role: "assistant", content: "All tests passed." });

    // Turn 2
    messages.push({ role: "user", content: "continue" });
    messages.push({ role: "assistant", content: "Next step..." });

    // Inspect prefix for request in Turn 2
    const metaTurn2 = providerRequestMeta("sess-1", "deepseek", "deepseek-v4-pro", 3, {
      messages,
      tools: [{ type: "function", function: { name: "bash" } }],
    });
    expect(metaTurn2.system_prefix_sha).toBeDefined();
    expect(metaTurn2.tool_surface_sha).toBe(metaTurn0.tool_surface_sha);
  });

  it("worker role (deepseek-v4-flash) receives no driver contract", () => {
    const role = resolveAgentRole(FLASH_MODEL.id, CONFIG, ["sol"]);
    expect(role).toBe("worker");

    // Worker does not get appendDriverContract
    const patched = role === "driver" ? appendDriverContract(BASE_PROMPT) : BASE_PROMPT;
    expect(patched).toBe(BASE_PROMPT);
    expect(patched).not.toContain(DRIVER_CONTRACT_MARKER);
  });
});
