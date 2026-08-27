import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

const ensureMock = vi.hoisted(() => vi.fn());
const updateMock = vi.hoisted(() => vi.fn());
const updateSyncMock = vi.hoisted(() => vi.fn());
const renderMock = vi.hoisted(() => vi.fn());
const messageMock = vi.hoisted(() => vi.fn());
vi.mock("../src/active-state-mirror", () => ({
  runActiveStateEnsure: ensureMock,
  runActiveStateUpdate: updateMock,
  runActiveStateUpdateSync: updateSyncMock,
  renderActiveState: renderMock,
  activeStateMessage: messageMock,
}));
const runOmpVisibilityMock = vi.hoisted(() => vi.fn());
vi.mock("../src/visibility-bridge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/visibility-bridge")>();
  return { ...actual, runOmpVisibility: runOmpVisibilityMock };
});

import factory from "../src/index";

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;
let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-active-state-wiring-"));
  mkdirSync(join(tmp, "telemetry", "agent-performance"), { recursive: true });
  process.env.SECOND_BRAIN_HOME = tmp;
  ensureMock.mockReset();
  updateMock.mockReset();
  updateSyncMock.mockReset();
  renderMock.mockReset();
  messageMock.mockReset();
  runOmpVisibilityMock.mockReset();
  runOmpVisibilityMock.mockResolvedValue({ visibility_plan: null, hydrated_instructions: {}, error: null });
  ensureMock.mockResolvedValue({ ok: true, sessionId: "omp-session" });
  updateMock.mockResolvedValue({ ok: true, sessionId: "omp-session", changed: true });
  mkdirSync(join(tmp, "config"), { recursive: true });
  writeFileSync(join(tmp, "config", "autoinject.toml"), "[autoinject]\nmode = \"active\"\n");
  updateSyncMock.mockReturnValue({ ok: true, sessionId: "omp-session", changed: true });
  renderMock.mockResolvedValue({
    ok: true,
    sessionId: "omp-session",
    renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Resume task",
  });
  messageMock.mockReturnValue({
    customType: "brain.active-state",
    content: "[SECOND_BRAIN_ACTIVE_STATE]\nObjective: Resume task",
    display: false,
    details: { session_id: "omp-session" },
  });
});

afterEach(async () => {
  delete process.env.SECOND_BRAIN_HOME;
  // Drain any still-in-flight fire-and-forget telemetry writes before
  // removing the temp dir (avoids a Windows ENOTEMPTY/ENOENT/EPERM race
  // between a lingering append() and rm(), independent of test correctness).
  await new Promise((resolve) => setTimeout(resolve, 150));
  await rm(tmp, { recursive: true, force: true });
});

function loadFactory(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler) } as unknown as ExtensionAPI;
  factory(pi);
  return handlers;
}

function context(): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "gpt-5.6-luna", provider: "openai-codex" },
    sessionManager: { getSessionFile: () => join(tmp, "session.jsonl") },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE",
    signal: undefined,
    hasUI: false,
  } as unknown as ExtensionContext;
}

describe("P3.1 active-state OMP lifecycle", () => {
  it("binds and exposes the same capsule on before_agent_start", async () => {
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: "Resume task" }, context());

    expect(ensureMock).toHaveBeenCalledWith(expect.objectContaining({
      objective: "Resume task",
      hostSessionId: expect.any(String),
    }));
    expect(renderMock).toHaveBeenCalledWith(expect.objectContaining({ hostSessionId: expect.any(String) }));
    expect(messageMock).toHaveBeenCalled();
    expect((result as { message?: { customType?: string } }).message?.customType).toBe("brain.active-state");
  });

  it("persists the capsule before compaction and at shutdown", async () => {
    const handlers = loadFactory();
    const ctx = context();

    await handlers.get("session_before_compact")!({ branchEntries: [] }, ctx);
    handlers.get("session_shutdown")!({ reason: "normal" }, ctx);

    expect(updateMock).toHaveBeenCalledWith(expect.objectContaining({
      verification: { pre_compaction: "persisted" },
    }));
    expect(updateSyncMock).toHaveBeenCalledWith(expect.objectContaining({
      verification: { session_shutdown: "normal" },
    }));
  });
});
