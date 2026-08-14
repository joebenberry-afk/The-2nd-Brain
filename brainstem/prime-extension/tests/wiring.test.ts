import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import factory from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

/**
 * Wiring tests: exercise the REAL factory from src/index.ts through a fake
 * ExtensionAPI / ExtensionContext, with SECOND_BRAIN_HOME pointed at a per-
 * test temp dir so nothing ever touches the real brain.
 */

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

const SAVED_ENV: Record<string, string | undefined> = {};
let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-wiring-"));
  SAVED_ENV.SECOND_BRAIN_HOME = process.env.SECOND_BRAIN_HOME;
  SAVED_ENV.SECOND_BRAIN_OBSERVABILITY = process.env.SECOND_BRAIN_OBSERVABILITY;
  process.env.SECOND_BRAIN_HOME = tmp;
  delete process.env.SECOND_BRAIN_OBSERVABILITY;
});

afterEach(async () => {
  if (SAVED_ENV.SECOND_BRAIN_HOME === undefined) delete process.env.SECOND_BRAIN_HOME;
  else process.env.SECOND_BRAIN_HOME = SAVED_ENV.SECOND_BRAIN_HOME;
  if (SAVED_ENV.SECOND_BRAIN_OBSERVABILITY === undefined) delete process.env.SECOND_BRAIN_OBSERVABILITY;
  else process.env.SECOND_BRAIN_OBSERVABILITY = SAVED_ENV.SECOND_BRAIN_OBSERVABILITY;
  await rm(tmp, { recursive: true, force: true });
});

/** Load the factory with a recording fake ExtensionAPI. */
function loadFactory(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
  } as unknown as ExtensionAPI;
  factory(pi);
  return handlers;
}

/** Fake ExtensionContext; session file lives inside the temp dir. */
function makeCtx(overrides: Partial<ExtensionContext> = {}): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    sessionManager: {
      getSessionFile: () => join(tmp, "sessions", "wiring-test.jsonl"),
    },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    signal: undefined,
    hasUI: false,
    ui: undefined,
    ...overrides,
  };
}

function telemetryFile(): string {
  return join(tmp, "telemetry", "agent-performance", "wiring-test.jsonl");
}

function telemetryDir(): string {
  return join(tmp, "telemetry", "agent-performance");
}

/** Poll-read until the file has at least `minLines` JSONL lines. */
async function waitForLines(minLines: number, timeoutMs = 3000): Promise<Record<string, unknown>[]> {
  const file = telemetryFile();
  const deadline = Date.now() + timeoutMs;
  let last: string[] = [];
  while (Date.now() < deadline) {
    try {
      last = (await readFile(file, "utf8")).split("\n").filter((l) => l.trim().length > 0);
      if (last.length >= minLines) return last.map((l) => JSON.parse(l));
    } catch {
      // file not created yet
    }
    await new Promise((r) => setTimeout(r, 15));
  }
  throw new Error(`timed out waiting for ${minLines} lines in ${file}; got ${last.length}`);
}

/** Poll-read the telemetry dir for any .jsonl (unknown session stem). */
async function waitForAnyTelemetryFile(timeoutMs = 3000): Promise<string> {
  const dir = telemetryDir();
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const names = (await readdir(dir)).filter((n) => n.endsWith(".jsonl"));
      if (names.length > 0) return join(dir, names[0]);
    } catch {
      // dir not created yet
    }
    await new Promise((r) => setTimeout(r, 15));
  }
  throw new Error("no telemetry file appeared");
}

const EVENTS: Array<[string, unknown]> = [
  ["session_start", { reason: "startup" }],
  ["before_agent_start", { prompt: "hello world" }],
  ["turn_start", { turnIndex: 0 }],
  ["context", { messages: [{}, {}] }],
  ["tool_call", { toolName: "bash", toolCallId: "c1", input: { command: "echo hi" } }],
  ["tool_result", { toolName: "bash", toolCallId: "c1", input: {}, content: [], details: {}, isError: false }],
  ["turn_end", { turnIndex: 0, message: {}, toolResults: [] }],
  ["agent_end", { messages: [] }],
  ["session_before_compact", { preparation: {}, branchEntries: [] }],
  ["session_compact", { compactionEntry: {}, fromExtension: false }],
  ["session_shutdown", { reason: "quit" }],
];

describe("factory wiring (src/index.ts)", () => {
  it("subscribes exactly the 11 lifecycle events", () => {
    const handlers = loadFactory();
    expect([...handlers.keys()].sort()).toEqual(EVENTS.map(([name]) => name).sort());
  });

  it("every handler returns undefined (void) and still writes one record each", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    expect(handlers.size).toBe(11);
    for (const [name, event] of EVENTS) {
      const handler = handlers.get(name);
      expect(handler, `handler for ${name}`).toBeDefined();
      const result = handler!(event, ctx);
      expect(result, `${name} handler returned a value`).toBeUndefined();
    }
    // all 11 records land in the same session file (fire-and-forget drained).
    // NOTE: invoked back-to-back, the sync final write for session_shutdown can
    // land ahead of still-queued async writes, so order is asserted as a set
    // here; real ordering (shutdown last) is covered by the dedicated test
    // below, where prior writes have settled before shutdown fires.
    const records = await waitForLines(11);
    expect(records.map((r) => r.kind).sort()).toEqual(EVENTS.map(([name]) => name).sort());
    for (const rec of records) {
      expect(rec.v).toBe(2);
      expect(rec.session).toBe("wiring-test");
    }
  });

  it("session_shutdown is the final record once prior writes have settled", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    const records = await waitForLines(2); // async writes drained
    expect(records.map((r) => r.kind)).toEqual(["session_start", "turn_end"]);

    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);
    const final = await waitForLines(3);
    expect(final.map((r) => r.kind)).toEqual(["session_start", "turn_end", "session_shutdown"]);
  });

  it("tool_call handler never mutates event.input", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const input = { command: "echo hi", marker: "keep-me", nested: { a: 1, b: [1, 2] } };
    const original = structuredClone(input);
    const event = { toolName: "bash", toolCallId: "c1", input };

    const result = handlers.get("tool_call")!(event, ctx);
    expect(result).toBeUndefined();
    expect(event.input).toEqual(original); // deep-equal: untouched

    const [rec] = await waitForLines(1);
    expect(rec.kind).toBe("tool_call");
    expect(rec.tool).toBe("bash");
    expect(rec.command).toBe("echo hi");
    expect(typeof rec.input_bytes).toBe("number");
  });

  it("swallows a throwing getContextUsage and still records turn_end with null usage", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx({
      getContextUsage: () => {
        throw new Error("usage boom");
      },
    });

    expect(() =>
      handlers.get("turn_end")!({ turnIndex: 1, message: {}, toolResults: [{}] }, ctx),
    ).not.toThrow();

    const [rec] = await waitForLines(1);
    expect(rec.kind).toBe("turn_end");
    expect(rec.turn).toBe(1);
    expect(rec.context_usage).toBeNull();
    expect(rec.tool_results).toBe(1);
  });

  it("swallows a throwing sessionManager and records under an anonymous session id", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx({
      sessionManager: {
        getSessionFile: () => {
          throw new Error("session boom");
        },
      },
    });

    expect(() => handlers.get("turn_start")!({ turnIndex: 0 }, ctx)).not.toThrow();

    const file = await waitForAnyTelemetryFile();
    const [rec] = (await readFile(file, "utf8"))
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l));
    expect(rec.kind).toBe("turn_start");
    expect(rec.session).toMatch(/^anon-/);
  });

  it("swallows mapper exceptions and appends an extension_error record", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    // event.prompt getter throws -> before_agent_start mapper throws
    const event: Record<string, unknown> = {};
    Object.defineProperty(event, "prompt", {
      get() {
        throw new Error("prompt boom");
      },
    });

    expect(() => handlers.get("before_agent_start")!(event, ctx)).not.toThrow();

    const [rec] = await waitForLines(1);
    expect(rec.kind).toBe("extension_error");
    expect(rec.error).toBe("prompt boom");
    expect(rec.session).toBe("wiring-test");
  });

  it("writes schema-shaped records for session_start + turn_end", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("turn_end")!({ turnIndex: 2, message: {}, toolResults: [{}, {}] }, ctx);

    const records = await waitForLines(2);
    expect(records[0]).toMatchObject({
      v: 2,
      kind: "session_start",
      session: "wiring-test",
      reason: "startup",
      cwd: "C:/work",
      model: "deepseek/deepseek-v4-flash",
    });
    expect(records[1]).toMatchObject({
      v: 2,
      kind: "turn_end",
      session: "wiring-test",
      turn: 2,
      context_usage: { used: 10, total: 1000, percent: 1 },
      tool_results: 2,
    });
    expect(typeof records[0].ts).toBe("string");
  });

  it("registers no handlers when the env gate disables the extension", () => {
    process.env.SECOND_BRAIN_OBSERVABILITY = "off";
    const handlers = loadFactory();
    expect(handlers.size).toBe(0);
  });
});
