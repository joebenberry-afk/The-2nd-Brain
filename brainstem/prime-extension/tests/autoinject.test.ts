/**
 * Phase 0C host adapter — P0 AutoInject SHADOW (plan §6.9/§6.10).
 * - config: mode switch off|shadow, timeout, project resolution;
 * - spawn: execFile mocked — success parse, timeout/error/non-zero -> null;
 * - orchestration: mode=off no spawn, empty task no spawn, decision recorded,
 *   spawn failure -> extension_error (fail-open), never throws;
 * - wiring: real factory + fake ExtensionAPI — handlers return undefined and
 *   the shadow runner is called with the event task (no packet in any return).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join as joinTmp } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock }));
const shadowRunMock = vi.hoisted(() => vi.fn());
const advisoryRunMock = vi.hoisted(() => vi.fn());
vi.mock("../src/autoinject", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/autoinject")>();
  return { ...actual, runShadowAutoInject: shadowRunMock, runAdvisoryAutoInject: advisoryRunMock };
});
// The real runShadowAutoInject (module is mocked for wiring tests; unit
// tests below fetch the actual implementation explicitly).
let realRunShadowAutoInject: typeof import("../src/autoinject")["runShadowAutoInject"];
let realRunAdvisoryAutoInject: typeof import("../src/autoinject")["runAdvisoryAutoInject"];
import {
  AUTOINJECT_CUSTOM_TYPE,
  AUTOINJECT_DEFAULT_EMIT_TTL_MS,
  AUTOINJECT_DEFAULT_TIMEOUT_MS,
  resetAutoInjectEmitCache,
  AUTOINJECT_MAX_TASK_ARG_CHARS,
  loadAutoInjectHostConfig,
  parseShadowOutput,
  resolveProject,
  runAdvisoryAutoInject,
  runAutoInjectShadow,
  runShadowAutoInject,
  type AutoInjectShadowOutcome,
} from "../src/autoinject";
import { autoinjectShadowDecision, extensionError } from "../src/sensors";
import { REAL_CLI_INJECT_OUTPUT } from "./real-cli-output.fixture";
import factory from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

const ENV_KEYS = [
  "SECOND_BRAIN_AUTOINJECT_MODE",
  "SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS",
  "SECOND_BRAIN_PROJECT",
  "SECOND_BRAIN_HOME",
  "SECOND_BRAIN_PYTHON",
  "SECOND_BRAIN_RUNTIME_ROOT",
] as const;
const SAVED: Record<string, string | undefined> = {};

beforeEach(async () => {
  for (const key of ENV_KEYS) {
    SAVED[key] = process.env[key];
    delete process.env[key];
  }
  const realModule = await vi.importActual<typeof import("../src/autoinject")>(
    "../src/autoinject",
  );
  realRunShadowAutoInject = realModule.runShadowAutoInject;
  realRunAdvisoryAutoInject = realModule.runAdvisoryAutoInject;
  resetAutoInjectEmitCache();
  execFileMock.mockReset();
  shadowRunMock.mockReset();
  advisoryRunMock.mockReset();
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (SAVED[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED[key] as string;
  }
  vi.restoreAllMocks();
});

const OUT_JSON = JSON.stringify({
  decision: "INJECT",
  reason: null,
  packet: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-x\n",
  packet_tokens: 117,
  candidate_ids: ["mem-1"],
  selected_ids: ["mem-1"],
  delivery_id: "del-abc",
});

const CFG = { mode: "shadow" as const, timeoutMs: 5000 };

describe("loadAutoInjectHostConfig", () => {
  it("defaults to shadow with 5s timeout", () => {
    const cfg = loadAutoInjectHostConfig();
    expect(cfg.mode).toBe("shadow");
    expect(cfg.timeoutMs).toBe(AUTOINJECT_DEFAULT_TIMEOUT_MS);
  });
  it("honors off values and custom timeout", () => {
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    process.env.SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS = "2500";
    const cfg = loadAutoInjectHostConfig();
    expect(cfg.mode).toBe("off");
    expect(cfg.timeoutMs).toBe(2500);
  });
  it("falls back on invalid timeout", () => {
    process.env.SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS = "bogus";
    expect(loadAutoInjectHostConfig().timeoutMs).toBe(AUTOINJECT_DEFAULT_TIMEOUT_MS);
  });
  it("reads mode from config/autoinject.toml [autoinject] when env unset", async () => {
    delete process.env.SECOND_BRAIN_AUTOINJECT_MODE;
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-cfg-"));
    const configDir = joinTmp(home, "config");
    mkdirSync(configDir, { recursive: true });
    writeFileSync(joinTmp(configDir, "autoinject.toml"), "[autoinject]\nmode = \"advisory\"\n");
    expect(loadAutoInjectHostConfig(home).mode).toBe("advisory");
    expect(loadAutoInjectHostConfig().mode).toBe("shadow"); // absent file -> shadow
  });
  it("env overrides config file", async () => {
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "active";
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-cfg-"));
    const configDir = joinTmp(home, "config");
    mkdirSync(configDir, { recursive: true });
    writeFileSync(joinTmp(configDir, "autoinject.toml"), "[autoinject]\nmode = \"shadow\"\n");
    expect(loadAutoInjectHostConfig(home).mode).toBe("active");
  });
});

describe("resolveProject", () => {
  it("uses env SECOND_BRAIN_PROJECT else default", () => {
    expect(resolveProject()).toBe("default");
    process.env.SECOND_BRAIN_PROJECT = "proj-a";
    expect(resolveProject()).toBe("proj-a");
  });
});

describe("parseShadowOutput", () => {
  it("parses valid CLI JSON", () => {
    const out = parseShadowOutput(OUT_JSON);
    expect(out?.decision).toBe("INJECT");
    expect(out?.packetTokens).toBe(117);
    expect(out?.candidateCount).toBe(1);
    expect(out?.packetSha256).toMatch(/^[0-9a-f]{64}$/);
  });
  it("returns null for invalid JSON / non-object / missing decision", () => {
    expect(parseShadowOutput("not json")).toBeNull();
    expect(parseShadowOutput('"str"')).toBeNull();
    expect(parseShadowOutput("{}")).toBeNull();
  });
  it("REAL captured CLI output (INJECT) -> packet parsed end-to-end", () => {
    const out = parseShadowOutput(REAL_CLI_INJECT_OUTPUT);
    expect(out).not.toBeNull();
    expect(out?.decision).toBe("INJECT");
    expect(out?.packet).not.toBeNull();
    expect(out?.packet?.startsWith("[BRAIN_CONTEXT_DELTA v1]")).toBe(true);
    expect(out?.cliPacketChars).toBe(out?.packet?.length);
    expect(out?.cliStdoutChars).toBe(REAL_CLI_INJECT_OUTPUT.length);
  });
});

describe("runAutoInjectShadow (execFile mocked)", () => {
  const baseOpts = () => ({
    home: "H:/brain",
    task: "wire the adapter",
    cwd: "C:/work/proj",
    sessionId: "s1",
    agentId: "a1",
    cfg: CFG,
  });
  it("spawns env-clean python with --json and parses stdout", async () => {
    execFileMock.mockImplementation((_py, args, opts, cb) => {
      expect(args[0]).toBe("-m");
      expect(args).toContain("--json");
      expect(args).toContain("--cwd");
      expect(args[args.indexOf("--cwd") + 1]).toBe("C:/work/proj");
      expect(args).not.toContain("--project"); // project resolved in Python
      expect(opts.timeout).toBe(5000);
      expect(opts.env.PYTHONHOME).toBeUndefined();
      expect(opts.env.PYTHONPATH).toBeUndefined();
      expect(opts.env.SECOND_BRAIN_HOME).toBe("H:/brain");
      cb(null, OUT_JSON);
    });
    const out = await runAutoInjectShadow(baseOpts());
    expect(out?.decision).toBe("INJECT");
    expect(out?.deliveryId).toBe("del-abc");
  });
  it("uses SECOND_BRAIN_PYTHON independently of state home", async () => {
    process.env.SECOND_BRAIN_PYTHON = "R:/runtime/python.exe";
    execFileMock.mockImplementation((python, _args, _opts, callback) => {
      expect(python).toBe("R:/runtime/python.exe");
      callback(null, OUT_JSON);
    });

    expect((await runAutoInjectShadow(baseOpts()))?.decision).toBe("INJECT");
  });
  it("resolves null on error/timeout", async () => {
    execFileMock.mockImplementation((_py, _args, _opts, cb) => cb(new Error("timeout")));
    expect(await runAutoInjectShadow(baseOpts())).toBeNull();
  });
  it("resolves null on non-zero exit or malformed stdout", async () => {
    execFileMock.mockImplementation((_py, _args, _opts, cb) => cb(null, ""));
    expect(await runAutoInjectShadow(baseOpts())).toBeNull();
  });
  it("never passes the task via argv beyond the safety margin", () => {
    runAutoInjectShadow({ ...baseOpts(), task: "x".repeat(10000) });
    const args = execFileMock.mock.calls[0]?.[1] as string[];
    const idx = args.indexOf("--task");
    expect(args[idx + 1].length).toBe(AUTOINJECT_MAX_TASK_ARG_CHARS);
  });
});

describe("runShadowAutoInject orchestration (real implementation)", () => {
  function makeCall(
    over: Partial<Parameters<typeof runShadowAutoInject>[0]> = {},
  ): {
    callObj: Parameters<typeof runShadowAutoInject>[0];
    append: ReturnType<typeof vi.fn>;
    runner: ReturnType<typeof vi.fn>;
  } {
    const append = vi.fn<(record: unknown) => void>();
    const runner = vi.fn<() => Promise<AutoInjectShadowOutcome | null>>().mockResolvedValue({
      decision: "INJECT",
      reason: null,
      packet: null,
      packetTokens: 117,
      deliveryId: "del-abc",
      candidateCount: 1,
      selectedCount: 1,
      packetSha256: "ab",
      cliPacketChars: null,
      cliStdoutChars: 0,
      projectId: null,
      projectResolution: null,
    });
    const callObj: Parameters<typeof runShadowAutoInject>[0] = {
      home: "H:/brain",
      session: "s1",
      task: "wire the adapter",
      agentId: "a1",
      cwd: "C:/work/proj",
      cfg: CFG,
      append,
      runner,
      ...over,
    };
    return { callObj, append, runner: callObj.runner as ReturnType<typeof vi.fn> };
  }
  it("mode=off -> no spawn, no record", async () => {
    const { callObj, append, runner } = makeCall({ cfg: { mode: "off", timeoutMs: 5000 } });
    await realRunShadowAutoInject(callObj);
    expect(runner).not.toHaveBeenCalled();
    expect(append).not.toHaveBeenCalled();
  });
  it("empty task -> no spawn (session_start has no prompt)", async () => {
    const { callObj, append, runner } = makeCall({ task: "   " });
    await realRunShadowAutoInject(callObj);
    expect(runner).not.toHaveBeenCalled();
    expect(append).not.toHaveBeenCalled();
  });
  it("decision recorded privacy-safe, nothing returned", async () => {
    const { callObj, append, runner } = makeCall();
    const result = await realRunShadowAutoInject(callObj);
    expect(result).toBeUndefined(); // shadow: never returns a patch/packet
    expect(runner).toHaveBeenCalledTimes(1);
    const record = append.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(record.kind).toBe("autoinject_shadow_decision");
    expect(record.decision).toBe("INJECT");
    expect(record.latency_ms).toBeGreaterThanOrEqual(0);
    expect(record.mode).toBe("shadow");
    expect(record.model_visible).toBe(false);
    expect(record.result_patch).toBe(false);
  });
  it("spawn failure -> extension_error recorded, fail-open", async () => {
    const { callObj, append, runner } = makeCall({ runner: vi.fn<() => Promise<null>>().mockResolvedValue(null) });
    await realRunShadowAutoInject(callObj);
    const record = append.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(record.kind).toBe("extension_error");
    expect(runner).toHaveBeenCalledTimes(1);
  });
  it("runner rejection -> extension_error, never throws", async () => {
    const { callObj, append } = makeCall({
      runner: vi.fn<() => Promise<AutoInjectShadowOutcome | null>>().mockRejectedValue(new Error("boom")),
    });
    await expect(realRunShadowAutoInject(callObj)).resolves.toBeUndefined();
    expect(append.mock.calls[0]?.[0]).toMatchObject({ kind: "extension_error" });
  });
});

describe("index.ts wiring (real factory, fake ExtensionAPI)", () => {
  type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

  function loadFactory(): { handlers: Map<string, Handler>; api: ExtensionAPI } {
    const handlers = new Map<string, Handler>();
    const pi = {
      on(name: string, handler: Handler) {
        handlers.set(name, handler);
      },
    } as unknown as ExtensionAPI;
    factory(pi, {
      budgetRunner: async () => ({ state: "OK", used: 0, cap: 400000 }),
      ompRoutingRunner: async () => ({ decision: null }),
      ompVisibilityRunner: async () => ({ visibility_plan: null, hydrated_instructions: {}, error: null }),
    });
    return { handlers, api: pi };
  }

  const ctx = {
    cwd: "C:/work",
    model: { id: "deepseek/deepseek-v4-flash" },
    sessionManager: undefined,
  } as unknown as ExtensionContext;

  it("before_agent_start schedules shadow run with event prompt, returns undefined", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-"));
    const { handlers } = loadFactory();
    shadowRunMock.mockResolvedValue(undefined);
    const result = await handlers.get("before_agent_start")!(
      { prompt: "wire the adapter" },
      ctx,
    );
    expect(result).toBeUndefined(); // NO packet in any return (shadow)
    expect(shadowRunMock).toHaveBeenCalledTimes(1);
    const call = shadowRunMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(call.task).toBe("wire the adapter");
    expect(call.cwd).toBe("C:/work");
  });

  it("session_start schedules shadow run (empty task) and still records session_start", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-"));
    const { handlers } = loadFactory();
    expect(() => handlers.get("session_start")!({ reason: "startup" }, ctx)).not.toThrow();
    expect(shadowRunMock).toHaveBeenCalledTimes(1);
    expect((shadowRunMock.mock.calls[0]?.[0] as Record<string, unknown>).task).toBe("");
  });
});

describe("runAdvisoryAutoInject (real implementation)", () => {
  function makeCall(
    over: Partial<Parameters<typeof runAdvisoryAutoInject>[0]> = {},
  ): {
    callObj: Parameters<typeof runAdvisoryAutoInject>[0];
    append: ReturnType<typeof vi.fn>;
  } {
    const append = vi.fn<(record: unknown) => void>();
    const runner = vi.fn<() => Promise<AutoInjectShadowOutcome | null>>().mockResolvedValue({
      decision: "INJECT",
      reason: null,
      packet: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-x\nauthority: advisory\n",
      packetTokens: 117,
      deliveryId: "del-abc",
      candidateCount: 1,
      selectedCount: 1,
      packetSha256: "ab",
      cliPacketChars: null,
      cliStdoutChars: 0,
      projectId: null,
      projectResolution: null,
    });
    const callObj: Parameters<typeof runAdvisoryAutoInject>[0] = {
      home: "H:/brain",
      session: "s1",
      task: "wire the adapter",
      agentId: "a1",
      cwd: "C:/work/proj",
      cfg: { mode: "advisory", timeoutMs: 5000 },
      append,
      runner,
      ...over,
    };
    return { callObj, append };
  }
  it("INJECT -> returns low-authority custom_message patch, record logged", async () => {
    const { callObj, append } = makeCall();
    const result = await realRunAdvisoryAutoInject(callObj);
    expect(result).toEqual({
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-x\nauthority: advisory\n",
      display: true,
      details: { delivery_id: "del-abc", packet_tokens: 117 },
    });
    const record = append.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(record.kind).toBe("autoinject_shadow_decision");
    expect(record.decision).toBe("INJECT");
    expect(record.mode).toBe("advisory");
    expect(record.model_visible).toBe(true);
    expect(record.result_patch).toBe(true);
  });
  it("NO_INJECTION -> undefined, no patch", async () => {
    const { callObj, append } = makeCall({
      runner: vi
        .fn<() => Promise<AutoInjectShadowOutcome | null>>()
        .mockResolvedValue({
          decision: "NO_INJECTION",
          reason: "NO_RELEVANT_MEMORY",
          packet: null,
          packetTokens: null,
          deliveryId: null,
          candidateCount: 0,
          selectedCount: 0,
          packetSha256: null,
          cliPacketChars: null,
          cliStdoutChars: 0,
          projectId: null,
          projectResolution: null,
        }),
    });
    expect(await realRunAdvisoryAutoInject(callObj)).toBeUndefined();
    expect(append.mock.calls[0]?.[0]).toMatchObject({ kind: "autoinject_shadow_decision" });
  });
  it("spawn failure -> extension_error, undefined (fail-open)", async () => {
    const { callObj, append } = makeCall({ runner: vi.fn<() => Promise<null>>().mockResolvedValue(null) });
    expect(await realRunAdvisoryAutoInject(callObj)).toBeUndefined();
    expect(append.mock.calls[0]?.[0]).toMatchObject({ kind: "extension_error" });
  });
  it("shadow/off modes never return a patch", async () => {
    const { callObj } = makeCall({ cfg: { mode: "shadow", timeoutMs: 5000 } });
    expect(await realRunAdvisoryAutoInject(callObj)).toBeUndefined();
  });
});

describe("index.ts wiring — advisory mode (real factory, fake ExtensionAPI)", () => {
  type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

  function loadFactory(): Map<string, Handler> {
    const handlers = new Map<string, Handler>();
    const pi = {
      on(name: string, handler: Handler) {
        handlers.set(name, handler);
      },
    } as unknown as ExtensionAPI;
    factory(pi, {
      budgetRunner: async () => ({ state: "OK", used: 0, cap: 400000 }),
      ompRoutingRunner: async () => ({ decision: null }),
      ompVisibilityRunner: async () => ({ visibility_plan: null, hydrated_instructions: {}, error: null }),
    });
    return handlers;
  }

  const ctx = {
    cwd: "C:/work",
    model: { id: "deepseek/deepseek-v4-flash" },
    sessionManager: undefined,
  } as unknown as ExtensionContext;

  it("same session twice -> first call returns custom_message patch, second undefined (ALREADY_DELIVERED)", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-adv-"));
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const handlers = loadFactory();
    const packet = "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-x\nauthority: advisory\n";
    advisoryRunMock
      .mockResolvedValueOnce({
        customType: AUTOINJECT_CUSTOM_TYPE,
        content: packet,
        display: true,
        details: { delivery_id: "del-1", packet_tokens: 117 },
      })
      .mockResolvedValueOnce(undefined);
    const first = await handlers.get("before_agent_start")!({ prompt: "wire the adapter" }, ctx);
    expect(first).toEqual({
      message: {
        customType: AUTOINJECT_CUSTOM_TYPE,
        content: packet,
        display: true,
        details: { delivery_id: "del-1", packet_tokens: 117 },
      },
    });
    expect(advisoryRunMock).toHaveBeenCalledTimes(1);
    const second = await handlers.get("before_agent_start")!({ prompt: "wire the adapter" }, ctx);
    expect(second).toBeUndefined(); // python says ALREADY_DELIVERED -> no patch
    expect(advisoryRunMock).toHaveBeenCalledTimes(2);
  });

  it("shadow mode never returns a patch even when runner would", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-sh-"));
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "shadow";
    const handlers = loadFactory();
    shadowRunMock.mockResolvedValue(undefined);
    const result = await handlers.get("before_agent_start")!({ prompt: "wire the adapter" }, ctx);
    expect(result).toBeUndefined();
    expect(shadowRunMock).toHaveBeenCalledTimes(1);
    expect(advisoryRunMock).not.toHaveBeenCalled();
  });

  it("config FILE mode=advisory + env unset -> ADVISORY branch runs (C10 verifier fix)", async () => {
    // The branch decision must read the config file via config.home: with
    // env unset and [autoinject] mode = "advisory" in the brain's
    // config/autoinject.toml, the awaited advisory path runs (not shadow).
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-filemode-"));
    const configDir = joinTmp(home, "config");
    mkdirSync(configDir, { recursive: true });
    writeFileSync(joinTmp(configDir, "autoinject.toml"), "[autoinject]\nmode = \"advisory\"\n");
    process.env.SECOND_BRAIN_HOME = home;
    delete process.env.SECOND_BRAIN_AUTOINJECT_MODE;
    const handlers = loadFactory();
    advisoryRunMock.mockResolvedValueOnce({
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "packet-text",
      display: true,
      details: { delivery_id: "del-1", packet_tokens: 10 },
    });
    const result = await handlers.get("before_agent_start")!({ prompt: "adaptive fan-out policy" }, ctx);
    expect(result).toEqual({
      message: {
        customType: AUTOINJECT_CUSTOM_TYPE,
        content: "packet-text",
        display: true,
        details: { delivery_id: "del-1", packet_tokens: 10 },
      },
    });
    expect(advisoryRunMock).toHaveBeenCalledTimes(1);
    expect(shadowRunMock).not.toHaveBeenCalled();
  });

  it("config FILE mode=shadow + env unset -> SHADOW branch runs", async () => {
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-filemode2-"));
    const configDir = joinTmp(home, "config");
    mkdirSync(configDir, { recursive: true });
    writeFileSync(joinTmp(configDir, "autoinject.toml"), "[autoinject]\nmode = \"shadow\"\n");
    process.env.SECOND_BRAIN_HOME = home;
    delete process.env.SECOND_BRAIN_AUTOINJECT_MODE;
    const handlers = loadFactory();
    shadowRunMock.mockResolvedValue(undefined);
    const result = await handlers.get("before_agent_start")!({ prompt: "adaptive fan-out policy" }, ctx);
    expect(result).toBeUndefined();
    expect(shadowRunMock).toHaveBeenCalledTimes(1);
    expect(advisoryRunMock).not.toHaveBeenCalled();
  });

  it("advisory worker role returns a bare { message } patch (FIX 1)", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-w-"));
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const handlers = loadFactory();
    advisoryRunMock.mockResolvedValueOnce({
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "packet-text",
      display: true,
      details: { delivery_id: "del-1", packet_tokens: 10 },
    });
    const result = await handlers.get("before_agent_start")!(
      { prompt: "adaptive fan-out policy" },
      ctx, // deepseek-v4-flash -> worker role
    );
    expect(result).toEqual({
      message: {
        customType: AUTOINJECT_CUSTOM_TYPE,
        content: "packet-text",
        display: true,
        details: { delivery_id: "del-1", packet_tokens: 10 },
      },
    });
  });

  it("advisory orchestrator role merges message with the Sol systemPrompt (FIX 1)", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-o-"));
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    process.env.ORCHESTRATOR_MODELS = "openai-codex/gpt-5.6-sol";
    const handlers = loadFactory();
    advisoryRunMock.mockResolvedValueOnce({
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "packet-text",
      display: true,
      details: { delivery_id: "del-1", packet_tokens: 10 },
    });
    const solCtx = {
      cwd: "C:/work",
      model: { id: "openai-codex/gpt-5.6-sol" },
      sessionManager: undefined,
    } as unknown as ExtensionContext;
    const result = await handlers.get("before_agent_start")!({ prompt: "adaptive fan-out" }, solCtx);
    expect(result).toBeDefined();
    const r = result as Record<string, unknown>;
    expect(typeof r.systemPrompt).toBe("string"); // Sol contract present
    expect((r.message as Record<string, unknown>).content).toBe("packet-text");
  });

  it("advisory driver role merges message with the driver contract (FIX 1)", async () => {
    process.env.SECOND_BRAIN_HOME = await mkdtemp(joinTmp(tmpdir(), "sb-ai-d-"));
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const handlers = loadFactory();
    advisoryRunMock.mockResolvedValueOnce({
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "packet-text",
      display: true,
      details: { delivery_id: "del-1", packet_tokens: 10 },
    });
    const driverCtx = {
      cwd: "C:/work",
      model: { id: "deepseek/deepseek-v4-pro" },
      sessionManager: undefined,
      getSystemPrompt: () => "base prompt",
    } as unknown as ExtensionContext;
    const result = await handlers.get("before_agent_start")!({ prompt: "adaptive fan-out" }, driverCtx);
    expect(result).toBeDefined();
    const r = result as Record<string, unknown>;
    expect(typeof r.systemPrompt).toBe("string"); // driver contract appended
    expect((r.message as Record<string, unknown>).content).toBe("packet-text");
  });
});

describe("emit stability (Phase C5)", () => {
  function makeCall(
    mode: "shadow" | "advisory",
    over: Partial<Parameters<typeof runAdvisoryAutoInject>[0]> = {},
  ): {
    callObj: Parameters<typeof runAdvisoryAutoInject>[0];
    append: ReturnType<typeof vi.fn>;
    runner: ReturnType<typeof vi.fn>;
  } {
    const append = vi.fn<(record: unknown) => void>();
    const runner = vi.fn<() => Promise<AutoInjectShadowOutcome | null>>().mockResolvedValue({
      decision: "INJECT",
      reason: null,
      packet: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-x\nauthority: advisory\n",
      packetTokens: 117,
      deliveryId: "del-1",
      candidateCount: 1,
      selectedCount: 1,
      packetSha256: "ab",
      cliPacketChars: null,
      cliStdoutChars: 0,
      projectId: null,
      projectResolution: null,
    });
    const callObj: Parameters<typeof runAdvisoryAutoInject>[0] = {
      home: "H:/brain",
      session: "s1",
      task: "adaptive fan-out policy",
      agentId: "a1",
      cwd: "C:/work",
      cfg: { mode, timeoutMs: 5000 },
      append,
      runner,
      ...over,
    };
    return { callObj, append, runner };
  }

  it("advisory: same task twice within TTL -> ONE spawn, identical message object", async () => {
    const { callObj, append, runner } = makeCall("advisory");
    const first = await realRunAdvisoryAutoInject(callObj);
    const second = await realRunAdvisoryAutoInject(callObj);
    expect(runner).toHaveBeenCalledTimes(1); // exactly one spawn
    expect(second).toBe(first); // identical cached object
    const kinds = append.mock.calls.map((c) => (c[0] as Record<string, unknown>).kind);
    const hit = append.mock.calls.find(
      (c) => (c[0] as Record<string, unknown>).cache_hit === true,
    )?.[0] as Record<string, unknown>;
    expect(hit).toBeDefined();
    expect(hit.emit_index).toBe(2);
    expect(hit.result_patch).toBe(true);
    expect(kinds.filter((k) => k === "autoinject_shadow_decision").length).toBe(2);
  });

  it("advisory: after TTL expiry -> second spawn", async () => {
    vi.useFakeTimers();
    try {
      const { callObj, runner } = makeCall("advisory");
      await realRunAdvisoryAutoInject(callObj);
      await vi.advanceTimersByTimeAsync(AUTOINJECT_DEFAULT_EMIT_TTL_MS + 1000);
      await realRunAdvisoryAutoInject(callObj);
      expect(runner).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("different task -> second spawn", async () => {
    const { callObj, runner } = makeCall("advisory");
    await realRunAdvisoryAutoInject(callObj);
    await realRunAdvisoryAutoInject({ ...callObj, task: "another task entirely" });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("different session -> second spawn", async () => {
    const { callObj, runner } = makeCall("advisory");
    await realRunAdvisoryAutoInject(callObj);
    await realRunAdvisoryAutoInject({ ...callObj, session: "s2" });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("shadow: re-emit within TTL -> zero additional spawns", async () => {
    const { callObj, runner } = makeCall("shadow");
    await realRunShadowAutoInject(callObj);
    await realRunShadowAutoInject(callObj);
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("shadow cache-hit record: result_patch=false even when outcome has a packet (C10 verifier)", async () => {
    // The shadow spawn outcome carries an INJECT packet (makeCall default),
    // but shadow never returns a patch: the first-hit record must claim
    // result_patch=false + handler_returned_message=false.
    const { callObj, append, runner } = makeCall("shadow");
    await realRunShadowAutoInject(callObj);
    await realRunShadowAutoInject(callObj); // cache hit -> marker record
    expect(runner).toHaveBeenCalledTimes(1);
    const hit = append.mock.calls.find(
      (c) => (c[0] as Record<string, unknown>).cache_hit === true,
    )?.[0] as Record<string, unknown>;
    expect(hit).toBeDefined();
    expect(hit.result_patch).toBe(false);
    expect(hit.handler_returned_message).toBe(false);
  });

  it("different semantic task suffixes never share a cache entry", async () => {
    const { callObj, runner } = makeCall("advisory");
    const base =
      "adaptive fan-out policy for the P1 orchestration design with recursion blocked and retained worker reuse across multiple independent workstreams";
    await realRunAdvisoryAutoInject({ ...callObj, task: base });
    await realRunAdvisoryAutoInject({
      ...callObj,
      task: `${base} (attempt 2 - retry metadata)`,
    });
    await realRunAdvisoryAutoInject({
      ...callObj,
      task: `${base} [extra metadata appended]`,
    });
    expect(runner).toHaveBeenCalledTimes(3);
  });

  it("same session and task in another project never reuses a packet", async () => {
    const { callObj, runner } = makeCall("advisory");
    await realRunAdvisoryAutoInject({ ...callObj, cwd: "C:\\repo-a" });
    await realRunAdvisoryAutoInject({ ...callObj, cwd: "C:\\repo-b" });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("retrieval configuration change invalidates the cached packet", async () => {
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-config-"));
    mkdirSync(joinTmp(home, "config"), { recursive: true });
    const { callObj, runner } = makeCall("advisory", { home });
    writeFileSync(joinTmp(home, "config", "retrieval.toml"), "top_k = 2\n");
    await realRunAdvisoryAutoInject(callObj);
    writeFileSync(joinTmp(home, "config", "retrieval.toml"), "top_k = 3\n");
    await realRunAdvisoryAutoInject(callObj);
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("different prompt head within TTL -> replace entry + new spawn (Phase C8 guard)", async () => {
    const { callObj, runner } = makeCall("advisory");
    await realRunAdvisoryAutoInject(callObj);
    await realRunAdvisoryAutoInject({
      ...callObj,
      task: "completely different task about pizza flavors",
    });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("INVARIANT: handler_returned_message=true implies the handler result carries the SAME message object", async () => {
    // For every INJECT outcome the record flag must equal (message returned),
    // and when true the returned object is the message that was recorded as
    // returned — the flag can never be false while a packet was parsed.
    const { callObj, append, runner } = makeCall("advisory");
    const result = await realRunAdvisoryAutoInject(callObj);
    const record = append.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(record.handler_returned_message).toBe(result !== undefined);
    expect(record.result_patch).toBe(result !== undefined);
    expect(result).toBeDefined();
    expect(result?.content.length).toBeGreaterThan(0);
    // NO_INJECTION outcome: flag false, no message.
    runner.mockResolvedValueOnce({
      decision: "NO_INJECTION",
      reason: "NO_RELEVANT_MEMORY",
      packet: null,
      packetTokens: null,
      deliveryId: null,
      candidateCount: 0,
      selectedCount: 0,
      packetSha256: null,
      cliPacketChars: null,
      cliStdoutChars: 489,
      projectId: null,
      projectResolution: null,
    });
    resetAutoInjectEmitCache();
    const call2 = { ...callObj, session: "s-inv2" };
    const result2 = await realRunAdvisoryAutoInject(call2);
    expect(result2).toBeUndefined();
    const rec2 = append.mock.calls[1]?.[0] as Record<string, unknown>;
    expect(rec2.handler_returned_message).toBe(false);
  });

  it("REAL captured CLI output through the advisory pipeline -> message returned, handler_returned_message=true", async () => {
    const out = parseShadowOutput(REAL_CLI_INJECT_OUTPUT);
    expect(out).not.toBeNull();
    const { callObj, append, runner } = makeCall("advisory");
    runner.mockResolvedValue(out);
    const message = await realRunAdvisoryAutoInject(callObj);
    expect(message).toBeDefined();
    expect(message?.content).toBe(out?.packet);
    const record = append.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(record.handler_returned_message).toBe(true);
    expect(record.result_patch).toBe(true);
    expect(record.cli_packet_chars).toBe(out?.packet?.length);
    expect(record.cli_stdout_chars).toBe(REAL_CLI_INJECT_OUTPUT.length);
  });

  it("file-backed cache survives process restart (recovered worker)", async () => {
    const home = await mkdtemp(joinTmp(tmpdir(), "sb-ai-persist-"));
    const { callObj, runner } = makeCall("advisory", { home });
    const first = await realRunAdvisoryAutoInject(callObj);
    expect(first).toBeDefined();
    // Simulate a session-worker recovery: fresh process -> empty in-memory
    // cache, but the persisted file must serve the next emit.
    resetAutoInjectEmitCache();
    const second = await realRunAdvisoryAutoInject(callObj);
    expect(runner).toHaveBeenCalledTimes(1); // no second spawn
    expect(second).toBeDefined();
    expect(second).toEqual(first);
  });
});

describe("sensor record kind", () => {
  it("autoinject_shadow_decision has the documented shape", () => {
    const record = autoinjectShadowDecision("s1", {
      decision: "NO_INJECTION",
      reason: "NO_RELEVANT_MEMORY",
      packet_tokens: null,
      latency_ms: 12,
      candidate_count: 0,
      selected_count: 0,
      delivery_id: null,
      packet_sha256: null,
      mode: "shadow",
      model_visible: false,
      result_patch: false,
      emit_index: 1,
      cache_hit: false,
      handler_returned_message: false,
      cli_packet_chars: null,
      cli_stdout_chars: 120,
    });
    expect(record.kind).toBe("autoinject_shadow_decision");
    expect(record.session).toBe("s1");
    expect(record.reason).toBe("NO_RELEVANT_MEMORY");
    expect(record.mode).toBe("shadow");
    expect(record.model_visible).toBe(false);
    expect(record.result_patch).toBe(false);
    expect(record.emit_index).toBe(1);
    expect(record.cache_hit).toBe(false);
    expect(record.handler_returned_message).toBe(false);
    expect(record.cli_stdout_chars).toBe(120);
  });
  it("extensionError stays available for fail-open records", () => {
    const record = extensionError("s1", new Error("boom"));
    expect(record.kind).toBe("extension_error");
  });
});
