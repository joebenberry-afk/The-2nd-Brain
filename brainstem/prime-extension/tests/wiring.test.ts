import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import { createTelemetryDirEnsurer } from "../src/storage";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

/** sha256 hex (test-local helper, same primitive as rtd.ts's own
 * rtdSha256Hex) -- used to build a fake artifact preserver deterministically. */
function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

const recallRunMock = vi.hoisted(() => vi.fn());
vi.mock("../src/recall-gate", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/recall-gate")>();
  return { ...actual, runBrainRecall: recallRunMock };
});
const mirrorFireAndForgetMock = vi.hoisted(() => vi.fn());
vi.mock("../src/ledger-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/ledger-mirror")>();
  return { ...actual, mirrorFireAndForget: mirrorFireAndForgetMock };
});
const runVmemStoreMock = vi.hoisted(() => vi.fn());
const runVmemListSyncMock = vi.hoisted(() => vi.fn());
// Defect B (RC4 proactive-paging-repair pass): the real factory's context
// handler now calls `runVmemListPrePageSync` (pre-page correlation) and
// `runVmemClaimPagesSync` (the claim) instead of `runVmemListSync`
// (EVICTED-only) — see context-paging.ts. `runVmemListSync` itself is left
// mocked/unused by these wiring tests below (kept only so unrelated tests
// importing this module surface stay unaffected).
const runVmemListPrePageSyncMock = vi.hoisted(() => vi.fn());
const runVmemClaimPagesSyncMock = vi.hoisted(() => vi.fn());
vi.mock("../src/vmem", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/vmem")>();
  return {
    ...actual,
    runVmemStore: runVmemStoreMock,
    runVmemListSync: runVmemListSyncMock,
    runVmemListPrePageSync: runVmemListPrePageSyncMock,
    runVmemClaimPagesSync: runVmemClaimPagesSyncMock,
  };
});
// RC4 byte-exact recovery pass Part A wiring tests: control the AutoInject
// advisory/active outcome directly instead of spawning a real CLI process.
// Only `runAdvisoryAutoInject` is overridden -- `loadAutoInjectHostConfig`
// and `runShadowAutoInject` (the DEFAULT shadow-mode branch every other
// before_agent_start test in this file exercises) stay real.
const runAdvisoryAutoInjectMock = vi.hoisted(() => vi.fn());
vi.mock("../src/autoinject", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/autoinject")>();
  return { ...actual, runAdvisoryAutoInject: runAdvisoryAutoInjectMock };
});

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
  "ORCHESTRATOR_MODELS",
  "ORCHESTRATOR_BLOCKED_TOOLS",
  "SECOND_BRAIN_RECALL",
  "SECOND_BRAIN_RECALL_MAX_ROWS",
  "SECOND_BRAIN_RECALL_MIN_CHARS",
  "SECOND_BRAIN_RECALL_TIMEOUT_MS",
  "SECOND_BRAIN_AUTOINJECT_MODE",
  "SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS",
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
  recallRunMock.mockReset();
  mirrorFireAndForgetMock.mockReset();
  runVmemStoreMock.mockReset();
  runVmemStoreMock.mockResolvedValue({ ok: true, objId: "obj-test" });
  runVmemListSyncMock.mockReset();
  runVmemListSyncMock.mockReturnValue({ ok: true, objects: [] });
  runVmemListPrePageSyncMock.mockReset();
  runVmemListPrePageSyncMock.mockReturnValue({ ok: true, objects: [] });
  runVmemClaimPagesSyncMock.mockReset();
  // Default: auto-approve every requested candidate (most tests only care
  // about the list-side correlation) — tests exercising claim semantics
  // specifically override this.
  runVmemClaimPagesSyncMock.mockImplementation(
    (opts: { candidates: Array<{ objId: string; kind: string }> }) => ({
      ok: true,
      claimedObjIds: opts.candidates.map((c) => c.objId),
    }),
  );
  runAdvisoryAutoInjectMock.mockReset();
  runAdvisoryAutoInjectMock.mockResolvedValue(undefined);
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
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
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

/**
 * P3-D additive telemetry (plan §8, SCHEMA.md `lean_kernel`): every
 * before_agent_start now also emits one lean_kernel record (plus a bounded
 * extension_error when the lean-code skill file is absent in the test home).
 * Exact-kind assertions below account for the new records.
 */
function recordOf(records: Record<string, unknown>[], kind: string): Record<string, unknown> {
  const rec = records.find((r) => r.kind === kind);
  if (!rec) throw new Error(`record kind ${kind} not found in ${JSON.stringify(records.map((r) => r.kind))}`);
  return rec;
}

/** Write config/context.toml with [rtd] enabled=true (P3-F activation switch). */
function enableRtd(): void {
  const dir = join(tmp, "config");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "context.toml"),
    '[rtd]\nenabled = true\nthreshold_chars = 8000\nmax_distill_chars = 2000\nwhitelist_tools = ["bash"]\nwhitelist_commands = ["pytest", "git", "rg", "grep"]\n',
    "utf8",
  );
}

/** Write config/context.toml with BOTH [rtd] and [vmem_admission] enabled=true
 * (Phase B activation switch, independent of the plain [vmem] toggle). */
function enableRtdAndVmemAdmission(): void {
  const dir = join(tmp, "config");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "context.toml"),
    '[rtd]\nenabled = true\nthreshold_chars = 8000\nmax_distill_chars = 2000\nwhitelist_tools = ["bash"]\nwhitelist_commands = ["pytest", "git", "rg", "grep"]\n\n[vmem_admission]\nenabled = true\n',
    "utf8",
  );
}

/** Write config/context.toml with ONLY [vmem_admission] enabled=true (Part
 * A AutoInject wiring tests -- RTD is irrelevant here). */
function enableVmemAdmissionOnly(): void {
  const dir = join(tmp, "config");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "context.toml"), "[vmem_admission]\nenabled = true\n", "utf8");
}


/** Write config/context.toml with [context_paging] enabled=true (Part B/E
 * activation switch), with small conservative overrides for deterministic
 * wiring tests. */
function enableContextPaging(
  opts: { pinRecentMessages?: number; residentTokenBudget?: number; maxPagesPerContextEvent?: number } = {},
): void {
  const dir = join(tmp, "config");
  mkdirSync(dir, { recursive: true });
  const pin = opts.pinRecentMessages ?? 2;
  const budget = opts.residentTokenBudget ?? 1;
  const maxPages = opts.maxPagesPerContextEvent ?? 3;
  writeFileSync(
    join(dir, "context.toml"),
    `[context_paging]\nenabled = true\npin_recent_messages = ${pin}\n` +
      `resident_token_budget = ${budget}\nmax_pages_per_context_event = ${maxPages}\n`,
    "utf8",
  );
}

/** Context with NO session file: forces the anonymous fallback path. */
function anonCtx(): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    sessionManager: { getSessionFile: () => undefined },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
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
  // P3-B economics events: message_end carries usage so its record kind
  // (assistant_usage) is written by the generic loop below.
  ["before_provider_request", { payload: { model: "deepseek/deepseek-v4-flash", messages: [] } }],
  ["after_provider_response", { status: 200, headers: { "x-ratelimit-remaining": "1" } }],
  [
    "message_end",
    {
      message: {
        role: "assistant",
        content: [],
        usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      },
    },
  ],
  ["tool_call", { toolName: "bash", toolCallId: "c1", input: { command: "echo hi" } }],
  ["tool_result", { toolName: "bash", toolCallId: "c1", input: {}, content: [], details: {}, isError: false }],
  ["turn_end", { turnIndex: 0, message: {}, toolResults: [] }],
  ["agent_end", { messages: [] }],
  ["session_before_compact", { preparation: {}, branchEntries: [] }],
  ["session_compact", { compactionEntry: {}, fromExtension: false }],
  ["session_shutdown", { reason: "quit" }],
];

describe("factory wiring (src/index.ts)", () => {
  it("subscribes exactly the 14 lifecycle events (11 + P3-B economics)", () => {
    const handlers = loadFactory();
    expect([...handlers.keys()].sort()).toEqual(EVENTS.map(([name]) => name).sort());
  });

  it("every handler returns undefined (void) and still writes one record each", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    expect(handlers.size).toBe(14);
    for (const [name, event] of EVENTS) {
      const handler = handlers.get(name);
      expect(handler, `handler for ${name}`).toBeDefined();
      const result = await handler!(event, ctx);
      if (name === "message_end") {
        // P3-B: message_end MUST return the finalized message unchanged
        // (role preserved — the runtime replaces the message in place).
        expect(result).toEqual({
          message: (event as { message: unknown }).message,
        });
      } else if (name === "session_before_compact") {
        // T-G4: the pre-compaction durability barrier returns {cancel:true}
        // when the ledger checkpoint cannot prove durability (venv-less test
        // homes) — compaction must not proceed unprotected.
        expect(
          result === undefined ||
            (typeof result === "object" && result !== null && "cancel" in (result as object)),
          `${name} handler returned an unexpected value`,
        ).toBe(true);
      } else {
        expect(result, `${name} handler returned a value`).toBeUndefined();
      }
    }
    // all 11 records land in the same session file (fire-and-forget drained).
    // NOTE: invoked back-to-back, the sync final write for session_shutdown can
    // land ahead of still-queued async writes, so order is asserted as a set
    // here; real ordering (shutdown last) is covered by the dedicated test
    // below, where prior writes have settled before shutdown fires.
    // 14 event records + optional barrier extension_error + P3-D lean
    // fail-open records (missing skill in the venv-less test home).
    const records = await waitForLines(17);
    const kinds = records.map((r) => r.kind).sort();
    // The three P3-B hooks write record kinds that differ from their event
    // names (provider_request_meta / provider_response_meta / assistant_usage)
    // and are asserted separately; every other subscribed event writes its
    // own kind.
    const p3Kinds = ["provider_request_meta", "provider_response_meta", "assistant_usage"];
    const expected = EVENTS.map(([name]) => name)
      .filter((n) => !["before_provider_request", "after_provider_response", "message_end"].includes(n))
      .sort();
    // T-G4: the venv-less test home cannot prove the pre-compaction barrier,
    // so session_before_compact appends one extra extension_error and returns
    // {cancel:true}; every subscribed kind must still be present.
    for (const kind of expected) {
      expect(kinds).toContain(kind);
    }
    for (const kind of p3Kinds) {
      expect(kinds).toContain(kind);
    }
    expect(kinds).toContain("lean_kernel"); // P3-D: one lean decision per before_agent_start
    expect(kinds.filter((k) => k === "extension_error").length).toBeLessThanOrEqual(2);
    for (const rec of records) {
      expect([2, 3]).toContain(rec.v); // v=2 legacy kinds + v=3 P3-B kinds
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

  it("ledger-cwd-ordering-fix: user_task as FIRST mirror forwards ctx.cwd (project attribution)", async () => {
    // Real-run regression: the user_task mirror (before_agent_start) can be
    // the first to reach the ledger — its `ledger init` spawn wins the
    // per-process race against session_started — so it MUST carry ctx.cwd or
    // sessions.project_id resolves to ''.
    mirrorFireAndForgetMock.mockResolvedValue(undefined);
    const handlers = loadFactory();
    const ctx = makeCtx(); // cwd: "C:/work"

    // before_agent_start fires WITHOUT a prior session_start mirror.
    await handlers.get("before_agent_start")!({ prompt: "hello world" }, ctx);
    await settle();
    const userTaskCall = mirrorFireAndForgetMock.mock.calls.find(
      (c) => (c[0] as { record: { kind: string } }).record.kind === "user_task",
    )?.[0] as { cwd?: string };
    expect(userTaskCall).toBeDefined();
    expect(userTaskCall.cwd).toBe("C:/work");
  });

  it("ledger-cwd-ordering-fix: EVERY mirror call-site family forwards ctx.cwd when present", async () => {
    mirrorFireAndForgetMock.mockResolvedValue(undefined);
    const handlers = loadFactory();
    const ctx = makeCtx(); // cwd: "C:/work"

    for (const [name, event] of EVENTS) {
      await handlers.get(name)!(event, ctx);
    }
    await settle();
    const calls = mirrorFireAndForgetMock.mock.calls.map(
      (c) => c[0] as { cwd?: string; record: { kind: string } },
    );
    expect(calls.length).toBeGreaterThanOrEqual(10);
    for (const call of calls) {
      expect(call.cwd, `${call.record.kind} mirror must forward ctx.cwd`).toBe("C:/work");
    }
  });

  it("ledger-cwd-ordering-fix: cwd absent -> mirrors forward undefined (init omits --cwd)", async () => {
    mirrorFireAndForgetMock.mockResolvedValue(undefined);
    const handlers = loadFactory();
    const ctx = makeCtx({ cwd: "" });

    for (const [name, event] of EVENTS) {
      await handlers.get(name)!(event, ctx);
    }
    await settle();
    const calls = mirrorFireAndForgetMock.mock.calls.map(
      (c) => c[0] as { cwd?: string; record: { kind: string } },
    );
    expect(calls.length).toBeGreaterThanOrEqual(10);
    for (const call of calls) {
      expect(call.cwd, `${call.record.kind} must not fabricate a cwd`).toBeUndefined();
    }
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

  it("Phase R6: session_start captures the real tool surface when the host exposes getAllTools/getActiveTools", async () => {
    const handlers = new Map<string, Handler>();
    const pi = {
      on: (name: string, handler: Handler): void => {
        handlers.set(name, handler);
      },
      getAllTools: () => [{ name: "bash" }, { name: "edit" }, { name: "websearch" }],
      getActiveTools: () => ["bash", "edit"],
    } as unknown as ExtensionAPI;
    factory(pi);
    const ctx = makeCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);

    const records = await waitForLines(2);
    expect(records[0]).toMatchObject({
      kind: "prime_tool_surface",
      session: "wiring-test",
      all_tools_count: 3,
      active_tools_count: 2,
      all_tools: ["bash", "edit", "websearch"],
      active_tools: ["bash", "edit"],
    });
    expect(records[1].kind).toBe("session_start");
  });

  it("Phase R6: session_start writes no tool-surface record when the host does not expose getAllTools/getActiveTools", async () => {
    const handlers = loadFactory(); // default fake pi has no getAllTools/getActiveTools
    const ctx = makeCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);

    const records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["session_start"]); // no prime_tool_surface record
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

    const result = await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-1", input, content: bigContent, details: {}, isError: false },
      ctx,
    );
    expect(result).toBeUndefined(); // shadow-only: no substitution patch
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

  it("legacy env SECOND_BRAIN_RTD=active alone does NOT substitute (config is the switch, P3-F)", async () => {
    process.env.SECOND_BRAIN_RTD = "active";
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-4", input: { command: "git status" }, content: "y".repeat(9000), details: {}, isError: false },
      ctx,
    );
    expect(result).toBeUndefined(); // no substitution without [rtd] enabled=true
    const records = await waitForLines(2);
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toMatchObject({
      reason: "ok",
      would_trigger: true,
      tool: "bash",
    });
    expect(shadow!.substitution).toBeUndefined();
  });

  it("P3-F: [rtd] enabled=true + preservation OK -> substitution patch + distilled record", async () => {
    enableRtd();
    const handlers = loadFactory({
      rtdPreserver: {
        preserve: async (raw) => ({ sha256: require("node:crypto").createHash("sha256").update(raw).digest("hex"), handle: `[brain-artifact:sha256:${require("node:crypto").createHash("sha256").update(raw).digest("hex")}]` }),
        verify: async (_sha256, raw) => raw === "x".repeat(9000),
      },
    });
    const ctx = makeCtx();
    const result = await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-act-1", input: { command: "pytest -q tests/" }, content: [{ type: "text", text: "x".repeat(9000) }], details: {}, isError: false },
      ctx,
    );
    const patch = result as { content: Array<{ type: "text"; text: string }> } | undefined;
    expect(patch).toBeDefined();
    expect(patch!.content[0]!.text).toContain("[SECOND_BRAIN_RTD]");
    expect(patch!.content[0]!.text).toContain("original_chars=9000");
    expect(patch!.content[0]!.text).toContain("truncated=true");
    expect(patch!.content[0]!.text).toContain("artifact=[brain-artifact:sha256:");
    const records = await waitForLines(2);
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toMatchObject({
      distilled: true,
      original_chars: 9000,
      command_class: "pytest",
      error_status: false,
    });
    expect(shadow!.saved_chars).toBeGreaterThan(6000);
    expect(shadow!.artifact_ref).toContain("brain-artifact:sha256:");
  });

  it("P3-F: [rtd] enabled=true but preservation FAILS -> original content unchanged + distilled=false record", async () => {
    enableRtd();
    const handlers = loadFactory({
      rtdPreserver: {
        preserve: async () => null, // store failed
        verify: async () => false,
      },
    });
    const ctx = makeCtx();
    const result = await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "rtd-act-2", input: { command: "git log -p" }, content: [{ type: "text", text: "y".repeat(9000) }], details: {}, isError: false },
      ctx,
    );
    expect(result).toBeUndefined(); // plan §11.4: DO NOT DISTILL on preservation failure
    const records = await waitForLines(2);
    const shadow = records.find((r) => r.kind === "rtd_shadow");
    expect(shadow).toMatchObject({ distilled: false, command_class: "git", original_chars: 9000 });
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
    await handlers.get("before_agent_start")!({ prompt: "hello" }, ctx);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    handlers.get("tool_call")!({ toolName: "bash", toolCallId: "c1", input: { command: "echo hi" } }, ctx);
    handlers.get("tool_result")!({ toolName: "bash", toolCallId: "c1", input: {}, content: [], details: {}, isError: false }, ctx);
    handlers.get("turn_end")!({ turnIndex: 0, message: {}, toolResults: [] }, ctx);
    handlers.get("agent_end")!({ messages: [] }, ctx);
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    const file = await waitForAnyTelemetryFile();
    // P3-D: before_agent_start adds lean_kernel + fail-open extension_error
    const records = await waitForFileLines(file, 10);
    await settle();
    const names = (await readdir(telemetryDir())).filter((n) => n.endsWith(".jsonl"));
    expect(names.length).toBe(1); // one session file for the whole anonymous lifecycle
    expect(records.map((r) => r.kind).sort()).toEqual(
      ["session_start", "before_agent_start", "lean_kernel", "extension_error", "turn_start", "tool_call", "tool_result", "turn_end", "agent_end", "session_shutdown"].sort(),
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
// Phase B: VMem admission wiring (src/index.ts vmemAdmit + [vmem_admission])
// -------------------------------------------------------------------------

describe("Phase B VMem admission (src/index.ts)", () => {
  it("no-op when [vmem_admission] is absent (default OFF), even though RTD substitution fires", async () => {
    enableRtd(); // [rtd] enabled, [vmem_admission] left absent/default false
    const handlers = loadFactory({
      rtdPreserver: {
        preserve: async (raw) => ({
          sha256: require("node:crypto").createHash("sha256").update(raw).digest("hex"),
          handle: `[brain-artifact:sha256:${require("node:crypto").createHash("sha256").update(raw).digest("hex")}]`,
        }),
        verify: async (_sha256, raw) => raw === "x".repeat(9000),
      },
    });
    const ctx = makeCtx();
    await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "vmem-admit-noop-1", input: { command: "pytest -q tests/" }, content: [{ type: "text", text: "x".repeat(9000) }], details: {}, isError: false },
      ctx,
    );
    await waitForLines(2); // tool_result + rtd_shadow (distilled=true)
    await settle();
    expect(runVmemStoreMock).not.toHaveBeenCalled();
  });

  it("no-op for the AutoInject/compaction call sites when the flag is absent", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("session_before_compact")!({ preparation: {}, branchEntries: [] }, ctx);
    await settle();
    expect(runVmemStoreMock).not.toHaveBeenCalled();
  });

  it("fires the RTD-preserved-artifact admission ref when [vmem_admission].enabled=true", async () => {
    enableRtdAndVmemAdmission();
    const handlers = loadFactory({
      rtdPreserver: {
        preserve: async (raw) => ({
          sha256: require("node:crypto").createHash("sha256").update(raw).digest("hex"),
          handle: `[brain-artifact:sha256:${require("node:crypto").createHash("sha256").update(raw).digest("hex")}]`,
        }),
        verify: async (_sha256, raw) => raw === "x".repeat(9000),
      },
    });
    const ctx = makeCtx();
    await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "vmem-admit-1", input: { command: "pytest -q tests/" }, content: [{ type: "text", text: "x".repeat(9000) }], details: {}, isError: false },
      ctx,
    );
    await waitForLines(2);
    await settle();
    expect(runVmemStoreMock).toHaveBeenCalledTimes(1);
    const [call] = runVmemStoreMock.mock.calls[0] as [
      { kind: string; title: string; content: string; hostSessionId: string; metadata?: Record<string, unknown> },
    ];
    expect(call.kind).toBe("TOOL_OBSERVATION");
    expect(call.title).toBe("rtd_artifact");
    expect(call.hostSessionId).toBe("wiring-test");
    // privacy: only ids/hashes/sizes — never the raw or distilled tool text.
    expect(call.content).not.toContain("x".repeat(100));
    const parsed = JSON.parse(call.content) as Record<string, unknown>;
    expect(parsed.artifact_ref).toContain("brain-artifact:sha256:");
    expect(typeof parsed.original_chars).toBe("number");
    expect(parsed.command_class).toBe("pytest");
    // RC4 CVM closure repair (Repair A): the 5th `metadata` argument is now
    // populated with the REAL event.toolCallId and the REAL, already-
    // verified rtd.record.artifact_ref — this is what lets context-paging.ts's
    // `byToolCallId` correlation map find this object (Pilot 4's exact gap).
    expect(call.metadata).toBeDefined();
    expect(call.metadata?.toolCallId).toBe("vmem-admit-1");
    expect(call.metadata?.artifactRef).toBe(parsed.artifact_ref);
    // metadata never carries raw/distilled tool text either.
    expect(JSON.stringify(call.metadata)).not.toContain("x".repeat(100));
  });

  it("does NOT fire the RTD-preserved-artifact admission ref for a NON-distilled RTD result (regression: content below threshold never calls vmemAdmit for TOOL_OBSERVATION)", async () => {
    enableRtdAndVmemAdmission();
    const handlers = loadFactory({
      rtdPreserver: {
        preserve: async (raw) => ({
          sha256: require("node:crypto").createHash("sha256").update(raw).digest("hex"),
          handle: `[brain-artifact:sha256:${require("node:crypto").createHash("sha256").update(raw).digest("hex")}]`,
        }),
        verify: async (_sha256, raw) => raw === "small output",
      },
    });
    const ctx = makeCtx();
    // Well below the RTD threshold -> shouldDistill returns trigger:false,
    // rtd.record.distilled is never true -> the existing gate (unweakened
    // by this pass) must still prevent any vmemAdmit call.
    await handlers.get("tool_result")!(
      { toolName: "bash", toolCallId: "vmem-admit-no-distill-1", input: { command: "pytest -q tests/" }, content: [{ type: "text", text: "small output" }], details: {}, isError: false },
      ctx,
    );
    await waitForLines(1); // tool_result only — content is far too small to trigger rtd_shadow's distill path
    await settle();
    expect(runVmemStoreMock).not.toHaveBeenCalled();
  });

  it("real AutoInject delivery: preserve-before-admit fires, richer packetArtifactRef/packetSha256 metadata included on success", async () => {
    enableVmemAdmissionOnly();
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const packetText = "PACKET TEXT the model actually saw, verbatim.";
    runAdvisoryAutoInjectMock.mockResolvedValue({
      customType: "brain.autoinject.packet",
      content: packetText,
      display: true,
      details: { delivery_id: "del-preserve-1", packet_tokens: 55 },
    });
    const handlers = loadFactory({
      autoinjectPacketPreserver: {
        preserve: async (raw) => ({ sha256: sha256Hex(raw), handle: `[brain-artifact:sha256:${sha256Hex(raw)}]` }),
        verify: async (_sha256, raw) => raw === packetText,
      },
    });
    const ctx = makeCtx();

    await handlers.get("before_agent_start")!({ prompt: "do the research task" }, ctx);

    expect(runAdvisoryAutoInjectMock).toHaveBeenCalledTimes(1);
    expect(runVmemStoreMock).toHaveBeenCalledTimes(1);
    const [call] = runVmemStoreMock.mock.calls[0] as [
      { kind: string; title: string; content: string; metadata?: Record<string, unknown> },
    ];
    expect(call.kind).toBe("RESEARCH_RESULT");
    expect(call.title).toBe("autoinject_delivery");
    // content: the EXISTING delivery-only shape, unchanged (provenance/fallback key).
    const parsedContent = JSON.parse(call.content) as Record<string, unknown>;
    expect(parsedContent.delivery_id).toBe("del-preserve-1");
    // metadata: the RICHER shape -- existing fields kept, new artifact pointer added.
    expect(call.metadata).toBeDefined();
    expect(call.metadata?.delivery_id).toBe("del-preserve-1");
    expect(call.metadata?.packet_tokens).toBe(55);
    expect(call.metadata?.packetSha256).toBe(sha256Hex(packetText));
    expect(call.metadata?.packetArtifactRef).toBe(`[brain-artifact:sha256:${sha256Hex(packetText)}]`);
  });

  it("real AutoInject delivery: preserve/verify failure -> admission still happens with the EXISTING delivery-only shape (fail-open, no packetArtifactRef)", async () => {
    enableVmemAdmissionOnly();
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const packetText = "PACKET TEXT that fails to preserve.";
    runAdvisoryAutoInjectMock.mockResolvedValue({
      customType: "brain.autoinject.packet",
      content: packetText,
      display: true,
      details: { delivery_id: "del-preserve-fail-1", packet_tokens: 12 },
    });
    const handlers = loadFactory({
      autoinjectPacketPreserver: {
        preserve: async () => null, // preservation failed -> RtdPreserver contract: null
        verify: async () => false,
      },
    });
    const ctx = makeCtx();

    const result = await handlers.get("before_agent_start")!({ prompt: "do the research task" }, ctx);

    // The packet message itself is still returned to the host (never dropped).
    expect((result as { message?: { content?: unknown } } | undefined)?.message?.content).toBe(packetText);
    expect(runVmemStoreMock).toHaveBeenCalledTimes(1);
    const [call] = runVmemStoreMock.mock.calls[0] as [
      { kind: string; title: string; content: string; metadata?: Record<string, unknown> },
    ];
    expect(call.kind).toBe("RESEARCH_RESULT");
    const parsedContent = JSON.parse(call.content) as Record<string, unknown>;
    expect(parsedContent.delivery_id).toBe("del-preserve-fail-1");
    expect(call.metadata).toBeUndefined(); // no packetArtifactRef/packetSha256 on failure
  });

  it("real AutoInject delivery: preserver throwing unexpectedly is fail-open too -- admission still happens with the old shape", async () => {
    enableVmemAdmissionOnly();
    process.env.SECOND_BRAIN_AUTOINJECT_MODE = "advisory";
    const packetText = "PACKET TEXT whose preserver throws.";
    runAdvisoryAutoInjectMock.mockResolvedValue({
      customType: "brain.autoinject.packet",
      content: packetText,
      display: true,
      details: { delivery_id: "del-preserve-throw-1", packet_tokens: 7 },
    });
    const handlers = loadFactory({
      autoinjectPacketPreserver: {
        preserve: async () => {
          throw new Error("preserve boom");
        },
        verify: async () => false,
      },
    });
    const ctx = makeCtx();

    let threw = false;
    let result: unknown;
    try {
      result = await handlers.get("before_agent_start")!({ prompt: "do the research task" }, ctx);
    } catch {
      threw = true;
    }

    expect(threw).toBe(false); // never throws, never blocks before_agent_start
    expect((result as { message?: { content?: unknown } } | undefined)?.message?.content).toBe(packetText);
    expect(runVmemStoreMock).toHaveBeenCalledTimes(1);
    const [call] = runVmemStoreMock.mock.calls[0] as [{ metadata?: Record<string, unknown> }];
    expect(call.metadata).toBeUndefined();
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

// -------------------------------------------------------------------------
// Phase 1: minimal-orchestrator guard wiring (Sol)
// -------------------------------------------------------------------------

const SOL_CTX = makeCtx({ model: { id: "gpt-5.6-sol", provider: "openai-codex" } });

describe("minimal-orchestrator guard (src/index.ts)", () => {
  it("tool_call: Sol model + bash -> {block:true} with reason and a violation record", async () => {
    const handlers = loadFactory();
    const event = { toolName: "bash", toolCallId: "sol-1", input: { command: "echo hi" } };
    const inputBefore = structuredClone(event.input);

    const result = handlers.get("tool_call")!(event, SOL_CTX);
    expect(result).toEqual({ block: true, reason: expect.stringContaining("Sol minimal-orchestrator policy") });
    expect(event.input).toEqual(inputBefore); // still read-only

    const records = await waitForLines(2);
    const kinds = records.map((r) => r.kind).sort();
    expect(kinds).toEqual(["orchestrator_policy_violation", "tool_call"]);
    const violation = records.find((r) => r.kind === "orchestrator_policy_violation");
    expect(violation).toMatchObject({
      v: 2,
      kind: "orchestrator_policy_violation",
      session: "wiring-test",
      violation: "direct_execution",
      model: "openai-codex/gpt-5.6-sol",
      detected_by: "runtime_guard",
      blocked: true,
    });
    // privacy: no free-text tool/reason/command fields on the record
    expect(Object.keys(violation!).sort()).toEqual(
      ["blocked", "detected_by", "kind", "model", "session", "ts", "v", "violation"].sort(),
    );
  });

  it("tool_call: Sol model blocks edit and websearch too", async () => {
    const handlers = loadFactory();
    for (const tool of ["edit", "websearch"]) {
      const result = handlers.get("tool_call")!({ toolName: tool, toolCallId: `sol-${tool}`, input: {} }, SOL_CTX);
      expect(result).toEqual({ block: true, reason: expect.any(String) });
    }
    const records = await waitForLines(4); // 2 tool_call + 2 violation
    expect(records.filter((r) => r.kind === "orchestrator_policy_violation")).toHaveLength(2);
  });

  it("tool_call: Sol model + ipython -> NOT blocked, no violation (delegation path)", async () => {
    const handlers = loadFactory();
    const result = handlers.get("tool_call")!(
      { toolName: "ipython", toolCallId: "sol-ipy", input: { code: "await rlm('sub-task')" } },
      SOL_CTX,
    );
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["tool_call"]);
    await settle();
    const after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_call"]);
  });

  it("tool_call: non-Sol model + bash -> NOT blocked, no violation (measurement only)", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek/deepseek-v4-flash
    const result = handlers.get("tool_call")!(
      { toolName: "bash", toolCallId: "wk-1", input: { command: "echo hi" } },
      ctx,
    );
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    expect(records.map((r) => r.kind)).toEqual(["tool_call"]);
    await settle();
    const after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["tool_call"]);
  });

  it("before_agent_start: Sol model -> systemPrompt contains the delegation rule", async () => {
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: "do the thing" }, SOL_CTX);
    expect(result).toBeDefined();
    const patch = result as { systemPrompt?: string };
    expect(typeof patch.systemPrompt).toBe("string");
    expect(patch.systemPrompt).toContain("MUST delegate");
    expect(patch.systemPrompt).toContain("WORKER RETURN CONTRACT");
    expect(patch.systemPrompt!.split(/\s+/).length).toBeLessThan(1500); // contract size cap

    // measurement records still appended alongside the patch (P3-D: the
    // lean_kernel omit/role record proves Sol is never injected)
    const records = await waitForLines(2);
    expect(records.map((r) => r.kind)).toEqual(["lean_kernel", "before_agent_start"]);
    expect(recordOf(records, "lean_kernel").reason).toBe("role");
  });

  it("before_agent_start: non-Sol model -> undefined, no systemPrompt", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek/deepseek-v4-flash
    const result = await handlers.get("before_agent_start")!({ prompt: "hello" }, ctx);
    expect(result).toBeUndefined();

    // P3-D: venv-less test home has no lean-code skill -> fail-open records
    const records = await waitForLines(3);
    expect(records.map((r) => r.kind)).toEqual(["extension_error", "lean_kernel", "before_agent_start"]);
    expect(recordOf(records, "lean_kernel").reason).toBe("skill-missing");
  });

  it("ORCHESTRATOR_* env overrides change the wired guard behavior", async () => {
    process.env.ORCHESTRATOR_MODELS = "deepseek-v4-flash";
    process.env.ORCHESTRATOR_BLOCKED_TOOLS = "bash,ipython";
    const handlers = loadFactory();
    const workerCtx = makeCtx(); // deepseek is now the orchestrator under the override

    const blocked = handlers.get("tool_call")!(
      { toolName: "bash", toolCallId: "ov-1", input: { command: "echo hi" } },
      workerCtx,
    );
    expect(blocked).toEqual({ block: true, reason: expect.any(String) });

    // Sol is NOT the orchestrator under the override: bash allowed, no patch
    const solBash = handlers.get("tool_call")!(
      { toolName: "bash", toolCallId: "ov-2", input: { command: "echo hi" } },
      SOL_CTX,
    );
    expect(solBash).toBeUndefined();
    const patch = await handlers.get("before_agent_start")!({ prompt: "hi" }, SOL_CTX);
    expect(patch).toBeUndefined();

    await settle(); // drain fire-and-forget writes before the tmp dir is removed
  });
});

// -------------------------------------------------------------------------
// Phase 14: controlled Prime recall hook (default OFF)
// -------------------------------------------------------------------------

const RECALL_PROMPT =
  "the sqlite migration failed on the second run with a schema version mismatch and now the upgrade is blocked";

describe("Phase 14 recall gate (src/index.ts)", () => {
  it("default OFF: before_agent_start performs ZERO spawns and returns undefined", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek, non-Sol
    const result = await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx);
    expect(result).toBeUndefined();
    expect(recallRunMock).not.toHaveBeenCalled();
    // measurement records still appended (P3-D lean fail-open on missing skill)
    const records = await waitForLines(3);
    expect(records.map((r) => r.kind)).toEqual(["extension_error", "lean_kernel", "before_agent_start"]);
  });

  it("enabled + substantial prompt: spawns ONCE and appends the brief to the full system prompt", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockResolvedValue([
      { memory_id: "mem-1", title: "sqlite migration failure recovery", status: "current", evidence_grade: "VERIFIED" },
      { title: "no-id row", status: "candidate" },
    ]);
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx)) as {
      systemPrompt?: string;
    } | undefined;
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    const [options] = recallRunMock.mock.calls[0]! as [
      { home: string; query: string; cfg: { maxRows: number } },
    ];
    expect(options.home).toBe(tmp);
    expect(options.query).toBe(RECALL_PROMPT);
    expect(options.cfg.maxRows).toBe(3);
    expect(result).toBeDefined();
    expect(result!.systemPrompt).toContain("BASE SYSTEM PROMPT"); // base preserved, not replaced
    expect(result!.systemPrompt).toContain("## Brain Brief (retrieved)");
    expect(result!.systemPrompt).toContain("**sqlite migration failure recovery**");
    expect(result!.systemPrompt!.indexOf("BASE SYSTEM PROMPT")).toBeLessThan(
      result!.systemPrompt!.indexOf("## Brain Brief (retrieved)"),
    );
  });

  it("enabled + trivial prompt: no spawn, no injection", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = await handlers.get("before_agent_start")!({ prompt: "hi there" }, ctx);
    expect(result).toBeUndefined();
    expect(recallRunMock).not.toHaveBeenCalled();
  });

  it("enabled + recall spawn fails: silent, no injection, no throw", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockRejectedValue(new Error("spawn boom"));
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx);
    expect(result).toBeUndefined();
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    await settle(); // drain fire-and-forget telemetry writes before teardown
  });

  it("enabled but Sol session: contract injected, recall NOT spawned (no double-inject)", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    const handlers = loadFactory();
    const ctx = makeCtx({ model: { id: "gpt-5.6-sol", provider: "openai-codex" } });
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx)) as {
      systemPrompt?: string;
    } | undefined;
    expect(result).toBeDefined();
    expect(result!.systemPrompt).toContain("MUST delegate"); // guard contract only
    expect(result!.systemPrompt).not.toContain("## Brain Brief (retrieved)");
    expect(recallRunMock).not.toHaveBeenCalled();
  });

  it("enabled + brief builder yields nothing (no valid rows): no injection", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockResolvedValue([{ summary: "no title" }, "garbage"]);
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx);
    expect(result).toBeUndefined();
    expect(recallRunMock).toHaveBeenCalledTimes(1);
  });
});

// -------------------------------------------------------------------------
// Driver Orchestration Contract (campaign): role resolution + contract
// injection on before_agent_start. Driver = deepseek-v4-pro / gpt-5.6-luna
// (defaults); workers/normal never get the contract; Sol keeps its contract.
// -------------------------------------------------------------------------

const DRIVER_CTX = makeCtx({ model: { id: "deepseek-v4-pro", provider: "deepseek" } });
const TERRA_CTX = makeCtx({ model: { id: "gpt-5.6-terra", provider: "openai-codex" } });
const MARKER = "second-brain-driver-orchestration-contract";

describe("driver-orchestration contract (src/index.ts)", () => {
  it("before_agent_start: driver model -> contract appended after the base prompt, record role=driver injected=true", async () => {
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: "do the thing" }, DRIVER_CTX);
    const patch = result as { systemPrompt?: string } | undefined;
    expect(patch).toBeDefined();
    expect(patch!.systemPrompt).toContain("BASE SYSTEM PROMPT"); // base preserved, contract APPENDED
    expect(patch!.systemPrompt).toContain(MARKER);
    expect(patch!.systemPrompt!.indexOf("BASE SYSTEM PROMPT")).toBeLessThan(
      patch!.systemPrompt!.indexOf(MARKER),
    );

    const records = await waitForLines(3);
    expect(records.map((r) => r.kind)).toEqual(["extension_error", "lean_kernel", "before_agent_start"]);
    const contract = recordOf(records, "before_agent_start");
    expect(contract.role).toBe("driver");
    expect(contract.driver_contract_injected).toBe(true);
  });

  it("before_agent_start: driver model with base already containing the marker -> no duplicate append", async () => {
    const handlers = loadFactory();
    const seeded = makeCtx({
      model: { id: "gpt-5.6-luna", provider: "openai-codex" },
      getSystemPrompt: () => `SEEDED BASE\n\n[${MARKER}] already there`,
    });
    const result = await handlers.get("before_agent_start")!({ prompt: "do the thing" }, seeded);
    const patch = result as { systemPrompt?: string } | undefined;
    expect(patch).toBeDefined();
    expect(patch!.systemPrompt).toBe(`SEEDED BASE\n\n[${MARKER}] already there`); // stable prompt returned, no duplicate append

    const records = await waitForLines(3);
    const contract = recordOf(records, "before_agent_start");
    expect(contract.role).toBe("driver");
    expect(contract.driver_contract_injected).toBe(false);
    await settle();
    const after = (await readFile(telemetryFile(), "utf8")).trim().split("\n").filter(Boolean);
    // exactly the three P3-D records; no second before_agent_start append ever happens
    expect(after.map((l) => JSON.parse(l).kind)).toEqual(["extension_error", "lean_kernel", "before_agent_start"]);
  });

  it("before_agent_start: worker model -> no contract, record role=worker", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek/deepseek-v4-flash
    const result = await handlers.get("before_agent_start")!({ prompt: "hello" }, ctx);
    expect(result).toBeUndefined();

    const records = await waitForLines(3);
    expect(records.map((r) => r.kind)).toEqual(["extension_error", "lean_kernel", "before_agent_start"]);
    const contract = recordOf(records, "before_agent_start");
    expect(contract.role).toBe("worker");
    expect(contract.driver_contract_injected).toBeUndefined();
    expect(JSON.stringify(records)).not.toContain(MARKER);
  });

  it("before_agent_start: normal model -> no contract, record role=normal", async () => {
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: "hello" }, TERRA_CTX);
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    expect(records[0].role).toBe("normal");
    expect(JSON.stringify(records)).not.toContain(MARKER);
  });

  it("before_agent_start: Sol model -> Sol contract only, record role=hard_orchestrator, no driver marker", async () => {
    const handlers = loadFactory();
    const result = await handlers.get("before_agent_start")!({ prompt: "do the thing" }, SOL_CTX);
    const patch = result as { systemPrompt?: string } | undefined;
    expect(patch).toBeDefined();
    expect(patch!.systemPrompt).toContain("MUST delegate"); // Sol contract
    expect(patch!.systemPrompt).not.toContain(MARKER); // driver contract absent

    const records = await waitForLines(1);
    expect(records[0].role).toBe("hard_orchestrator");
    expect(records[0].driver_contract_injected).toBeUndefined();
  });

  it("driver + recall enabled: ONE patch with the Brain Brief AFTER the contract", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockResolvedValue([
      { memory_id: "mem-1", title: "driver recall row", status: "current", evidence_grade: "VERIFIED" },
    ]);
    const handlers = loadFactory();
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, DRIVER_CTX)) as {
      systemPrompt?: string;
    } | undefined;
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    expect(result).toBeDefined();
    expect(result!.systemPrompt).toContain("BASE SYSTEM PROMPT");
    expect(result!.systemPrompt).toContain(MARKER);
    expect(result!.systemPrompt).toContain("## Brain Brief (retrieved)");
    // ordering: contract before brief, in ONE patch
    expect(result!.systemPrompt!.indexOf(MARKER)).toBeLessThan(
      result!.systemPrompt!.indexOf("## Brain Brief (retrieved)"),
    );

    const records = await waitForLines(3);
    const contract = recordOf(records, "before_agent_start");
    expect(contract.role).toBe("driver");
    expect(contract.driver_contract_injected).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// P3-B economics wiring (plan §5.1/§5.4/§5.5; schema v3 records)
// ---------------------------------------------------------------------------

describe("P3-B economics wiring", () => {
  it("before_provider_request appends provider_request_meta and never replaces the payload", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const payload = {
      model: "deepseek/deepseek-v4-flash",
      messages: [
        { role: "system", content: "SYSTEM-SECRET" },
        { role: "user", content: "TOP SECRET TASK" },
      ],
      tools: [{ name: "bash" }],
    };
    const result = handlers.get("before_provider_request")!(
      { type: "before_provider_request", payload },
      ctx,
    );
    expect(result).toBeUndefined(); // payload untouched, measurement only

    const records = await waitForLines(1);
    const meta = records.find((r) => r.kind === "provider_request_meta");
    expect(meta).toBeDefined();
    expect(meta?.v).toBe(3);
    expect(meta?.request_seq).toBe(1);
    expect(meta?.message_count).toBe(2);
    expect(meta?.payload_keys).toEqual(["messages", "model", "tools"]);
    expect(meta?.provider).toBe("deepseek");
    expect(meta?.model).toBe("deepseek-v4-flash");
    expect(typeof meta?.system_prefix_sha).toBe("string");
    expect(typeof meta?.tool_surface_sha).toBe("string");
    // privacy: no payload content anywhere in the telemetry file
    expect(JSON.stringify(records)).not.toContain("TOP SECRET");
    expect(JSON.stringify(records)).not.toContain("SYSTEM-SECRET");
    expect(JSON.stringify(records)).not.toContain("bash");
  });

  it("before_provider_request request_seq increments across requests", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    handlers.get("before_provider_request")!({ type: "before_provider_request", payload: {} }, ctx);
    handlers.get("before_provider_request")!({ type: "before_provider_request", payload: {} }, ctx);
    const records = await waitForLines(2);
    const seqs = records
      .filter((r) => r.kind === "provider_request_meta")
      .map((r) => r.request_seq);
    expect(seqs).toEqual([1, 2]);
  });

  it("message_end returns the SAME message (role preserved) and records assistant_usage with exact host values", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const message = {
      role: "assistant",
      content: [{ type: "text", text: "hi" }],
      usage: {
        input: 10,
        output: 5,
        cacheRead: 3,
        cacheWrite: 0,
        totalTokens: 18,
        cost: { input: 0.01, output: 0.02, cacheRead: 0.03, cacheWrite: 0.04, total: 0.1 },
      },
    };
    const result = handlers.get("message_end")!({ type: "message_end", message }, ctx) as {
      message?: unknown;
    };
    expect(result?.message).toBe(message); // identical object, role untouched

    const records = await waitForLines(1);
    const usage = records.find((r) => r.kind === "assistant_usage");
    expect(usage).toBeDefined();
    expect(usage?.v).toBe(3);
    expect(usage?.provider).toBe("deepseek");
    expect(usage?.model).toBe("deepseek-v4-flash");
    expect(usage?.input_tokens).toBe(10);
    expect(usage?.output_tokens).toBe(5);
    expect(usage?.cache_read_tokens).toBe(3);
    expect(usage?.cache_write_tokens).toBe(0); // zero preserved
    expect(usage?.total_tokens).toBe(18);
    expect(usage?.cost_total).toBe(0.1);
    expect(JSON.stringify(records)).not.toContain("hi"); // message content never persisted
  });

  it("message_end without usage writes no assistant_usage record and still returns the message", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const message = { role: "assistant", content: [] };
    const result = handlers.get("message_end")!({ type: "message_end", message }, ctx) as {
      message?: unknown;
    };
    expect(result?.message).toBe(message);
    await settle();
    let lines: string[] = [];
    try {
      lines = (await readFile(telemetryFile(), "utf8")).split("\n").filter((l) => l.trim().length > 0);
    } catch {
      // no file yet — nothing was written
    }
    expect(lines.some((l) => l.includes('"assistant_usage"'))).toBe(false);
  });

  it("message_end falls back to ctx model when the message lacks provider/model", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek/deepseek-v4-flash
    const message = { role: "assistant", usage: { input: 1, output: 2 } };
    handlers.get("message_end")!({ type: "message_end", message }, ctx);
    const records = await waitForLines(1);
    const usage = records.find((r) => r.kind === "assistant_usage");
    expect(usage?.provider).toBe("deepseek");
    expect(usage?.model).toBe("deepseek-v4-flash");
    // counters the host did not report are omitted, never invented
    expect(usage).not.toHaveProperty("cache_read_tokens");
    expect(usage).not.toHaveProperty("total_tokens");
    expect(usage).not.toHaveProperty("cost_total");
  });

  it("after_provider_response records status and hashed allowlisted headers only", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = handlers.get("after_provider_response")!(
      {
        type: "after_provider_response",
        status: 200,
        headers: {
          "x-ratelimit-remaining": "99",
          "content-type": "application/json",
          "x-request-id": "abc123",
          authorization: "Bearer sk-abc",
        },
      },
      ctx,
    );
    expect(result).toBeUndefined(); // read-only hook

    const records = await waitForLines(1);
    const meta = records.find((r) => r.kind === "provider_response_meta");
    expect(meta).toBeDefined();
    expect(meta?.v).toBe(3);
    expect(meta?.status).toBe(200);
    expect(meta?.headers).toHaveLength(1);
    expect((meta?.headers as { key: string; value_sha256: string }[])[0].key).toBe(
      "x-ratelimit-remaining",
    );
    expect(
      (meta?.headers as { key: string; value_sha256: string }[])[0].value_sha256,
    ).toMatch(/^[0-9a-f]{64}$/);
    const text = JSON.stringify(records);
    expect(text).not.toContain("abc123");
    expect(text).not.toContain("application/json");
    expect(text).not.toContain("sk-abc");
  });

  it("provider hooks fail open: a throwing payload getter records extension_error and never blocks", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const payload: Record<string, unknown> = {};
    Object.defineProperty(payload, "messages", {
      get() {
        throw new Error("payload boom");
      },
    });
    let threw = false;
    let result: unknown;
    try {
      result = handlers.get("before_provider_request")!(
        { type: "before_provider_request", payload },
        ctx,
      );
    } catch {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    expect(records[0].kind).toBe("extension_error");
    expect(records[0].error).toBe("payload boom");
  });

  it("message_end fail open: a throwing usage getter still returns the message unchanged", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    const message: Record<string, unknown> = { role: "assistant" };
    Object.defineProperty(message, "usage", {
      get() {
        throw new Error("usage boom");
      },
    });
    let threw = false;
    let result: unknown;
    try {
      result = handlers.get("message_end")!({ type: "message_end", message }, ctx);
    } catch {
      threw = true;
    }
    expect(threw).toBe(false);
    expect((result as { message?: unknown }).message).toBe(message);

    const records = await waitForLines(1);
    expect(records[0].kind).toBe("extension_error");
    expect(records[0].error).toBe("usage boom");
  });
});

describe("Part B/E: context paging wiring (real factory, [context_paging])", () => {
  const AUTOINJECT_CUSTOM_TYPE = "brain.autoinject.packet";

  function autoinjectMsg(deliveryId: string): unknown {
    return {
      role: "custom",
      customType: AUTOINJECT_CUSTOM_TYPE,
      content: "x".repeat(500),
      display: true,
      details: { delivery_id: deliveryId, packet_tokens: 100 },
      timestamp: "2026-01-01T00:00:00Z",
    };
  }

  function assistantMsg(): unknown {
    return {
      role: "assistant",
      content: [{ type: "text", text: "y".repeat(500) }],
      api: "messages",
      provider: "anthropic",
      model: "claude",
      usage: {},
      stopReason: "end_turn",
      timestamp: "2026-01-01T00:00:01Z",
      responseId: "resp-1",
    };
  }

  it("paging disabled (no [context_paging] section) -> always undefined even with eligible-looking input", async () => {
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1" },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
    expect(runVmemListPrePageSyncMock).not.toHaveBeenCalled();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();
  });

  it("current-turn pin window respected: an eligible element inside the pin window is never paged", async () => {
    enableContextPaging({ pinRecentMessages: 3, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1" },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    const handlers = loadFactory();
    const ctx = makeCtx();
    // Only 3 messages total, pin window is 3 -> pinFrom <= 0 -> nothing eligible.
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
  });

  it("budget respected: below budget -> undefined, vmem list AND claim never called", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 999999 });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
    expect(runVmemListPrePageSyncMock).not.toHaveBeenCalled();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();
  });

  it("max-pages cap respected: more eligible than the cap -> only the cap's worth requested/claimed/replaced, patch actually returned", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1, maxPagesPerContextEvent: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          residencyState: "RESIDENT",
          pinned: false,
        },
        {
          objId: "obj-2",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-2", packetArtifactRef: "art-2", packetSha256: "b".repeat(64) },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), autoinjectMsg("del-2"), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx) as
      | { messages?: unknown[] }
      | undefined;
    expect(result).toBeDefined();
    const patched = result!.messages as Array<Record<string, unknown>>;
    expect(patched).toHaveLength(3);
    // Exactly one of the two eligible elements was replaced (the cap = 1).
    const replacedCount = patched.filter(
      (m, i) => typeof m.content === "string" && (m.content as string).includes("[SECOND_BRAIN_VMEM]") && i < 2,
    ).length;
    expect(replacedCount).toBe(1);
    // The claim call itself was also capped -- never more than 1 candidate.
    expect(runVmemClaimPagesSyncMock).toHaveBeenCalledTimes(1);
    const claimArgs = runVmemClaimPagesSyncMock.mock.calls[0]?.[0] as { candidates: unknown[] };
    expect(claimArgs.candidates).toHaveLength(1);

    const records = await waitForLines(1);
    const paging = records.find((r) => r.kind === "context_paging");
    expect(paging?.paged_count).toBe(1);
    expect(paging?.requested_page_count).toBe(1);
    expect(paging?.claimed_page_count).toBe(1);
  });

  it("fail-open on a simulated vmem-list failure: undefined + extension_error, never throws", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({ ok: false, error: "simulated vmem list failure" });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];

    let threw = false;
    let result: unknown;
    try {
      result = handlers.get("context")!({ type: "context", messages }, ctx);
    } catch {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(result).toBeUndefined();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();

    const records = await waitForLines(1);
    const errRec = records.find((r) => r.kind === "extension_error");
    expect(errRec).toBeDefined();
    expect(String(errRec?.error)).toContain("simulated vmem list failure");
  });

  it("fail-open on a throwing runVmemListPrePageSync mock: undefined + extension_error, never throws", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockImplementation(() => {
      throw new Error("mock boom");
    });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];

    let threw = false;
    let result: unknown;
    try {
      result = handlers.get("context")!({ type: "context", messages }, ctx);
    } catch {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    const errRec = records.find((r) => r.kind === "extension_error");
    expect(errRec).toBeDefined();
  });

  it("fail-open on a simulated claim-pages failure: undefined + extension_error, original messages untouched", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    runVmemClaimPagesSyncMock.mockReturnValue({ ok: false, error: "simulated claim-pages failure" });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();

    const records = await waitForLines(1);
    const errRec = records.find((r) => r.kind === "extension_error");
    expect(errRec).toBeDefined();
    expect(String(errRec?.error)).toContain("simulated claim-pages failure");
  });

  it("claim confirms nothing (lost a race): undefined, no replacement, no context_paging record", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    runVmemClaimPagesSyncMock.mockReturnValue({ ok: true, claimedObjIds: [] });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
  });

  it("zero mutation when no eligible cold items exist: enabled + over budget but no claimable match -> undefined", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({ ok: true, objects: [] });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();
  });

  function toolResultMsg(toolCallId: string, content = "z".repeat(500)): unknown {
    return {
      role: "toolResult",
      toolCallId,
      toolName: "ipython",
      content: [{ type: "text", text: content }],
      details: { some: "detail" },
      isError: false,
      timestamp: "2026-01-01T00:00:02Z",
    };
  }

  it("RC4 CVM closure repair (Repair A closure, end-to-end): an RTD-backed toolResult whose VMem object metadata carries BOTH toolCallId and artifactRef is now a real live paging candidate — claimed and pointerized through the real factory, mirroring the AutoInject success shape", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-rtd-1",
          kind: "TOOL_OBSERVATION",
          metadata: { toolCallId: "call-rtd-1", artifactRef: "art-rtd-1" },
          residencyState: "RESIDENT",
          pinned: false,
        },
      ],
    });
    runVmemClaimPagesSyncMock.mockReturnValue({ ok: true, claimedObjIds: ["obj-rtd-1"] });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [toolResultMsg("call-rtd-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx) as
      | { messages?: unknown[] }
      | undefined;
    expect(result).toBeDefined();
    const patched = result!.messages as Array<Record<string, unknown>>;
    expect(Array.isArray(patched[0]?.content)).toBe(true);
    const blocks = patched[0]?.content as Array<{ type: string; text: string }>;
    expect(blocks[0]?.text).toContain("[SECOND_BRAIN_VMEM]");
    expect(blocks[0]?.text).toContain("obj-rtd-1");
    expect(runVmemClaimPagesSyncMock).toHaveBeenCalledTimes(1);
    const claimArgs = runVmemClaimPagesSyncMock.mock.calls[0]?.[0] as { candidates: Array<{ objId: string }> };
    expect(claimArgs.candidates).toEqual([{ objId: "obj-rtd-1", kind: "TOOL_OBSERVATION" }]);

    const records = await waitForLines(1);
    const paging = records.find((r) => r.kind === "context_paging");
    expect(paging?.paged_count).toBe(1);
    expect(paging?.newly_claimed_count).toBe(1);
    expect(paging?.reprojected_page_count).toBe(0);
  });

  it("Repair B (real factory, end-to-end): an already-EVICTED, proof-backed AutoInject object correlates to a reconstructed full-text live message -> NO claim call is made -> reprojected via the real 'context' handler; telemetry counts route correctly", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({
      ok: true,
      objects: [
        {
          objId: "obj-evicted-wiring-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-evicted-1", packetArtifactRef: "art-evicted-1", packetSha256: "a".repeat(64) },
          residencyState: "EVICTED",
          pinned: false,
        },
      ],
    });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const messages = [autoinjectMsg("del-evicted-1"), assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx) as
      | { messages?: unknown[] }
      | undefined;
    expect(result).toBeDefined();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled(); // Path B: no claim call for an already-EVICTED object
    const patched = result!.messages as Array<Record<string, unknown>>;
    expect(typeof patched[0]?.content).toBe("string");
    expect((patched[0]?.content as string)).toContain("[SECOND_BRAIN_VMEM]");

    const records = await waitForLines(1);
    const paging = records.find((r) => r.kind === "context_paging");
    expect(paging?.paged_count).toBe(1);
    expect(paging?.newly_claimed_count).toBe(0);
    expect(paging?.reprojected_page_count).toBe(1);
  });

  it("Repair B double-wrap guard (real factory): a live message whose content already starts with [SECOND_BRAIN_VMEM] is never re-paged, never mutated, vmem list not even consulted for it in isolation", async () => {
    enableContextPaging({ pinRecentMessages: 1, residentTokenBudget: 1 });
    runVmemListPrePageSyncMock.mockReturnValue({ ok: true, objects: [] });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const alreadyPointerized = autoinjectMsg("del-already-paged");
    (alreadyPointerized as Record<string, unknown>).content =
      "[SECOND_BRAIN_VMEM]\nkind=RESEARCH_RESULT\nobj_id=obj-x\ndelivery_id=del-already-paged\nstate=EVICTED\n...";
    const messages = [alreadyPointerized, assistantMsg(), assistantMsg()];
    const result = handlers.get("context")!({ type: "context", messages }, ctx);
    expect(result).toBeUndefined();
    expect(runVmemListPrePageSyncMock).not.toHaveBeenCalled();
    expect(runVmemClaimPagesSyncMock).not.toHaveBeenCalled();
  });
});
