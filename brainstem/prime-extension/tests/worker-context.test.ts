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

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

/** ES2022 lib has no `Promise.withResolvers`, so tests build the deferred locally. */
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

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
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    cwd: "C:/omp-project",
    model: { provider: "openai-codex", id: "gpt-5.6-luna" },
    sessionManager: {
      getSessionFile: () => "C:/omp-project/omp-session.jsonl",
      getSessionId: () => "native-omp-session",
      getHeader: () => ({ type: "session", version: 1, id: "native-omp-session", timestamp }),
      getEntries: () => [],
    },
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
        input: { agent: "scout", task: "Inspect the bounded seam", access_intent: "read_only" },
      },
      ctx(),
    );

    expect(runner).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ input: { agent: "scout", access_intent: "read_only" } });
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
      input: { agent: "scout", task: "Inspect the bounded seam", access_intent: "read_only" },
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
        input: { agent: "scout", task: "Needs Brain context", access_intent: "read_only" },
      },
      ctx(),
    );

    expect(result).toEqual({ block: true, reason: "CONTEXT_REF_UNRESOLVED" });
  });

  const dispatch = (input: unknown) => {
    const runner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });
    const context = ctx();
    context.observeAsyncJobLifecycle = () => () => {};
    return {
      runner,
      call: handlers.get("tool_call")!(
        { toolName: "task", toolCallId: "task-call-intent", input },
        context,
      ),
    };
  };

  it("derives a read-only intent for a read-only agent the harness cannot annotate", async () => {
    const { runner, call } = dispatch({ agent: "scout", task: "Inspect the seam" });
    const result = await call;

    expect(runner).toHaveBeenCalledTimes(1);
    expect(runner.mock.calls[0][0].accessIntent).toBe("read_only");
    expect(rewrittenTask(result)).toContain("Brain-owned child context");
  });

  it("derives a mutating intent for a mutating agent instead of demanding the absent field", async () => {
    const { runner, call } = dispatch({ agent: "task", task: "Mutate the seam" });
    const result = await call;

    expect(runner.mock.calls[0][0].accessIntent).toBe("mutating");
    expect(result).not.toEqual({ block: true, reason: "BRAIN_WORKER_ACCESS_INTENT_REQUIRED" });
    expect(rewrittenTask(result)).toContain("Brain-owned child context");
  });

  it("treats an omitted agent as the mutating spawn default", async () => {
    const { runner, call } = dispatch({ task: "Ordinary dispatch" });
    await call;

    expect(runner.mock.calls[0][0].accessIntent).toBe("mutating");
  });

  it("fails closed for an agent Brain has not classified", async () => {
    const { runner, call } = dispatch({ agent: "custom-worker", task: "Unknown surface" });

    expect(await call).toEqual({ block: true, reason: "BRAIN_WORKER_AGENT_UNCLASSIFIED" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("rejects an explicit read-only claim on a mutating worker rather than downgrading it", async () => {
    const { runner, call } = dispatch({
      agent: "task", task: "Mutate", access_intent: "read_only",
    });

    expect(await call).toEqual({ block: true, reason: "BRAIN_WORKER_ACCESS_INTENT_DOWNGRADE" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("escalates an explicit mutating request from a read-only agent", async () => {
    const { runner, call } = dispatch({
      agent: "scout", task: "Escalate", access_intent: "mutating",
    });
    await call;

    expect(runner.mock.calls[0][0].accessIntent).toBe("mutating");
  });

  it("escalates when a read-only agent is granted non-read-only capability", async () => {
    const { runner, call } = dispatch({
      agent: "scout", task: "Capability", tools: ["kernel_helper"],
    });
    await call;

    expect(runner.mock.calls[0][0].accessIntent).toBe("mutating");
  });

  it("keeps a read-only agent holding only read-only tools read-only", async () => {
    const { runner, call } = dispatch({ agent: "scout", task: "Inspect", tools: ["read", "grep"] });
    await call;

    expect(runner.mock.calls[0][0].accessIntent).toBe("read_only");
  });

  it("rejects an unrecognised explicit intent", async () => {
    const { runner, call } = dispatch({
      agent: "scout", task: "Invalid", access_intent: "write_only",
    });

    expect(await call).toEqual({ block: true, reason: "BRAIN_WORKER_ACCESS_INTENT_INVALID" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("still fails closed when no settlement source exists at all", async () => {
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

  it("admits mutating dispatch on a stock host and releases only after a post-finalization frame", async () => {
    const contextRunner = vi.fn(async (options: OmpWorkerContextOptions) =>
      contextResultForRequest(options));
    let bindOptions: Parameters<NonNullable<ExtensionOptions["ompWorkerBindRunner"]>>[0] | undefined;
    const bindRunner: NonNullable<ExtensionOptions["ompWorkerBindRunner"]> = vi.fn(async (options) => {
      bindOptions = options;
      return {
        ok: true,
        status: "accepted" as const,
        taskId: options.taskId,
        attemptId: options.attemptId,
      };
    });
    const lifecycleSeen = deferred<Parameters<NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]>>[0]>();
    const lifecycleRunner: NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]> = vi.fn(async (options) => {
      lifecycleSeen.resolve(options);
      return {
        ok: true,
        status: "accepted" as const,
        taskId: options.taskId,
        attemptId: options.attemptId,
        sequence: options.sequence,
      };
    });
    const subscribers = new Set<(payload: unknown) => void>();
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
      events: {
        on: (_channel: string, handler: (payload: unknown) => void) => {
          subscribers.add(handler);
          return () => subscribers.delete(handler);
        },
      },
    } as unknown as ExtensionAPI;
    factory(pi, {
      ompWorkerContextRunner: contextRunner,
      ompWorkerBindRunner: bindRunner,
      ompWorkerLifecycleRunner: lifecycleRunner,
    });
    const context = ctx();
    context.getAsyncJobSnapshot = () => ({
      running: [{ id: "WorkerA", type: "task", status: "running", agentId: "WorkerA" }],
      recent: [],
    });

    const result = await handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-stock",
        input: { agent: "task", task: "Mutate the seam" },
      },
      context,
    );

    expect(result).not.toEqual({ block: true, reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE" });
    expect(rewrittenTask(result)).toContain("Brain-owned child context");
    expect(lifecycleRunner).not.toHaveBeenCalled();
    expect(subscribers.size).toBe(1);

    for (const handler of subscribers) {
      handler({ id: "WorkerA", parentToolCallId: "task-call-stock", index: 0, status: "completed" });
    }
    const observed = await lifecycleSeen.promise;

    expect(bindRunner).toHaveBeenCalledTimes(1);
    expect(bindOptions).toMatchObject({ nativeJobId: "WorkerA", agentId: "WorkerA" });
    expect(observed).toMatchObject({
      outcome: "completed",
      executorSettled: true,
      // Stock hosts detach late cleanup and expose no completion signal, so the
      // default native path never claims cleanup it cannot prove.
      cleanupComplete: false,
      sequence: 1,
    });
  });

  const settlementHarness = (releaseLifecycle?: Promise<void>) => {
    const contextRunner = vi.fn(async (options: OmpWorkerContextOptions) =>
      contextResultForRequest(options));
    const boundAttempts: Array<Parameters<NonNullable<ExtensionOptions["ompWorkerBindRunner"]>>[0]> = [];
    const bindRunner: NonNullable<ExtensionOptions["ompWorkerBindRunner"]> = vi.fn(async options => {
      boundAttempts.push(options);
      return {
        ok: true,
        status: "accepted" as const,
        taskId: options.taskId,
        attemptId: options.attemptId,
      };
    });
    const lifecycleCalls: Array<Parameters<NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]>>[0]> = [];
    const lifecycleSettled = deferred<void>();
    const lifecycleRunner: NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]> = vi.fn(
      async options => {
        lifecycleCalls.push(options);
        lifecycleSettled.resolve();
        if (releaseLifecycle) await releaseLifecycle;
        return {
          ok: true,
          status: "accepted" as const,
          taskId: options.taskId,
          attemptId: options.attemptId,
          sequence: options.sequence,
        };
      },
    );
    const observers = new Set<(snapshot: unknown) => void>();
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) =>
        handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, {
      ompWorkerContextRunner: contextRunner,
      ompWorkerBindRunner: bindRunner,
      ompWorkerLifecycleRunner: lifecycleRunner,
      ompWorkerResultRunner: async () => ({ ok: true }),
    });
    const context = ctx();
    context.observeAttemptSettlement = observer => {
      observers.add(observer as (snapshot: unknown) => void);
      return () => observers.delete(observer as (snapshot: unknown) => void);
    };
    return { handlers, context, boundAttempts, lifecycleCalls, observers, lifecycleSettled };
  };

  const settlementSnapshot = (overrides: Record<string, unknown>) => ({
    capabilityVersion: 1,
    attemptId: "host-generation:7",
    agentId: "WorkerS",
    jobId: "WorkerS",
    parentToolCallId: "task-call-settlement",
    sourceIndex: 0,
    generation: 7,
    resultAccepted: true,
    outcome: "completed",
    cleanupState: "pending",
    cleanupPendingResources: ["owner-jobs"],
    cleanupFailedResources: [],
    releasePermitted: false,
    revision: 1,
    ...overrides,
  });

  const nextLifecycleCall = async (
    harness: ReturnType<typeof settlementHarness>,
    expected: number,
  ) => {
    for (let attempt = 0; attempt < 200 && harness.lifecycleCalls.length < expected; attempt += 1) {
      const gate = deferred<void>();
      harness.lifecycleSettled = gate;
      await Promise.race([gate.promise, Promise.resolve()]);
    }
    return harness.lifecycleCalls[expected - 1];
  };

  it("releases only at the host's proven settlement boundary, not on result acceptance", async () => {
    const harness = settlementHarness();
    const admitted = await harness.handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-settlement",
        input: { agent: "task", task: "Mutate the seam" },
      },
      harness.context,
    );
    expect(admitted).not.toEqual({ block: true, reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE" });
    expect(harness.observers.size).toBe(1);

    for (const observer of harness.observers) {
      observer(settlementSnapshot({}));
    }
    await nextLifecycleCall(harness, 1);
    expect(harness.lifecycleCalls).toHaveLength(1);
    expect(harness.lifecycleCalls[0]).toMatchObject({
      outcome: "completed",
      executorSettled: true,
      cleanupComplete: false,
      sequence: 1,
    });

    for (const observer of harness.observers) {
      observer(
        settlementSnapshot({
          cleanupState: "settled",
          cleanupPendingResources: [],
          releasePermitted: true,
          revision: 2,
        }),
      );
    }
    await nextLifecycleCall(harness, 2);
    expect(harness.lifecycleCalls).toHaveLength(2);
    expect(harness.lifecycleCalls[1]).toMatchObject({
      executorSettled: true,
      cleanupComplete: true,
      sequence: 2,
    });
    expect(harness.boundAttempts[0]).toMatchObject({
      nativeAttemptId: "host-generation:7",
      nativeJobId: "WorkerS",
      agentId: "WorkerS",
      hostGeneration: 7,
    });
  });

  it("returns the subscription lifetime for a filtered read-only sibling", async () => {
    const harness = settlementHarness();
    await harness.handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-settlement",
        input: {
          tasks: [
            { agent: "scout", task: "Inspect the seam", access_intent: "read_only" },
            { agent: "task", task: "Mutate the seam" },
          ],
        },
      },
      harness.context,
    );
    expect(harness.observers.size).toBe(1);
    let returned: unknown;
    for (const observer of harness.observers) {
      returned = observer(
        settlementSnapshot({
          attemptId: "host-generation:9",
          agentId: "Scout",
          jobId: "Scout",
          sourceIndex: 0,
          generation: 9,
          resultAccepted: false,
          outcome: "running",
          releasePermitted: false,
          revision: 1,
        }),
      );
    }
    // A filtered read-only sibling is not a writer receipt, but it is still part of
    // this call: the subscription lifetime must be returned so a rejected writer
    // group reaches the host drain instead of dying in the adapter's standalone
    // catch. The lifetime stays pending until the call's writers settle or the
    // observer is disposed, so the host owns real work, not a resolved placeholder.
    expect(returned).toBeInstanceOf(Promise);
    let settled = false;
    void (returned as Promise<void>).then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );
    await Promise.resolve();
    expect(settled).toBe(false);
  });

  it("reconciles a single lost acknowledgement successfully", async () => {
    const contextRunner = vi.fn(async (options: OmpWorkerContextOptions) =>
      contextResultForRequest(options));
    const bindRunner: NonNullable<ExtensionOptions["ompWorkerBindRunner"]> = vi.fn(async options => ({
      ok: true,
      status: "accepted" as const,
      taskId: options.taskId,
      attemptId: options.attemptId,
    }));
    const persisted = new Map<number, string>();
    let sequenceTwoAttempts = 0;
    const lifecycleRunner: NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]> = vi.fn(
      async options => {
        const payload = JSON.stringify(options);
        const prior = persisted.get(options.sequence);
        if (prior !== undefined && prior !== payload) {
          return { ok: false, error: "RECEIPT_CONFLICT" };
        }
        persisted.set(options.sequence, payload);
        if (options.sequence === 2) {
          sequenceTwoAttempts += 1;
          if (sequenceTwoAttempts === 1) {
            return { ok: false, error: "BRAIN_WORKER_CALLBACK_UNAVAILABLE" };
          }
        }
        return {
          ok: true,
          status: "accepted" as const,
          taskId: options.taskId,
          attemptId: options.attemptId,
          sequence: options.sequence,
        };
      },
    );
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
      ompWorkerResultRunner: async () => ({ ok: true }),
    });
    const prepared = await handlers.get("tool_call")!({
      toolName: "task",
      toolCallId: "mutating-attempt",
      input: { task: "Mutate", access_intent: "mutating" },
    }, context);
    expect(prepared).toMatchObject({ input: { access_intent: "mutating" } });
    const base: AsyncJobLifecycleObservation = {
      jobId: null,
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
    // The first sequence-2 acknowledgement is lost; the single identical-payload
    // resend is accepted and the same receipt completes the writer.
    await expect(Promise.resolve(observer!({
      ...base,
      status: "completed",
      executorSettled: true,
      revision: 2,
    }))).resolves.toBe(true);
    expect(sequenceTwoAttempts).toBe(2);
    await handlers.get("session_shutdown")!({ reason: "quit" }, context);
    await expect(Promise.resolve(observer!({
      ...base,
      status: "completed",
      executorSettled: true,
      cleanupComplete: true,
      revision: 3,
    }))).resolves.toBe(true);
    expect(lifecycleRunner).toHaveBeenCalledTimes(4);
    expect([...persisted.keys()]).toEqual([1, 2, 3]);
    expect(disposeObserver).toHaveBeenCalledTimes(1);
  });

  it("keeps host-visible work pending through a delayed lifecycle RPC", async () => {
    const gate = deferred<void>();
    const harness = settlementHarness(gate.promise);
    await harness.handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-settlement",
        input: { agent: "task", task: "Mutate the seam" },
      },
      harness.context,
    );
    expect(harness.observers.size).toBe(1);
    let returned: unknown;
    for (const observer of harness.observers) {
      returned = observer(settlementSnapshot({}));
    }
    let settled = false;
    void (returned as Promise<void>).then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );
    await Promise.resolve();
    await Promise.resolve();
    expect(settled).toBe(false);
    gate.resolve();
    await nextLifecycleCall(harness, 1);
    await Promise.resolve();
    await Promise.resolve();
    // The RPC returned, but cleanup is not proven: host-owned work stays open.
    expect(settled).toBe(false);
  });

  it("does not invent an observer obligation for a read-only-only call", async () => {
    const harness = settlementHarness();
    const prepared = await harness.handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-read-only",
        input: { agent: "scout", task: "Inspect", access_intent: "read_only" },
      },
      harness.context,
    );
    expect(prepared).not.toEqual({
      block: true,
      reason: "BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE",
    });
    expect(harness.observers.size).toBe(0);
  });

  it("never treats a failed or pending cleanup as settlement", async () => {
    const harness = settlementHarness();
    await harness.handlers.get("tool_call")!(
      {
        toolName: "task",
        toolCallId: "task-call-settlement",
        input: { agent: "task", task: "Mutate the seam" },
      },
      harness.context,
    );
    for (const observer of harness.observers) {
      observer(
        settlementSnapshot({
          cleanupState: "failed",
          cleanupPendingResources: [],
          cleanupFailedResources: ["session-disposal"],
          releasePermitted: false,
          revision: 3,
        }),
      );
    }
    await nextLifecycleCall(harness, 1);
    expect(harness.lifecycleCalls.at(-1)).toMatchObject({
      executorSettled: true,
      cleanupComplete: false,
    });
  });

  it.each([false, true])("preserves shutdown receipts and advances revisions after lost response=%s", async (loseResponse) => {
    const contextRunner = vi.fn(async (options: OmpWorkerContextOptions) => contextResultForRequest(options));
    const bindRunner: NonNullable<ExtensionOptions["ompWorkerBindRunner"]> = vi.fn(async (options) => ({
      ok: true,
      status: "accepted" as const,
      taskId: options.taskId,
      attemptId: options.attemptId,
    }));
    const persisted = new Map<number, string>();
    const payloads: string[] = [];
    const lifecycleRunner: NonNullable<ExtensionOptions["ompWorkerLifecycleRunner"]> = vi.fn(async (options) => {
      const payload = JSON.stringify(options);
      payloads.push(payload);
      const prior = persisted.get(options.sequence);
      if (prior !== undefined && prior !== payload) {
        return { ok: false, error: "RECEIPT_CONFLICT" };
      }
      persisted.set(options.sequence, payload);
      if (loseResponse && options.sequence === 2) {
        return { ok: false, error: "BRAIN_WORKER_CALLBACK_UNAVAILABLE" };
      }
      return {
        ok: true,
        status: "accepted" as const,
        taskId: options.taskId,
        attemptId: options.attemptId,
        sequence: options.sequence,
      };
    });
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
      jobId: null,
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
    }))).resolves.toBe(!loseResponse);
    expect(resultRunner).toHaveBeenCalledTimes(loseResponse ? 0 : 1);
    await handlers.get("session_shutdown")!({ reason: "quit" }, context);
    expect(disposeObserver).not.toHaveBeenCalled();
    await expect(Promise.resolve(observer!({
      ...base,
      status: "completed",
      executorSettled: true,
      cleanupComplete: true,
      revision: 3,
    }))).resolves.toBe(true);

    expect(bindRunner).toHaveBeenCalledTimes(1);
    // A lost acknowledgement earns exactly one identical-payload reconciliation resend.
    expect(payloads).toHaveLength(loseResponse ? 4 : 3);
    if (loseResponse) expect(payloads[2]).toBe(payloads[1]);
    expect([...persisted.keys()]).toEqual([1, 2, 3]);
    expect(lifecycleRunner).toHaveBeenLastCalledWith(expect.objectContaining({
      hostGeneration: 7,
      nativeAttemptId: "native-attempt-1",
      nativeJobId: null,
      cleanupComplete: true,
    }));
    expect(disposeObserver).toHaveBeenCalledTimes(1);
  });

  it("recovers a rejected blocking-worker result with its durable native binding", async () => {
    const journal: Array<{ type: string; customType: string; data: unknown }> = [];
    const context = ctx();
    context.sessionManager.getEntries = () => journal;
    let observer: ((value: Readonly<AsyncJobLifecycleObservation>) => boolean | Promise<boolean>) | undefined;
    context.observeAsyncJobLifecycle = (callback) => {
      observer = callback;
      return () => {};
    };
    const load = (resultRunner: NonNullable<ExtensionOptions["ompWorkerResultRunner"]>) => {
      const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
      factory({
        on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
        appendEntry: (customType: string, data: unknown) => journal.push({ type: "custom", customType, data }),
      } as unknown as ExtensionAPI, {
        ompWorkerContextRunner: async (options) => contextResultForRequest(options),
        ompWorkerBindRunner: async () => ({ ok: true }),
        ompWorkerLifecycleRunner: async () => ({ ok: true }),
        ompWorkerResultRunner: resultRunner,
      });
      return handlers;
    };
    const first = load(async () => ({ ok: false, error: "UNAVAILABLE" }));
    await first.get("tool_call")!({
      toolName: "task", toolCallId: "blocking-recovery",
      input: { task: "Persist the bounded result", access_intent: "mutating" },
    }, context);
    expect(observer).toBeDefined();
    await observer!({
      jobId: null, generation: 7, nativeAttemptId: "blocking-native-attempt",
      type: "task", agentId: "BlockingWorker", sourceToolCallId: "blocking-recovery",
      sourceIndex: 0, status: "completed", executorSettled: true, cleanupComplete: true, revision: 1,
    });
    expect(journal.some((entry) => entry.customType === "second-brain.worker-job-pending")).toBe(false);
    expect(journal.some((entry) => entry.customType === "second-brain.worker-result-accepted")).toBe(false);
    const resumed = load(async (options) => ({
      ok: options.childOmpAgentId === "BlockingWorker" &&
        options.hostGeneration === 7 &&
        options.nativeAttemptId === "blocking-native-attempt" &&
        options.nativeJobId === null,
      error: "BINDING_MISMATCH",
    }));
    await resumed.get("before_agent_start")!({ prompt: "Recover the pending result", systemPrompt: "BASE" }, context);
    expect(journal.filter((entry) => entry.customType === "second-brain.worker-result-accepted")).toHaveLength(1);
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
