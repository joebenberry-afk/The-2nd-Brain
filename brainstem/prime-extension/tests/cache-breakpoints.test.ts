/**
 * T2.3 Cache-break points and model-switch preflight tests for Prime extension.
 *
 * Core rule:
 * Paging/eviction runs ONLY when at least one of the 5 cache-break conditions holds:
 * (a) previous tool_result bytes > [rtd].threshold_chars (default 8000 from config/context.toml [rtd]);
 * (b) session_before_compact event occurred;
 * (c) model/provider changed since last request;
 * (d) last assistant_usage.cache_read_tokens == 0;
 * (e) resident tokens > capacity_hard (default 6000 or 1.5 * budget).
 *
 * If NONE hold, return the previous rendered view unchanged (skip paging).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTOINJECT_CUSTOM_TYPE } from "../src/autoinject";
import extensionFactory from "../src/index";
import { TelemetryStore } from "../src/storage";
import type { ExtensionContext } from "../types/prime";

const runVmemListPrePageSyncMock = vi.hoisted(() => vi.fn());
const runVmemClaimPagesSyncMock = vi.hoisted(() => vi.fn());
const runVmemEvictSyncMock = vi.hoisted(() => vi.fn());

vi.mock("../src/vmem", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/vmem")>();
  return {
    ...actual,
    runVmemListPrePageSync: runVmemListPrePageSyncMock,
    runVmemClaimPagesSync: runVmemClaimPagesSyncMock,
    runVmemEvictSync: runVmemEvictSyncMock,
  };
});

type Handler = (event: Record<string, unknown>, ctx: ExtensionContext) => unknown;

let tempDir: string;
let originalHome: string | undefined;
const stores = new Set<TelemetryStore>();
const appendTelemetry = TelemetryStore.prototype.append;

function autoinjectMsg(deliveryId: string, content = "x".repeat(300)): unknown {
  return {
    role: "custom",
    customType: AUTOINJECT_CUSTOM_TYPE,
    content,
    display: true,
    details: { delivery_id: deliveryId, packet_tokens: 100 },
    timestamp: "2026-01-01T00:00:00Z",
  };
}

function toolResultMsg(toolCallId: string, content = "y".repeat(300)): unknown {
  return {
    role: "toolResult",
    toolCallId,
    toolName: "ipython",
    content: [{ type: "text", text: content }],
    details: {},
    isError: false,
    timestamp: "2026-01-01T00:00:01Z",
  };
}

function assistantMsg(): unknown {
  return {
    role: "assistant",
    content: [{ type: "text", text: "z".repeat(200) }],
    api: "messages",
    provider: "anthropic",
    model: "claude-3-opus",
    usage: { cacheRead: 500 }, // warm cache
    stopReason: "end_turn",
    timestamp: "2026-01-01T00:00:02Z",
    responseId: "resp-1",
  };
}

function makeCtx(overrides?: Partial<ExtensionContext>): ExtensionContext {
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    cwd: "C:/work",
    model: { id: "test-model", provider: "test-provider" },
    sessionManager: {
      getSessionFile: () => join(tempDir, "session.json"),
      getSessionId: () => "native-cache-session",
      getHeader: () => ({ type: "session", version: 1, id: "native-cache-session", timestamp }),
      getEntries: () => [],
    },
    ...overrides,
  } as unknown as ExtensionContext;
}

beforeEach(() => {
  tempDir = mkdtempSync(join(tmpdir(), "prime-cb-"));
  originalHome = process.env.SECOND_BRAIN_HOME;
  process.env.SECOND_BRAIN_HOME = tempDir;
  mkdirSync(join(tempDir, "config"), { recursive: true });
  mkdirSync(join(tempDir, "telemetry"), { recursive: true });
  writeFileSync(join(tempDir, "session.json"), JSON.stringify({ id: "cb-session" }));
  writeFileSync(
    join(tempDir, "config", "context.toml"),
    `
[context_paging]
enabled = true
pin_recent_messages = 1
resident_token_budget = 100
max_pages_per_context_event = 3

[rtd]
threshold_chars = 8000
`,
  );
  writeFileSync(
    join(tempDir, "config", "v2.toml"),
    `
[models.test-model-tight]
context_tokens = 500

[models.test-model-overflow]
context_tokens = 5

[providers.test-provider]
cache_scope = "model"
`,
  );
  runVmemListPrePageSyncMock.mockReset();
  runVmemClaimPagesSyncMock.mockReset();
  runVmemEvictSyncMock.mockReset();
  vi.spyOn(TelemetryStore.prototype, "append").mockImplementation(function (this: TelemetryStore, record) {
    stores.add(this);
    appendTelemetry.call(this, record);
  });
});

afterEach(async () => {
  await Promise.all([...stores].map((store) => store.flush()));
  stores.clear();
  if (originalHome !== undefined) {
    process.env.SECOND_BRAIN_HOME = originalHome;
  } else {
    delete process.env.SECOND_BRAIN_HOME;
  }
  rmSync(tempDir, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("T2.3 Cache Breakpoints and Model-Switch Preflight", () => {
  it("test_paging_skipped_when_no_break_point", async () => {
    const handlers = new Map<string, Handler>();
    const pi = {
      on: (name: string, handler: Handler): void => {
        handlers.set(name, handler);
      },
    };
    extensionFactory(pi as unknown as Parameters<typeof extensionFactory>[0]);

    const ctx = makeCtx();
    handlers.get("session_start")!({ reason: "startup" }, ctx);

    // Provide warm cache turn: assistant_usage with cacheRead > 0
    handlers.get("message_end")!({
      message: {
        role: "assistant",
        provider: "test-provider",
        model: "test-model",
        usage: { cacheRead: 500, input: 100, output: 50 },
      },
    }, ctx);

    // Provide small tool result (bytes <= 8000)
    handlers.get("tool_result")!({
      toolName: "bash",
      toolCallId: "call-1",
      input: { command: "ls" },
      content: "small output",
      isError: false,
    }, ctx);

    // Messages under capacity_hard (e.g. 500 tokens < 6000)
    const messages = [autoinjectMsg("del-1"), toolResultMsg("call-1"), assistantMsg()];

    // Call context: none of (a)-(e) hold -> paging MUST be skipped (returns undefined)
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();
  });

  it("host-selected model changes recheck Brain context without blocking native requests", async () => {
    runVmemEvictSyncMock.mockReturnValue({ ok: true, evictedCount: 2, evictedTokens: 200 });

    const handlers = new Map<string, Handler>();
    const pi = {
      on: (name: string, handler: Handler): void => {
        handlers.set(name, handler);
      },
    };
    extensionFactory(pi as unknown as Parameters<typeof extensionFactory>[0]);

    const ctx = makeCtx();
    handlers.get("session_start")!({ reason: "startup" }, ctx);

    // First request establishes baseline model
    handlers.get("before_provider_request")!({
      type: "before_provider_request",
      payload: { provider: "test-provider", model: "test-model", messages: [] },
    }, ctx);

    // Scenario A: Switch to test-model-tight (capacity 500 tokens). Messages ~450 tokens > 500*0.85 (425).
    // Step 5: reclaim runs; load is recomputed after reclaim and drops below 500. Fit succeeds!
    const tightPayload = {
      provider: "test-provider",
      model: "test-model-tight",
      messages: [{ role: "user", content: "x".repeat(1800) }], // ~450 tokens
    };
    const tightResult = handlers.get("before_provider_request")!({
      type: "before_provider_request",
      payload: tightPayload,
    }, ctx);
    expect(runVmemEvictSyncMock).toHaveBeenCalledWith(
      expect.objectContaining({ budgetTokens: 425 }),
    );
    expect(tightResult).toBeUndefined(); // proceed successfully

    // A host-selected model's tiny context can exceed Brain's local reclaim
    // capacity. Brain reports the limitation but cannot refuse the host request.
    runVmemEvictSyncMock.mockReturnValue({ ok: true, evictedCount: 0, evictedTokens: 0 });
    const overflowPayload = {
      provider: "test-provider",
      model: "test-model-overflow",
      messages: [{ role: "user", content: "x".repeat(500) }],
    };
    const originalMessages = structuredClone(overflowPayload.messages);
    const result = handlers.get("before_provider_request")!({
      type: "before_provider_request",
      payload: overflowPayload,
    }, ctx);
    expect(result).toBeUndefined();
    expect(overflowPayload.messages).toEqual(originalMessages);

  });

  it("test_hard_capacity_forces_eviction_ignoring_net", async () => {
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-heavy-1",
          kind: "TOOL_OBSERVATION",
          metadata: { toolCallId: "call-small", artifactRef: "art-1" },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    runVmemClaimPagesSyncMock.mockReturnValue({ ok: true, claimedObjIds: ["obj-heavy-1"] });

    const handlers = new Map<string, Handler>();
    const pi = {
      on: (name: string, handler: Handler): void => {
        handlers.set(name, handler);
      },
    };
    extensionFactory(pi as unknown as Parameters<typeof extensionFactory>[0]);

    const ctx = makeCtx();
    handlers.get("session_start")!({ reason: "startup" }, ctx);

    // Assistant with warm cache
    handlers.get("message_end")!({
      message: {
        role: "assistant",
        provider: "test-provider",
        model: "test-model",
        usage: { cacheRead: 500 },
      },
    }, ctx);

    // Small tool result (bytes <= 8000)
    handlers.get("tool_result")!({
      toolName: "bash",
      toolCallId: "call-small",
      input: { command: "echo ok" },
      content: "ok",
      isError: false,
    }, ctx);

    // Case 1: Small messages below capacity_hard (< 6000 tokens) -> no break-point, paging skipped
    const smallMessages = [
      toolResultMsg("call-small", "short content"),
      assistantMsg(),
    ];
    const skippedResult = handlers.get("context")!({ type: "context", messages: smallMessages }, ctx);
    expect(skippedResult).toBeUndefined();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();

    // Case 2: Very large messages exceeding capacity_hard (6000 tokens ~ 24,000 chars)
    const heavyMessages = [
      autoinjectMsg("del-heavy-1", "H".repeat(15000)),
      toolResultMsg("call-small", "H".repeat(15000)),
      assistantMsg(),
    ];

    // Gated context handler MUST trigger paging because resident tokens > capacity_hard (condition e)
    const result = handlers.get("context")!({ type: "context", messages: heavyMessages }, ctx) as
      | { messages: Array<Record<string, unknown>> }
      | undefined;
    expect(result).toBeDefined();
    expect(result?.messages).toBeDefined();
    expect(runVmemClaimPagesSyncMock).toHaveBeenCalledWith(
      expect.objectContaining({
        candidates: expect.arrayContaining([expect.objectContaining({ objId: "obj-heavy-1" })]),
      }),
    );
    const patchedContent = result!.messages[1]?.content as Array<{ type: string; text: string }>;
    expect(patchedContent[0]?.text).toContain("[SECOND_BRAIN_VMEM]");
  });
});
