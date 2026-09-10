import { execFile } from "node:child_process";
import { readFile, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import factory from "../src/index";
import type {
  AsyncJobLifecycleObservation,
  ExtensionAPI,
  ExtensionContext,
  ToolCallEventResult,
} from "../types/prime";

type ToolCallHandler = (
  event: { toolName: string; toolCallId: string; input: Record<string, unknown>; [key: string]: unknown },
  ctx: ExtensionContext,
) => Promise<ToolCallEventResult | undefined> | ToolCallEventResult | undefined;

interface ProbeJob {
  promise: Promise<void>;
  status: "running" | "completed" | "failed" | "cancelled";
  errorText?: string;
}

interface ProbeRunContext {
  signal: AbortSignal;
  deferCleanup(completion: Promise<void>): void;
}

interface ProbeManager {
  register(
    type: "task",
    label: string,
    run: (ctx: ProbeRunContext) => Promise<string>,
    options: {
      ownerId: string;
      agentId: string;
      sourceToolCallId: string;
      sourceIndex: number;
      cleanupTracked: true;
    },
  ): string;
  getJob(id: string): ProbeJob | undefined;
  cancel(id: string, filter: { ownerId: string }): boolean;
  observeJobLifecycle(
    observer: (observation: Readonly<AsyncJobLifecycleObservation>) => boolean | Promise<boolean>,
    options: { ownerId: string; sourceToolCallId: string },
  ): () => void;
  dispose(): Promise<boolean>;
}

interface ProbeManagerConstructor {
  new(options: { retentionMs: number }): ProbeManager;
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return resolve(value);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}

async function waitForFile(path: string, timeoutMs = 10_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await readFile(path, "utf8").catch(() => undefined);
    if (value !== undefined) return value;
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${path}`);
}

async function waitForEviction(manager: ProbeManager, jobId: string): Promise<void> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (manager.getJob(jobId) === undefined) return;
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${jobId} eviction`);
}

async function waitForMarkerOrFailure(
  manager: ProbeManager,
  jobId: string,
  marker: string,
  timeoutMs = 10_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await readFile(marker, "utf8").then(() => true, () => false)) return;
    const job = manager.getJob(jobId);
    if (job?.status === "failed") {
      throw new Error(`Writer job ${jobId} failed before its running marker: ${job.errorText ?? "unknown error"}`);
    }
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${marker}`);
}

function runWriter(
  python: string,
  cwd: string,
  marker: string,
  gate: string | null,
  target: string,
  value: string,
): Promise<void> {
  return new Promise((resolveWriter, rejectWriter) => {
    const script = [
      "import pathlib, sys, time",
      "marker = pathlib.Path(sys.argv[1])",
      "gate = pathlib.Path(sys.argv[2])",
      "target = pathlib.Path(sys.argv[3])",
      "value = sys.argv[4]",
      "marker.write_text('running', encoding='utf-8')",
      "if str(gate) == '-':",
      "    time.sleep(0.5)",
      "else:",
      "    while not gate.exists():",
      "        time.sleep(0.02)",
      "target.write_text(value, encoding='utf-8')",
    ].join("\n");
    const env: Record<string, string | undefined> = { ...process.env };
    delete env.PYTHONHOME;
    delete env.PYTHONPATH;
    execFile(
      python,
      ["-c", script, marker, gate ?? "-", target, value],
      { cwd, env, windowsHide: true },
      (error, _stdout, stderr) => {
        if (error) {
          rejectWriter(new Error(`Python writer failed: ${error.message}\n${stderr}`));
        } else {
          resolveWriter();
        }
      },
    );
  });
}

function waitForCancellation(signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolveCancellation) => {
    signal.addEventListener("abort", () => resolveCancellation(), { once: true });
  });
}

async function main(): Promise<void> {
  const ompRoot = required("OMP_SOURCE_ROOT");
  const brainHome = required("SECOND_BRAIN_HOME");
  const worktreeA = required("SECOND_BRAIN_PROBE_WORKTREE_A");
  const driverModel = process.env.SECOND_BRAIN_PROBE_DRIVER_MODEL?.trim();
  if (!driverModel) throw new Error("SECOND_BRAIN_PROBE_DRIVER_MODEL is required");
  const driverProvider = process.env.SECOND_BRAIN_PROBE_DRIVER_PROVIDER?.trim() || "openai-codex";
  const worktreeB = required("SECOND_BRAIN_PROBE_WORKTREE_B");
  const python = process.env.SECOND_BRAIN_PYTHON?.trim() || join(brainHome, ".venv", "Scripts", "python.exe");
  const runId = process.env.SECOND_BRAIN_PROBE_RUN_ID?.trim() || `${process.pid}-${Date.now()}`;
  const managerModuleUrl = pathToFileURL(join(
    ompRoot,
    "packages",
    "coding-agent",
    "src",
    "async",
    "job-manager.ts",
  )).href;
  // Cross-checkout probe: the OMP source root is intentionally selected at runtime.
  const managerModule: unknown = await import(managerModuleUrl);
  if (
    !managerModule ||
    typeof managerModule !== "object" ||
    !("AsyncJobManager" in managerModule) ||
    typeof managerModule.AsyncJobManager !== "function"
  ) {
    throw new Error("OMP AsyncJobManager export unavailable");
  }
  const Manager = managerModule.AsyncJobManager as ProbeManagerConstructor;
  const manager = new Manager({ retentionMs: 0 });
  const handlers = new Map<string, ToolCallHandler>();
  const journal: Array<{ customType: string; data: unknown }> = [];
  const pi = {
    on(name: string, handler: ToolCallHandler): void {
      handlers.set(name, handler);
    },
    appendEntry(customType: string, data?: unknown): void {
      journal.push({ customType, data });
    },
  } as unknown as ExtensionAPI;
  factory(pi);
  const toolCall = handlers.get("tool_call");
  if (!toolCall) throw new Error("Second Brain task admission handler unavailable");
  const toolResult = handlers.get("tool_result");
  if (!toolResult) throw new Error("Second Brain task result handler unavailable");
  const makeContext = (cwd: string, session: string): ExtensionContext => {
    const nativeId = `native-${session}`;
    const timestamp = "2026-01-01T00:00:00.000Z";
    return {
      cwd,
      model: { provider: driverProvider, id: driverModel },
      sessionManager: {
        getSessionFile: () => join(cwd, `${session}.jsonl`),
        getSessionId: () => nativeId,
        getHeader: () => ({ type: "session", version: 1, id: nativeId, timestamp }),
        getEntries: () => [],
      },
      getContextUsage: () => undefined,
      getSystemPrompt: () => "probe",
      signal: undefined,
      hasUI: false,
      ui: undefined,
      observeAsyncJobLifecycle: (observer, options) => manager.observeJobLifecycle(observer, {
        ownerId: "Main",
        sourceToolCallId: options?.sourceToolCallId ?? "",
      }),
    };
  };
  const ctxA = makeContext(worktreeA, `probe-a-${runId}`);
  const ctxB = makeContext(worktreeB, `probe-b-${runId}`);
  const admit = (ctx: ExtensionContext, toolCallId: string) => toolCall({
    toolName: "task",
    toolCallId,
    input: {
      task: `write from ${toolCallId}`,
      access_intent: "mutating",
      context_refs: [],
    },
  }, ctx);
  const assertAdmitted = (result: ToolCallEventResult | undefined, label: string): void => {
    if (!result || "block" in result) {
      throw new Error(`${label} admission failed: ${JSON.stringify(result)}`);
    }
  };
  const assertBlocked = (result: ToolCallEventResult | undefined, label: string): void => {
    if (!result || !("block" in result) || result.block !== true) {
      throw new Error(`${label} was not excluded: ${JSON.stringify(result)}`);
    }
  };
  const waitForReleasedAdmission = async (
    ctx: ExtensionContext,
    prefix: string,
  ): Promise<string> => {
    const deadline = Date.now() + 15_000;
    for (let index = 0; Date.now() < deadline; index += 1) {
      const toolCallId = `${prefix}-${index}`;
      const result = await admit(ctx, toolCallId);
      if (result && !("block" in result)) return toolCallId;
      await delay(100);
    }
    throw new Error(`Brain never durably acknowledged cleanup for ${prefix}`);
  };
  const failUndispatched = async (ctx: ExtensionContext, toolCallId: string): Promise<void> => {
    const acceptedBefore = journal.filter(
      (entry) => entry.customType === "second-brain.worker-dispatch-failed-accepted",
    ).length;
    await toolResult({
      toolName: "task",
      toolCallId,
      input: {},
      content: [],
      isError: true,
    }, ctx);
    const acceptedAfter = journal.filter(
      (entry) => entry.customType === "second-brain.worker-dispatch-failed-accepted",
    ).length;
    if (acceptedAfter !== acceptedBefore + 1) {
      throw new Error(`Brain did not return an exact dispatch-failed receipt for ${toolCallId}`);
    }
  };

  const targetA = join(worktreeA, ".second-brain-probe-shared.txt");
  const targetB = join(worktreeB, ".second-brain-probe-b.txt");
  const markerA = join(worktreeA, ".second-brain-probe-a.running");
  const markerB = join(worktreeB, ".second-brain-probe-b.running");
  const gateA = join(worktreeA, ".second-brain-probe-a.release");
  const cleanupPaths = [targetA, targetB, markerA, markerB, gateA];
  await Promise.all(cleanupPaths.map((path) => rm(path, { force: true })));

  try {
    const first = await admit(ctxA, "probe-a-first");
    assertAdmitted(first, "initial same-worktree");
    const jobA = manager.register("task", "probe-a", async ({ signal, deferCleanup }) => {
      const writer = runWriter(python, worktreeA, markerA, gateA, targetA, "first");
      deferCleanup(writer);
      await Promise.race([
        waitForFile(markerA),
        writer.then(() => {
          throw new Error("Writer exited before cancellation");
        }),
      ]);
      await waitForCancellation(signal);
      return "cancelled while writer cleanup remains";
    }, {
      ownerId: "Main",
      agentId: "ProbeA",
      sourceToolCallId: "probe-a-first",
      sourceIndex: 0,
      cleanupTracked: true,
    });
    await waitForMarkerOrFailure(manager, jobA, markerA);
    assertBlocked(await admit(ctxA, "probe-a-running-conflict"), "running same-worktree writer");

    const different = await admit(ctxB, "probe-b-first");
    assertAdmitted(different, "different-worktree");
    const jobB = manager.register("task", "probe-b", async ({ deferCleanup }) => {
      const writer = runWriter(python, worktreeB, markerB, null, targetB, "different");
      deferCleanup(writer);
      await writer;
      return "different worktree completed";
    }, {
      ownerId: "Main",
      agentId: "ProbeB",
      sourceToolCallId: "probe-b-first",
      sourceIndex: 0,
      cleanupTracked: true,
    });
    await waitForMarkerOrFailure(manager, jobB, markerB);

    if (!manager.cancel(jobA, { ownerId: "Main" })) throw new Error("Native cancellation was not accepted");
    await manager.getJob(jobA)?.promise;
    assertBlocked(await admit(ctxA, "probe-a-cancelled-conflict"), "cancelled unsettled writer");
    await waitForEviction(manager, jobA);
    assertBlocked(await admit(ctxA, "probe-a-evicted-conflict"), "evicted unsettled writer");

    await writeFile(gateA, "release", "utf8");
    const releasedToolCallId = await waitForReleasedAdmission(ctxA, "probe-a-after-cleanup");

    const secondJob = manager.register("task", "probe-a-second", async ({ deferCleanup }) => {
      const writer = runWriter(python, worktreeA, markerA, null, targetA, "second");
      deferCleanup(writer);
      await writer;
      return "second same-file writer completed";
    }, {
      ownerId: "Main",
      agentId: "ProbeASecond",
      sourceToolCallId: releasedToolCallId,
      sourceIndex: 0,
      cleanupTracked: true,
    });
    await Promise.all([manager.getJob(secondJob)?.promise, manager.getJob(jobB)?.promise]);
    if (await readFile(targetA, "utf8") !== "second") {
      throw new Error("Second same-file writer did not run after durable release");
    }
    if (await readFile(targetB, "utf8") !== "different") {
      throw new Error("Different-worktree writer did not complete");
    }
    const finalA = await waitForReleasedAdmission(ctxA, "probe-a-final-release");
    await failUndispatched(ctxA, finalA);
    const finalB = await waitForReleasedAdmission(ctxB, "probe-b-final-release");
    await failUndispatched(ctxB, finalB);
    process.stdout.write(JSON.stringify({
      native_cancelled: true,
      unsettled_blocked_after_cancel: true,
      obligation_survived_eviction: true,
      cleanup_durably_released: true,
      same_file_second_writer_completed: true,
      different_worktree_concurrent: true,
      providers_used: 0,
    }) + "\n");
  } finally {
    await manager.dispose();
    await Promise.all(cleanupPaths.map((path) => rm(path, { force: true })));
  }
}

await main();
