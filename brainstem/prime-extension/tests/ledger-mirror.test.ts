/**
 * P2 host event mirror (Phase 2B): spawn contract, privacy (sha256-only task
 * text), fail-open behavior, and index.ts wiring per event kind.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock }));
const mirrorFireAndForgetMock = vi.hoisted(() => vi.fn());
vi.mock("../src/ledger-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/ledger-mirror")>();
  return { ...actual, mirrorFireAndForget: mirrorFireAndForgetMock };
});
import {
  buildMirrorEventJson,
  mirrorEvent,
  resetMirrorInitCache,
  taskSha256,
} from "../src/ledger-mirror";
import factory from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

const ENV_KEYS = ["SECOND_BRAIN_HOME"] as const;
const SAVED: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const key of ENV_KEYS) {
    SAVED[key] = process.env[key];
    delete process.env[key];
  }
  execFileMock.mockReset();
  mirrorFireAndForgetMock.mockReset();
  resetMirrorInitCache();
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (SAVED[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED[key] as string;
  }
  vi.restoreAllMocks();
});

async function fakeHome(): Promise<{ home: string; python: string }> {
  const home = await mkdtemp(join(tmpdir(), "sb-mirror-"));
  const bin = join(home, ".venv", "Scripts");
  mkdirSync(bin, { recursive: true });
  writeFileSync(join(bin, "python.exe"), "");
  return { home, python: join(bin, "python.exe") };
}

function fakeSpawn(result: { error?: Error; stdout?: string }) {
  execFileMock.mockImplementation((_py, _args, _opts, cb) => {
    cb(result.error ?? null, result.stdout ?? "");
  });
}

describe("mirrorEvent spawn contract", () => {
  it("spawns env-clean ledger append with one event JSON on stdin (after auto-init)", async () => {
    const { home, python } = await fakeHome();
    const calls: { args: string[]; opts: { env: Record<string, string | undefined>; timeout: number }; stdin: string }[] = [];
    execFileMock.mockImplementation((_py, args, opts, cb) => {
      const entry = { args: args as string[], opts: opts as never, stdin: "" };
      calls.push(entry);
      const child = {
        stdin: { write: (s: string) => { entry.stdin = s; }, end: () => {} },
      };
      cb(null, '{"appended":[1]}');
      return child as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "host-1",
      record: { kind: "user_task", fields: { task_sha256: "abc", prompt_chars: 10 } },
      python,
    });
    expect(result.ok).toBe(true);
    // call 1 = init, call 2 = append
    expect(calls.length).toBe(2);
    expect(calls[0].args).toContain("init");
    expect(calls[0].args).toContain("--host");
    expect(calls[0].args).toContain("prime");
    const append = calls[1];
    expect(append.args).toEqual([
      "-m", "second_brain", "ledger", "append",
      "--session", "host-1", "--stdin-json",
    ]);
    expect(append.opts.env.PYTHONHOME).toBeUndefined();
    expect(append.opts.env.PYTHONPATH).toBeUndefined();
    expect(append.opts.env.SECOND_BRAIN_HOME).toBe(home);
    expect(append.opts.timeout).toBe(5000);
    const parsed = JSON.parse(append.stdin);
    expect(parsed.event_type).toBe("user_task");
    expect(parsed.payload.task_sha256).toBe("abc");
  });

  it("never sends raw task text in the payload", async () => {
    const json = buildMirrorEventJson({
      kind: "user_task",
      fields: { task_sha256: taskSha256("the full secret prompt"), prompt_chars: 25 },
    });
    const payload = JSON.parse(json).payload as Record<string, unknown>;
    expect(payload.task_sha256).toBe(taskSha256("the full secret prompt"));
    expect(JSON.stringify(payload)).not.toContain("secret prompt");
    expect(payload.task_sha256).not.toBe("the full secret prompt");
  });

  it("resolves ok=false on spawn error (fail-open, never throws)", async () => {
    const { home, python } = await fakeHome();
    fakeSpawn({ error: new Error("timeout") });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s1",
      record: { kind: "session_started", fields: {} },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("timeout");
  });

  it("turn_end / agent_ended mirror records carry their canonical event_type and NO seq", () => {
    for (const kind of ["turn_end", "agent_ended"]) {
      const parsed = JSON.parse(
        buildMirrorEventJson({ kind, fields: { turn_index: 0 } }),
      ) as Record<string, unknown>;
      expect(parsed.event_type).toBe(kind);
      expect(parsed.seq).toBeUndefined(); // ledger auto-assigns (T-G6-F1)
    }
  });

  it("failed append advances NO local sequence state (stateless retry)", async () => {
    // First append is rejected by the ledger (e.g. unknown event type):
    // the mirror resolves ok=false and keeps NO seq/mirror-side state.
    const { home, python } = await fakeHome();
    fakeSpawn({ stdout: "{\"error\":\"brainctl: error: unknown required event type: 'turn_end'\"}" });
    const failed = await mirrorEvent({
      home,
      hostSessionId: "s-fail",
      record: { kind: "turn_end", fields: { turn_index: 0 } },
      python,
    });
    expect(failed.ok).toBe(false);

    // Retry (after the canonical contract fix): the payload is byte-for-byte
    // identical and seq-less — one rejected event cannot poison later writes.
    let stdin = "";
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      const child = { stdin: { write: (s: string) => { stdin = s; }, end: () => {} } };
      cb(null, '{"appended":[1]}');
      return child as never;
    });
    const retried = await mirrorEvent({
      home,
      hostSessionId: "s-fail",
      record: { kind: "turn_end", fields: { turn_index: 0 } },
      python,
    });
    expect(retried.ok).toBe(true);
    const payload = JSON.parse(stdin) as Record<string, unknown>;
    expect(payload.seq).toBeUndefined();
    expect(payload.event_type).toBe("turn_end");
  });

  it("resolves ok=false on CLI error output", async () => {
    const { home, python } = await fakeHome();
    fakeSpawn({ stdout: '{"error":"boom"}' });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s1",
      record: { kind: "turn_end", fields: {} },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toBe("boom");
  });

  it("silent no-op (ok=true) when the brain home has no venv", async () => {
    const result = await mirrorEvent({
      home: "H:/no-such-home",
      hostSessionId: "s1",
      record: { kind: "user_task", fields: {} },
      python: "H:/no-such-home/.venv/Scripts/python.exe",
    });
    expect(result.ok).toBe(true);
    expect(execFileMock).not.toHaveBeenCalled();
  });
});


describe("index.ts wiring — every lifecycle event mirrors one ledger record", () => {
  type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

  function loadFactory(): Map<string, Handler> {
    const handlers = new Map<string, Handler>();
    const pi = {
      on(name: string, handler: Handler) {
        handlers.set(name, handler);
      },
    } as unknown as ExtensionAPI;
    factory(pi);
    return handlers;
  }

  const ctx = {
    cwd: "C:/work",
    model: { id: "deepseek/deepseek-v4-flash" },
    sessionManager: undefined,
  } as unknown as ExtensionContext;

  it("fires mirror records for session_started/user_task/tool_requested/tool_completed/turn_end/agent_ended/compaction/session_inactive", async () => {
    process.env.SECOND_BRAIN_HOME = await fakeHome().then((h) => h.home);
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    const handlers = loadFactory();
    mirrorFireAndForgetMock.mockResolvedValue(undefined);

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("before_agent_start")!({ prompt: "secret task text" }, ctx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "ls" } }, ctx);
    handlers.get("tool_result")!({ toolName: "bash", toolCallId: "c1", input: {}, content: ["out"], details: {}, isError: false }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    handlers.get("agent_end")!({ messages: [] }, ctx);
    handlers.get("session_before_compact")!({ preparation: {}, branchEntries: [] }, ctx);
    handlers.get("session_compact")!({ compactionEntry: {}, fromExtension: false }, ctx);
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    await new Promise((r) => setTimeout(r, 20)); // let fire-and-forget settle
    const kinds = mirrorFireAndForgetMock.mock.calls.map(
      (c) => (c[0] as { record: { kind: string } }).record.kind,
    );
    require("node:fs").writeFileSync("C:/Users/assas/AppData/Local/Temp/kinds-debug.json", JSON.stringify(kinds));
    expect(kinds).toContain("session_started");
    expect(kinds).toContain("user_task");
    expect(kinds).toContain("tool_requested");
    expect(kinds).toContain("tool_completed");
    expect(kinds).toContain("turn_end");
    expect(kinds).toContain("agent_ended");
    expect(kinds).toContain("compaction_started");
    expect(kinds).toContain("compaction_completed");
    expect(kinds).toContain("session_inactive");
    // privacy: user_task payload carries only the hash
    const userTask = mirrorFireAndForgetMock.mock.calls.find(
      (c) => (c[0] as { record: { kind: string } }).record.kind === "user_task",
    )?.[0] as { record: { fields: Record<string, unknown> } };
    expect(userTask.record.fields.task_sha256).toBe(taskSha256("secret task text"));
    expect(JSON.stringify(userTask.record.fields)).not.toContain("secret task text");
    // artifact refs recorded on session_start (reference only)
    expect(kinds).toContain("host_artifact_ref");
  });

  it("EVERY mirror call-site family forwards ctx.cwd (project attribution)", async () => {
    process.env.SECOND_BRAIN_HOME = await fakeHome().then((h) => h.home);
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    const handlers = loadFactory();
    mirrorFireAndForgetMock.mockResolvedValue(undefined);

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("before_agent_start")!({ prompt: "secret task text" }, ctx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "ls" } }, ctx);
    handlers.get("tool_result")!({ toolName: "bash", toolCallId: "c1", input: {}, content: ["out"], details: {}, isError: false }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    handlers.get("agent_end")!({ messages: [] }, ctx);
    handlers.get("session_before_compact")!({ preparation: {}, branchEntries: [] }, ctx);
    handlers.get("session_compact")!({ compactionEntry: {}, fromExtension: false }, ctx);
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    await new Promise((r) => setTimeout(r, 20)); // let fire-and-forget settle
    const calls = mirrorFireAndForgetMock.mock.calls.map((c) => c[0] as {
      hostSessionId: string;
      cwd?: string;
      record: { kind: string };
    });
    expect(calls.length).toBeGreaterThanOrEqual(10); // 10 mirrored kinds + artifact refs
    for (const call of calls) {
      expect(call.cwd, `${call.record.kind} mirror must forward ctx.cwd`).toBe("C:/work");
    }
    // every mirrored kind family is represented
    const kinds = calls.map((c) => c.record.kind);
    for (const kind of [
      "session_started", "user_task", "tool_requested", "tool_completed",
      "turn_end", "agent_ended", "compaction_started", "compaction_completed",
      "session_inactive",
    ]) {
      expect(kinds).toContain(kind);
    }
  });

  it("user_task as the FIRST mirror (before_agent_start alone) still forwards cwd", async () => {
    // Real-run regression (ledger-cwd-ordering-fix): the user_task mirror can
    // be the first to reach the ledger (its `ledger init` spawn wins the
    // per-process race against session_started). It MUST carry ctx.cwd so the
    // init argv includes --cwd and project_id resolves instead of ''.
    process.env.SECOND_BRAIN_HOME = await fakeHome().then((h) => h.home);
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    const handlers = loadFactory();
    mirrorFireAndForgetMock.mockResolvedValue(undefined);

    await handlers.get("before_agent_start")!({ prompt: "secret task text" }, ctx);
    await new Promise((r) => setTimeout(r, 20));
    const userTaskCall = mirrorFireAndForgetMock.mock.calls.find(
      (c) => (c[0] as { record: { kind: string } }).record.kind === "user_task",
    )?.[0] as { cwd?: string; record: { kind: string; fields: Record<string, unknown> } };
    expect(userTaskCall).toBeDefined();
    expect(userTaskCall.cwd).toBe("C:/work");
    // privacy preserved alongside the cwd fix
    expect(userTaskCall.record.fields.task_sha256).toBe(taskSha256("secret task text"));
  });

  it("cwd absent -> every mirror call forwards cwd undefined (init omits the flag)", async () => {
    process.env.SECOND_BRAIN_HOME = await fakeHome().then((h) => h.home);
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    const handlers = loadFactory();
    mirrorFireAndForgetMock.mockResolvedValue(undefined);
    const noCwdCtx = { ...ctx, cwd: "" } as unknown as ExtensionContext;

    handlers.get("session_start")!({ reason: "startup" }, noCwdCtx);
    handlers.get("before_agent_start")!({ prompt: "secret task text" }, noCwdCtx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "ls" } }, noCwdCtx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, noCwdCtx);
    handlers.get("session_shutdown")!({ reason: "quit" }, noCwdCtx);

    await new Promise((r) => setTimeout(r, 20));
    const calls = mirrorFireAndForgetMock.mock.calls.map((c) => c[0] as {
      cwd?: string;
      record: { kind: string };
    });
    expect(calls.length).toBeGreaterThanOrEqual(5);
    for (const call of calls) {
      expect(call.cwd, `${call.record.kind} must NOT fabricate a cwd`).toBeUndefined();
    }
  });
});


describe("T-G4 compaction barrier + segment rollover wiring", () => {
  type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

  function loadFactory(): Map<string, Handler> {
    const handlers = new Map<string, Handler>();
    const pi = {
      on(name: string, handler: Handler) {
        handlers.set(name, handler);
      },
    } as unknown as ExtensionAPI;
    factory(pi);
    return handlers;
  }

  const ctx = {
    cwd: "C:/work",
    model: { id: "deepseek/deepseek-v4-flash" },
    sessionManager: undefined,
  } as unknown as ExtensionContext;

  it("session_before_compact awaits the checkpoint and returns {cancel:true} on failure", async () => {
    const { home } = await fakeHome();
    process.env.SECOND_BRAIN_HOME = home;
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if (args.includes("checkpoint")) {
        cb(new Error("checkpoint failed"));
        return {} as never;
      }
      cb(null, "{}");
      return {} as never;
    });
    const handlers = loadFactory();
    const result = await handlers.get("session_before_compact")!(
      { preparation: {}, branchEntries: [] },
      ctx,
    );
    expect(result).toEqual({ cancel: true }); // never compact on an unproven barrier
  });

  it("session_before_compact returns undefined when the checkpoint proves durability", async () => {
    const { home } = await fakeHome();
    process.env.SECOND_BRAIN_HOME = home;
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if (args.includes("checkpoint")) {
        cb(null, '{"ok":true,"integrity":{"seq_contiguous":true}}');
        return {} as never;
      }
      cb(null, "{}");
      return {} as never;
    });
    const handlers = loadFactory();
    const result = await handlers.get("session_before_compact")!(
      { preparation: {}, branchEntries: [] },
      ctx,
    );
    expect(result).toBeUndefined();
  });

  it("session_compact fires the segment rollover (ledger segment open --reason compact)", async () => {
    const { home } = await fakeHome();
    process.env.SECOND_BRAIN_HOME = home;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      cb(null, "{}");
      return {} as never;
    });
    const handlers = loadFactory();
    handlers.get("session_compact")!({ compactionEntry: {}, fromExtension: false }, ctx);
    await new Promise((r) => setTimeout(r, 20));
    const rolloverCall = execFileMock.mock.calls.find((c) =>
      (c[1] as string[]).includes("segment"),
    );
    expect(rolloverCall).toBeDefined();
    const args = rolloverCall?.[1] as string[];
    expect(args).toContain("segment");
    expect(args).toContain("open");
    expect(args).toContain("--reason");
    expect(args).toContain("compact");
  });
});


describe("T-G6-F1/F2 mirror fixes", () => {
  it("mirror payload carries NO seq key (ledger auto-assigns)", () => {
    const json = buildMirrorEventJson({ kind: "user_task", fields: {} });
    const parsed = JSON.parse(json) as Record<string, unknown>;
    expect(parsed.seq).toBeUndefined();
  });

  it("first event auto-inits the ledger (init argv) then appends; second skips init", async () => {
    const { home, python } = await fakeHome();
    const calls: string[][] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      calls.push(args as string[]);
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const record = { kind: "user_task", fields: { task_sha256: "abc" } };
    await mirrorEvent({ home, hostSessionId: "s-f2", record, python });
    await mirrorEvent({ home, hostSessionId: "s-f2", record, python });
    const initCalls = calls.filter((a) => a.includes("init"));
    const appendCalls = calls.filter((a) => a.includes("append"));
    expect(initCalls.length).toBe(1); // init exactly once per session
    expect(initCalls[0]).toContain("--host");
    expect(initCalls[0]).toContain("prime");
    expect(appendCalls.length).toBe(2); // both events appended
    // different session -> init again
    await mirrorEvent({ home, hostSessionId: "s-f2b", record, python });
    expect(calls.filter((a) => a.includes("init")).length).toBe(2);
  });

  it("auto-init spawns `ledger init --cwd <cwd>` when a cwd is available", async () => {
    const { home, python } = await fakeHome();
    const calls: string[][] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      calls.push(args as string[]);
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const record = { kind: "user_task", fields: { task_sha256: "abc" } };
    await mirrorEvent({ home, hostSessionId: "s-cwd", record, python, cwd: "C:/proj/x" });
    const initCall = calls.find((a) => a.includes("init"));
    expect(initCall).toBeDefined();
    // --cwd is the LAST init arg (append never carries it)
    expect(initCall).toEqual([
      "-m", "second_brain", "ledger", "init",
      "--session", "s-cwd", "--host", "prime", "--cwd", "C:/proj/x",
    ]);
    expect(calls[1]).not.toContain("--cwd");
  });

  it("auto-init omits --cwd when none is available (never garbage)", async () => {
    const { home, python } = await fakeHome();
    const calls: string[][] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      calls.push(args as string[]);
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const record = { kind: "user_task", fields: { task_sha256: "abc" } };
    await mirrorEvent({ home, hostSessionId: "s-nocwd", record, python });
    const initCall = calls.find((a) => a.includes("init"));
    expect(initCall).toBeDefined();
    expect(initCall).not.toContain("--cwd");
    expect(initCall).toEqual([
      "-m", "second_brain", "ledger", "init",
      "--session", "s-nocwd", "--host", "prime",
    ]);
  });

  it("init failure -> ok=false with ledger init error (no append attempted)", async () => {
    const { home, python } = await fakeHome();
    resetMirrorInitCache();
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if (args.includes("init")) {
        cb(new Error("init boom"));
        return {} as never;
      }
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-f2c",
      record: { kind: "user_task", fields: {} },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("ledger init");
    const appends = execFileMock.mock.calls.filter((c) =>
      (c[1] as string[]).includes("append"),
    );
    expect(appends.length).toBe(0);
  });
});
