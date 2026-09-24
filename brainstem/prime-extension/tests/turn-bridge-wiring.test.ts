/**
 * E01 wiring: the batched/reused-interpreter path must behave exactly like the
 * per-phase path from inside `before_agent_start`.
 *
 * These tests drive the real factory with the bridge and the phase runners
 * mocked, and assert the observable contract of the hook:
 *   - the batched AutoInject stdout is parsed by the SAME `parseShadowOutput`
 *     and handed to the SAME advisory orchestration through its runner seam;
 *   - the active-state message and its delivery record are built from the
 *     batched capsule/render stdout;
 *   - a bridge failure falls back to the per-phase spawns (identical result);
 *   - a cached emit skips the Python AutoInject decision (no duplicate
 *     delivery) while capsule/render still run.
 */
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

// The resolved host session id is OMP's native `<timestamp>_<native id>` form
// (index.ts defaultNativeSessionId); the batched payload must carry that exact
// id or `parseActiveStateResult` refuses the capsule as a session mismatch.
const NATIVE_ID = "native-e01";
const NATIVE_TIMESTAMP = "2026-01-01T00:00:00.000Z";
const SESSION = "2026-01-01T00-00-00-000Z_native-e01";
const PACKET = "[SECOND_BRAIN_PACKET]\nmem-abc123456";
const CAPSULE_SHA = "a".repeat(64);

const prepareTurnMock = vi.hoisted(() => vi.fn());
const advisoryEmitCachedMock = vi.hoisted(() => vi.fn());
const runAdvisoryAutoInjectMock = vi.hoisted(() => vi.fn());
const runActiveStateEnsureMock = vi.hoisted(() => vi.fn());
const renderActiveStateMock = vi.hoisted(() => vi.fn());

vi.mock("../src/turn-bridge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/turn-bridge")>();
  return {
    ...actual,
    loadTurnBridgeConfig: () => ({
      // the shipped default (E01 pilot decision): one batched spawn per prompt
      mode: "once" as const,
      timeoutMs: 1000,
      helperStart: "lazy" as const,
      helperMaxRequests: 8,
      helperLifetimeMs: 60_000,
      queueLimit: 2,
    }),
    resolveTurnPython: () => "python.exe",
    prepareTurnWithBridge: prepareTurnMock,
    getTurnHelper: () => ({ ensureStarted: async () => true, dispose: () => undefined }),
    stopTurnHelpers: () => undefined,
  };
});
vi.mock("../src/autoinject", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/autoinject")>();
  return {
    ...actual,
    advisoryEmitCached: advisoryEmitCachedMock,
    runAdvisoryAutoInject: runAdvisoryAutoInjectMock,
  };
});
vi.mock("../src/active-state-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/active-state-mirror")>();
  return {
    ...actual,
    runActiveStateEnsure: runActiveStateEnsureMock,
    renderActiveState: renderActiveStateMock,
  };
});
vi.mock("../src/environment-mirror", () => ({
  runEnvironmentAssessmentSync: () => ({ ok: true, sessionId: "s" }),
  runEnvironmentAssessment: async () => ({ ok: true, sessionId: "s" }),
}));
vi.mock("../src/p4-mirror", () => ({
  runP4PulseSync: () => ({ ok: true, sessionId: "s" }),
  runP4Pulse: async () => ({ ok: true, sessionId: "s" }),
}));
vi.mock("../src/ledger-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/ledger-mirror")>();
  return { ...actual, mirrorFireAndForget: () => undefined };
});
vi.mock("../src/visibility-bridge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/visibility-bridge")>();
  return {
    ...actual,
    runOmpVisibility: async () => ({
      visibility_plan: null,
      hydrated_instructions: {},
      error: null,
    }),
  };
});

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;
let tmp: string;

const ENV_KEYS = [
  "SECOND_BRAIN_HOME",
  "SECOND_BRAIN_PYTHON",
  "SECOND_BRAIN_PROJECT",
  "SECOND_BRAIN_AUTOINJECT_MODE",
  "SECOND_BRAIN_RECALL",
] as const;
const SAVED_ENV: Record<string, string | undefined> = {};

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-e01-wiring-"));
  for (const key of ENV_KEYS) {
    SAVED_ENV[key] = process.env[key];
    delete process.env[key];
  }
  process.env.SECOND_BRAIN_HOME = tmp;
  process.env.SECOND_BRAIN_PYTHON = join(tmp, "python.exe");
  await mkdir(join(tmp, "config"), { recursive: true });
  await mkdir(join(tmp, "sessions"), { recursive: true });
  await writeFile(
    join(tmp, "sessions", "e01.jsonl"),
    `${JSON.stringify({ type: "session", version: 1, id: NATIVE_ID, timestamp: NATIVE_TIMESTAMP })}\n`,
    "utf8",
  );
  await writeFile(join(tmp, "config", "autoinject.toml"), '[autoinject]\nmode = "active"\n', "utf8");

  prepareTurnMock.mockReset();
  prepareTurnMock.mockImplementation(async (options: { request: { want: string[] } }) =>
    batchedPayload(options.request.want.includes("autoinject")),
  );
  advisoryEmitCachedMock.mockReset();
  advisoryEmitCachedMock.mockReturnValue(false);
  runAdvisoryAutoInjectMock.mockReset();
  runAdvisoryAutoInjectMock.mockImplementation(
    async (call: { runner?: () => Promise<unknown> }) => {
      const outcome = call.runner === undefined ? undefined : await call.runner();
      const packet =
        outcome !== null && typeof outcome === "object" && "packet" in outcome
          ? (outcome as { packet: string | null }).packet
          : null;
      if (packet === null || packet === undefined) return undefined;
      return {
        customType: "brain.autoinject.packet",
        content: packet,
        display: true,
        details: {
          delivery_id: (outcome as { deliveryId?: string }).deliveryId,
          packet_tokens: (outcome as { packetTokens?: number }).packetTokens,
        },
      };
    },
  );
  runActiveStateEnsureMock.mockReset();
  runActiveStateEnsureMock.mockResolvedValue({
    ok: true,
    sessionId: SESSION,
    changed: true,
    capsuleSha256: "b".repeat(64),
    capsuleBytes: 7,
  });
  renderActiveStateMock.mockReset();
  renderActiveStateMock.mockResolvedValue({
    ok: true,
    sessionId: SESSION,
    renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: per-phase",
  });
});

afterEach(async () => {
  for (const key of ENV_KEYS) {
    if (SAVED_ENV[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED_ENV[key];
  }
  await new Promise((resolve) => setTimeout(resolve, 100));
  await rm(tmp, { recursive: true, force: true });
});

function batchedPayload(includeAutoinject = true) {
  return {
    ok: true,
    session_id: SESSION,
    capsule: { session_id: SESSION, changed: true, capsule_sha256: CAPSULE_SHA, capsule_bytes: 42 },
    capsule_stdout: `${JSON.stringify(
      {
        session_id: SESSION,
        changed: true,
        capsule_sha256: CAPSULE_SHA,
        capsule_bytes: 42,
        capsule: { objective: "batched" },
      },
      null,
      2,
    )}\n`,
    active_state: { ok: true, session_id: SESSION, rendered_text: "[SECOND_BRAIN_HOT_CONTEXT]" },
    render_stdout: `${JSON.stringify(
      {
        session_id: SESSION,
        rendered_text: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: batched",
        resident_count: 0,
        evicted_count: 0,
        resident_tokens: 0,
      },
      null,
      2,
    )}\n`,
    autoinject: includeAutoinject ? { decision: "INJECT" } : null,
    autoinject_stdout: includeAutoinject ? `${JSON.stringify({
      decision: "INJECT",
      reason: null,
      packet: PACKET,
      packet_tokens: 7,
      candidate_ids: ["mem-abc123456"],
      selected_ids: ["mem-abc123456"],
      delivery_id: "del-1",
      project_id: "default",
      project_resolution: "env",
    })}\n` : null,
  };
}

function loadFactory(options?: ExtensionOptions): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
    appendEntry: (): void => undefined,
  } as unknown as ExtensionAPI;
  factory(pi, options);
  return handlers;
}

function makeCtx(): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
    signal: undefined,
    hasUI: false,
    ui: undefined,
    sessionManager: {
      getSessionFile: () => join(tmp, "sessions", "e01.jsonl"),
      getSessionId: () => NATIVE_ID,
      getHeader: () => ({ type: "session", version: 1, id: NATIVE_ID, timestamp: NATIVE_TIMESTAMP }),
      getEntries: () => [],
    },
  };
}

async function telemetryLines(
  minLines = 1,
  kind?: string,
  timeoutMs = 10_000,
): Promise<Record<string, unknown>[]> {
  const dir = join(tmp, "telemetry", "agent-performance");
  const deadline = Date.now() + timeoutMs;
  let last: Record<string, unknown>[] = [];
  while (Date.now() < deadline) {
    try {
      const names = await readdir(dir);
      const lines: Record<string, unknown>[] = [];
      for (const name of names) {
        if (!name.endsWith(".jsonl")) continue;
        const text = await readFile(join(dir, name), "utf8");
        for (const line of text.split("\n")) {
          if (line.trim().length > 0) lines.push(JSON.parse(line) as Record<string, unknown>);
        }
      }
      last = lines;
      // A specific kind (not just "some line") removes the load sensitivity:
      // fire-and-forget writes land whenever the event loop gets to them.
      const ready = kind === undefined ? last.length >= minLines : last.some((l) => l.kind === kind);
      if (ready) return last;
    } catch {
      // not written yet
    }
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  return last;
}

type HookResult = {
  message?: { content?: string; details?: Record<string, unknown> };
  systemPrompt?: string;
} | undefined;

describe("E01 batched turn bridge wiring", () => {
  it("feeds the batched stdout through the same parsers and orchestration", async () => {
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!(
      { prompt: "a batched task" },
      makeCtx(),
    )) as HookResult;

    expect(prepareTurnMock).toHaveBeenCalledTimes(1);
    const request = prepareTurnMock.mock.calls[0][0] as {
      request: { want: string[]; cwd?: string; projectId?: string };
    };
    expect(request.request.want).toEqual(["capsule", "render", "autoinject"]);
    // Project isolation (reviewer finding 1): an inferred project must NOT be
    // forwarded as an explicit override — Python resolves from cwd/registry/env
    // exactly like the pre-E01 per-phase spawn did.
    expect(request.request.cwd).toBe("C:/work");
    expect(request.request.projectId).toBeUndefined();

    // The runner seam carries exactly what `autoinject shadow --json` would
    // have printed, parsed by the production parser.
    const call = runAdvisoryAutoInjectMock.mock.calls[0][0] as {
      runner?: () => Promise<{ packet: string | null; deliveryId: string | null }>;
    };
    expect(typeof call.runner).toBe("function");
    const outcome = await call.runner!();
    expect(outcome.packet).toBe(PACKET);
    expect(outcome.deliveryId).toBe("del-1");

    expect(result?.message?.content).toContain(PACKET);
    expect(result?.message?.content).toContain("[SECOND_BRAIN_HOT_CONTEXT]");
    const details = result?.message?.details as {
      active_state?: { session_id?: string };
    };
    expect(details?.active_state?.session_id).toBe(SESSION);

    const lines = await telemetryLines(1, "active_state_delivery");
    const delivery = lines.find((line) => line.kind === "active_state_delivery");
    expect(delivery?.capsule_sha256).toBe(CAPSULE_SHA);
    expect(delivery?.capsule_bytes).toBe(42);
    expect(delivery?.changed).toBe(true);
  });

  it("consumes the successful phases of a partial batch and retries only the failed one", async () => {
    // Regression: a batch whose AutoInject phase succeeded but whose render
    // failed must not be discarded — re-running AutoInject would see
    // ALREADY_DELIVERED and the packet would never reach the host.
    prepareTurnMock.mockResolvedValue({
      ...batchedPayload(),
      ok: false,
      errors: ["render_error"],
      render_error: "ValueError: render exploded",
      active_state: { ok: false },
      render_stdout: null,
      phases_ok: { capsule: true, render: false, autoinject: true },
    });
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!(
      { prompt: "a partial task" },
      makeCtx(),
    )) as HookResult;

    // capsule + autoinject consumed from the batch, render retried
    expect(renderActiveStateMock).toHaveBeenCalledTimes(1);
    const call = runAdvisoryAutoInjectMock.mock.calls[0][0] as {
      runner?: () => Promise<{ packet: string | null }>;
    };
    expect(typeof call.runner).toBe("function");
    expect((await call.runner!()).packet).toBe(PACKET);
    expect(result?.message?.content).toContain(PACKET);

    const lines = await telemetryLines(1, "active_state_delivery");
    // the render outcome came from the retried per-phase spawn
    expect(lines.find((line) => line.kind === "active_state_delivery")).toBeTruthy();
  });

  it("falls back to the per-phase spawns when the batched call fails", async () => {
    prepareTurnMock.mockResolvedValue(null);
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!(
      { prompt: "a per-phase task" },
      makeCtx(),
    )) as HookResult;

    expect(runActiveStateEnsureMock).toHaveBeenCalledTimes(1);
    expect(renderActiveStateMock).toHaveBeenCalledTimes(1);
    const call = runAdvisoryAutoInjectMock.mock.calls[0][0] as { runner?: unknown };
    expect(call.runner).toBeUndefined();

    const lines = await telemetryLines(1, "active_state_delivery");
    const delivery = lines.find((line) => line.kind === "active_state_delivery");
    expect(delivery?.capsule_sha256).toBe("b".repeat(64));
    // No packet from the mocked orchestration, but the per-phase active-state
    // message still reaches the host (the batched path must not change that).
    expect(result?.message?.content).toContain("[SECOND_BRAIN_ACTIVE_STATE]");
    expect(result?.message?.content).not.toContain(PACKET);
  });

  it("skips the Python AutoInject decision when the emit is already cached", async () => {
    advisoryEmitCachedMock.mockReturnValue(true);
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: "a cached task" }, makeCtx());

    const request = prepareTurnMock.mock.calls[0][0] as { request: { want: string[] } };
    expect(request.request.want).toEqual(["capsule", "render"]);
    const call = runAdvisoryAutoInjectMock.mock.calls[0][0] as { runner?: unknown };
    expect(call.runner).toBeUndefined();
  });
});
