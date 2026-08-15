import { mkdirSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import { createTelemetryDirEnsurer } from "../src/storage";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

/**
 * Wiring tests: exercise the REAL factory from src/index.ts through a fake
 * ExtensionAPI / ExtensionContext, with SECOND_BRAIN_HOME pointed at a per-
 * test temp dir so nothing ever touches the real brain.
 */

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

const ENV_KEYS = [
  "SECOND_BRAIN_HOME",
  "SECOND_BRAIN_OBSERVABILITY",
  "SECOND_BRAIN_RTD",
  "SECOND_BRAIN_RTD_THRESHOLD",
] as const;
const SAVED_ENV: Record<string, string | undefined> = {};
let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-wiring-"));
  for (const key of ENV_KEYS) {
    SAVED_ENV[key] = process.env[key];
    delete process.env[key];
  }
  process.env.SECOND_BRAIN_HOME = tmp;
});

afterEach(async () => {
  for (const key of ENV_KEYS) {
    if (SAVED_ENV[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED_ENV[key] as string;
  }
  await rm(tmp, { recursive: true, force: true });
});

/** Load the factory with a recording fake ExtensionAPI (+ optional options). */
function loadFactory(options?: ExtensionOptions): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
  } as unknown as ExtensionAPI;
  factory(pi, options);
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

/** Give pending fire-and-forget writes a chance to land (negative assertions). */
async function settle(ms = 150): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

/** Poll-read a specific telemetry file until it has `minLines` JSONL lines. */
async function waitForFileLines(file: string, minLines: number, timeoutMs = 3000): Promise<Record<string, unknown>[]> {
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

/** Context with NO session file: forces the anonymous fallback path. */
function anonCtx(): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    sessionManager: { getSessionFile: () => undefined },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    signal: undefined,
    hasUI: false,
    ui: undefined,
  };
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

  // -------------------------------------------------------------------------
  // Phase 5 RTD shadow wiring
  // -------------------------------------------------------------------------

  it("tool_result with big bash pytest output writes rtd_shadow (shadow only)", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const bigContent = [{ type: "text", text: "x".repeat(9000) }];
    const input = { command: "pytest -q tests/", timeout: 120 };
    const originalInput = structuredClone(input);

    const result = handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-1", input, content: bigContent, details: {}, isError: false },
      ctx,
    );
    expect(result).toBeUndefined();
    expect(input).toEqual(originalInput); // input unmutated

    const records = await waitForLines(2); // tool_result + rtd_shadow
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toBeDefined();
    expect(shadow).toMatchObject({
      v: 2,
      kind: "rtd_shadow",
      session: "wiring-test",
      tool: "bash",
      id: "rtd-1",
      would_trigger: true,
      reason: "ok",
      threshold: 8000, // default, env unset
    });
    expect(shadow!.size).toBeGreaterThan(8000);
    // privacy: neither command text nor content is ever stored
    expect(JSON.stringify(records)).not.toContain("pytest -q");
    expect(JSON.stringify(records)).not.toContain("xxxx");
  });

  it("tool_result with small output writes no rtd_shadow", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-2", input: { command: "pytest -q" }, content: "ok", details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["tool_result"]);
    await settle();
    const after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_result"]);
  });

  it("tool_result with big non-bash output writes no rtd_shadow", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("tool_result")!(
      { toolName: "ipython", toolCallId: "rtd-3", input: { code: "print(1)" }, content: "x".repeat(9000), details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["tool_result"]);
    await settle();
    const after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_result"]);
  });

  it("SECOND_BRAIN_RTD=active logs intent without substituting", async () => {
    process.env.SECOND_BRAIN_RTD = "active";
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-4", input: { command: "git status" }, content: "y".repeat(9000), details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(2);
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toMatchObject({
      reason: "would-substitute",
      substitution: "enabled-not-implemented",
      would_trigger: true,
      tool: "bash",
    });
  });

  it("SECOND_BRAIN_RTD_THRESHOLD overrides the default threshold", async () => {
    process.env.SECOND_BRAIN_RTD_THRESHOLD = "100";
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-5", input: { command: "rg pattern" }, content: "z".repeat(500), details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(2);
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toMatchObject({ threshold: 100, would_trigger: true, reason: "ok" });
    expect(shadow!.size).toBe(502); // 500 chars + 2 JSON quotes
  });
});

// -------------------------------------------------------------------------
// Phase 2: stable anonymous session identity (one id per extension lifecycle)
// -------------------------------------------------------------------------

describe("Phase 2 anonymous session identity (src/index.ts)", () => {
  it("reuses ONE stable anonymous id for every event without a session file", async () => {
    const handlers = loadFactory();
    const ctx = anonCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "echo hi" } }, ctx);
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    const file = await waitForAnyTelemetryFile();
    const records = await waitForFileLines(file, 4);
    const sessions = new Set(records.map((r) => String(r.session)));
    expect(sessions.size).toBe(1);
    expect([...sessions][0]).toMatch(/^anon-/);
  });

  it("appends all anonymous lifecycle events to ONE telemetry file, not one per event", async () => {
    const handlers = loadFactory();
    const ctx = anonCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("before_agent_start")!({ prompt: "hello" }, ctx);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "echo hi" } }, ctx);
    handlers.get("tool_result")!({ toolName: "bash", toolCallId: "c1", input: {}, content: [], details: {}, isError: false }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    handlers.get("agent_end")!({ messages: [] }, ctx);
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    const file = await waitForAnyTelemetryFile();
    const records = await waitForFileLines(file, 8);
    await settle();
    const names = (await readdir(telemetryDir())).filter((n) => n.endsWith(".jsonl"));
    expect(names.length).toBe(1); // one session file for the whole anonymous lifecycle
    expect(records.map((r) => r.kind).sort()).toEqual(
      ["session_start", "before_agent_start", "turn_start", "tool_call", "tool_result", "turn_end", "agent_end", "session_shutdown"].sort(),
    );
    expect(new Set(records.map((r) => String(r.session))).size).toBe(1);
  });

  it("separate extension lifecycles get distinct anonymous ids (deterministic)", async () => {
    // Deterministic: two factories consume two different Math.random draws.
    const randomSpy = vi.spyOn(Math, "random").mockReturnValueOnce(0.5).mockReturnValueOnce(0.25);
    try {
      const handlersA = loadFactory();
      const handlersB = loadFactory();
      handlersA.get("turn_start")!({ turnIndex: 0 }, anonCtx());
      handlersB.get("turn_start")!({ turnIndex: 0 }, anonCtx());

      const fileA = await waitForAnyTelemetryFile();
      await settle(250);
      const names = (await readdir(telemetryDir())).filter((n) => n.endsWith(".jsonl"));
      expect(names.length).toBe(2);
      const fileB = names.map((n) => join(telemetryDir(), n)).find((f) => f !== fileA)!;
      const [recA] = await waitForFileLines(fileA, 1);
      const [recB] = await waitForFileLines(fileB, 1);
      expect(recA.session).toMatch(/^anon-/);
      expect(recB.session).toMatch(/^anon-/);
      expect(recA.session).not.toBe(recB.session);
    } finally {
      randomSpy.mockRestore();
    }
  });

  it("explicit Prime session file stem still overrides the fallback, byte-for-byte", async () => {
    const handlers = loadFactory();
    // First event has NO session file -> anonymous fallback caches one id.
    handlers.get("turn_start")!({ turnIndex: 0 }, anonCtx());
    const anonFile = await waitForAnyTelemetryFile();
    const [anonRec] = await waitForFileLines(anonFile, 1);
    expect(anonRec.session).toMatch(/^anon-/);

    // Later events WITH an explicit session file must still use the explicit
    // stem (explicit identity always wins over the cached fallback).
    const ctx = makeCtx(); // getSessionFile -> .../wiring-test.jsonl
    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);

    const records = await waitForLines(2); // wiring-test.jsonl
    expect(records.map((r) => String(r.session))).toEqual(["wiring-test", "wiring-test"]);
    await settle();
    // anon file unchanged: still exactly the one anonymous record
    const anonAfter = (await readFile(anonFile, "utf8")).trim().split("\n").filter(Boolean);
    expect(anonAfter.map((l) => JSON.parse(l).kind)).toEqual(["turn_start"]);
  });
});

// -------------------------------------------------------------------------
// Phase 3: RTD hot path — eligibility first, content measured once and shared
// -------------------------------------------------------------------------

describe("Phase 3 RTD hot path (src/index.ts)", () => {
  it("ineligible tool/command: no RTD shadow record, telemetry still measured once", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    let stringifyCount = 0;
    const content = {
      toJSON() {
        stringifyCount += 1;
        return { text: "x".repeat(9000) };
      },
    };

    // ipython tool with big content: ineligible by tool
    handlers.get("tool_result")!(
      { toolName: "ipython", toolCallId: "rtd-t-1", input: { code: "print(1)" }, content, details: {}, isError: false },
      ctx,
    );
    let records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["tool_result"]);
    await settle();
    let after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_result"]);

    // bash tool with ineligible command and big content
    const before = stringifyCount;
    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-t-2", input: { command: "ls -la" }, content, details: {}, isError: false },
      ctx,
    );
    await waitForLines(2);
    await settle();
    after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_result", "tool_result"]);
    // the measurement was the telemetry one (one stringify per event), no extra RTD work
    expect(stringifyCount).toBe(before + 1);
  });

  it("eligible result: content serialized exactly once, output_bytes and rtd_shadow.size share the same measurement", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    let stringifyCount = 0;
    const content = {
      toJSON() {
        stringifyCount += 1;
        return { type: "text", text: "x".repeat(9000) };
      },
    };

    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-shared-1", input: { command: "pytest -q" }, content, details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(2); // tool_result + rtd_shadow
    const result = records.find((r) => r.kind === "tool_result");
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(result).toBeDefined();
    expect(shadow).toBeDefined();
    // ASCII object: serialized chars == UTF-8 bytes, so both consumers report the SAME number
    expect(shadow!.size).toBe(result!.output_bytes);
    expect(shadow!.size).toBeGreaterThan(8000);
    expect(shadow).toMatchObject({
      reason: "ok",
      threshold: 8000,
      would_trigger: true,
      tool: "bash",
      id: "rtd-shared-1",
    });
    // ONE serialization served both records — nothing re-serialized afterwards
    expect(stringifyCount).toBe(1);
    // privacy: no content payload anywhere
    expect(JSON.stringify(records)).not.toContain('"xxxx');
    expect(JSON.stringify(records)).not.toContain("pytest -q");
  });

  it("eligible string result: telemetry raw-string bytes and RTD JSON char length stay divergent-legacy", async () => {
    process.env.SECOND_BRAIN_RTD_THRESHOLD = "100";
    const handlers = loadFactory();
    const ctx = makeCtx();
    // 500 ASCII chars: JSON char length 502 (quotes), raw UTF-8 bytes 500
    handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-str-1", input: { command: "rg pattern" }, content: "z".repeat(500), details: {}, isError: false },
      ctx,
    );
    const records = await waitForLines(2);
    const result = records.find((r) => r.kind === "tool_result");
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(result!.output_bytes).toBe(500);
    expect(shadow!.size).toBe(502); // legacy JSON char length preserved
    expect(shadow).toMatchObject({ threshold: 100, would_trigger: true, reason: "ok" });
  });
});

// -------------------------------------------------------------------------
// Phase 4: shared directory readiness across stores of one factory
// -------------------------------------------------------------------------

describe("Phase 4 shared directory readiness (src/index.ts)", () => {
  it("two distinct session stores from ONE factory share exactly ONE mkdir attempt", async () => {
    let mkdirCount = 0;
    const ensureTelemetryDir = createTelemetryDirEnsurer((dir: string) => {
      mkdirCount += 1;
      mkdirSync(dir, { recursive: true });
    });
    const handlers = loadFactory({ ensureTelemetryDir });

    // store A: anonymous session (no session file)
    handlers.get("turn_start")!({ turnIndex: 0 }, anonCtx());
    const anonFile = await waitForAnyTelemetryFile();
    const [anonRec] = await waitForFileLines(anonFile, 1);
    expect(anonRec.session).toMatch(/^anon-/);

    // store B: explicit session file -> a SECOND TelemetryStore, same factory
    const ctx = makeCtx();
    handlers.get("session_start")!({ reason: "startup" }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    const records = await waitForLines(2);
    expect(records.map((r) => String(r.session))).toEqual(["wiring-test", "wiring-test"]);
    await settle();

    // one shared destination, one mkdir attempt across BOTH stores
    expect(mkdirCount).toBe(1);
    // both files exist and are complete
    expect((await readdir(telemetryDir())).filter((n) => n.endsWith(".jsonl")).length).toBe(2);
  });

  it("a failing shared ensurer: first store reports once, second store still constructs and never re-attempts mkdir", async () => {
    const blocker = join(tmp, "blocker-file");
    await import("node:fs/promises").then((m) => m.writeFile(blocker, "not a dir"));
    let mkdirCount = 0;
    const ensureTelemetryDir = createTelemetryDirEnsurer(() => {
      mkdirCount += 1;
      throw new Error("mkdir boom");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const handlers = loadFactory({ ensureTelemetryDir });

    // store A (anon): constructor mkdir fails -> logged once, still fail-open
    handlers.get("turn_start")!({ turnIndex: 0 }, anonCtx());
    await settle();
    expect(mkdirCount).toBe(1);
    expect(errorSpy).toHaveBeenCalledTimes(1); // A's readiness failure reported once

    // store B (explicit): second store construction -> NO mkdir re-attempt
    // (permanently marked attempted), construction still non-fatal; B's own
    // first append failure is reported once per its own one-time reporting
    // (same as pre-Phase-4 per-store behavior; the mkdir storm is gone).
    handlers.get("session_start")!({ reason: "startup" }, makeCtx());
    await settle();
    expect(mkdirCount).toBe(1); // the key invariant: mkdir attempted at most once per factory
    expect(errorSpy).toHaveBeenCalledTimes(2); // A readiness + B first append
    errorSpy.mockRestore();
  });
});

// -------------------------------------------------------------------------
// Phase 3 correction: eligibility BEFORE measurement; zero RTD serialization
// for ineligible results (JSON.stringify spy filtered by content identity)
// -------------------------------------------------------------------------

describe("Phase 3 correction: no RTD JSON work for ineligible results (src/index.ts)", () => {
  /** Spy on JSON.stringify counting only calls whose first argument === content. */
  function countStringifiesOf(content: unknown): { count: () => number; restore: () => void } {
    let n = 0;
    const real = JSON.stringify;
    const spy = vi.spyOn(JSON, "stringify").mockImplementation(((...args: unknown[]) => {
      if (args[0] === content) n += 1;
      return real.apply(JSON, args as [unknown]);
    }) as typeof JSON.stringify);
    return { count: () => n, restore: () => spy.mockRestore() };
  }

  it("ineligible primitive-string result: ZERO JSON.stringify of the content (raw TextEncoder only)", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const content = "x".repeat(9000);
    const counter = countStringifiesOf(content);
    try {
      handlers.get("tool_result")!(
        { toolName: "bash", toolCallId: "rtd-inelig-str", input: { command: "ls -la" }, content, details: {}, isError: false },
        ctx,
      );
      const records = await waitForLines(1);
      await settle();
      expect(records.map((r) => r.kind)).toEqual(["tool_result"]); // no rtd_shadow
      expect(records[0].output_bytes).toBe(9000); // raw UTF-8 bytes (legacy parity, no quotes)
      expect(counter.count()).toBe(0); // never stringified for RTD
    } finally {
      counter.restore();
    }
  });

  it("eligible primitive-string result: stringified EXACTLY once (shared by telemetry + RTD)", async () => {
    process.env.SECOND_BRAIN_RTD_THRESHOLD = "100";
    const handlers = loadFactory();
    const ctx = makeCtx();
    const content = "z".repeat(500);
    const counter = countStringifiesOf(content);
    try {
      handlers.get("tool_result")!(
        { toolName: "bash", toolCallId: "rtd-elig-str", input: { command: "pytest -q" }, content, details: {}, isError: false },
        ctx,
      );
      const records = await waitForLines(2); // tool_result + rtd_shadow
      const result = records.find((r) => r.kind === "tool_result");
      const shadow = records.find((r) => r.kind === "rtd_shadow");
      expect(result!.output_bytes).toBe(500); // raw bytes
      expect(shadow!.size).toBe(502); // legacy JSON char length (quotes)
      expect(counter.count()).toBe(1); // exactly one stringify served both
    } finally {
      counter.restore();
    }
  });

  it("ineligible object result: serialized exactly ONCE for base telemetry, no extra RTD work", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const content = [{ type: "text", text: "x".repeat(9000) }];
    // expected bytes computed BEFORE the spy window (the assertion itself
    // must not be counted)
    const expectedBytes = new TextEncoder().encode(JSON.stringify(content)).length;
    const counter = countStringifiesOf(content);
    try {
      handlers.get("tool_result")!(
        { toolName: "ipython", toolCallId: "rtd-inelig-obj", input: { code: "print(1)" }, content, details: {}, isError: false },
        ctx,
      );
      const records = await waitForLines(1);
      await settle();
      expect(records.map((r) => r.kind)).toEqual(["tool_result"]); // no rtd_shadow
      expect(records[0].output_bytes).toBe(expectedBytes);
      expect(counter.count()).toBe(1); // the ONE serialization base telemetry already required
    } finally {
      counter.restore();
    }
  });
});
