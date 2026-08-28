import { describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import {
  parseOmpWorkerContextOutput,
  renderOmpWorkerContext,
  type OmpWorkerContextHandoff,
  type OmpWorkerContextResult,
} from "../src/worker-context-bridge";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

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

describe("OMP worker Context Capsule bridge", () => {
  it("parses bounded Brain handoff metadata and renders no parent transcript", () => {
    const parsed = parseOmpWorkerContextOutput(JSON.stringify({
      status: "prepared",
      task_id: "omp-task-1",
      packet_sha256: "c".repeat(64),
      context_metadata: contextResult().contextMetadata,
      context_handoff: contextHandoff,
    }));
    expect(parsed.ok).toBe(true);
    const rendered = renderOmpWorkerContext(parsed.contextHandoff!);
    expect(rendered).toContain("Brain-owned child context");
    expect(rendered).not.toContain("parent transcript");
  });

  it("rewrites the real task tool input before child dispatch", async () => {
    const runner = vi.fn(async () => contextResult());
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
        input: { agent: "task", task: "Inspect the bounded seam" },
      },
      ctx(),
    );

    expect(runner).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ input: { agent: "task" } });
    expect((result as { input: { task: string } }).input.task).toContain("Brain-owned child context");
  });

  it("does not resend unchanged context and sends only a delta after change", async () => {
    const runner = vi.fn()
      .mockResolvedValueOnce(contextResult("full"))
      .mockResolvedValueOnce(contextResult("unchanged"))
      .mockResolvedValueOnce(contextResult("delta"));
    const handlers = new Map<string, (event: unknown, context: ExtensionContext) => unknown>();
    const pi = {
      on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => handlers.set(name, handler),
    } as unknown as ExtensionAPI;
    factory(pi, { ompWorkerContextRunner: runner });
    const event = {
      toolName: "task",
      toolCallId: "task-call-modes",
      input: { agent: "task", task: "Inspect the bounded seam" },
    };

    const full = await handlers.get("tool_call")!(event, ctx());
    const unchanged = await handlers.get("tool_call")!(event, ctx());
    const delta = await handlers.get("tool_call")!(event, ctx());
    const fullTask = (full as { input: { task: string } }).input.task;
    const unchangedTask = (unchanged as { input: { task: string } }).input.task;
    const deltaTask = (delta as { input: { task: string } }).input.task;

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
      { toolName: "task", toolCallId: "task-call-fail", input: { task: "Needs Brain context" } },
      ctx(),
    );

    expect(result).toEqual({ block: true, reason: "CONTEXT_REF_UNRESOLVED" });
  });
});
