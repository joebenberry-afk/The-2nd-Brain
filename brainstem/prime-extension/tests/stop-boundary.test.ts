import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import factory from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";
import { describe, expect, it, vi } from "vitest";
import {
  STOP_CONTROL_COMMAND,
  StopBoundaryState,
  parseStopDecisionOutput,
  rewriteSessionPlaceholders,
  rewriteStopControlCommand,
} from "../src/stop-boundary";
describe("OMP STOP boundary", () => {
  it("parses bounded stop evidence and preserves task identities", () => {
    const parsed = parseStopDecisionOutput(JSON.stringify({
      decision: "stop",
      stop_id: "stop-abc123",
      task_id: "task-1",
      session_id: "worker-session",
      parent_session_id: "parent-session",
      worker_session_id: "worker-session",
      reason_code: "completion_proven",
      triggering_condition: "completion_condition_satisfied",
      verification_state: "passed",
      completion_condition_state: "satisfied",
      final_substantive_event: "task_result",
      continuation_forbidden: true,
    }) + "\n\nWall time: 0.33 seconds");

    expect(parsed).toEqual(expect.objectContaining({
      decision: "stop",
      stop_id: "stop-abc123",
      task_id: "task-1",
      parent_session_id: "parent-session",
      worker_session_id: "worker-session",
      continuation_forbidden: true,
    }));
  });

  it("blocks substantive calls after STOP but allows bounded finalization", () => {
    const state = new StopBoundaryState();
    state.accept({
      decision: "stop",
      stop_id: "stop-1",
      task_id: "task-1",
      session_id: "session-1",
      parent_session_id: "",
      worker_session_id: "",
      reason_code: "completion_proven",
      triggering_condition: "completion_condition_satisfied",
      verification_state: "passed",
      completion_condition_state: "satisfied",
      final_substantive_event: "message_end",
      continuation_forbidden: true,
    });

    expect(state.shouldBlock("read")).toBe(true);
    expect(state.shouldBlock("bash")).toBe(true);
    expect(state.shouldBlock("task")).toBe(true);
    expect(state.shouldBlock("session_shutdown")).toBe(false);
    expect(state.shouldBlock("yield")).toBe(false);
    expect(state.shouldBlock("telemetry")).toBe(false);
  });

  it("does not arm on unresolved completion evidence", () => {
    const state = new StopBoundaryState();
    const parsed = parseStopDecisionOutput(JSON.stringify({
      decision: "continue",
      stop_id: "stop-2",
      task_id: "task-2",
      session_id: "session-2",
      parent_session_id: "",
      worker_session_id: "",
      reason_code: "requirements_unresolved",
      triggering_condition: "material_requirement_unverified",
      verification_state: "passed",
      completion_condition_state: "unresolved",
      final_substantive_event: "message_end",
      continuation_forbidden: false,
    }));

    expect(parsed?.decision).toBe("continue");
    state.accept(parsed!);
    expect(state.shouldBlock("bash")).toBe(false);
  });

  it("recognizes only the bounded STOP control command", () => {
    expect(STOP_CONTROL_COMMAND.test("brainctl stop decide --json")).toBe(true);
    expect(STOP_CONTROL_COMMAND.test("python -m second_brain stop decide --json")).toBe(true);
    expect(STOP_CONTROL_COMMAND.test("python -m second_brain requirements check s1")).toBe(false);
    expect(
      rewriteStopControlCommand(
        "brainctl stop decide --session current --worker-session-id current --json",
        "actual-session",
      ),
    ).toContain("--session actual-session");
    expect(
      rewriteStopControlCommand(
        "brainctl stop decide --session current --parent-session-id current --worker-session-id current --json",
        "worker-session",
        "parent-session",
      ),
    ).toContain("--parent-session-id parent-session");
    expect(
      rewriteSessionPlaceholders(
        "python -m second_brain requirements add current task --importance critical",
        "actual-session",
      ),
    ).toContain("requirements add actual-session");
  });
});

it("blocks later OMP tool calls after a real STOP control result", async () => {
  const home = mkdtempSync(join(tmpdir(), "second-brain-stop-"));
  const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
  const pi = {
    on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => {
      handlers.set(name, handler);
    },
  } as unknown as ExtensionAPI;
  const context: ExtensionContext = {
    cwd: home,
    model: { provider: "openai-codex", id: "gpt-5.6-luna" },
    sessionManager: { getSessionFile: () => `${home}/session.jsonl` },
    getContextUsage: () => undefined,
    getSystemPrompt: () => "base",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  };
  factory(pi);

  const command = "brainctl stop decide --session worker-1 --task-id task-1 --json";
  await handlers.get("tool_call")!(
    { toolName: "bash", toolCallId: "stop-call", input: { command } },
    context,
  );
  await handlers.get("tool_result")!(
    {
      toolName: "bash",
      toolCallId: "stop-call",
      input: { command },
      content: [{
        text: JSON.stringify({
          decision: "stop",
          stop_id: "stop-1",
          task_id: "task-1",
          session_id: "worker-1",
          parent_session_id: "parent-1",
          worker_session_id: "worker-1",
          reason_code: "completion_proven",
          triggering_condition: "completion_condition_satisfied",
          verification_state: "passed",
          completion_condition_state: "satisfied",
          final_substantive_event: "task_result",
          continuation_forbidden: true,
        }),
      }],
      details: {},
      isError: false,
    },
    context,
  );

  expect(
    handlers.get("tool_call")!(
      { toolName: "read", toolCallId: "after-stop", input: { path: "unrelated" } },
      context,
    ),
  ).toEqual({ block: true, reason: "Second Brain STOP boundary is active" });
  vi.unstubAllEnvs();
});
