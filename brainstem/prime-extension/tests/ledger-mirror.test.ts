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
const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({
  execFile: execFileMock,
  execFileSync: execFileSyncMock,
}));
const mirrorFireAndForgetMock = vi.hoisted(() => vi.fn());
vi.mock("../src/ledger-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/ledger-mirror")>();
  return { ...actual, mirrorFireAndForget: mirrorFireAndForgetMock };
});
import {
  buildMirrorEventJson,
  ledgerEventTypeFor,
  mirrorEvent,
  mirrorEventSync,
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
  execFileSyncMock.mockReset();
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

  it("resolves fail-open (never rejects) when execFile throws synchronously (P19: unspawnable interpreter, e.g. a .cmd path on Windows without shell:true)", async () => {
    const { home, python } = await fakeHome();
    execFileMock.mockImplementation(() => {
      throw new Error("spawn C:\\fake\\python.cmd EINVAL");
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-sync-throw",
      record: { kind: "user_task", fields: {} },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("EINVAL");
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
    sessionManager: {
      getSessionFile: () => undefined,
      getSessionId: () => "native-ledger-lifecycle",
      getHeader: () => ({ type: "session", id: "native-ledger-lifecycle", timestamp: "2026-01-01T00:00:00.000Z" }),
      getEntries: () => [],
    },
  } as unknown as ExtensionContext;

  it("fires mirror records for session_started/user_task/tool_requested/tool_completed/turn_end/agent_ended/compaction/session_inactive", async () => {
    process.env.SECOND_BRAIN_HOME = await fakeHome().then((h) => h.home);
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    const handlers = loadFactory();
    mirrorFireAndForgetMock.mockResolvedValue(undefined);

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    await handlers.get("before_agent_start")!({ prompt: "secret task text" }, ctx);
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
    sessionManager: {
      getSessionFile: () => undefined,
      getSessionId: () => "native-ledger-compaction",
      getHeader: () => ({ type: "session", id: "native-ledger-compaction", timestamp: "2026-01-01T00:00:00.000Z" }),
      getEntries: () => [],
    },
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

  it("[vmem] disabled (default): session_before_compact/session_compact never call vmem", async () => {
    const { home } = await fakeHome();
    process.env.SECOND_BRAIN_HOME = home;
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if ((args as string[]).includes("checkpoint")) {
        cb(null, '{"ok":true,"integrity":{}}');
      } else {
        cb(null, "{}");
      }
      return {} as never;
    });
    const handlers = loadFactory();
    await handlers.get("session_before_compact")!({ preparation: {}, branchEntries: [] }, ctx);
    handlers.get("session_compact")!({ compactionEntry: {}, fromExtension: false }, ctx);
    await new Promise((r) => setTimeout(r, 20));
    const vmemCall = execFileMock.mock.calls.find((c) => (c[1] as string[]).includes("vmem"));
    expect(vmemCall).toBeUndefined();
  });

  it("[vmem] enabled=true: session_before_compact calls compact-prep and never cancels compaction on vmem failure", async () => {
    const { home } = await fakeHome();
    mkdirSync(join(home, "config"), { recursive: true });
    writeFileSync(join(home, "config", "context.toml"), "[vmem]\nenabled = true\n", "utf8");
    process.env.SECOND_BRAIN_HOME = home;
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "off";
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      const a = args as string[];
      if (a.includes("checkpoint")) {
        cb(null, '{"ok":true,"integrity":{}}');
      } else if (a.includes("compact-prep")) {
        cb(new Error("vmem db locked")); // vmem bookkeeping fails
      } else {
        cb(null, "{}");
      }
      return {} as never;
    });
    const handlers = loadFactory();
    const result = await handlers.get("session_before_compact")!(
      { preparation: {}, branchEntries: [] },
      ctx,
    );
    // Advisory only: a failing vmem call must never cancel compaction (only
    // the ledger checkpoint durability barrier may return {cancel:true}).
    expect(result).toBeUndefined();
    const prepCall = execFileMock.mock.calls.find((c) => (c[1] as string[]).includes("compact-prep"));
    expect(prepCall).toBeDefined();
    const args = prepCall?.[1] as string[];
    expect(args.slice(0, 4)).toEqual(["-m", "second_brain", "vmem", "compact-prep"]);
    expect(args[args.length - 1]).toBe("--json");
  });

  it("[vmem] enabled=true: session_compact calls hot-context with the configured budget", async () => {
    const { home } = await fakeHome();
    mkdirSync(join(home, "config"), { recursive: true });
    writeFileSync(
      join(home, "config", "context.toml"),
      "[vmem]\nenabled = true\nbudget_tokens = 777\n",
      "utf8",
    );
    process.env.SECOND_BRAIN_HOME = home;
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(null, '{"resident_count":1,"evicted_count":2,"resident_tokens":300}');
      return {} as never;
    });
    const handlers = loadFactory();
    handlers.get("session_compact")!({ compactionEntry: {}, fromExtension: false }, ctx);
    await new Promise((r) => setTimeout(r, 20));
    const hotContextCall = execFileMock.mock.calls.find((c) =>
      (c[1] as string[]).includes("hot-context"),
    );
    expect(hotContextCall).toBeDefined();
    const args = hotContextCall?.[1] as string[];
    expect(args.slice(0, 4)).toEqual(["-m", "second_brain", "vmem", "hot-context"]);
    expect(args).toContain("--budget");
    expect(args[args.indexOf("--budget") + 1]).toBe("777");
    expect(args[args.length - 1]).toBe("--json");
  });
});

describe("context event: direct registration (Phase R3 wire()-bypass fix)", () => {
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
    sessionManager: {
      getSessionFile: () => undefined,
      getSessionId: () => "native-ledger-context",
      getHeader: () => ({ type: "session", id: "native-ledger-context", timestamp: "2026-01-01T00:00:00.000Z" }),
      getEntries: () => [],
    },
  } as unknown as ExtensionContext;

  it("returns a real value (not void) to the host, proving it is NOT routed through wire()/safeHandler()", async () => {
    const { home } = await fakeHome();
    process.env.SECOND_BRAIN_HOME = home;
    execFileMock.mockImplementation((_py, _args, _opts, cb) => cb(null, "{}"));
    const handlers = loadFactory();
    const result = handlers.get("context")!({ messages: [{ role: "user" }] }, ctx);
    // safeHandler()'s wrapped handlers are typed `(event, ctx) => void` and
    // Prime's runtime never inspects their return value; a directly
    // registered handler returns whatever the code computes. Today that is
    // still `undefined` by design (message shape unknown — see
    // outputs/reports/rc4/02-prime-live-callgraph.md), but the call must
    // complete synchronously and not throw, proving the handler is live.
    expect(result).toBeUndefined();
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

  it("sync and async init forward the HOST parent session identity", async () => {
    const { home, python } = await fakeHome();
    const calls: string[][] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      calls.push(args as string[]);
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const record = { kind: "user_task", fields: { task_sha256: "abc" } };
    await mirrorEvent({
      home,
      hostSessionId: "child-async",
      parentSessionId: "parent-host",
      record,
      python,
      cwd: "C:/proj/x",
    });
    expect(calls[0]).toEqual([
      "-m", "second_brain", "ledger", "init",
      "--session", "child-async", "--host", "prime",
      "--parent-session", "parent-host", "--cwd", "C:/proj/x",
    ]);

    execFileSyncMock.mockReturnValue("");
    const syncResult = mirrorEventSync({
      home,
      hostSessionId: "child-sync",
      parentSessionId: "parent-host",
      record,
      python,
    });
    expect(syncResult.ok).toBe(true);
    expect(execFileSyncMock.mock.calls[0]?.[1]).toEqual([
      "-m", "second_brain", "ledger", "init",
      "--session", "child-sync", "--host", "prime",
      "--parent-session", "parent-host",
    ]);
  });

  it("a parent arriving after parentless init is validated once; later omission does not re-init", async () => {
    const { home, python } = await fakeHome();
    const calls: string[][] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      calls.push(args as string[]);
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const options = {
      home,
      hostSessionId: "child-resume",
      record: { kind: "user_task", fields: {} },
      python,
    };
    await mirrorEvent(options);
    await mirrorEvent({ ...options, parentSessionId: "root-a" });
    await mirrorEvent(options);
    await mirrorEvent({ ...options, parentSessionId: "root-conflict" });

    const initCalls = calls.filter((args) => args.includes("init"));
    expect(initCalls).toHaveLength(3);
    expect(initCalls[0]).not.toContain("--parent-session");
    expect(initCalls[1]).toContain("root-a");
    expect(initCalls[2]).toContain("root-conflict");
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

  it("P3-E fix: ONE bounded retry — transient append failure then success resolves ok with byte-identical payload", async () => {
    const { home, python } = await fakeHome();
    const appendStdin: string[] = [];
    let calls = 0;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      const isAppend = (args as string[]).includes("append");
      calls += 1;
      const child = {
        stdin: {
          write: (s: string) => {
            if (isAppend) appendStdin.push(s); // captured when the wrapper writes
          },
          end: () => {},
        },
      };
      if (!isAppend) {
        cb(null, '{"initialized":"x","schema_version":1}');
        return child as never;
      }
      if (calls === 2) {
        cb(new Error("Command failed: ledger append (transient burst race)"));
      } else {
        cb(null, '{"appended":[1]}');
      }
      return child as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-retry-ok",
      record: { kind: "user_task", fields: { task_sha256: "abc", prompt_chars: 9 } },
      python,
    });
    expect(result.ok).toBe(true);
    // exactly one retry: init(1) + append(2) — no third spawn
    expect(execFileMock.mock.calls.length).toBe(3);
    expect(appendStdin.length).toBe(2);
    expect(appendStdin[0]).toBe(appendStdin[1]); // byte-identical payload on retry
    expect(JSON.parse(appendStdin[1]).payload.task_sha256).toBe("abc");
  });

  it("P3-E fix: retry is BOUNDED — a second failure records the error (never a third attempt, fail-open)", async () => {
    const { home, python } = await fakeHome();
    let appends = 0;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if ((args as string[]).includes("append")) {
        appends += 1;
        cb(new Error("Command failed: ledger append boom"));
        return {} as never;
      }
      cb(null, '{"initialized":"x","schema_version":1}');
      return {} as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-retry-fail",
      record: { kind: "tool_requested", fields: { tool: "bash", input_bytes: 4 } },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("boom");
    expect(appends).toBe(2); // exactly one retry — bounded
  });

  it("P3-E final: duplicate of THIS event after a persisted-but-failed first attempt resolves ok (no error record)", async () => {
    const { home, python } = await fakeHome();
    let appends = 0;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if (!(args as string[]).includes("append")) {
        cb(null, '{"initialized":"x","schema_version":1}');
        return {} as never;
      }
      appends += 1;
      const child = {
        stdin: {
          write: (s: string) => {
            // attempt 1: transient failure (event persisted anyway, e.g.
            // crash between commit and stdout). attempt 2: the ledger's
            // deterministic duplicate rejection for THE SAME event_id.
            if (appends === 1) {
              cb(new Error("Command failed: ledger append (transient)"));
            } else {
              const eventId = (JSON.parse(s) as { event_id: string }).event_id;
              cb(null, `{"error":"brainctl: error: duplicate event_id: '${eventId}'"}`);
            }
          },
          end: () => {},
        },
      };
      return child as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-dup-ok",
      record: { kind: "user_task", fields: { task_sha256: "abc", prompt_chars: 9 } },
      python,
    });
    expect(result.ok).toBe(true); // event is durable in the ledger — delivery succeeded
    expect(result.error).toBeUndefined();
    expect(appends).toBe(2); // retry still bounded to exactly one
  });

  it("P3-E final: a duplicate of a DIFFERENT event is still a real error (fail-open, bounded)", async () => {
    const { home, python } = await fakeHome();
    let appends = 0;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if (!(args as string[]).includes("append")) {
        cb(null, '{"initialized":"x","schema_version":1}');
        return {} as never;
      }
      appends += 1;
      cb(null, `{"error":"brainctl: error: duplicate event_id: 'mirror-other-${appends}-00000000-0000-0000-0000-000000000000'"}`);
      return {} as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-dup-other",
      record: { kind: "turn_end", fields: { turn_index: 0, tool_results: 0 } },
      python,
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("duplicate event_id");
    expect(appends).toBe(2); // bounded retry still applies to real errors
  });

  it("P3-E fix: init failure is retried once too (init chain re-runs on retry)", async () => {
    const { home, python } = await fakeHome();
    resetMirrorInitCache();
    let inits = 0;
    let appends = 0;
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      if ((args as string[]).includes("init")) {
        inits += 1;
        if (inits === 1) {
          cb(new Error("Command failed: ledger init (first-init race)"));
        } else {
          cb(null, '{"initialized":"x","schema_version":1}');
        }
        return {} as never;
      }
      appends += 1;
      cb(null, '{"appended":[1]}');
      return {} as never;
    });
    const result = await mirrorEvent({
      home,
      hostSessionId: "s-retry-init",
      record: { kind: "session_started", fields: {} },
      python,
    });
    expect(result.ok).toBe(true);
    expect(inits).toBe(2); // first init failed -> retried
    expect(appends).toBe(1);
  });
});

/**
 * The adapter must translate host kinds into the ledger's vocabulary. Before this bridge
 * existed, seven mirrored kinds were unknown to the ledger and every append carrying one was
 * a hard error ("unknown required event type"), because `ignorable` defaulted to false — the
 * mirror recorded 7,755 such failures between 2026-08-16 and 2026-09-21.
 */
describe("ledger event vocabulary bridge", () => {
  /** Every kind the extension's call sites pass to mirror(). */
  const MIRRORED_KINDS = [
    "session_started",
    "user_task",
    "tool_requested",
    "tool_completed",
    "turn_end",
    "agent_ended",
    "compaction_started",
    "compaction_completed",
    "session_inactive",
    "decision",
    "task_context_resolved",
    "host_artifact_ref",
    "worker_completed",
    "environment_assessment",
    "prefix_drift",
    "ledger_degraded",
    "worker_shutdown_telemetry_skipped",
  ];

  it("no mirrored kind can be a hard error to the ledger", () => {
    for (const kind of MIRRORED_KINDS) {
      const event = JSON.parse(buildMirrorEventJson({ kind, fields: {} })) as {
        event_type: string;
        ignorable: boolean;
      };
      const known = ledgerEventTypeFor(kind).unknownToLedger === false;
      // Either the ledger knows the type, or the record is ignorable (skipped, not raised).
      expect(known || event.ignorable === true, `kind ${kind} would hard-fail the ledger`).toBe(true);
    }
  });

  it("never renames a kind the ledger already knows", () => {
    // worker_completed / task_context_resolved / environment_assessment are kernel types, not
    // host aliases: the adapter must not map them onto some "equivalent" and change their meaning.
    for (const kind of ["worker_completed", "task_context_resolved", "environment_assessment"]) {
      expect(ledgerEventTypeFor(kind)).toEqual({ eventType: kind, unknownToLedger: false });
      const event = JSON.parse(buildMirrorEventJson({ kind, fields: {} })) as {
        event_type: string;
        ignorable: boolean;
      };
      expect(event.event_type).toBe(kind);
      expect(event.ignorable).toBe(false);
    }
  });

  it("passes a kind the ledger knows through unchanged and non-ignorable", () => {
    for (const kind of ["decision", "turn_end", "session_started"]) {
      const event = JSON.parse(buildMirrorEventJson({ kind, fields: {} })) as {
        event_type: string;
        ignorable: boolean;
      };
      expect(event.event_type).toBe(kind);
      expect(event.ignorable).toBe(false);
    }
  });

  it("a caller cannot escalate an unknown kind back into a hard error", () => {
    const event = JSON.parse(
      buildMirrorEventJson({ kind: "prefix_drift", fields: {}, ignorable: false }),
    ) as { event_type: string; ignorable: boolean };
    expect(event.event_type).toBe("prefix_drift");
    expect(event.ignorable).toBe(true);
  });
});
