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
import { rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import { quietCorpusMemories, writeQuietCorpus } from "./quiet-corpus-fixture";
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
const runActiveStateUpdateMock = vi.hoisted(() => vi.fn());
const renderActiveStateMock = vi.hoisted(() => vi.fn());
const runOmpVisibilityMock = vi.hoisted(() => vi.fn());
const startDetachedMaintenanceMock = vi.hoisted(() => vi.fn());

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
    runActiveStateUpdate: runActiveStateUpdateMock,
    renderActiveState: renderActiveStateMock,
  };
});
vi.mock("../src/environment-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/environment-mirror")>();
  return {
    ...actual,
    // A constant fingerprint: no prompt boundary re-assesses the environment in
    // these tests (the cadence itself is covered by the environment tests).
    environmentFingerprint: () => "fingerprint-test",
    runEnvironmentAssessment: async () => ({ ok: true, sessionId: "s" }),
  };
});
vi.mock("../src/detached-maintenance", () => ({
  startDetachedShutdownMaintenance: startDetachedMaintenanceMock,
}));
vi.mock("../src/p4-mirror", () => ({
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
    runOmpVisibility: runOmpVisibilityMock,
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
  runActiveStateUpdateMock.mockReset();
  runActiveStateUpdateMock.mockResolvedValue({ ok: true, sessionId: SESSION, changed: true });
  renderActiveStateMock.mockReset();
  renderActiveStateMock.mockResolvedValue({
    ok: true,
    sessionId: SESSION,
    renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: per-phase",
  });
  runOmpVisibilityMock.mockReset();
  runOmpVisibilityMock.mockResolvedValue({
    visibility_plan: null,
    hydrated_instructions: {},
    error: null,
  });
  startDetachedMaintenanceMock.mockReset();
  startDetachedMaintenanceMock.mockImplementation(() => ({ environment: true, p4: true }));
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

/** Let every already-queued microtask run: deterministic, no wall clock. */
async function flushMicrotasks(rounds = 12): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve();
}

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

/**
 * Quiet fast path (V3 S2, QuietPath): a no-benefit prompt must cost ZERO Python
 * spawns on the critical path — no batched turn prepare, no visibility plan, no
 * per-phase capsule/render/AutoInject, no advisory orchestration — while the
 * capsule ensure is preserved as ONE coalesced background spawn per session.
 */
describe("quiet fast path wiring", () => {
  const PROMPT = "runtime state ledger";

  function cleanCorpus(): void {
    writeQuietCorpus(tmp, quietCorpusMemories());
  }

  function corpusWithRareHeadline(): void {
    writeQuietCorpus(
      tmp,
      quietCorpusMemories().concat([
        { id: "mem-k8s1", title: "kubernetes rollout", summary: "s" },
        { id: "mem-k8s2", title: "kubernetes ingress", summary: "s" },
        { id: "mem-k8s3", title: "kubernetes secrets", summary: "s" },
      ]),
    );
  }

  it("spawns nothing on the critical path and coalesces the background ensure", async () => {
    cleanCorpus();
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());

    expect(result).toBeUndefined();
    expect(prepareTurnMock).not.toHaveBeenCalled();
    // Visibility is planned independently of the precheck, but this home's
    // skills.toml is absent, so `resolve_visibility_mode` fails safe to shadow
    // and no plan could be injected — the spawn is the precheck's whole saving.
    expect(runOmpVisibilityMock).not.toHaveBeenCalled();
    expect(runAdvisoryAutoInjectMock).not.toHaveBeenCalled();
    expect(renderActiveStateMock).not.toHaveBeenCalled();
    // The capsule ensure is NOT dropped, only moved off the critical path.
    expect(runActiveStateEnsureMock).toHaveBeenCalledTimes(1);
    expect(runActiveStateEnsureMock).toHaveBeenCalledWith(
      expect.objectContaining({
        hostSessionId: SESSION,
        objective: PROMPT,
        nextAction: PROMPT,
      }),
    );

    const lines = await telemetryLines(1, "quiet_skip");
    const record = lines.find((line) => line.kind === "quiet_skip");
    expect(record).toMatchObject({
      reason: "no_evidence",
      capsule: "missing",
      vmem_objects: 0,
      total_documents: 40,
      model_visible: false,
    });
    expect(JSON.stringify(record)).not.toContain("runtime state ledger");
    expect(lines.some((line) => line.kind === "autoinject_shadow_decision")).toBe(false);
  });

  it("keeps one ensure in flight per session and lets the latest prompt win", async () => {
    cleanCorpus();
    const gate = Promise.withResolvers<{
      ok: boolean;
      sessionId: string;
      changed: boolean;
      capsuleSha256: string;
      capsuleBytes: number;
    }>();
    runActiveStateEnsureMock.mockImplementation(() => gate.promise);
    const handlers = loadFactory();
    const handler = handlers.get("before_agent_start")!;

    await handler({ prompt: `${PROMPT} one` }, makeCtx());
    await handler({ prompt: `${PROMPT} two` }, makeCtx());
    expect(runActiveStateEnsureMock).toHaveBeenCalledTimes(1);

    gate.resolve({
      ok: true,
      sessionId: SESSION,
      changed: true,
      capsuleSha256: "b".repeat(64),
      capsuleBytes: 7,
    });
    await vi.waitFor(() => expect(runActiveStateEnsureMock).toHaveBeenCalledTimes(2));
    expect(runActiveStateEnsureMock.mock.calls[1][0]).toMatchObject({
      objective: `${PROMPT} two`,
    });
  });

  it("leaves the run path unchanged when a memory could contribute", async () => {
    corpusWithRareHeadline();
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!(
      { prompt: "kubernetes runtime" },
      makeCtx(),
    )) as HookResult;

    expect(prepareTurnMock).toHaveBeenCalledTimes(1);
    expect(runOmpVisibilityMock).toHaveBeenCalledTimes(1);
    expect(runAdvisoryAutoInjectMock).toHaveBeenCalledTimes(1);
    expect(result?.message?.content).toContain(PACKET);
    const lines = await telemetryLines(1, "active_state_delivery");
    expect(lines.some((line) => line.kind === "quiet_skip")).toBe(false);
  });

  /**
   * Review counterexample: quiet turn A schedules a background ensure, a later
   * foreground turn C writes its own capsule — A's completion must not launch a
   * queued quiet prompt over C, and C must not start its capsule write while A's
   * ensure is still in flight (AutoInject reads objective/next_action from it).
   */
  it("drains the quiet ensure before the next turn's capsule write", async () => {
    corpusWithRareHeadline();
    const log: string[] = [];
    const quietGate = Promise.withResolvers<{
      ok: boolean;
      sessionId: string;
      changed: boolean;
      capsuleSha256: string;
      capsuleBytes: number;
    }>();
    let ensures = 0;
    runActiveStateEnsureMock.mockImplementation(async () => {
      ensures += 1;
      log.push(`ensure:${ensures}`);
      if (ensures === 1) return quietGate.promise;
      return {
        ok: true,
        sessionId: SESSION,
        changed: true,
        capsuleSha256: "b".repeat(64),
        capsuleBytes: 7,
      };
    });
    prepareTurnMock.mockImplementation(async (options: { request: { want: string[] } }) => {
      log.push("batch");
      return batchedPayload(options.request.want.includes("autoinject"));
    });
    const handlers = loadFactory();
    const handler = handlers.get("before_agent_start")!;

    // Turn 1: memory-invisible → one coalesced background ensure, still running.
    await handler({ prompt: PROMPT }, makeCtx());
    expect(log).toEqual(["ensure:1"]);

    // Turn 2: a memory-contributing prompt — its capsule work waits for turn 1.
    const foreground = handler({ prompt: "kubernetes runtime" }, makeCtx()) as Promise<HookResult>;
    await flushMicrotasks();
    expect(runOmpVisibilityMock).toHaveBeenCalledTimes(1); // it reached the barrier
    expect(prepareTurnMock).not.toHaveBeenCalled();
    expect(log).toEqual(["ensure:1"]);

    quietGate.resolve({
      ok: true,
      sessionId: SESSION,
      changed: true,
      capsuleSha256: "c".repeat(64),
      capsuleBytes: 7,
    });
    const result = await foreground;
    // The quiet ensure settled BEFORE the foreground batch, and the quiet prompt
    // that batch superseded never ran a second ensure afterwards.
    expect(log).toEqual(["ensure:1", "batch"]);
    expect(result?.message?.content).toContain(PACKET);
    await flushMicrotasks();
    expect(log).toEqual(["ensure:1", "batch"]);
  });

  it("drains the quiet ensure before the compaction checkpoint", async () => {
    cleanCorpus();
    const log: string[] = [];
    const quietGate = Promise.withResolvers<{
      ok: boolean;
      sessionId: string;
      changed: boolean;
      capsuleSha256: string;
      capsuleBytes: number;
    }>();
    runActiveStateEnsureMock.mockImplementation(async () => {
      log.push("ensure");
      return quietGate.promise;
    });
    runActiveStateUpdateMock.mockImplementation(async () => {
      log.push("compaction_checkpoint");
      return { ok: true, sessionId: SESSION, changed: true };
    });
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());
    expect(log).toEqual(["ensure"]);

    // The pre-compaction checkpoint runs inside the same barrier: it must not
    // read/modify the capsule while the quiet ensure is still writing it.
    const compaction = handlers.get("session_before_compact")!(
      { branchEntries: [] },
      makeCtx(),
    ) as Promise<unknown>;
    await flushMicrotasks();
    expect(log).toEqual(["ensure"]);

    quietGate.resolve({
      ok: true,
      sessionId: SESSION,
      changed: true,
      capsuleSha256: "b".repeat(64),
      capsuleBytes: 7,
    });
    await compaction;
    expect(log).toEqual(["ensure", "compaction_checkpoint"]);
  });

  it("drains the quiet ensure before shutdown persistence", async () => {
    cleanCorpus();
    const log: string[] = [];
    const quietGate = Promise.withResolvers<{
      ok: boolean;
      sessionId: string;
      changed: boolean;
      capsuleSha256: string;
      capsuleBytes: number;
    }>();
    runActiveStateEnsureMock.mockImplementation(async () => {
      log.push("ensure");
      return quietGate.promise;
    });
    startDetachedMaintenanceMock.mockImplementation(() => {
      log.push("shutdown_persistence");
      return { environment: true, p4: true };
    });
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());
    expect(log).toEqual(["ensure"]);

    // The shutdown handler must hold its persistence until the barrier is idle.
    const shutdown = handlers.get("session_shutdown")!(
      { type: "session_shutdown", reason: "normal" },
      makeCtx(),
    ) as Promise<unknown>;
    await flushMicrotasks();
    expect(log).toEqual(["ensure"]);

    quietGate.resolve({
      ok: true,
      sessionId: SESSION,
      changed: true,
      capsuleSha256: "b".repeat(64),
      capsuleBytes: 7,
    });
    await shutdown;
    expect(log).toEqual(["ensure", "shutdown_persistence"]);
    const lines = await telemetryLines(1, "session_shutdown");
    expect(lines.some((line) => line.kind === "session_shutdown")).toBe(true);
  });

  /**
   * Review counterexample: the memory precheck examines only memory/capsule/VMem
   * state, while enforced skill visibility routes independently through the
   * approved skill files — suppressing the plan on a quiet turn would drop the
   * specialist instructions the same task used to receive.
   */
  it("plans enforced skill visibility even on a memory-invisible turn", async () => {
    cleanCorpus();
    writeFileSync(
      join(tmp, "config", "skills.toml"),
      '[visibility]\nmode = "enforced"\n',
      "utf8",
    );
    runOmpVisibilityMock.mockResolvedValue({
      visibility_plan: {
        visibility_plan_id: "vplan-quiet",
        mode: "enforced",
        selected_skill_ids: ["skill-a"],
        hydrated_skill_ids: ["skill-a"],
        rejected_skill_ids: {},
        unavailable_skill_ids: {},
      },
      hydrated_instructions: { "skill-a": "SPECIALIST INSTRUCTIONS" },
      error: null,
    });
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!(
      { prompt: PROMPT },
      makeCtx(),
    )) as HookResult;

    // The memory precheck still answered `skip`: no memory phase spawned.
    expect(prepareTurnMock).not.toHaveBeenCalled();
    expect(runAdvisoryAutoInjectMock).not.toHaveBeenCalled();
    expect(renderActiveStateMock).not.toHaveBeenCalled();
    // ...and the enforced skill plan was still computed and delivered.
    expect(runOmpVisibilityMock).toHaveBeenCalledTimes(1);
    expect(result?.message?.content).toContain("SPECIALIST INSTRUCTIONS");
    const lines = await telemetryLines(1, "quiet_skip");
    expect(lines.some((line) => line.kind === "quiet_skip")).toBe(true);
  });

  it("skips the visibility spawn only when the mode cannot be enforced", async () => {
    cleanCorpus();
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());
    // No skills.toml at all: `skills.resolve_visibility_mode` fails safe to
    // "shadow", so no plan could ever be injected.
    expect(runOmpVisibilityMock).not.toHaveBeenCalled();

    // An explicit shadow mode config behaves the same way.
    writeFileSync(
      join(tmp, "config", "skills.toml"),
      '[visibility]\nmode = "shadow"\n',
      "utf8",
    );
    const second = loadFactory();
    await second.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());
    expect(runOmpVisibilityMock).not.toHaveBeenCalled();
  });

  it("runs the batched path when the corpus cannot be read", async () => {
    writeQuietCorpus(tmp, quietCorpusMemories());
    rmSync(join(tmp, "db", "brain.sqlite"));
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());

    expect(prepareTurnMock).toHaveBeenCalledTimes(1);
    expect(runActiveStateEnsureMock).not.toHaveBeenCalled();
    const lines = await telemetryLines(1, "active_state_delivery");
    expect(lines.some((line) => line.kind === "quiet_skip")).toBe(false);
  });

  it("honors the env kill switch", async () => {
    cleanCorpus();
    process.env.SECOND_BRAIN_QUIET_PRECHECK = "0";
    const handlers = loadFactory();
    await handlers.get("before_agent_start")!({ prompt: PROMPT }, makeCtx());
    delete process.env.SECOND_BRAIN_QUIET_PRECHECK;

    expect(prepareTurnMock).toHaveBeenCalledTimes(1);
    const lines = await telemetryLines(1, "active_state_delivery");
    expect(lines.some((line) => line.kind === "quiet_skip")).toBe(false);
  });
});
