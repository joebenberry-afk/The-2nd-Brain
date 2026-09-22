/**
 * Reserve-before-dispatch through the real route: real factory, real budget bridges, real governor
 * CLI, disposable brain home.
 *
 * `tests/wiring.test.ts` stubs the budget seams so its scope stays on the wiring; this file is the
 * opposite subject — nothing about the reservation is simulated. The load-bearing invariant is the
 * owner's: the preparation-failure branch runs before any billable/native dispatch, so
 * `cancel(proven_unused)` is an evidenced fact rather than an assumption. Both sides of that
 * statement are checked: the host call is blocked (so no tool ran) and the durable attempt row the
 * reconciler would read as "dispatch observed" does not exist.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import { cancelBudget, consumeBudget, reserveBudget } from "../src/budget-bridge";
import { TelemetryStore } from "../src/storage";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

const PYTHON = fileURLToPath(new URL("../../../.venv/Scripts/python.exe", import.meta.url));
const WORKER_TOKENS = 10;
/** Observed session spend: the cap covers it, so the dispatch may claim only the remainder. */
const SEEDED_USAGE = 2;
const REMAINING_ALLOWANCE = WORKER_TOKENS - SEEDED_USAGE;
const SESSION_STEM = "reservation-test";
const TASK_INPUT = { agent: "scout", task: "bounded task", completion_condition: "return evidence" };

const savedEnv: Record<string, string | undefined> = {};
const stores = new Set<TelemetryStore>();
const appendTelemetry = TelemetryStore.prototype.append;
let home: string;

beforeEach(async () => {
  home = await mkdtemp(join(tmpdir(), "sb-reservation-"));
  mkdirSync(join(home, "config"), { recursive: true });
  writeFileSync(
    join(home, "config", "governor.toml"),
    `[budgets]\nworker_tokens = ${WORKER_TOKENS}\n`,
    "utf8",
  );
  for (const key of ["SECOND_BRAIN_HOME", "SECOND_BRAIN_PYTHON"]) savedEnv[key] = process.env[key];
  process.env.SECOND_BRAIN_HOME = home;
  // The extension resolves its runtime python once at factory startup; the disposable home has no
  // .venv of its own, so the real bridges are pointed at the project venv the CLI lives in.
  process.env.SECOND_BRAIN_PYTHON = PYTHON;
  seedUsage(SESSION_STEM, SEEDED_USAGE);
  vi.spyOn(TelemetryStore.prototype, "append").mockImplementation(function (
    this: TelemetryStore,
    record,
  ) {
    stores.add(this);
    appendTelemetry.call(this, record);
  });
});

afterEach(async () => {
  // Await the telemetry the extension writes fire-and-forget before the home is removed: a write
  // racing `rm` can recreate the directory mid-delete on Windows.
  await Promise.all([...stores].map((store) => store.flush()));
  stores.clear();
  vi.restoreAllMocks();
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  await rm(home, { recursive: true, force: true }).catch(() => {});
});

function makeCtx(): ExtensionContext {
  const file = join(home, "sessions", `${SESSION_STEM}.jsonl`);
  const id = `native-${createHash("sha256").update(file, "utf8").digest("hex").slice(0, 24)}`;
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    sessionManager: {
      getSessionFile: () => file,
      getSessionId: () => id,
      getHeader: () => ({ type: "session", version: 1, id, timestamp }),
      getEntries: () => [
        { type: "session", version: 1, id, timestamp },
        {
          type: "custom",
          customType: "brain.active-state",
          details: { session_id: SESSION_STEM },
          timestamp,
        },
      ],
    },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  } as unknown as ExtensionContext;
}

/** The real factory with the real budget bridges; only the context runner is supplied. */
function loadFactory(options: ExtensionOptions = {}): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
  } as unknown as ExtensionAPI;
  const runner = options.ompWorkerContextRunner;
  factory(pi, {
    ...options,
    ompWorkerContextRunner:
      runner === undefined
        ? undefined
        : async (request) => {
            const result = await runner(request);
            if (!result.ok) return result;
            return {
              ...result,
              taskId: request.taskId,
              attemptId: `attempt-${request.taskId}`,
              projectId: request.projectId,
              worktreeId: null,
              accessIntent: request.accessIntent,
            };
          },
  });
  return handlers;
}

async function dispatchTask(handlers: Map<string, Handler>, toolCallId: string): Promise<unknown> {
  const handler = handlers.get("tool_call");
  if (handler === undefined) throw new Error("tool_call handler was not registered");
  return handler(
    { type: "tool_call", toolName: "task", toolCallId, input: TASK_INPUT },
    makeCtx(),
  );
}

/**
 * The host session has authoritative usage. Without it the Brain refuses with
 * ACCOUNTING_UNAVAILABLE (fail closed on unresolvable accounting), which would make every case
 * below a test of that refusal instead of the reservation.
 */
function seedUsage(session: string, totalTokens: number): void {
  const dir = join(home, "telemetry", "agent-performance");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, `${session}.jsonl`),
    `${JSON.stringify({
      v: 3,
      kind: "assistant_usage",
      session,
      timestamp: "2026-01-01T00:00:00.000Z",
      provider: "deepseek",
      model: "deepseek-v4-flash",
      response_id: "seed-response-1",
      total_tokens: totalTokens,
    })}\n`,
    "utf8",
  );
}

type ReservationRow = {
  session_id: string;
  task_id: string;
  tokens: number;
  consumed_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  resolution: string | null;
};

const SELECT_RESERVATIONS =
  "SELECT session_id, task_id, tokens, consumed_at, cancelled_at, cancel_reason, resolution " +
  "FROM budget_reservations ORDER BY rowid";

/** Read durable Brain state through the real database, not through the code under test. */
function query(sql: string): Record<string, unknown>[] {
  const script =
    "import json, sqlite3, sys;" +
    "conn = sqlite3.connect(sys.argv[1]); conn.row_factory = sqlite3.Row;" +
    "print(json.dumps([dict(row) for row in conn.execute(sys.argv[2])]))";
  const env = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  const stdout = execFileSync(PYTHON, ["-c", script, join(home, "db", "brain.sqlite"), sql], {
    env,
    windowsHide: true,
  });
  return JSON.parse(stdout.toString()) as Record<string, unknown>[];
}

function reservations(): ReservationRow[] {
  return query(SELECT_RESERVATIONS) as unknown as ReservationRow[];
}

async function extensionErrors(): Promise<Record<string, unknown>[]> {
  const dir = join(home, "telemetry", "agent-performance");
  const files = await readdir(dir).catch(() => [] as string[]);
  const records: Record<string, unknown>[] = [];
  for (const file of files) {
    const text = await readFile(join(dir, file), "utf8").catch(() => "");
    for (const line of text.split("\n")) {
      if (line.trim().length === 0) continue;
      records.push(JSON.parse(line) as Record<string, unknown>);
    }
  }
  return records.filter((record) => record.kind === "extension_error");
}

const contextResult = {
  ok: true,
  packetSha256: "d".repeat(64),
  contextHandoff: {
    mode: "full" as const,
    resolved_context: [],
    context_delta: { changed_refs: [], removed_ref_hashes: [], jit_delta: "" },
    context_fingerprint: "e".repeat(64),
    jit_context: "",
  },
  contextMetadata: {
    mode: "full" as const,
    reused: false,
    cache_hit: false,
    resolved_count: 0,
    context_fingerprint: "e".repeat(64),
    context_handoff_bytes: 10,
    context_handoff_tokens_estimate: 3,
    context_delta_bytes: 0,
    context_delta_tokens_estimate: 0,
  },
};

describe("reserve-before-dispatch through the real extension -> Brain route", () => {
  it("cancels a preparation-failure reservation as proven-unused and restores capacity once", async () => {
    const preparation = vi
      .fn()
      .mockResolvedValue({ ok: false, error: "P3.2 worker context preparation failed" });
    const handlers = loadFactory({ ompWorkerContextRunner: preparation });

    const blocked = await dispatchTask(handlers, "prep-failure");
    expect(blocked).toMatchObject({
      block: true,
      reason: "P3.2 worker context preparation failed",
    });
    expect(preparation).toHaveBeenCalledTimes(1);

    const rows = reservations();
    expect(rows, JSON.stringify(rows)).toHaveLength(1);
    const row = rows[0];
    expect(row.resolution).toBe("cancelled_unused");
    expect(row.cancel_reason).toBe("OMP_BATCH_PREPARATION_FAILED");
    expect(row.cancelled_at).not.toBeNull();
    expect(row.consumed_at).toBeNull();
    // The claim is the episode's remainder, not a second full cap: a dispatch must not book
    // capacity the session has already spent.
    expect(row.tokens).toBe(REMAINING_ALLOWANCE);

    // Pre-dispatch, proven twice over: the host call was blocked (so no tool ran) and the durable
    // attempt row the reconciler reads as "dispatch observed" was never created.
    const attempts = query(`SELECT task_id FROM worker_tasks WHERE task_id='${row.task_id}'`);
    expect(attempts).toEqual([]);

    // Capacity came back exactly once: the whole remainder fits again.
    const probe = await reserveBudget({
      home,
      sessionId: row.session_id,
      taskId: "probe-after-cancel",
      tokens: REMAINING_ALLOWANCE,
      python: PYTHON,
    });
    expect(probe.reserved, JSON.stringify(probe)).toBe(true);
    expect(probe.outstanding).toBe(REMAINING_ALLOWANCE);
  });

  it("refuses a late dispatch on the cancelled reservation without refunding twice", async () => {
    const preparation = vi.fn().mockResolvedValue({ ok: false, error: "preparation failed" });
    const handlers = loadFactory({ ompWorkerContextRunner: preparation });

    const first = await dispatchTask(handlers, "late-dispatch");
    expect(first).toMatchObject({ block: true, reason: "preparation failed" });
    preparation.mockClear();

    // The same attempt identity arriving again is a late dispatch on capacity that was already
    // returned: refused before preparation, and no second refund.
    const retry = await dispatchTask(handlers, "late-dispatch");
    expect(retry).toMatchObject({
      block: true,
      reason: "BRAIN_WORKER_BUDGET_RESERVATION_CANCELLED",
    });
    expect(preparation).not.toHaveBeenCalled();

    const rows = reservations();
    expect(rows, JSON.stringify(rows)).toHaveLength(1);
    expect(rows[0].resolution).toBe("cancelled_unused");
    expect(rows[0].cancelled_at).not.toBeNull();

    // One refund, not two: the remainder fits, a second claim of it does not.
    const session = rows[0].session_id;
    const fits = await reserveBudget({
      home, sessionId: session, taskId: "probe-1", tokens: REMAINING_ALLOWANCE, python: PYTHON,
    });
    expect(fits.reserved, JSON.stringify(fits)).toBe(true);
    const overbook = await reserveBudget({
      home, sessionId: session, taskId: "probe-2", tokens: REMAINING_ALLOWANCE, python: PYTHON,
    });
    expect(overbook.reserved).toBe(false);
    expect(overbook.reason).toBe("BUDGET_EXHAUSTED");
    // A refusal writes nothing: the outstanding liability is still exactly the one claim.
    expect(overbook.outstanding).toBe(REMAINING_ALLOWANCE);
  });

  it("keeps the reservation and consumes it normally once the dispatch starts", async () => {
    const preparation = vi.fn().mockResolvedValue(contextResult);
    const handlers = loadFactory({ ompWorkerContextRunner: preparation });

    const spawned = await dispatchTask(handlers, "prep-success");
    expect(spawned, JSON.stringify(spawned)).toMatchObject({ input: { task: expect.any(String) } });
    expect(preparation).toHaveBeenCalledTimes(1);

    // Preparation succeeded, so the cancellation route is never reached: the reservation stays an
    // open liability for the attempt that is now running.
    const rows = reservations();
    expect(rows, JSON.stringify(rows)).toHaveLength(1);
    expect(rows[0].cancelled_at).toBeNull();
    expect(rows[0].consumed_at).toBeNull();
    expect(rows[0].resolution).toBeNull();

    // Completion keeps the normal route: consumed exactly once.
    const consumed = await consumeBudget({
      home,
      sessionId: rows[0].session_id,
      taskId: rows[0].task_id,
      consumedBy: "attempt-finished",
      python: PYTHON,
    });
    expect(consumed).toMatchObject({ consumed: true, alreadyConsumed: false });
    const after = reservations();
    expect(after[0]).toMatchObject({ resolution: "consumed" });
    expect(after[0].cancelled_at).toBeNull();
  });

  it("records a failed cancellation instead of restoring capacity locally", async () => {
    const handlers = loadFactory({
      ompWorkerContextRunner: async () => ({ ok: false, error: "preparation failed" }),
      // The real bridge against an interpreter that cannot run: a transport failure, not a
      // Brain refusal.
      budgetCanceller: (options) => cancelBudget({ ...options, python: join(home, "no-python.exe") }),
    });

    const blocked = await dispatchTask(handlers, "cancel-bridge-failure");
    expect(blocked).toMatchObject({ block: true, reason: "preparation failed" });

    const rows = reservations();
    expect(rows, JSON.stringify(rows)).toHaveLength(1);
    expect(rows[0].cancelled_at).toBeNull();
    expect(rows[0].consumed_at).toBeNull();

    // The reservation is still a liability: nothing was returned locally, so the remainder
    // cannot be claimed again.
    const probe = await reserveBudget({
      home,
      sessionId: rows[0].session_id,
      taskId: "probe-after-failed-cancel",
      tokens: REMAINING_ALLOWANCE,
      python: PYTHON,
    });
    expect(probe.reserved).toBe(false);
    expect(probe.reason).toBe("BUDGET_EXHAUSTED");
    expect(probe.outstanding).toBe(REMAINING_ALLOWANCE);

    // And the failure is reported rather than swallowed.
    const errors = await extensionErrors();
    expect(errors.length, JSON.stringify(errors)).toBeGreaterThan(0);
  });
});
