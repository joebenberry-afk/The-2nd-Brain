import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import { RECALL_DEFAULT_MAX_TERMS } from "../src/recall-gate";
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
const runEnvironmentAssessmentMock = vi.hoisted(() => vi.fn());
const runEnvironmentAssessmentAsyncMock = vi.hoisted(() => vi.fn());
vi.mock("../src/environment-mirror", () => ({
  runEnvironmentAssessmentSync: runEnvironmentAssessmentMock,
  runEnvironmentAssessment: runEnvironmentAssessmentAsyncMock,
}));

const runP4PulseMock = vi.hoisted(() => vi.fn());
const runP4PulseSyncMock = vi.hoisted(() => vi.fn());
vi.mock("../src/p4-mirror", () => ({
  runP4Pulse: runP4PulseMock,
  runP4PulseSync: runP4PulseSyncMock,
}));

// P3.16 skill-visibility wiring: control the visibility outcome directly
// instead of spawning a real CLI process on every before_agent_start (same
// rationale as runAdvisoryAutoInjectMock/runEnvironmentAssessmentMock above).
// Default: no plan (fails open exactly like a fresh/unconfigured brain home),
// so every pre-existing before_agent_start assertion below now also sees one
// additional "omp_visibility_plan" record -- tests specifically exercising
// the visibility bridge override this via ExtensionOptions.ompVisibilityRunner.
const runOmpVisibilityMock = vi.hoisted(() => vi.fn());
vi.mock("../src/visibility-bridge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/visibility-bridge")>();
  return { ...actual, runOmpVisibility: runOmpVisibilityMock };
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
  runEnvironmentAssessmentMock.mockReset();
  runEnvironmentAssessmentMock.mockReturnValue({
    ok: true,
    sessionId: "wiring-test",
    environmentStewardId: "envsteward-test",
    environmentHash: "a".repeat(64),
    mutationDetected: false,
    mutationClassification: "none",
    completionEligible: true,
  });
  // Background (session_start / task_boundary) assessments share the sync mock's
  // configured result and call log unless a test overrides the async mock.
  runEnvironmentAssessmentAsyncMock.mockReset();
  runEnvironmentAssessmentAsyncMock.mockImplementation(async (options: unknown) =>
    runEnvironmentAssessmentMock(options),
  );
  runP4PulseMock.mockReset();
  runP4PulseMock.mockResolvedValue({ ok: true, sessionId: "wiring-test" });
  runP4PulseSyncMock.mockReset();
  runP4PulseSyncMock.mockReturnValue({ ok: true, sessionId: "wiring-test" });
  runOmpVisibilityMock.mockReset();
  runOmpVisibilityMock.mockResolvedValue({ visibility_plan: null, hydrated_instructions: {}, error: null });
});

afterEach(async () => {
  for (const key of ENV_KEYS) {
    if (SAVED_ENV[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED_ENV[key] as string;
  }
  // Drain any still-in-flight fire-and-forget telemetry writes (append()'s
  // internal promise chain) before removing the temp dir: without this, a
  // write racing rm() can recreate the directory mid-delete on Windows
  // (ENOTEMPTY/ENOENT/EPERM), independent of test correctness.
  await settle();
  await rm(tmp, { recursive: true, force: true });
});

/** Load the factory with a recording fake ExtensionAPI (+ optional options). */
function loadFactory(options?: ExtensionOptions, journal?: unknown[], journalError?: Error): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
    appendEntry: (customType: string, data?: unknown): void => {
      if (journalError) throw journalError;
      journal?.push({ type: "custom", customType, data });
    },
  } as unknown as ExtensionAPI;
  factory(pi, options);
  return handlers;
}

/** Native session-manager fixture: identity is independent of the filename. */
function nativeManager(file: string): ExtensionContext["sessionManager"] {
  const stem = file.split(/[\\/]/u).pop()?.replace(/\.jsonl$/u, "") ?? "unknown";
  const id = `native-${sha256Hex(file).slice(0, 24)}`;
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    getSessionFile: () => file,
    getSessionId: () => id,
    getHeader: () => ({ type: "session", version: 1, id, timestamp }),
    getEntries: () =>
      stem === "wiring-test"
        ? [{
            type: "custom",
            customType: "brain.active-state",
            details: { session_id: "wiring-test" },
            timestamp,
          }]
        : [],
  };
}

/** Fake ExtensionContext with the actual native identity surface. */
function makeCtx(overrides: Partial<ExtensionContext> = {}): ExtensionContext {
  const defaultFile = () => join(tmp, "sessions", "wiring-test.jsonl");
  const overrideManager = overrides.sessionManager;
  const getSessionFile = overrideManager?.getSessionFile?.bind(overrideManager) ?? defaultFile;
  const generated = () => nativeManager(getSessionFile() ?? defaultFile());
  const manager = typeof overrideManager?.getHeader === "function" && typeof overrideManager?.getSessionId === "function"
    ? overrideManager
    : {
        getSessionFile,
        getSessionId: () => generated().getSessionId!(),
        getHeader: () => generated().getHeader!(),
        getEntries: () => generated().getEntries!(),
        ...overrideManager,
      };
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
    signal: undefined,
    hasUI: false,
    ui: undefined,
    ...overrides,
    sessionManager: manager,
  };
}

/** Create OMP-native transcript ancestry with real session headers. */
function nativeSessionCtx(rootSession: string, ...agents: string[]): ExtensionContext {
  const sessionsDir = join(tmp, "native-sessions");
  mkdirSync(sessionsDir, { recursive: true });
  const timestamp = "2026-01-01T00:00:00.000Z";
  const writeHeader = (file: string): void => {
    const id = `native-${sha256Hex(file).slice(0, 24)}`;
    const stem = file.split(/[\\/]/u).pop()?.replace(/\.jsonl$/u, "") ?? "unknown";
    writeFileSync(
      file,
      `${JSON.stringify({ type: "session", version: 1, id, timestamp })}\n` +
        `${JSON.stringify({ type: "custom", customType: "brain.active-state", details: { session_id: stem }, timestamp })}\n`,
      "utf8",
    );
  };
  let transcript = join(sessionsDir, `${rootSession}.jsonl`);
  writeHeader(transcript);
  for (const agent of agents) {
    const artifactsDir = transcript.slice(0, -".jsonl".length);
    mkdirSync(artifactsDir, { recursive: true });
    transcript = join(artifactsDir, `${agent}.jsonl`);
    writeHeader(transcript);
  }
  const stem = transcript.split(/[\\/]/u).pop()?.replace(/\.jsonl$/u, "") ?? "unknown";
  return makeCtx({
    sessionManager: {
      getSessionFile: () => transcript,
      getEntries: () => [{
        type: "custom",
        customType: "brain.active-state",
        details: { session_id: stem },
        timestamp,
      }],
    },
  });
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

  it("frozen-per-lifecycle: writes one runtime-ready status file at factory startup, never per session", () => {
    loadFactory();
    const statusPath = join(tmp, "state", "extension-runtime-ready.json");
    const status = JSON.parse(readFileSync(statusPath, "utf8")) as {
      home: string;
      runtime_python: string;
      brain_version: string | null;
      identity_hash: string;
    };
    expect(status.home).toBe(tmp);
    expect(status.brain_version).toBeNull(); // no VERSION file in this fixture home
    expect(status.identity_hash).toMatch(/^[0-9a-f]{64}$/);

    // A later env change never silently retargets a running instance:
    // only a fresh factory load (/reload) re-resolves and rewrites the
    // frozen identity file.
    process.env.SECOND_BRAIN_PYTHON = "R:/other/python.exe";
    loadFactory();
    const reloaded = JSON.parse(readFileSync(statusPath, "utf8")) as { runtime_python: string };
    expect(reloaded.runtime_python).toBe("R:/other/python.exe");
  });

  it("frozen-per-lifecycle: reads the Brain's own VERSION file into the status record", () => {
    writeFileSync(join(tmp, "VERSION"), "2.0.0-rc.1\n");
    loadFactory();
    const status = JSON.parse(
      readFileSync(join(tmp, "state", "extension-runtime-ready.json"), "utf8"),
    ) as { brain_version: string | null };
    expect(status.brain_version).toBe("2.0.0-rc.1");
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

  it("consumes Environment Steward evidence at task and session boundaries", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    const started = mirrorFireAndForgetMock.mock.calls.find(
      (call) => call[0]?.record?.kind === "session_started",
    );
    expect(started).toBeDefined();
    expect(runEnvironmentAssessmentMock).toHaveBeenCalledWith(
      expect.objectContaining({ phase: "session_start", hostSessionId: "wiring-test" }),
    );
    await vi.waitFor(() => {
      const assessed = mirrorFireAndForgetMock.mock.calls.find(
        (call) =>
          call[0]?.record?.kind === "environment_assessment" &&
          call[0]?.record?.fields?.phase === "session_start",
      );
      expect(assessed?.[0]?.record?.fields?.environment_steward_id).toBe("envsteward-test");
    });

    await handlers.get("before_agent_start")!({ prompt: "task boundary" }, ctx);
    expect(runEnvironmentAssessmentMock).toHaveBeenCalledWith(
      expect.objectContaining({ phase: "task_boundary", taskId: expect.any(String) }),
    );

    runEnvironmentAssessmentMock.mockReturnValue({
      ok: true,
      sessionId: "wiring-test",
      environmentStewardId: "envsteward-test",
      environmentHash: "b".repeat(64),
      mutationDetected: false,
      mutationClassification: "none",
      completionEligible: true,
      evidence: { project_id: "project-a" },
    });
    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);
    const inactive = mirrorFireAndForgetMock.mock.calls.find(
      (call) => call[0]?.record?.kind === "session_inactive",
    );
    expect(inactive?.[0]?.record?.fields?.environment_hash).toBe("b".repeat(64));
    expect(runEnvironmentAssessmentMock).toHaveBeenCalledWith(
      expect.objectContaining({ phase: "shutdown", hostSessionId: "wiring-test" }),
    );
    expect(runP4PulseSyncMock).toHaveBeenCalledWith(
      expect.objectContaining({
        hostSessionId: "wiring-test",
        event: "session_shutdown",
        projectId: "project-a",
        repo: "C:/work",
      }),
    );
    await settle();
  });

  it("never waits for the environment assessment before the host turn (PERF-02)", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    runEnvironmentAssessmentAsyncMock.mockImplementation(() => new Promise(() => undefined));

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    await handlers.get("before_agent_start")!({ prompt: "rename tmp to buffer" }, ctx);

    expect(runEnvironmentAssessmentAsyncMock).toHaveBeenCalledWith(
      expect.objectContaining({ phase: "task_boundary" }),
    );
    expect(runEnvironmentAssessmentMock).not.toHaveBeenCalled();
    const kinds = mirrorFireAndForgetMock.mock.calls.map((call) => call[0]?.record?.kind);
    expect(kinds).toContain("session_started");
    expect(kinds).toContain("user_task");
    expect(kinds).not.toContain("environment_assessment");
    await settle();
  });

  it("Task 7: session_start/turn_start queue a fire-and-forget P4 pulse and append its bounded heartbeat", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    runP4PulseMock.mockResolvedValue({
      ok: true,
      sessionId: "wiring-test",
      heartbeat: {
        mode: "shadow", event: "session_start", due: true, ran: true, healthy: true,
        db_ok: true, cache_pruned_count: 0, git_dirty: false, issue_codes: [],
        latency_ms: 2, model_tokens_used: 0,
      },
    });

    handlers.get("session_start")!({ reason: "startup" }, ctx);
    expect(runP4PulseMock).toHaveBeenCalledWith(
      expect.objectContaining({ hostSessionId: "wiring-test", event: "session_start", repo: "C:/work" }),
    );

    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    expect(runP4PulseMock).toHaveBeenCalledWith(
      expect.objectContaining({ hostSessionId: "wiring-test", event: "turn_start", repo: "C:/work" }),
    );

    await settle();
    const records = (await readFile(telemetryFile(), "utf8"))
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l));
    const heartbeats = records.filter((r) => r.kind === "heartbeat_pulse");
    expect(heartbeats.length).toBeGreaterThan(0);
    expect(heartbeats[0].model_tokens_used).toBe(0);
  });

  it("Task 7: session_shutdown persists heartbeat and fingerprint records before returning", () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    runP4PulseSyncMock.mockReturnValue({
      ok: true,
      sessionId: "wiring-test",
      heartbeat: {
        mode: "shadow", event: "session_shutdown", due: true, ran: true, healthy: true,
        db_ok: true, cache_pruned_count: 1, git_dirty: false, issue_codes: [],
        latency_ms: 5, model_tokens_used: 0,
      },
      candidates: [{ candidate_id: "candidate-1", lifecycle_state: "candidate" }],
      fingerprints: [
        {
          fingerprint_id: "fp-1", category: "PROMPT_BLOAT", scope_id: "project-a",
          occurrence_count: 3, impact_score: 4.2, evidence_count: 2, evidence_hash: "a".repeat(64),
        },
      ],
    });

    handlers.get("session_shutdown")!({ reason: "quit" }, ctx);

    const records = readFileSync(telemetryFile(), "utf8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l));
    const heartbeat = records.find((r) => r.kind === "heartbeat_pulse");
    const fingerprint = records.find((r) => r.kind === "bottleneck_fingerprint");
    expect(heartbeat?.mode).toBe("shadow");
    expect(heartbeat?.model_tokens_used).toBe(0);
    expect(fingerprint?.fingerprint_id).toBe("fp-1");
    expect(fingerprint?.evidence_hash).toBe("a".repeat(64));
    // Privacy: the raw candidate dict (lifecycle_state, candidate_id, ...)
    // is never serialized into telemetry by these sensors.
    const serialized = JSON.stringify(records);
    expect(serialized).not.toContain("candidate_id");
    expect(serialized).not.toContain("lifecycle_state");
    expect(records.map((r) => r.kind)).toContain("session_shutdown");
  });

  it("Task 7: a failed P4 pulse persists its error before shutdown returns", () => {
    const handlers = loadFactory();
    const ctx = makeCtx();
    runP4PulseSyncMock.mockReturnValue({ ok: false, sessionId: "wiring-test", error: "p4 pulse timed out" });

    const result = handlers.get("session_shutdown")!({ reason: "quit" }, ctx);
    expect(result).toBeUndefined();

    const records = readFileSync(telemetryFile(), "utf8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l));
    expect(records.map((r) => r.kind)).toContain("session_shutdown");
    const error = records.find((r) => r.kind === "extension_error" && r.error === "p4 pulse timed out");
    expect(error).toBeDefined();
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

  it("swallows a throwing sessionManager without creating an anonymous identity", async () => {
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
    expect(rec.kind).toBe("extension_error");
    expect(rec.session).toBe("unknown");
    expect(rec.session).not.toMatch(/^anon-/);
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
// Native session identity (src/index.ts)
// -------------------------------------------------------------------------

describe("native session identity (src/index.ts)", () => {
  const timestamp = "2026-01-01T00:00:00.000Z";

  function identityCtx(
    file: string,
    id: string,
    entries: unknown[] = [],
    headerTimestamp = timestamp,
  ): ExtensionContext {
    return makeCtx({
      sessionManager: {
        getSessionFile: () => file,
        getSessionId: () => id,
        getHeader: () => ({
          type: "session",
          version: 1,
          id,
          timestamp: headerTimestamp,
        }),
        getEntries: () => entries,
      },
    });
  }

  it("refuses a missing native identity without creating an anonymous shared key", async () => {
    const handlers = loadFactory();
    handlers.get("turn_start")!({ turnIndex: 0 }, anonCtx());
    const file = await waitForAnyTelemetryFile();
    const [record] = await waitForFileLines(file, 1);
    expect(record.kind).toBe("extension_error");
    expect(record.session).toBe("unknown");
    expect(record.session).not.toMatch(/^anon-/u);
  });

  it("keeps same-basename native sessions in distinct telemetry ledgers", async () => {
    const handlers = loadFactory();
    const left = identityCtx(join(tmp, "left", "shared-session.jsonl"), "native-left");
    const right = identityCtx(join(tmp, "right", "shared-session.jsonl"), "native-right");
    handlers.get("session_start")!({ reason: "startup" }, left);
    handlers.get("session_start")!({ reason: "startup" }, right);
    const rightFile = join(
      telemetryDir(),
      `${timestamp.replace(/[:.]/gu, "-")}_native-right.jsonl`,
    );
    await waitForFileLines(rightFile, 1);
    const names = (await readdir(telemetryDir())).filter((name) => name.endsWith(".jsonl"));
    expect(names).toEqual(expect.arrayContaining([
      `${timestamp.replace(/[:.]/gu, "-")}_native-left.jsonl`,
      `${timestamp.replace(/[:.]/gu, "-")}_native-right.jsonl`,
    ]));
  });

  it("preserves a verified timestamp-qualified legacy assignment", async () => {
    const handlers = loadFactory();
    const entries = [{
      type: "custom",
      customType: "brain.active-state",
      details: { session_id: "EconomicsRuntimeBinding" },
      timestamp,
    }];
    const file = join(tmp, "named", "native.jsonl");
    handlers.get("turn_start")!({ turnIndex: 0 }, identityCtx(file, "native-named", entries));
    const telemetry = await waitForAnyTelemetryFile();
    const [record] = await waitForFileLines(telemetry, 1);
    expect(record.session).toBe("EconomicsRuntimeBinding");
  });

  it("preserves the native session manager receiver when reading identity history", async () => {
    const handlers = loadFactory();
    const entries = [{
      type: "custom_message", customType: "brain.active-state",
      details: { session_id: "receiver-bound-history" }, timestamp,
    }];
    const ctx = identityCtx(join(tmp, "receiver.jsonl"), "native-receiver", entries);
    ctx.sessionManager = {
      ...ctx.sessionManager,
      entries,
      getEntries() { return this.entries; },
    } as ExtensionContext["sessionManager"] & { entries: unknown[] };
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    const [record] = await waitForFileLines(await waitForAnyTelemetryFile(), 1);
    expect(record.kind).toBe("turn_start");
    expect(record.session).toBe("receiver-bound-history");
  });

  it("uses a fresh key for a fork with provably inherited active-state hints", async () => {
    const handlers = loadFactory();
    const entries = [{
      type: "custom",
      customType: "brain.active-state",
      details: { session_id: "parent-ledger" },
      timestamp: "2025-12-31T23:59:59.000Z",
    }];
    const id = "native-fork";
    const file = join(tmp, "fork", "shared-session.jsonl");
    const ctx = identityCtx(file, id, entries, timestamp);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    const telemetry = await waitForAnyTelemetryFile();
    const [record] = await waitForFileLines(telemetry, 1);
    expect(record.session).toBe(`${timestamp.replace(/[:.]/gu, "-")}_${id}`);
    expect(record.session).not.toBe("parent-ledger");
  });

  it("refuses an existing legacy hint whose ownership cannot be proven", async () => {
    const handlers = loadFactory();
    const file = join(tmp, "ambiguous", "native.jsonl");
    const ctx = identityCtx(file, "native-ambiguous", [{
      type: "custom",
      customType: "brain.active-state",
      details: { session_id: "ambiguous-ledger" },
    }]);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    const telemetry = await waitForAnyTelemetryFile();
    const [record] = await waitForFileLines(telemetry, 1);
    expect(record.kind).toBe("extension_error");
    expect(record.session).toBe("unknown");
    const names = (await readdir(telemetryDir())).filter((name) => name.endsWith(".jsonl"));
    expect(names).not.toContain("ambiguous-ledger.jsonl");
  });

  it("refuses an unbound user-only transcript when its prior canonical state exists", async () => {
    const journal: Array<{ type: string; customType: string; data: unknown }> = [];
    const handlers = loadFactory({}, journal);
    const oldState = join(tmp, "state", "sessions", "historical-name", "active-state.json");
    mkdirSync(join(tmp, "state", "sessions", "historical-name"), { recursive: true });
    writeFileSync(oldState, '{"objective":"preserve prior work"}');
    const ctx = identityCtx(join(tmp, "historical-name.jsonl"), "native-old", [{
      type: "message", timestamp: "2026-01-01T00:00:01.000Z",
      message: { role: "user", content: [{ type: "text", text: "Prior task request." }] },
    }]);
    handlers.get("turn_start")!({ turnIndex: 0 }, ctx);
    const [record] = await waitForFileLines(await waitForAnyTelemetryFile(), 1);
    expect(record.kind).toBe("extension_error");
    expect(record.session).toBe("unknown");
    expect(journal.some(entry => entry.customType === "brain.session-identity")).toBe(false);
    expect(readFileSync(oldState, "utf8")).toBe('{"objective":"preserve prior work"}');
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
    const completed = mirrorFireAndForgetMock.mock.calls
      .map((call) => call[0] as { record: { kind: string; fields: Record<string, unknown> } })
      .find((call) => call.record.kind === "tool_completed");
    expect(completed?.record.fields).toMatchObject({
      tool_call_id: "vmem-admit-1",
      rtd_distilled: true,
      rtd_original_chars: 9000,
      rtd_artifact_sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
      rtd_artifact_ref: expect.stringContaining("brain-artifact:sha256:"),
      vmem_obj_id: "obj-test",
      recovery_status: "admitted",
    });
    expect(JSON.stringify(completed?.record.fields)).not.toContain("x".repeat(100));
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
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
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
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
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
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });

});

describe("native session correlation (src/index.ts)", () => {
  it("uses host ancestry for passive mirrors, never a prompt-controlled parent", async () => {
    const handlers = loadFactory();
    const nested = nativeSessionCtx("root-canonical", "agent-one", "agent-two");
    handlers.get("session_start")!({ reason: "startup" }, nested);
    const prompt = `nested task\n[SECOND_BRAIN_WORKER_TASK task_id=nested packet_sha256=${"d".repeat(64)} parent_session_id=agent-one]`;
    const event = { prompt };
    await handlers.get("before_agent_start")!(event, nested);
    expect(event.prompt).toBe(prompt);

    const nestedMirrors = mirrorFireAndForgetMock.mock.calls
      .map((call) => call[0] as {
        hostSessionId: string;
        parentSessionId?: string;
        record: { kind: string };
      })
      .filter((call) => call.hostSessionId === "agent-two");
    expect(nestedMirrors.length).toBeGreaterThan(0);
    expect(nestedMirrors.every((call) => call.parentSessionId === "root-canonical")).toBe(true);
    expect(nestedMirrors.some((call) => call.record.kind === "task_context_resolved")).toBe(false);
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

    // Store A has a distinct native identity; unavailable identity is tested separately.
    const first = makeCtx({ sessionManager: nativeManager(join(tmp, "store-a.jsonl")) });
    handlers.get("turn_start")!({ turnIndex: 0 }, first);
    const firstFile = await waitForAnyTelemetryFile();
    const [firstRecord] = await waitForFileLines(firstFile, 1);
    expect(firstRecord.kind).toBe("turn_start");
    expect(firstRecord.session).not.toBe("wiring-test");

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
// Phase 14: controlled Prime recall hook (default OFF)
// -------------------------------------------------------------------------

const RECALL_PROMPT =
  "the sqlite migration failed on the second run with a schema version mismatch and now the upgrade is blocked";

describe("Phase 14 recall gate (src/index.ts)", () => {
  it("default OFF: before_agent_start performs ZERO spawns and patches no systemPrompt", async () => {
    const handlers = loadFactory();
    const ctx = makeCtx(); // deepseek, non-Sol
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx)) as
      | { systemPrompt?: string }
      | undefined;
    expect(result?.systemPrompt).toBeUndefined(); // PERF-01: host prompt untouched
    expect(recallRunMock).not.toHaveBeenCalled();
    // measurement records still appended (P3-D lean fail-open on missing skill)
    const records = await waitForLines(4);
    expect(records.map((r) => r.kind)).toEqual(["omp_visibility_plan", "extension_error", "lean_kernel", "before_agent_start"]);
  });

  it("enabled + substantial prompt: spawns ONCE and appends the brief to the TAIL message, never systemPrompt", async () => {
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
      message?: { content?: string };
    } | undefined;
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    const [options] = recallRunMock.mock.calls[0]! as [
      { home: string; query: string; cfg: { maxRows: number } },
    ];
    expect(options.home).toBe(tmp);
    // The CLI needs bounded keywords, not the raw prompt: it keeps up to eight
    // query terms by IDF and requires at least half of them to occur in one
    // memory, so a prose prompt matches nothing.
    expect(options.query).not.toBe(RECALL_PROMPT);
    expect(options.query.split(" ")).toHaveLength(RECALL_DEFAULT_MAX_TERMS);
    for (const term of options.query.split(" ")) {
      expect(term).toMatch(/^[a-z0-9]{3,}$/);
    }
    expect(options.cfg.maxRows).toBe(3);
    expect(result).toBeDefined();
    expect(result!.systemPrompt).toBeUndefined(); // dynamic recall content never touches the system prompt
    expect(result!.message?.content).toContain("## Brain Brief (retrieved)");
    expect(result!.message?.content).toContain("**sqlite migration failure recovery**");
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });

  it("enabled + trivial prompt: no recall spawn and no systemPrompt patch", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: "hi there" }, ctx)) as
      | { systemPrompt?: string }
      | undefined;
    expect(result?.systemPrompt).toBeUndefined();
    expect(recallRunMock).not.toHaveBeenCalled();
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });

  it("enabled + recall spawn fails: silent, no recall injection, no throw", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockRejectedValue(new Error("spawn boom"));
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx)) as
      | { systemPrompt?: string }
      | undefined;
    expect(result?.systemPrompt).toBeUndefined();
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    await settle(); // drain fire-and-forget telemetry writes before teardown
  });

  it("native model labels do not suppress useful recall", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockResolvedValue([{ title: "Stored note", status: "current", evidence_grade: "TESTED" }]);
    const handlers = loadFactory();
    const ctx = makeCtx({ model: { id: "gpt-5.6-sol", provider: "openai-codex" } });
    const result = await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx) as
      | { systemPrompt?: string; message?: { content?: string } }
      | undefined;
    expect(result?.systemPrompt).toBeUndefined(); // dynamic recall never patches the system prompt
    expect(result?.message?.content).toContain("## Brain Brief (retrieved)");
    expect(recallRunMock).toHaveBeenCalledTimes(1);
  });

  it("enabled + brief builder yields nothing (no valid rows): no recall injection and no systemPrompt patch", async () => {
    process.env.SECOND_BRAIN_RECALL = "1";
    process.env.SECOND_BRAIN_RECALL_MIN_CHARS = "10";
    recallRunMock.mockResolvedValue([{ summary: "no title" }, "garbage"]);
    const handlers = loadFactory();
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: RECALL_PROMPT }, ctx)) as
      | { systemPrompt?: string }
      | undefined;
    expect(result?.systemPrompt).toBeUndefined();
    expect(recallRunMock).toHaveBeenCalledTimes(1);
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
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
      content: [{ type: "text", text: "y".repeat(30000) }],
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
  it("audited closeout retains appended and same-length current messages after a cached paging view", async () => {
    enableContextPaging({ residentTokenBudget: 6000 });
    const handlers = loadFactory();
    const ctx = makeCtx();
    const hook = handlers.get("context")!;
    const previous = [{ role: "user", content: "old requirement" }];
    handlers.get("session_before_compact")!({ preparation: {}, branchEntries: [] }, ctx);
    hook({ messages: previous }, ctx);
    for (const current of [
      [...previous, { role: "user", content: "new requirement" }, { role: "assistant", content: [{ type: "toolCall", id: "current-call", name: "read", arguments: {} }] }, { role: "toolResult", toolCallId: "current-call", content: "current result" }],
      [{ role: "user", content: "replacement requirement" }],
    ]) {
      const result = hook({ messages: current }, ctx) as { messages?: unknown[] } | undefined;
      expect(result?.messages ?? current).toEqual(current);
    }
  });
});

describe("P3.16 skill-visibility wiring (real factory, ompVisibilityRunner seam)", () => {
  it("shadow-mode plan never injects specialist text into the returned message", async () => {
    const handlers = loadFactory({
      ompVisibilityRunner: async () => ({
        visibility_plan: {
          visibility_plan_id: "vplan-shadow-1",
          mode: "shadow",
          selected_skill_ids: ["x"],
          hydrated_skill_ids: ["x"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { x: "text" },
        error: null,
      }),
    });
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: "do the thing" }, ctx)) as
      | { message?: { content?: unknown }; systemPrompt?: string }
      | undefined;
    expect(JSON.stringify(result ?? {})).not.toContain("text");
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });

  it("enforced-mode plan with a hydrated skill injects specialist text into the returned message", async () => {
    const handlers = loadFactory({
      ompVisibilityRunner: async () => ({
        visibility_plan: {
          visibility_plan_id: "vplan-x",
          mode: "enforced",
          selected_skill_ids: ["skill1"],
          hydrated_skill_ids: ["skill1"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { skill1: "specialist body text" },
        error: null,
      }),
    });
    const ctx = makeCtx();
    const result = (await handlers.get("before_agent_start")!({ prompt: "do the thing" }, ctx)) as
      | { message?: { content?: unknown }; systemPrompt?: string }
      | undefined;
    expect(result).toBeDefined();
    expect(result?.message?.content).toContain("specialist body text");
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });

  it("a rejecting/erroring runner injects nothing and the handler completes without throwing", async () => {
    const handlers = loadFactory({
      ompVisibilityRunner: async () => ({
        visibility_plan: null,
        hydrated_instructions: {},
        error: "BRAIN_VISIBILITY_UNAVAILABLE",
      }),
    });
    const ctx = makeCtx();
    let result: unknown;
    await expect(
      (async () => {
        result = await handlers.get("before_agent_start")!({ prompt: "do the thing" }, ctx);
      })(),
    ).resolves.not.toThrow();
    expect(JSON.stringify(result ?? {})).not.toContain("specialist");
    await settle(); // drain pending fire-and-forget telemetry writes before teardown

    const throwingHandlers = loadFactory({
      ompVisibilityRunner: async () => {
        throw new Error("boom");
      },
    });
    const throwingCtx = makeCtx();
    await expect(
      throwingHandlers.get("before_agent_start")!({ prompt: "do the thing" }, throwingCtx),
    ).resolves.not.toThrow();
    await settle(); // drain pending fire-and-forget telemetry writes before teardown
  });
  it("caches visibility per session, turn, and task while reusing enforced injection", async () => {
    const runner = vi.fn(async () => ({
      visibility_plan: {
        visibility_plan_id: "vplan-cached",
        mode: "enforced" as const,
        selected_skill_ids: ["skill1"],
        hydrated_skill_ids: ["skill1"],
        rejected_skill_ids: {},
        unavailable_skill_ids: {},
      },
      hydrated_instructions: { skill1: "cached specialist body" },
      error: null,
    }));
    const handlers = loadFactory({ ompVisibilityRunner: runner });
    const ctx = makeCtx();
    const beforeAgentStart = handlers.get("before_agent_start")!;
    const first = (await beforeAgentStart({ prompt: "repeat this task" }, ctx)) as {
      message?: { content?: unknown };
    };
    const second = (await beforeAgentStart({ prompt: "repeat this task" }, ctx)) as {
      message?: { content?: unknown };
    };

    expect(runner).toHaveBeenCalledTimes(1);
    expect(first.message?.content).toContain("cached specialist body");
    expect(second.message?.content).toContain("cached specialist body");
    const records = await waitForLines(4);
    await settle(300);
    const finalRecords = (await readFile(telemetryFile(), "utf8"))
      .split("\n")
      .filter((line) => line.trim().length > 0)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(finalRecords.length).toBeGreaterThanOrEqual(records.length);
    const visibilityRecords = finalRecords.filter((record) => record.kind === "omp_visibility_plan");
    expect(visibilityRecords).toHaveLength(1);
  });
});

