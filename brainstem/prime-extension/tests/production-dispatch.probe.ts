import { execFile as execFileCallback, spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";
import { createServer, createConnection, type Socket } from "node:net";
import brainFactory from "../src/index";

const execFile = promisify(execFileCallback);
const THIS_FILE = fileURLToPath(import.meta.url);
const BRAIN_ROOT = resolve(dirname(THIS_FILE), "../../..");
const OMP_ROOT = process.env.OMP_SOURCE_ROOT?.trim();
const PYTHON = process.env.SECOND_BRAIN_PYTHON?.trim() || join(BRAIN_ROOT, ".venv", "Scripts", "python.exe");
const TIMEOUT_MS = 30_000;

interface DriverSpec {
  id: string;
  mode: "background" | "blocking";
  accessIntent: "mutating" | "read_only";
  marker?: string;
  gate?: string;
  target?: string;
  value?: string;
  allowedRead?: string;
  projectId?: string;
  participationEvidence?: string;
  forbiddenSentinel?: string;
  cleanupFault?: {
    order: "failure-first" | "failure-last" | "setup-throw" | "success";
    port: number;
  };
  resultPath: string;
}

interface DriverResult {
  id: string;
  taskBlocked: boolean;
  taskError: boolean;
  taskText: string;
  targetWritten: boolean;
  forbiddenSentinelWritten: boolean;
  allowedReadObserved: boolean;
  forbiddenHubRejected: boolean;
  providerRequests: number;
  cleanupEvidence?: Record<string, unknown>;
}
interface WorkerEvidence {
  capturedBeforeWriterAt?: string;
  rows: Array<{
    task_id: string;
    attempt_id: string;
    project_id: string;
    worktree_id: string | null;
    access_intent: string;
    writer_ownership: string | null;
    native_attempt_id: string | null;
    native_job_id: string | null;
    host_generation: number | null;
    lifecycle_sequence: number;
    bound_at: string | null;
    accepted_at: string | null;
    updated_at: string;
  }>;
  receipts: Array<{
    attempt_id: string;
    sequence: number;
    payload_json: string;
    recorded_at: string;
  }>;
}


interface RunningDriver {
  spec: DriverSpec;
  child: ChildProcess;
  output: Promise<{ code: number | null; stdout: string; stderr: string }>;
}
const activeDrivers = new Set<RunningDriver>();

interface CaseResult {
  case: string;
  passed: boolean;
  facts: Record<string, unknown>;
}

interface ProviderApi {
  registerProvider(name: string, config: Record<string, unknown>): void;
  on(
    event: "session_start",
    handler: (_event: unknown, context: {
      sessionManager: { getSessionId(): string; close(): Promise<void> };
    }) => void,
  ): void;
}

interface MockContext {
  messages?: Array<{ role?: string; toolName?: string; isError?: boolean; content?: unknown }>;
}

interface MockModel {
  calls: unknown[];
  stream(model: unknown, context: unknown, options?: unknown): unknown;
}

interface HostSession {
  prompt(text: string): Promise<void>;
  subscribe(listener: (event: Record<string, unknown>) => void): () => void;
  settleAsyncWork(): Promise<void>;
  dispose(): Promise<void>;
}

// Line-framed local IPC: every state transition is acknowledged; timeouts are
// failure bounds, never ordering guesses. No lifecycle/admission rows are authored.
class BarrierPeer {
  readonly socket: Socket;
  readonly queued = new Map<string, unknown[]>();
  readonly waiting = new Map<string, Array<(value: unknown) => void>>();
  constructor(socket: Socket) {
    this.socket = socket;
    let buffer = "";
    socket.on("data", chunk => {
      buffer += String(chunk);
      for (;;) {
        const newline = buffer.indexOf("\n");
        if (newline < 0) break;
        const message = JSON.parse(buffer.slice(0, newline)) as { event: string; value: unknown };
        trace("ipc", message.event);
        buffer = buffer.slice(newline + 1);
        const waiter = this.waiting.get(message.event)?.shift();
        if (waiter) waiter(message.value);
        else this.queued.set(message.event, [...(this.queued.get(message.event) ?? []), message.value]);
      }
    });
  }
  send(event: string, value: unknown = null): void {
    this.socket.write(`${JSON.stringify({ event, value })}\n`);
  }
  async wait(event: string): Promise<unknown> {
    const queue = this.queued.get(event);
    if (queue?.length) return queue.shift();
    // The extension targets ES2022, so use its existing Promise executor pattern.
    return withDeadline(new Promise(resolve => {
      this.waiting.set(event, [...(this.waiting.get(event) ?? []), resolve]);
    }), `IPC ${event}`);
  }
}

async function connectBarrier(port: number, role: string): Promise<BarrierPeer> {
  const socket = createConnection({ port, host: "127.0.0.1" });
  await new Promise<void>((resolve, reject) => {
    socket.once("connect", resolve);
    socket.once("error", reject);
  });
  const peer = new BarrierPeer(socket);
  peer.send("hello", role);
  return peer;
}

function cleanupErrorEvidence(error: unknown): unknown {
  if (!(error instanceof Error)) return String(error);
  return {
    name: error.name, message: error.message,
    ...(error instanceof AggregateError ? { errors: Array.from(error.errors, cleanupErrorEvidence) } : {}),
    ...(error.cause === undefined ? {} : { cause: cleanupErrorEvidence(error.cause) }),
  };
}

function requiredOmpRoot(): string {
  if (!OMP_ROOT) throw new Error("OMP_SOURCE_ROOT is required");
  return OMP_ROOT;
}

function cleanPythonEnv(extra: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  const env = { ...process.env, ...extra };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  return env;
}
function trace(scope: string, event: string, facts: Record<string, unknown> = {}): void {
  process.stdout.write(`${JSON.stringify({ trace: true, at: new Date().toISOString(), scope, event, ...facts })}\n`);
}

async function withDeadline<T>(operation: Promise<T>, label: string, timeoutMs = TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const expired = delay(timeoutMs, undefined, { signal: controller.signal }).then(() => {
    throw new Error(`Timed out during ${label}`);
  });
  try {
    return await Promise.race([operation, expired]);
  } finally {
    controller.abort();
  }
}


async function run(executable: string, args: string[], options: { cwd?: string; env?: NodeJS.ProcessEnv } = {}): Promise<string> {
  const { stdout } = await execFile(executable, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 4 * 1024 * 1024,
    timeout: TIMEOUT_MS,
  });
  return stdout;
}

async function git(cwd: string, ...args: string[]): Promise<void> {
  await run("git", args, { cwd });
}

async function waitFor(predicate: () => boolean, label: string, timeoutMs = TIMEOUT_MS): Promise<void> {
  trace("wait", "begin", { label, timeoutMs });
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(`Timed out waiting for ${label}`);
    await delay(20);
  }
  trace("wait", "satisfied", { label });
}

async function waitForPath(path: string, label = path, timeoutMs = TIMEOUT_MS): Promise<void> {
  await waitFor(() => existsSync(path), label, timeoutMs);
}
async function waitForDriverDecision(driver: RunningDriver, paths: string[], label: string): Promise<void> {
  await Promise.race([
    waitFor(() => paths.some((path) => existsSync(path)), label),
    driver.output.then((output) => {
      if (!paths.some((path) => existsSync(path))) {
        throw new Error(`${driver.spec.id} exited ${output.code} before ${label}: ${output.stderr || output.stdout}`);
      }
    }),
  ]);
}

async function queryWorkerEvidence(brainHome: string, projectId: string): Promise<WorkerEvidence> {
  const query = [
    "import json, sqlite3, sys",
    "from pathlib import Path",
    "from second_brain import db",
    "home, project_id = Path(sys.argv[1]), sys.argv[2]",
    "conn = sqlite3.connect(db.db_path(home))",
    "conn.row_factory = sqlite3.Row",
    "rows = [dict(row) for row in conn.execute(\"SELECT task_id,attempt_id,project_id,worktree_id,access_intent,writer_ownership,native_attempt_id,native_job_id,host_generation,lifecycle_sequence,bound_at,accepted_at,updated_at FROM worker_tasks WHERE project_id=? ORDER BY updated_at DESC LIMIT 8\", (project_id,))]",
    "attempts = [row['attempt_id'] for row in rows]",
    "receipts = [dict(row) for row in conn.execute(\"SELECT attempt_id,sequence,payload_json,recorded_at FROM worker_lifecycle_receipts ORDER BY recorded_at\")]",
    "print(json.dumps({'rows': rows, 'receipts': [row for row in receipts if row['attempt_id'] in attempts]}))",
  ].join(";");
  const stdout = await run(PYTHON, ["-c", query, brainHome, projectId], {
    env: cleanPythonEnv({ SECOND_BRAIN_HOME: brainHome }),
  });
  return JSON.parse(stdout) as WorkerEvidence;
}

async function readWriterEvidence(spec: DriverSpec): Promise<WorkerEvidence | null> {
  if (!spec.participationEvidence || !existsSync(spec.participationEvidence)) return null;
  return JSON.parse(await readFile(spec.participationEvidence, "utf8")) as WorkerEvidence;
}

function participationSummary(evidence: WorkerEvidence | null): {
  admissionBeforeWriter: boolean;
  bindingBeforeWriter: boolean;
  latestAttemptId: string | null;
  lifecycleSequence: number | null;
  projectId: string | null;
  worktreeId: string | null;
} {
  const row = evidence?.rows[0];
  return {
    admissionBeforeWriter: row !== undefined,
    bindingBeforeWriter:
      row?.native_attempt_id != null &&
      row.bound_at != null &&
      evidence!.receipts.some((receipt) => receipt.attempt_id === row.attempt_id),
    latestAttemptId: row?.attempt_id ?? null,
    lifecycleSequence: row?.lifecycle_sequence ?? null,
    projectId: row?.project_id ?? null,
    worktreeId: row?.worktree_id ?? null,
  };
}


async function createFixture(root: string, labels: string[]): Promise<{ brainHome: string; repo: string }> {
  const brainHome = join(root, "brain-home");
  const repo = join(root, "worktree");
  await mkdir(repo, { recursive: true });
  await git(repo, "init", "-q");
  await writeFile(join(repo, "tracked.txt"), "fixture read content\n", "utf8");
  await git(repo, "add", "tracked.txt");
  await git(repo, "-c", "user.name=Physical Safety Harness", "-c", "user.email=harness@example.invalid", "commit", "-qm", "fixture");
  await mkdir(join(repo, ".omp", "agents"), { recursive: true });
  await writeFile(
    join(repo, ".omp", "agents", "blocking-writer.md"),
    [
      "---",
      "name: blocking-writer",
      "description: Blocking production harness writer",
      "blocking: true",
      "tools: [bash]",
      "---",
      "Execute only the requested harness operation, then yield.",
      "",
    ].join("\n"),
    "utf8",
  );
  const setup = [
    "import shutil, sys",
    "from pathlib import Path",
    "from second_brain import db, paths, registry",
    "home, source, repo = map(Path, sys.argv[1:4])",
    "labels = sys.argv[4:]",
    "home.mkdir(parents=True, exist_ok=True)",
    "paths.ensure_layout(home)",
    "(home / 'VERSION').write_text('0.1.0\\n', encoding='utf-8')",
    "[(home / 'config' / name).write_text('schema_version = 1\\n', encoding='utf-8') for name in paths.REQUIRED_CONFIG_FILES]",
    "shutil.copytree(source / 'templates', home / 'templates', dirs_exist_ok=True)",
    "db.migrate(db.db_path(home))",
    "[registry.add_project(home, repo, project_id=label) for label in labels]",
  ].join(";");
  await run(PYTHON, ["-c", setup, brainHome, BRAIN_ROOT, repo, ...labels], {
    env: cleanPythonEnv({ SECOND_BRAIN_HOME: brainHome }),
  });
  return { brainHome, repo };
}

function encodeSpec(spec: DriverSpec): string {
  return Buffer.from(JSON.stringify(spec), "utf8").toString("base64url");
}

function decodeSpec(): DriverSpec {
  const encoded = process.env.SECOND_BRAIN_HARNESS_SPEC;
  if (!encoded) throw new Error("SECOND_BRAIN_HARNESS_SPEC is required in worker mode");
  return JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as DriverSpec;
}

function flattenContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.map((part) => {
    if (typeof part === "string") return part;
    if (part && typeof part === "object" && "text" in part && typeof part.text === "string") return part.text;
    return "";
  }).join("\n");
}

function shellQuote(value: string): string {
  return `"${value.replaceAll('"', '\\"')}"`;
}


async function runDriver(): Promise<void> {
  const ompRoot = requiredOmpRoot();
  const spec = decodeSpec();
  // OMP is a separately checked-out runtime selected by the harness caller, so its module paths are runtime data.
  const sdk = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "sdk.ts")).href) as Record<string, unknown>;
  const settingsModule = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "config", "settings.ts")).href) as Record<string, unknown>;
  const registryModule = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "config", "model-registry.ts")).href) as Record<string, unknown>;
  const authModule = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "session", "auth-storage.ts")).href) as Record<string, unknown>;
  const sessionManagerModule = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "session", "session-manager.ts")).href) as Record<string, unknown>;
  const mockModule = await import(pathToFileURL(join(ompRoot, "packages", "ai", "src", "providers", "mock.ts")).href) as Record<string, unknown>;
  const runtimeModule = await import(pathToFileURL(join(ompRoot, "packages", "coding-agent", "src", "modes", "runtime-init.ts")).href) as Record<string, unknown>;
  const initializeExtensions = runtimeModule.initializeExtensions as (
    session: HostSession,
    options: { reportSendError(action: string, error: Error): void; reportRuntimeError(error: unknown): void },
  ) => Promise<void>;
  const createAgentSession = sdk.createAgentSession as (options: Record<string, unknown>) => Promise<{ session: HostSession }>;
  const Settings = settingsModule.Settings as { isolated(values: Record<string, unknown>): { setModelRole(role: string, model: string): void } };
  const ModelRegistry = registryModule.ModelRegistry as new(auth: unknown, path: string) => unknown;
  const AuthStorage = authModule.AuthStorage as { create(path: string): Promise<{ close(): void }> };
  const SessionManager = sessionManagerModule.SessionManager as { create(cwd: string, dir: string): unknown };
  const createMockModel = mockModule.createMockModel as (options: Record<string, unknown>) => MockModel;
  const cwd = process.cwd();
  const agentDir = join(dirname(spec.resultPath), `agent-${spec.id}`);
  const sessionsDir = join(agentDir, "sessions");
  await mkdir(sessionsDir, { recursive: true });
  const auth = await AuthStorage.create(join(agentDir, "auth.db"));
  let allowedReadObserved = false;
  let forbiddenHubRejected = false;
  let request = 0;
  const payload = encodeSpec(spec);
  const mock = createMockModel({
    id: "physical-safety-model",
    provider: "physical-safety",
    handler: async (rawContext: unknown) => {
      const context = rawContext as MockContext;
      const messages = context.messages ?? [];
      const transcript = messages.map((message) => flattenContent(message.content)).join("\n");
      const isChild = transcript.includes("SECOND_BRAIN_WORKER_TASK") || transcript.includes("HARNESS_CHILD=");
      const toolResults = messages.filter((message) => message.role === "toolResult");
      const lastToolResult = toolResults.at(-1);
      const call = (name: string, args: Record<string, unknown>) => ({
        content: [{ type: "toolCall", id: `${spec.id}-${request}-${name}`, name, arguments: args }],
        stopReason: "toolUse",
      });
      if (!isChild) {
        const taskResult = toolResults.find((message) => message.toolName === "task");
        if (!taskResult) {
          return call("task", {
            name: spec.id,
            agent: spec.mode === "blocking" ? "blocking-writer" : "task",
            task: `HARNESS_CHILD=${payload}`,
            access_intent: spec.accessIntent,
            // Exercise the authorized shared physical worktree, not an isolated copy.
          });
        }
        if (spec.cleanupFault && transcript.includes("HARNESS_CANCEL") && lastToolResult?.toolName !== "hub") {
          const jobId = /job `([^`]+)`/.exec(flattenContent(taskResult.content))?.[1];
          if (!jobId) throw new Error("Cleanup fault case did not receive a native background job id");
          return call("hub", { op: "cancel", ids: [jobId] });
        }
        return { content: ["parent complete"], stopReason: "stop" };
      }
      if (spec.accessIntent === "read_only") {
        if (toolResults.length === 0) {
          return call("hub", {
            op: "start",
            name: `forbidden-${spec.id}`,
            application: process.execPath,
            args: [THIS_FILE, "--write-once", spec.forbiddenSentinel ?? ""],
          });
        }
        if (toolResults.length === 1) {
          forbiddenHubRejected = lastToolResult?.isError === true || /not found|unknown tool|unavailable/i.test(flattenContent(lastToolResult?.content));
          return call("read", { path: spec.allowedRead });
        }
        if (toolResults.length === 2) {
          allowedReadObserved = flattenContent(lastToolResult?.content).includes("fixture read content");
          return call("yield", { data: { allowed_read: allowedReadObserved, forbidden_hub_rejected: forbiddenHubRejected } });
        }
        return { content: ["read-only complete"], stopReason: "stop" };
      }
      if (spec.cleanupFault && toolResults.length > 0) {
        return call("yield", { data: { writer: spec.id } });
      }
      if (toolResults.length === 0) {
        const command = [
          shellQuote(process.execPath),
          shellQuote(THIS_FILE),
          "--writer",
          shellQuote(spec.marker ?? ""),
          shellQuote(spec.gate ?? "-"),
          shellQuote(spec.target ?? ""),
          shellQuote(spec.value ?? spec.id),
          shellQuote(spec.participationEvidence ?? ""),
          ...(spec.cleanupFault ? [String(spec.cleanupFault.port)] : []),
        ].join(" ");
        return call("bash", { command });
      }
      return call("yield", { data: { writer: spec.id, target: spec.target } });
    },
  });
  const providerFactory = (pi: ProviderApi): void => {
    pi.registerProvider("physical-safety", {
      baseUrl: "mock://physical-safety",
      apiKey: "local-harness",
      api: "physical-safety-mock",
      streamSimple: (model: unknown, context: unknown, options?: unknown) => mock.stream(model, context, options),
      models: [{
        id: "physical-safety-model",
        name: "Physical Safety Deterministic Model",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32_768,
        maxTokens: 4096,
      }],
    });
  };
  const settings = Settings.isolated({
    "async.enabled": true,
    ...(spec.cleanupFault ? { "bash.autoBackground.enabled": false } : {}),
    "compaction.enabled": false,
    "retry.enabled": false,
    "todo.enabled": false,
    "task.enableLsp": false,
    "task.agentIdleTtlMs": 0,
    "task.isolation.enabled": false,
    "tools.xdev": false,
  });
  settings.setModelRole("default", "physical-safety/physical-safety-model");
  const modelRegistry = new ModelRegistry(auth, join(agentDir, "models.yml"));
  let taskBlocked = false;
  let taskError = false;
  let taskText = "";
  let session: HostSession | undefined;
  try {
    ({ session } = await withDeadline(createAgentSession({
      cwd,
      agentDir,
      sessionManager: SessionManager.create(cwd, sessionsDir),
      authStorage: auth,
      modelRegistry,
      settings,
      modelPattern: "physical-safety/physical-safety-model",
      disableExtensionDiscovery: true,
      extensions: [providerFactory, brainFactory],
      rules: [],
      contextFiles: [],
      promptTemplates: [],
      slashCommands: [],
      enableMCP: false,
      enableLsp: false,
      enableIrc: spec.cleanupFault !== undefined,
      skipPythonPreflight: true,
      toolNames: ["task", "hub"],
      spawns: "task,blocking-writer",
      hasUI: false,
      autoApprove: true,
    }), `${spec.id} AgentSession setup`));
    await withDeadline(initializeExtensions(session, {
      reportSendError: (action, error) => { throw new Error(`${action}: ${error.message}`); },
      reportRuntimeError: (error) => { trace(spec.id, "extension-runtime-error", { error }); },
    }), `${spec.id} extension runtime initialization`);
    const unsubscribe = session.subscribe((event) => {
      if (event.type !== "tool_execution_end" || event.toolName !== "task") return;
      taskError = event.isError === true;
      const result = event.result as { content?: unknown } | undefined;
      taskText = flattenContent(result?.content);
      taskBlocked = taskError && taskText.includes("WORKTREE_WRITER_BUSY");
    });
    let cleanupEvidence: Record<string, unknown> | undefined;
    let barrier: BarrierPeer | undefined;
    const parentSession = session;
    const prototype = Object.getPrototypeOf(session) as {
      abort(...args: unknown[]): Promise<void>;
      dispose(...args: unknown[]): Promise<void>;
    };
    const nativeAbort = prototype.abort;
    const nativeDispose = prototype.dispose;
    if (spec.cleanupFault) {
      barrier = await connectBarrier(spec.cleanupFault.port, "driver");
      const channel = barrier;
      // CONTROLLED FAULT INJECTION: actual child abort/dispose boundaries only.
      // The native Task registration, executor, policy, binding and receipt
      // observer remain untouched. B calls the genuine disposal after its gate.
      prototype.abort = function (this: HostSession, ...args: unknown[]): Promise<void> {
        if (this === parentSession) return nativeAbort.apply(this, args);
        channel.send("A-started");
        if (spec.cleanupFault!.order === "setup-throw") throw new Error("F3 injected synchronous abort setup");
        return channel.wait("finish-a").then(() => {
          if (spec.cleanupFault!.order !== "success") throw new Error("F3 injected abort cleanup A");
          return nativeAbort.apply(this, args);
        });
      };
      prototype.dispose = function (this: HostSession, ...args: unknown[]): Promise<void> {
        if (this === parentSession) return nativeDispose.apply(this, args);
        channel.send("B-started");
        return channel.wait("finish-b").then(() => nativeDispose.apply(this, args)).then(
          () => { channel.send("B-settled"); },
          error => { channel.send("B-settled", cleanupErrorEvidence(error)); throw error; },
        );
      };
    }
    try {
      await withDeadline(session.prompt(`HARNESS_PARENT=${payload}`), `${spec.id} parent prompt`);
      if (spec.cleanupFault && barrier) {
        const managerModule = await import(pathToFileURL(join(ompRoot, "packages/coding-agent/src/async/job-manager.ts")).href);
        const manager = managerModule.AsyncJobManager.instance();
        await barrier.wait("cancel");
        await withDeadline(session.prompt("HARNESS_CANCEL"), `${spec.id} hub cancellation`);
        const cancelled = manager.getAllJobs().find((job: { id: string }) => job.id === spec.id);
        if (cancelled?.status !== "cancelled") throw new Error(`Native hub did not cancel writer: ${cancelled?.status}`);
        barrier.send("logically-cancelled", { id: cancelled.id, status: cancelled.status });
        await barrier.wait("evict");
        const drained = await manager.dispose({ timeoutMs: 0 });
        barrier.send("display-evicted", { drained, rows: manager.getAllJobs().length });
        let outcome: unknown;
        const cleanup = manager.waitForAll().then(
          () => { outcome = { status: "fulfilled" }; },
          (error: unknown) => { outcome = { status: "rejected", error: cleanupErrorEvidence(error) }; },
        );
        await barrier.wait("inspect-pending");
        barrier.send("pending", { pending: outcome === undefined });
        await cleanup;
        cleanupEvidence = { outcome };
        barrier.send("cleanup-outcome", outcome);
        await barrier.wait("finish-driver");
      } else if (!taskError && spec.accessIntent === "mutating" && spec.target) {
        await waitForPath(spec.target, `${spec.id} writer target`);
        await withDeadline(session.settleAsyncWork(), `${spec.id} writer settlement`);
      } else if (spec.accessIntent === "read_only") {
        await withDeadline(session.settleAsyncWork(), `${spec.id} read-only settlement`);
      }
    } finally {
      unsubscribe();
      prototype.abort = nativeAbort;
      prototype.dispose = nativeDispose;
      if (barrier) barrier.socket.end();
    }
    if (cleanupEvidence) trace(spec.id, "cleanup-evidence", cleanupEvidence);
  } finally {
    try {
      if (session) await withDeadline(session.dispose(), `${spec.id} parent disposal`);
    } catch (error) {
      if (!spec.cleanupFault) throw error;
      trace(spec.id, "parent-disposal-error", { error: cleanupErrorEvidence(error) });
    }
    auth.close();
  }
  const result: DriverResult = {
    id: spec.id,
    taskBlocked,
    taskError,
    taskText,
    targetWritten: spec.target ? existsSync(spec.target) : false,
    forbiddenSentinelWritten: spec.forbiddenSentinel ? existsSync(spec.forbiddenSentinel) : false,
    allowedReadObserved,
    forbiddenHubRejected,
    providerRequests: mock.calls.length,
  };
  await writeFile(spec.resultPath, JSON.stringify(result), "utf8");
}

async function runWriter(args: string[]): Promise<void> {
  const [marker, gate, target, value, participationEvidence, controlPort] = args;
  if (!marker || !target || value === undefined) throw new Error("writer arguments missing");
  if (participationEvidence) {
    const brainHome = process.env.SECOND_BRAIN_HOME;
    const projectId = process.env.SECOND_BRAIN_PROJECT;
    if (!brainHome || !projectId) throw new Error("writer participation environment missing");
    const evidence = await queryWorkerEvidence(brainHome, projectId);
    evidence.capturedBeforeWriterAt = new Date().toISOString();
    await writeFile(participationEvidence, JSON.stringify(evidence), "utf8");
  }
  await writeFile(marker, JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() }), "utf8");
  if (controlPort) {
    const peer = await connectBarrier(Number(controlPort), "writer");
    peer.send("writer-ready", { pid: process.pid });
    await peer.wait("write-after-cancel");
    await writeFile(target, value, "utf8");
    peer.send("write-confirmed", { target, value });
    await peer.wait("exit");
    peer.socket.end();
    return;
  }
  if (gate && gate !== "-") await waitForPath(gate, `writer gate ${gate}`);
  await writeFile(target, value, "utf8");
}

async function writeOnce(path: string | undefined): Promise<void> {
  if (!path) throw new Error("write-once path missing");
  await writeFile(path, "forbidden mutation", "utf8");
}

function startDriver(brainHome: string, repo: string, project: string, spec: DriverSpec): RunningDriver {
  // The production resolver prioritizes a project manifest over environment
  // fallback. Select the fixture's authorized label before this session starts.
  mkdirSync(join(repo, ".brain"), { recursive: true });
  writeFileSync(join(repo, ".brain", "project.toml"), `id = ${JSON.stringify(project)}\n`);
  spec.projectId = project;
  // The mutation must land inside the admitted physical worktree, not merely
  // alongside the fixture's logs and IPC markers.
  if (spec.target) spec.target = join(repo, basename(spec.target));
  const child = spawn(process.execPath, [THIS_FILE, "--worker"], {
    cwd: repo,
    env: cleanPythonEnv({
      OMP_SOURCE_ROOT: requiredOmpRoot(),
      SECOND_BRAIN_HOME: brainHome,
      SECOND_BRAIN_PYTHON: PYTHON,
      SECOND_BRAIN_PROJECT: project,
      SECOND_BRAIN_HARNESS_SPEC: encodeSpec(spec),
      SECOND_BRAIN_OBSERVABILITY: "on",
      DRIVER_MODELS: "physical-safety-model",
      SECOND_BRAIN_RTD: "off",
      SECOND_BRAIN_RECALL: "off",
      SECOND_BRAIN_AUTOINJECT_MODE: "advisory",
    }),
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  trace(spec.id, "driver-started", { pid: child.pid, project });
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (chunk) => {
    stdout += String(chunk);
    process.stdout.write(String(chunk));
  });
  child.stderr?.on("data", (chunk) => {
    stderr += String(chunk);
    process.stderr.write(String(chunk));
  });
  let driver: RunningDriver;
  const output = new Promise<{ code: number | null; stdout: string; stderr: string }>((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => {
      activeDrivers.delete(driver);
      resolve({ code, stdout, stderr });
    });
  });
  driver = { spec, child, output };
  activeDrivers.add(driver);
  return driver;
}

async function finishDriver(driver: RunningDriver): Promise<DriverResult> {
  await Promise.race([
    waitForPath(driver.spec.resultPath, `${driver.spec.id} result`),
    driver.output.then((output) => {
      if (!existsSync(driver.spec.resultPath)) {
        throw new Error(`${driver.spec.id} exited ${output.code} before writing a result: ${output.stderr || output.stdout}`);
      }
    }),
  ]);
  const output = await driver.output;
  if (output.code !== 0) throw new Error(`${driver.spec.id} exited ${output.code}: ${output.stderr || output.stdout}`);
  return JSON.parse(await readFile(driver.spec.resultPath, "utf8")) as DriverResult;
}

async function stopDriver(driver: RunningDriver): Promise<void> {
  if (driver.child.exitCode === null) driver.child.kill();
  try {
    await withDeadline(driver.output, `${driver.spec.id} process close`, 5_000);
  } catch (error) {
    if (driver.child.exitCode === null) driver.child.kill("SIGKILL");
    throw error;
  }
}

function writerSpec(root: string, id: string, mode: DriverSpec["mode"], gate: string | undefined): DriverSpec {
  return {
    id,
    mode,
    accessIntent: "mutating",
    marker: join(root, `${id}.started.json`),
    gate: gate ?? "-",
    target: join(root, `${id}.written.txt`),
    value: id,
    participationEvidence: join(root, `${id}.pre-writer-evidence.json`),
    resultPath: join(root, `${id}.result.json`),
  };
}

async function f1AliasOverlap(root: string): Promise<CaseResult> {
  const fixture = await createFixture(join(root, "f1"), ["alpha", "beta"]);
  const gate = join(root, "f1", "release");
  const firstSpec = writerSpec(join(root, "f1"), "f1-alpha", "background", gate);
  const secondSpec = writerSpec(join(root, "f1"), "f1-beta", "background", gate);
  const first = startDriver(fixture.brainHome, fixture.repo, "alpha", firstSpec);
  let second: RunningDriver | undefined;
  try {
    await waitForDriverDecision(first, [firstSpec.marker!], "F1 alpha writer start");
    const firstParticipation = participationSummary(await readWriterEvidence(firstSpec));
    second = startDriver(fixture.brainHome, fixture.repo, "beta", secondSpec);
    await waitForDriverDecision(second, [secondSpec.marker!, secondSpec.resultPath], "F1 beta decision");
    const overlapped = existsSync(secondSpec.marker!);
    const contenderParticipation = participationSummary(await readWriterEvidence(secondSpec));
    await writeFile(gate, "release", "utf8");
    const firstResult = await finishDriver(first);
    const secondResult = await finishDriver(second);
    const retrySpec = writerSpec(join(root, "f1"), "f1-beta-after-release", "background", undefined);
    const retry = startDriver(fixture.brainHome, fixture.repo, "beta", retrySpec);
    const retryResult = await finishDriver(retry);
    const retryParticipation = participationSummary(await readWriterEvidence(retrySpec));
    return {
      case: "F1 alias exclusion",
      passed:
        !overlapped &&
        firstParticipation.admissionBeforeWriter &&
        firstParticipation.bindingBeforeWriter &&
        firstResult.targetWritten &&
        secondResult.taskBlocked &&
        retryParticipation.admissionBeforeWriter &&
        retryParticipation.bindingBeforeWriter &&
        retryResult.targetWritten,
      facts: {
        overlapped,
        firstParticipation,
        contenderParticipation,
        retryParticipation,
        firstResult,
        secondResult,
        retryResult,
      },
    };
  } finally {
    if (!existsSync(gate)) await writeFile(gate, "release", "utf8");
    await stopDriver(first);
    if (second) await stopDriver(second);
  }
}

async function a03PhysicalAliasOverlap(root: string): Promise<CaseResult> {
  const caseRoot = join(root, "a03");
  const fixture = await createFixture(caseRoot, ["alpha", "beta"]);
  const gate = join(caseRoot, "release");
  const firstSpec = writerSpec(caseRoot, "a03-holder", "background", gate);
  const first = startDriver(fixture.brainHome, fixture.repo, "alpha", firstSpec);
  const contenders: RunningDriver[] = [];
  const contenderResults: Record<string, DriverResult> = {};
  const junction = join(caseRoot, "junction");
  const unresolved = join(caseRoot, "unresolved");
  let firstResult: DriverResult | undefined;
  let retryResult: DriverResult | undefined;
  let distinctResult: DriverResult | undefined;
  try {
    await waitForDriverDecision(first, [firstSpec.marker!], "A03 first writer barrier");
    const firstParticipation = participationSummary(await readWriterEvidence(firstSpec));
    await run("cmd.exe", ["/d", "/c", "mklink", "/J", junction, fixture.repo]);
    for (const [label, cwd] of [
      ["case", resolve(fixture.repo).toUpperCase()],
      ["junction", junction],
    ] as const) {
      const spec = writerSpec(caseRoot, `a03-${label}`, "background", gate);
      const contender = startDriver(fixture.brainHome, cwd, "beta", spec);
      contenders.push(contender);
      await waitForDriverDecision(contender, [spec.resultPath], `A03 ${label} decision`);
      contenderResults[label] = await finishDriver(contender);
    }
    await git(fixture.repo, "switch", "-c", "a03-branch");
    const branchSpec = writerSpec(caseRoot, "a03-branch", "background", gate);
    const branch = startDriver(fixture.brainHome, fixture.repo, "beta", branchSpec);
    contenders.push(branch);
    await waitForDriverDecision(branch, [branchSpec.resultPath], "A03 branch decision");
    contenderResults.branch = await finishDriver(branch);
    await mkdir(unresolved, { recursive: true });
    const unresolvedSpec = writerSpec(caseRoot, "a03-unresolved", "background", gate);
    const unresolvedDriver = startDriver(fixture.brainHome, unresolved, "beta", unresolvedSpec);
    contenders.push(unresolvedDriver);
    await waitForDriverDecision(unresolvedDriver, [unresolvedSpec.resultPath], "A03 unresolved decision");
    contenderResults.unresolved = await finishDriver(unresolvedDriver);
    const distinct = await createFixture(join(caseRoot, "distinct"), ["distinct"]);
    const distinctSpec = writerSpec(caseRoot, "a03-distinct", "background", undefined);
    const distinctDriver = startDriver(distinct.brainHome, distinct.repo, "distinct", distinctSpec);
    contenders.push(distinctDriver);
    distinctResult = await finishDriver(distinctDriver);
    await writeFile(gate, "release", "utf8");
    firstResult = await finishDriver(first);
    const retrySpec = writerSpec(caseRoot, "a03-after-release", "background", undefined);
    const retry = startDriver(fixture.brainHome, fixture.repo, "beta", retrySpec);
    contenders.push(retry);
    retryResult = await finishDriver(retry);
    const denied = Object.fromEntries(
      Object.entries(contenderResults).map(([label, result]) => [label, {
        taskBlocked: result.taskBlocked,
        identityRefused: result.taskText.includes("WORKTREE_IDENTITY_INVALID"),
        writerEntered: result.targetWritten,
      }]),
    );
    return {
      case: "A03 production physical aliases and branch transition",
      passed:
        firstParticipation.admissionBeforeWriter &&
        firstParticipation.bindingBeforeWriter &&
        firstResult.targetWritten &&
        denied.case.taskBlocked &&
        denied.junction.taskBlocked &&
        denied.branch.taskBlocked &&
        denied.unresolved.identityRefused &&
        !denied.case.writerEntered &&
        !denied.junction.writerEntered &&
        !denied.branch.writerEntered &&
        !denied.unresolved.writerEntered &&
        distinctResult.targetWritten &&
        retryResult.targetWritten,
      facts: {
        firstParticipation,
        denied,
        firstResult,
        distinctResult,
        retryResult,
        branch: { command: ["git", "-C", fixture.repo, "switch", "-c", "a03-branch"] },
        barrier: "First writer held before alias/branch decisions; release and retry were observed through real driver results.",
      },
    };
  } finally {
    if (!existsSync(gate)) await writeFile(gate, "release", "utf8");
    await stopDriver(first);
    await Promise.all(contenders.map(driver => stopDriver(driver)));
    if (existsSync(junction)) await run("cmd.exe", ["/d", "/c", "rmdir", junction]);
  }
}

async function f2ReadOnly(root: string): Promise<CaseResult> {
  const fixture = await createFixture(join(root, "f2"), ["alpha"]);
  const spec: DriverSpec = {
    id: "f2-readonly",
    mode: "background",
    accessIntent: "read_only",
    allowedRead: join(fixture.repo, "tracked.txt"),
    forbiddenSentinel: join(fixture.repo, "forbidden-readonly-write.txt"),
    resultPath: join(root, "f2", "readonly.result.json"),
  };
  const driver = startDriver(fixture.brainHome, fixture.repo, "alpha", spec);
  let result: DriverResult;
  try {
    result = await finishDriver(driver);
  } finally {
    await stopDriver(driver);
  }
  const brainEvidence = await queryWorkerEvidence(fixture.brainHome, "alpha");
  const readOnlyAdmission = brainEvidence.rows.some((row) => row.access_intent === "read_only");
  return {
    case: "F2 native read-only restriction",
    passed:
      readOnlyAdmission &&
      !result.forbiddenSentinelWritten &&
      result.forbiddenHubRejected &&
      result.allowedReadObserved,
    facts: { readOnlyAdmission, brainEvidence, result },
  };
}



async function contentionPair(root: string, firstMode: DriverSpec["mode"], secondMode: DriverSpec["mode"]): Promise<CaseResult> {
  const name = `${firstMode}-${secondMode}`;
  const pairRoot = join(root, "f4", name);
  const fixture = await createFixture(pairRoot, ["alpha"]);
  const gate = join(pairRoot, "release");
  const firstSpec = writerSpec(pairRoot, `${name}-first`, firstMode, gate);
  const blockedSpec = writerSpec(pairRoot, `${name}-contender`, secondMode, undefined);
  const first = startDriver(fixture.brainHome, fixture.repo, "alpha", firstSpec);
  let contender: RunningDriver | undefined;
  try {
    await waitForDriverDecision(first, [firstSpec.marker!], `${name} first start`);
    const firstParticipation = participationSummary(await readWriterEvidence(firstSpec));
    contender = startDriver(fixture.brainHome, fixture.repo, "alpha", blockedSpec);
    await waitForDriverDecision(contender, [blockedSpec.marker!, blockedSpec.resultPath], `${name} contention decision`);
    const overlapped = existsSync(blockedSpec.marker!);
    const contenderParticipation = participationSummary(await readWriterEvidence(blockedSpec));
    await writeFile(gate, "release", "utf8");
    const firstResult = await finishDriver(first);
    const contenderResult = await finishDriver(contender);
    const retrySpec = writerSpec(pairRoot, `${name}-after-release`, secondMode, undefined);
    const retry = startDriver(fixture.brainHome, fixture.repo, "alpha", retrySpec);
    const retryResult = await finishDriver(retry);
    const retryParticipation = participationSummary(await readWriterEvidence(retrySpec));
    return {
      case: `F4 ${name}`,
      passed:
        !overlapped &&
        firstParticipation.admissionBeforeWriter &&
        firstParticipation.bindingBeforeWriter &&
        firstResult.targetWritten &&
        contenderResult.taskBlocked &&
        retryParticipation.admissionBeforeWriter &&
        retryParticipation.bindingBeforeWriter &&
        retryResult.targetWritten,
      facts: {
        overlapped,
        firstParticipation,
        contenderParticipation,
        retryParticipation,
        firstResult,
        contenderResult,
        retryResult,
      },
    };
  } finally {
    if (!existsSync(gate)) await writeFile(gate, "release", "utf8");
    await stopDriver(first);
    if (contender) await stopDriver(contender);
  }
}

async function distinctWorktreeOverlap(root: string): Promise<CaseResult> {
  const caseRoot = join(root, "distinct-worktrees");
  const fixture = await createFixture(caseRoot, ["alpha"]);
  const secondRepo = join(caseRoot, "second-worktree");
  await git(fixture.repo, "worktree", "add", "--detach", secondRepo, "HEAD");
  await run(PYTHON, ["-c",
    "import sys; from pathlib import Path; from second_brain import registry; registry.add_project(Path(sys.argv[1]), Path(sys.argv[2]), project_id='beta')",
    fixture.brainHome, secondRepo], { env: cleanPythonEnv() });
  const gate = join(caseRoot, "release");
  const firstSpec = writerSpec(caseRoot, "distinct-alpha", "background", gate);
  const secondSpec = writerSpec(caseRoot, "distinct-beta", "background", gate);
  const first = startDriver(fixture.brainHome, fixture.repo, "alpha", firstSpec);
  let second: RunningDriver | undefined;
  try {
    await waitForDriverDecision(first, [firstSpec.marker!], "distinct first native writer");
    second = startDriver(fixture.brainHome, secondRepo, "beta", secondSpec);
    await waitForDriverDecision(second, [secondSpec.marker!], "distinct simultaneous native writer");
    const firstParticipation = participationSummary(await readWriterEvidence(firstSpec));
    const secondParticipation = participationSummary(await readWriterEvidence(secondSpec));
    const simultaneous = !existsSync(firstSpec.target!) && !existsSync(secondSpec.target!);
    await writeFile(gate, "release", "utf8");
    const firstResult = await finishDriver(first);
    const secondResult = await finishDriver(second);
    return {
      case: "Distinct physical worktrees overlap",
      passed: simultaneous && firstParticipation.bindingBeforeWriter && secondParticipation.bindingBeforeWriter &&
        firstParticipation.worktreeId !== secondParticipation.worktreeId && firstResult.targetWritten && secondResult.targetWritten,
      facts: { simultaneous, firstParticipation, secondParticipation, firstResult, secondResult },
    };
  } finally {
    if (!existsSync(gate)) await writeFile(gate, "release", "utf8");
    await stopDriver(first);
    if (second) await stopDriver(second);
  }
}


async function f3Cleanup(root: string, order: NonNullable<DriverSpec["cleanupFault"]>["order"]): Promise<CaseResult> {
  const caseRoot = join(root, `f3-${order}`);
  const fixture = await createFixture(caseRoot, ["alpha", "beta"]);
  const peers = new Map<string, BarrierPeer>();
  const arrivals = new Map<string, (peer: BarrierPeer) => void>();
  const server = createServer(socket => {
    const peer = new BarrierPeer(socket);
    void peer.wait("hello").then(role => {
      peers.set(String(role), peer);
      arrivals.get(String(role))?.(peer);
    });
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing IPC port");
  const getPeer = async (role: string): Promise<BarrierPeer> => {
    const existing = peers.get(role);
    if (existing) return existing;
    return withDeadline(new Promise<BarrierPeer>(resolve => {
      arrivals.set(role, resolve);
    }), `${order} ${role} connection`);
  };
  const spec = writerSpec(caseRoot, `f3-${order}`, "background", undefined);
  spec.cleanupFault = { order, port: address.port };
  const driver = startDriver(fixture.brainHome, fixture.repo, "alpha", spec);
  let osWaiter: ChildProcess | undefined;
  let exited: Promise<number | null> | undefined;
  const facts: Record<string, unknown> = { faultBoundary: "CONTROLLED child AgentSession.abort/dispose", order };
  try {
    const control = await getPeer("driver");
    const writer = await getPeer("writer");
    const ready = await writer.wait("writer-ready") as { pid: number };
    // Retain a Windows kernel process handle BEFORE cancellation/exit. A socket
    // close, marker, driver exit or kill request alone is not process-exit proof.
    let resolveOpened!: () => void;
    let rejectOpened!: (reason: unknown) => void;
    const opened = new Promise<void>((resolve, reject) => {
      resolveOpened = resolve;
      rejectOpened = reject;
    });
    osWaiter = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
      "$p = [System.Diagnostics.Process]::GetProcessById([int]$env:F3_WRITER_PID); $h = $p.Handle; [Console]::WriteLine('HANDLE_OPEN'); $p.WaitForExit(); [Console]::WriteLine('PROCESS_EXITED'); $p.Dispose()"],
      { env: { ...process.env, F3_WRITER_PID: String(ready.pid) }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let handleLog = "";
    osWaiter.stdout!.on("data", chunk => {
      handleLog += String(chunk);
      if (handleLog.includes("HANDLE_OPEN")) resolveOpened();
    });
    osWaiter.once("error", rejectOpened);
    const processExited = new Promise<number | null>(resolve => {
      osWaiter!.once("close", code => {
        resolve(code);
        if (!handleLog.includes("HANDLE_OPEN")) rejectOpened(new Error(handleLog));
      });
    });
    exited = processExited;
    await withDeadline(opened, "retained writer process handle");
    facts.writerPid = ready.pid;
    facts.participation = participationSummary(await readWriterEvidence(spec));
    control.send("cancel");
    await control.wait("logically-cancelled");
    await control.wait("A-started");
    if (order === "failure-first") control.send("finish-a");
    // The genuine native cleanup deadline advances to B while A is outstanding
    // in reverse/success cases. B itself supplies the barrier, not a sleep.
    await control.wait("B-started");
    writer.send("write-after-cancel");
    facts.writeAfterCancellation = await writer.wait("write-confirmed");
    control.send("evict");
    facts.eviction = await control.wait("display-evicted");
    control.send("inspect-pending");
    facts.pendingAfterEviction = await control.wait("pending");
    const contenderSpec = writerSpec(caseRoot, `f3-${order}-alias`, "background", undefined);
    const contender = startDriver(fixture.brainHome, fixture.repo, "beta", contenderSpec);
    facts.contender = await finishDriver(contender);
    facts.heldEvidence = await queryWorkerEvidence(fixture.brainHome, "alpha");
    writer.send("exit");
    const processExit = await withDeadline(processExited, "actual writer process exit");
    facts.processExit = { code: processExit, handleLog };
    if (processExit !== 0 || !handleLog.includes("PROCESS_EXITED")) throw new Error("Writer exit not observed");
    control.send("finish-b");
    await control.wait("B-settled");
    if (order === "failure-last" || order === "success") control.send("finish-a");
    const outcome = await control.wait("cleanup-outcome");
    facts.cleanupOutcome = outcome;
    // The production observer asynchronously persists; read-only DB queries wait
    // for the exact attempt's native terminal revision, never fabricate a receipt.
    const participant = participationSummary(await readWriterEvidence(spec));
    const attemptId = participant.latestAttemptId;
    const successful = order === "success";
    let terminal: WorkerEvidence;
    const deadline = Date.now() + TIMEOUT_MS;
    for (;;) {
      terminal = await queryWorkerEvidence(fixture.brainHome, "alpha");
      if (terminal.receipts.some(receipt => {
        const payload = JSON.parse(receipt.payload_json) as { executor_settled?: boolean; cleanup_complete?: boolean };
        return receipt.attempt_id === attemptId && payload.executor_settled === true &&
          payload.cleanup_complete === successful;
      })) break;
      if (Date.now() > deadline) throw new Error("Exact-attempt terminal receipt not persisted");
    }
    facts.terminalEvidence = terminal;
    const row = terminal.rows.find(row => row.attempt_id === attemptId);
    facts.errorsRetained = successful || JSON.stringify(outcome).includes("F3 injected");
    control.send("finish-driver");
    facts.driver = await finishDriver(driver);
    const retrySpec = writerSpec(caseRoot, `f3-${order}-after-cleanup`, "background", undefined);
    facts.receiptObservedBeforeRetryAt = new Date().toISOString();
    facts.retry = await finishDriver(startDriver(fixture.brainHome, fixture.repo, "beta", retrySpec));
    facts.retryPreWriter = await readWriterEvidence(retrySpec);
    const contenderResult = facts.contender as DriverResult;
    const retry = facts.retry as DriverResult;
    const eviction = facts.eviction as { rows: number };
    const pending = facts.pendingAfterEviction as { pending: boolean };
    return {
      case: `F3 ${order}`,
      passed: participant.admissionBeforeWriter && participant.bindingBeforeWriter &&
        existsSync(spec.target!) && contenderResult.taskBlocked &&
        eviction.rows === 0 && pending.pending &&
        facts.errorsRetained === true &&
        (successful ? row?.writer_ownership === "released" && retry.targetWritten : row?.writer_ownership === "quarantined" && retry.taskBlocked),
      facts,
    };
  } catch (error) {
    facts.harnessError = cleanupErrorEvidence(error);
    return { case: `F3 ${order}`, passed: false, facts };
  } finally {
    peers.get("writer")?.send("exit");
    peers.get("driver")?.send("finish-a");
    peers.get("driver")?.send("finish-b");
    peers.get("driver")?.send("finish-driver");
    if (exited) await withDeadline(exited, "fixture retained writer exit");
    await stopDriver(driver);
    for (const peer of peers.values()) peer.socket.destroy();
    server.close();
  }
}
async function orchestrate(): Promise<void> {
  requiredOmpRoot();
  const root = await mkdtemp(join(tmpdir(), "sb-production-dispatch-"));
  const results: CaseResult[] = [];
  const capture = async (name: string, runCase: () => Promise<CaseResult>): Promise<void> => {
    trace(name, "case-start", { root });
    try {
      const result = await runCase();
      results.push(result);
      trace(name, "case-result", { passed: result.passed });
    } catch (error) {
      results.push({
        case: name,
        passed: false,
        facts: { harnessError: error instanceof Error ? error.stack ?? error.message : String(error) },
      });
      trace(name, "case-error", { error: error instanceof Error ? error.message : String(error) });
    } finally {
      const stopped = await Promise.allSettled(Array.from(activeDrivers, (driver) => stopDriver(driver)));
      for (const failure of stopped) {
        if (failure.status === "fulfilled") continue;
        results.push({
          case: `${name} driver cleanup`,
          passed: false,
          facts: { cleanupError: failure.reason instanceof Error ? failure.reason.stack ?? failure.reason.message : String(failure.reason) },
        });
      }
    }
  };
  const selected = new Set(
    (process.env.SECOND_BRAIN_HARNESS_CASES ?? "F1,F2,F4")
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean),
  );
  if (selected.has("A03")) await capture("A03 production physical aliases and branch transition", () => a03PhysicalAliasOverlap(root));
  if (selected.has("F1")) await capture("F1 alias exclusion", () => f1AliasOverlap(root));
  if (selected.has("F1D")) await capture("Distinct physical worktrees overlap", () => distinctWorktreeOverlap(root));
  if (selected.has("F2")) await capture("F2 native read-only restriction", () => f2ReadOnly(root));
  if (selected.has("F3")) {
    const orders = (process.env.SECOND_BRAIN_F3_ORDERS ?? "failure-first,failure-last,setup-throw,success").split(",");
    for (const order of orders) {
      if (order !== "failure-first" && order !== "failure-last" && order !== "setup-throw" && order !== "success") throw new Error(`Unknown F3 order ${order}`);
      await capture(`F3 ${order}`, () => f3Cleanup(root, order));
    }
  }
  if (selected.has("F4")) {
    for (const first of ["background", "blocking"] as const) {
      for (const second of ["background", "blocking"] as const) {
        await capture(`F4 ${first}-${second}`, () => contentionPair(root, first, second));
      }
    }
  }
  const retainFixture = selected.has("F3") || process.env.SECOND_BRAIN_RETAIN_FIXTURE === "1";
  if (!retainFixture && results.every((result) => result.passed)) {
    try {
      await delay(1000);
      await rm(root, { recursive: true, force: true, maxRetries: 30, retryDelay: 1000 });
    } catch (error) {
      results.push({
        case: "Harness-owned fixture cleanup",
        passed: false,
        facts: {
          root,
          cleanupError: error instanceof Error ? error.stack ?? error.message : String(error),
        },
      });
    }
  }
  const failed = results.some((result) => !result.passed);
  const output = {
    boundary: "simulated provider transport; real AgentSession, registered TaskTool, executor, Brain extension/adapter, and local tools",
    simulated_provider_requests: results.reduce((total, result) => {
      const serialized = JSON.stringify(result.facts);
      return total + (serialized.match(/"providerRequests":\d+/g) ?? [])
        .reduce((caseTotal, field) => caseTotal + Number(field.split(":")[1]), 0);
    }, 0),
    provider_calls: 0,
    production_usage: null,
    retained_fixture_root: failed || retainFixture ? root : null,
    fixture_cleanup: retainFixture ? "HELD: historical EBUSY owner not yet identified; no deletion/retry attempted" : "attempted only after driver exit",
    results,
  };
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  if (failed) process.exitCode = 1;
}

const mode = process.argv[2];
if (mode === "--worker") {
  try {
    await runDriver();
    // F3 barriers settle the real writer and native cleanup before driver exit.
    process.exit(0);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    process.exit(1);
  }
} else if (mode === "--writer") await runWriter(process.argv.slice(3));
else if (mode === "--write-once") await writeOnce(process.argv[3]);
else await orchestrate();
