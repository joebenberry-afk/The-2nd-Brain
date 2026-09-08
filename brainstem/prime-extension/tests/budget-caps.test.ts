import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, {
  type BudgetCheckResult,
  type BudgetRunner,
  BUDGET_HARD_LINE,
  type ExtensionOptions,
  runBudgetCheck,
} from "../src/index";
import {
  type OmpRoutingDecision,
} from "../src/routing-bridge";
import type { ExtensionAPI, ExtensionContext, ToolCallEvent } from "../types/prime";
import { TelemetryStore } from "../src/storage";

let home: string;
const savedHome = process.env.SECOND_BRAIN_HOME;
const stores = new Set<TelemetryStore>();
const appendTelemetry = TelemetryStore.prototype.append;

beforeEach(async () => {
  home = await mkdtemp(join(tmpdir(), "sb-budget-test-"));
  process.env.SECOND_BRAIN_HOME = home;
  vi.spyOn(TelemetryStore.prototype, "append").mockImplementation(function (this: TelemetryStore, record) {
    stores.add(this);
    appendTelemetry.call(this, record);
  });
});

afterEach(async () => {
  await Promise.all([...stores].map((store) => store.flush()));
  stores.clear();
  vi.restoreAllMocks();
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

  });


  it("runBudgetCheck bridge parses CLI JSON output and handles fail-open", async () => {
    const failOpen = await runBudgetCheck({
      home: "non-existent-dir",
      sessionId: "missing-session",
      python: "non-existent-python",
    });
    expect(failOpen.state).toBe("OK");
    expect(failOpen.used).toBeNull();
    expect(failOpen.error).toBeDefined();
  });

  it("replaces stale HARD after complete or degraded accounting without leaking roots", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();
    let next: BudgetCheckResult = { state: "HARD", used: 400001, cap: 400000 };
    const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler) } as unknown as ExtensionAPI;
    factory(pi, { budgetRunner: async () => next, ompRoutingRunner: async () => ({ decision: mockDecision() }) });
    const rootA = ctx("root-A");
    const rootB = ctx("root-B");
    const task = { prompt: "Check the current budget boundary" };
    const read = { type: "tool_call", toolName: "read", toolCallId: "check-read", input: { path: "src/file.ts" } };
    await handlers.get("before_agent_start")!(task, rootA);
    expect(await handlers.get("tool_call")!(read, rootA)).toMatchObject({ block: true });
    next = { state: "OK", used: 10, cap: 400000 };
    await handlers.get("before_agent_start")!(task, rootB);
    expect(await handlers.get("tool_call")!(read, rootB)).toBeUndefined();
    expect(await handlers.get("tool_call")!(read, rootA)).toMatchObject({ block: true });
    await handlers.get("before_agent_start")!(task, rootA);
    expect(await handlers.get("tool_call")!(read, rootA)).toBeUndefined();
    next = { state: "HARD", used: 400001, cap: 400000 };
    await handlers.get("before_agent_start")!(task, rootA);
    next = { state: "OK", used: null, cap: 400000, error: "ACCOUNTING_UNAVAILABLE" };
    await handlers.get("before_agent_start")!(task, rootA);
    expect(await handlers.get("tool_call")!(read, rootA)).toBeUndefined();
  });
});
