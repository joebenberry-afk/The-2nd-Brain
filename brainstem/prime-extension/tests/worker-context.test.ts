import { describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import {
  parseOmpWorkerContextOutput,
  renderOmpWorkerContext,
  type OmpWorkerContextHandoff,
  type OmpWorkerContextOptions,
  type OmpWorkerContextResult,
} from "../src/worker-context-bridge";
import { parseOmpWorkerCallbackOutput } from "../src/worker-lifecycle-bridge";
import type { AsyncJobLifecycleObservation, ExtensionAPI, ExtensionContext } from "../types/prime";

const contextHandoff: OmpWorkerContextHandoff = {
  mode: "full",
  resolved_context: [
    {
      ref: "memory:mem-worker",
      kind: "memory",
      content: "Brain-owned child context",
      content_sha256: "a".repeat(64),
      content_chars: 28,
      truncated: false,
    },
  ],
  context_delta: { changed_refs: [], removed_ref_hashes: [], jit_delta: "" },
  context_fingerprint: "b".repeat(64),
  jit_context: "# Task\n\nInspect the bounded seam",
};

function contextResult(mode: "full" | "unchanged" | "delta" = "full"): OmpWorkerContextResult {
  const handoff: OmpWorkerContextHandoff =
    mode === "full"
      ? contextHandoff
      : mode === "unchanged"
        ? { ...contextHandoff, mode, resolved_context: [], jit_context: "" }
        : {
            ...contextHandoff,
            mode,
            resolved_context: [],
            context_delta: {
              changed_refs: [{ ref: "memory:mem-worker", content: "Changed Brain context" }],
              removed_ref_hashes: [],
              jit_delta: "+++ changed",
            },
            jit_context: "",
          };
  return {
    ok: true,
    taskId: "omp-task-1",
    packetSha256: "c".repeat(64),
    attemptId: "attempt-1",
    projectId: "default",
    worktreeId: null,
    accessIntent: "read_only",
    contextHandoff: handoff,
    contextMetadata: {
      mode,
      reused: mode === "unchanged",
      cache_hit: mode === "unchanged",
      resolved_count: mode === "full" ? 1 : 0,
      context_fingerprint: "b".repeat(64),
      context_handoff_bytes: mode === "full" ? 500 : 80,
      context_handoff_tokens_estimate: mode === "full" ? 125 : 20,
      context_delta_bytes: mode === "delta" ? 120 : 0,
      context_delta_tokens_estimate: mode === "delta" ? 30 : 0,
    },
  };
}

function contextResultForRequest(
  options: OmpWorkerContextOptions,
  mode: "full" | "unchanged" | "delta" = "full",
): OmpWorkerContextResult {
  return {
    ...contextResult(mode),
    taskId: options.taskId,
    projectId: options.projectId,
    worktreeId: options.accessIntent === "mutating" ? "worktree-1" : null,
    accessIntent: options.accessIntent,
    ...(options.accessIntent === "mutating" ? { callbackToken: "callback-token-1" } : {}),
  };
}

function ctx(): ExtensionContext {
  return {
    cwd: "C:/omp-project",
    model: { provider: "openai-codex", id: "gpt-5.6-luna" },
    sessionManager: { getSessionFile: () => "C:/omp-project/omp-session.jsonl" },
    getContextUsage: () => undefined,
    getSystemPrompt: () => "base",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  };
}

function rewrittenTask(result: unknown): string {
  if (
    !result ||
    typeof result !== "object" ||
    !("input" in result) ||
    !result.input ||
    typeof result.input !== "object" ||
    !("task" in result.input) ||
    typeof result.input.task !== "string"
  ) {
    throw new Error("Expected rewritten task input");
  }
  return result.input.task;
}

describe("OMP worker Context Capsule bridge", () => {
  it("parses bounded Brain handoff metadata and renders no parent transcript", () => {
    const parsed = parseOmpWorkerContextOutput(JSON.stringify({
      status: "prepared",
      task_id: "omp-task-1",
      packet_sha256: "c".repeat(64),
      attempt_id: "attempt-1",
      project_id: "default",
      worktree_id: null,
      access_intent: "read_only",
      context_metadata: contextResult().contextMetadata,
      context_handoff: contextHandoff,
    }));
    expect(parsed.ok).toBe(true);
    const rendered = renderOmpWorkerContext(parsed.contextHandoff!);
    expect(rendered).toContain("Brain-owned child context");
    expect(rendered).not.toContain("parent transcript");
  });

  it("rewrites the real task tool input before child dispatch", async () => {
    const runner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    const options: ExtensionOptions = { ompWorkerContextRunner: runner };
    factory(pi, options);

    const result = await handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-1",
        input: { agent: "task", task: "Inspect the bounded seam", access_intent: "read_only" },
      },
      ctx(),
    );

    expect(runner).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ input: { agent: "task", access_intent: "read_only" } });
    expect(rewrittenTask(result)).toContain("Brain-owned child context");
  });

  it("does not resend unchanged context and sends only a delta after change", async () => {
    const modes: Array<"full" | "unchanged" | "delta"> = ["full", "unchanged", "delta"];
    const runner = vi.fn(async (options: OmpWorkerContextOptions) =>
      contextResultForRequest(options, modes.shift() ?? "full"));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });
    const event = {
      toolName: "task",
      toolCallId: "task-call-modes",
      input: { agent: "task", task: "Inspect the bounded seam", access_intent: "read_only" },
    };

    const full = await handlers.get("tool_call")!(event, ctx());
    const unchanged = await handlers.get("tool_call")!(event, ctx());
    const delta = await handlers.get("tool_call")!(event, ctx());
    const fullTask = rewrittenTask(full);
    const unchangedTask = rewrittenTask(unchanged);
    const deltaTask = rewrittenTask(delta);

    expect(runner).toHaveBeenCalledTimes(3);
    expect(fullTask).toContain("Brain-owned child context");
    expect(unchangedTask).not.toContain("Brain-owned child context");
    expect(deltaTask).toContain("Changed Brain context");
    expect(deltaTask).not.toContain("Brain-owned child context");
  });

  it("blocks task dispatch when Brain context preparation fails", async () => {
    const runner = vi.fn(async () => ({ ok: false, error: "CONTEXT_REF_UNRESOLVED" }));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });

    const result = await handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-fail",
        input: { task: "Needs Brain context", access_intent: "read_only" },
      },
      ctx(),
    );

    expect(result).toEqual({ block: true, reason: "CONTEXT_REF_UNRESOLVED" });
  });

  it("requires an explicit access intent", async () => {
    const runner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });

    const result = await handlers.get("tool_call")!(
      { toolName: "task", toolCallId: "task-call-no-intent", input: { task: "Ambiguous attempt" } },
      ctx(),
    );

    expect(result).toEqual({ block: true, reason: "BRAIN_WORKER_ACCESS_INTENT_REQUIRED" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("fails closed before mutating admission without lifecycle observation", async () => {
    const runner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });

    const result = await handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-mutating",
        input: { task: "Mutate", access_intent: "mutating" },
      },
      ctx(),
    );

    expect(result).toEqual({ block: true, reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("binds exact native identity and releases only after executor cleanup persistence", async () => {
    const contextRunner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const bindRunner: NonNullable<ExtensionOptions["ompWorkerBindRunner"]> = vi.fn(async (options) => ({
      ok: true,
      status: "accepted" as const,
      taskId: options.taskId,
      attemptId: options.attemptId,
    }));
    const lifecycleRunner: NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]> = vi.fn(async (options) => ({
      ok: true,
      status: "accepted" as const,
      taskId: options.taskId,
      attemptId: options.attemptId,
      sequence: options.sequence,
    }));
    const resultRunner = vi.fn(async () => ({ ok: true }));
    let observer: ((observation: Readonly<AsyncJobLifecycleObservation>) => boolean | Promise<boolean>) | undefined;
    const disposeObserver = vi.fn();
    const context = ctx();
    context.observeAsyncJobLifecycle = (callback) => {
      observer = callback;
      return disposeObserver;
    };
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, {
      ompWorkerContextRunner: contextRunner,
      ompWorkerBindRunner: bindRunner,
      ompWorkerLifecycleRunner: lifecycleRunner,
      ompWorkerResultRunner: resultRunner,
    });

    const prepared = await handlers.get("tool_call")!({
      toolName: "task",
      toolCallId: "mutating-attempt",
      input: { task: "Mutate", access_intent: "mutating" },
    }, context);
    expect(prepared).toMatchObject({ input: { access_intent: "mutating" } });
    expect(observer).toBeDefined();
    const base: AsyncJobLifecycleObservation = {
      jobId: "native-job-1",
      generation: 7,
      nativeAttemptId: "native-attempt-1",
      type: "task",
      agentId: "Worker",
      sourceToolCallId: "mutating-attempt",
      sourceIndex: 0,
      status: "running",
      executorSettled: false,
      cleanupComplete: false,
      revision: 1,
    };

    await expect(Promise.resolve(observer!(base))).resolves.toBe(true);
    await expect(Promise.resolve(observer!({
      ...base,
      status: "completed",
      executorSettled: true,
      revision: 2,
    }))).resolves.toBe(true);
    expect(resultRunner).toHaveBeenCalledTimes(1);
    expect(disposeObserver).not.toHaveBeenCalled();
    await expect(Promise.resolve(observer!({
      ...base,
      status: "completed",
      executorSettled: true,
      cleanupComplete: true,
      revision: 3,
    }))).resolves.toBe(true);

    expect(bindRunner).toHaveBeenCalledTimes(1);
    expect(lifecycleRunner).toHaveBeenCalledTimes(3);
    expect(lifecycleRunner).toHaveBeenLastCalledWith(expect.objectContaining({
      hostGeneration: 7,
      nativeAttemptId: "native-attempt-1",
      nativeJobId: "native-job-1",
      cleanupComplete: true,
    }));
    expect(disposeObserver).toHaveBeenCalledTimes(1);
  });
});

describe("OMP worker lifecycle callback bridge", () => {
  it("accepts only exact persisted attempt and lifecycle sequence receipts", () => {
    const accepted = parseOmpWorkerCallbackOutput(JSON.stringify({
      status: "accepted",
      task_id: "task-1",
      attempt_id: "attempt-1",
      lifecycle_sequence: 4,
      failure_code: null,
    }), { taskId: "task-1", attemptId: "attempt-1", sequence: 4 });
    const reused = parseOmpWorkerCallbackOutput(JSON.stringify({
      status: "accepted",
      task_id: "task-1",
      attempt_id: "old-attempt",
      lifecycle_sequence: 4,
    }), { taskId: "task-1", attemptId: "attempt-1", sequence: 4 });

    expect(accepted).toMatchObject({ ok: true, sequence: 4 });
    expect(reused).toEqual({ ok: false, error: "BRAIN_WORKER_CALLBACK_RECEIPT_MISMATCH" });
  });

  it("does not treat a rejected callback as persistence acknowledgement", () => {
    const rejected = parseOmpWorkerCallbackOutput(JSON.stringify({
      status: "rejected",
      task_id: "task-1",
      attempt_id: "attempt-1",
      failure_code: "STALE_HOST_GENERATION",
    }), { taskId: "task-1", attemptId: "attempt-1" });

    expect(rejected).toMatchObject({
      ok: false,
      status: "rejected",
      failureCode: "STALE_HOST_GENERATION",
    });
  });
});
