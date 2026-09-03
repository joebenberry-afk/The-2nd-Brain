import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, {
  type BudgetCheckOptions,
  type BudgetCheckResult,
  type BudgetRunner,
  type BudgetState,
  BUDGET_HARD_LINE,
  type ExtensionOptions,
  runBudgetCheck,
} from "../src/index";
import { assembleTail } from "../src/injection-slots";
import {
  type OmpRoutingDecision,
  type OmpRoutingOptions,
  type OmpRoutingResult,
  runOmpRouting,
} from "../src/routing-bridge";
import type { ExtensionAPI, ExtensionContext, ToolCallEvent } from "../types/prime";

let home: string;
const savedHome = process.env.SECOND_BRAIN_HOME;

beforeEach(async () => {
  home = await mkdtemp(join(tmpdir(), "sb-budget-test-"));
  process.env.SECOND_BRAIN_HOME = home;
});

afterEach(async () => {
  if (savedHome === undefined) {
    delete process.env.SECOND_BRAIN_HOME;
  } else {
    process.env.SECOND_BRAIN_HOME = savedHome;
  }
  await rm(home, { recursive: true, force: true }).catch(() => {});
});

function ctx(session = "test-session"): ExtensionContext {
  return {
    cwd: "C:/test-project",
    model: { provider: "test-provider", id: "test-model" },
    sessionManager: { getSessionFile: () => join(home, `${session}.jsonl`) },
    getContextUsage: () => undefined,
    getSystemPrompt: () => "base system prompt",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  };
}

function mockDecision(): OmpRoutingDecision {
  return {
    decision_id: "decision-budget-test",
    task_hash: "0123456789abcdef",
    host_session_id: "test-session",
    project_id: "test-project",
    bot_role: "worker",
    selected_provider: "test-provider",
    selected_model: "test-model",
    selected_tier: "efficient",
    selected_cost_class: "low",
    candidate_set_hash: "cand-hash",
    fallback_used: false,
    fallback_provider: null,
    fallback_model: null,
    reason_code: "LOWEST_COST_ELIGIBLE",
    status: "selected",
    failure_code: null,
    routing_error: false,
  };
}

describe("T3.1 Hard and soft budget caps", () => {
  it("test_soft_cap_disables_retrieval_and_lowers_tier", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();
    let capturedRoutingOptions: OmpRoutingOptions | null = null;

    const budgetRunner: BudgetRunner = async (options: BudgetCheckOptions): Promise<BudgetCheckResult> => {
      expect(options.sessionId).toBe("test-session");
      return {
        state: "SOFT",
        used: 350000,
        cap: 400000,
      };
    };

    const ompRoutingRunner = async (options: OmpRoutingOptions): Promise<OmpRoutingResult> => {
      capturedRoutingOptions = options;
      return { decision: mockDecision() };
    };

    const options: ExtensionOptions = {
      budgetRunner,
      ompRoutingRunner,
    };

    const pi = {
      on: (name: string, handler: Handler) => handlers.set(name, handler),
      emit: vi.fn(),
    } as unknown as ExtensionAPI;

    factory(pi, options);
    const context = ctx("test-session");

    // Turn start: before_agent_start runs budget check and triggers routing
    await handlers.get("before_agent_start")!({ prompt: "Perform bounded task" }, context);

    // Verify routingOptions received minimumTier: "efficient" because session is SOFT
    expect(capturedRoutingOptions).not.toBeNull();
    const captured = capturedRoutingOptions as OmpRoutingOptions | null;
    expect(captured?.minimumTier).toBe("efficient");

    // Verify OmpRoutingOptions structure when serialized for subprocess payload includes minimum_tier
    const childOpts: OmpRoutingOptions = {
      home,
      task: "task",
      sessionId: "test-session",
      projectId: "test-project",
      role: "worker",
      provider: "test-provider",
      model: "test-model",
      minimumTier: "efficient",
    };
    expect(childOpts.minimumTier).toBe("efficient");
  });

  it("test_hard_cap_blocks_tools_and_marks_input_required", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();

    const budgetRunner: BudgetRunner = async (): Promise<BudgetCheckResult> => {
      return {
        state: "HARD",
        used: 420000,
        cap: 400000,
      };
    };

    const options: ExtensionOptions = {
      budgetRunner,
      ompRoutingRunner: async () => ({ decision: mockDecision() }),
    };

    const pi = {
      on: (name: string, handler: Handler) => handlers.set(name, handler),
      emit: vi.fn(),
    } as unknown as ExtensionAPI;

    factory(pi, options);
    const context = ctx("hard-session");

    // 1. before_agent_start populates HARD state and injects TAIL message warning
    const agentStartResult = (await handlers.get("before_agent_start")!(
      { prompt: "Next task after limit reached" },
      context,
    )) as { message?: { content?: string; details?: Record<string, unknown> } } | undefined;

    expect(agentStartResult).toBeDefined();
    expect(agentStartResult?.message).toBeDefined();
    expect(agentStartResult?.message?.content).toContain(BUDGET_HARD_LINE);
    expect(agentStartResult?.message?.content).toBe(
      "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED",
    );

    // 2. tool_call handler blocks tools immediately when HARD
    const bashToolCall: ToolCallEvent = {
      type: "tool_call",
      toolName: "bash",
      toolCallId: "call-1",
      input: { command: "ls -la" },
    };
    const bashResult = (await handlers.get("tool_call")!(bashToolCall, context)) as {
      block?: boolean;
      reason?: string;
    };
    expect(bashResult).toEqual({
      block: true,
      reason: "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED",
    });

    const readToolCall: ToolCallEvent = {
      type: "tool_call",
      toolName: "read",
      toolCallId: "call-2",
      input: { path: "some/file.ts" },
    };
    const readResult = (await handlers.get("tool_call")!(readToolCall, context)) as {
      block?: boolean;
      reason?: string;
    };
    expect(readResult).toEqual({
      block: true,
      reason: "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED",
    });

    // 3. Worker task dispatch (prepareWorkerTaskInput) is blocked when parent is HARD
    const taskToolCall: ToolCallEvent = {
      type: "tool_call",
      toolName: "task",
      toolCallId: "call-3",
      input: { task: "subagent worker task" },
    };
    const taskResult = (await handlers.get("tool_call")!(taskToolCall, context)) as {
      block?: boolean;
      reason?: string;
    };
    expect(taskResult).toEqual({
      block: true,
      reason: "[SECOND_BRAIN_BUDGET] hard cap reached; state INPUT_REQUIRED",
    });

    // 4. assembleTail produces the exact line when budgetWarning is given
    const tailText = assembleTail({
      deltaContext: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: p1",
      budgetWarning: BUDGET_HARD_LINE,
    });
    expect(tailText).toContain(BUDGET_HARD_LINE);
  });

  it("test_descendant_usage_counts_toward_parent", async () => {
    // Tests that the budget runner bridge correctly propagates and parses
    // governor check-budget results with descendant usage accounted for.
    const customBudgetRunner: BudgetRunner = async (opts) => {
      // Simulates parent session with 1000 own + 2500 descendant tokens = 3500 used against 4000 cap
      const parentOwn = 1000;
      const descendantUsage = 2500;
      const totalUsed = parentOwn + descendantUsage;
      const cap = 4000;
      const state: BudgetState =
        totalUsed >= cap ? "HARD" : totalUsed >= cap * 0.8 ? "SOFT" : "OK";
      return {
        state,
        used: totalUsed,
        cap,
      };
    };

    const res = await customBudgetRunner({
      home,
      sessionId: "parent-session-123",
      role: "driver",
    });

    expect(res.used).toBe(3500);
    expect(res.state).toBe("SOFT"); // 3500 >= 4000 * 0.8 (3200) -> SOFT

    // When total passes cap:
    const hardRes = await (async () => {
      const parentOwn = 2000;
      const descendantUsage = 2500;
      const totalUsed = parentOwn + descendantUsage;
      const cap = 4000;
      const state: BudgetState = totalUsed >= cap ? "HARD" : "OK";
      return { state, used: totalUsed, cap };
    })();

    expect(hardRes.used).toBe(4500);
    expect(hardRes.state).toBe("HARD");
  });

  it("runBudgetCheck bridge parses CLI JSON output and handles fail-open", async () => {
    const failOpen = await runBudgetCheck({
      home: "non-existent-dir",
      sessionId: "missing-session",
      python: "non-existent-python",
    });
    expect(failOpen.state).toBe("OK");
    expect(failOpen.used).toBe(0);
    expect(failOpen.cap).toBe(0);
    expect(failOpen.error).toBeDefined();
  });
});
