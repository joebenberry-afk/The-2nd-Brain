import { spawn, execFileSync } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";
import factory from "../src/index";
import type { AsyncJobLifecycleObservation, ExtensionAPI, ExtensionContext } from "../types/prime";

interface Deferred<T> { resolve(value: T): void; promise: Promise<T> }
interface ProbeResult { input?: { task: string }; block?: boolean; reason?: string }
type Handler = (event: Record<string, unknown>, ctx: ExtensionContext) => ProbeResult | undefined | Promise<ProbeResult | undefined>;
interface OwnerRow { task_id: string; writer_ownership: string; logical_outcome: string | null }

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const output = resolve(process.argv[2]);
mkdirSync(output, { recursive: false });
const fixture = mkdtempSync(join(tmpdir(), "brain-observer-expiry-"));
const python = process.env.SECOND_BRAIN_PYTHON ?? join(root, ".venv/Scripts/python.exe");
const env = { ...process.env };
for (const key of Object.keys(env)) if (key.startsWith("SECOND_BRAIN_") || key === "PYTHONHOME" || key === "PYTHONPATH") delete env[key];
const setup = `import json, subprocess, sys
from pathlib import Path
def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
r=Path(sys.argv[2]); a=r/"a"; a.mkdir(); git(a, "init", "-q")
(a/"tracked.txt").write_text("initial" + chr(10), encoding="utf-8"); git(a, "add", "tracked.txt")
git(a, "-c", "user.name=Observer Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial")
git(a, "branch", "side-worktree"); b=r/"b"; git(a, "worktree", "add", "-q", str(b), "side-worktree")
home=r/"home"; from second_brain import db, registry, paths; paths.ensure_layout(home); db.migrate(db.db_path(home)); registry.add_project(home, a, project_id="writer-project")
print(json.dumps({"home":str(home), "a":str(a), "b":str(b), "base":sys._base_executable}))`;
const layout = JSON.parse(execFileSync(python, ["-c", setup, root, fixture], { env, encoding: "utf8" }));
Object.assign(process.env, env);
process.env.SECOND_BRAIN_HOME = layout.home;
process.env.SECOND_BRAIN_PROJECT = "writer-project";
process.env.SECOND_BRAIN_PYTHON = python;
// Runtime-selected isolated host checkout; static import would bind another authority.
const { AsyncJobManager } = await import(pathToFileURL(join(process.env.OMP_SOURCE_ROOT!, "packages/coding-agent/src/async/job-manager.ts")).href);
const manager = new AsyncJobManager({ retentionMs: 0 });
const events: Array<Record<string, unknown>> = [];
function record(event: string, data: Record<string, unknown> = {}) { events.push({ event, at: new Date().toISOString(), ...data }); writeFileSync(join(output, "events.json"), JSON.stringify(events, null, 2)); }
function deferred<T>(): Deferred<T> { let resolve!: (v: T) => void; const promise = new Promise<T>(r => resolve = r); return { resolve, promise }; }
async function deadline<T>(promise: Promise<T>, label: string, ms = 45_000) {
  let timer: NodeJS.Timeout;
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(label)), ms); })]); }
  finally { clearTimeout(timer!); }
}
const handlers = new Map<string, Handler>();
const accepted = new Map<string, Deferred<unknown>>();
const disposals = new Map<string, Deferred<number>>();
const counts = new Map<string, number>();
const probeApi = { on(name: string, fn: Handler) { handlers.set(name, fn); }, appendEntry(type: string, data: unknown) {
  record(type, { data });
  if (type === "second-brain.worker-lifecycle-accepted" && data && typeof data === "object" && "taskId" in data && typeof data.taskId === "string") accepted.get(data.taskId)?.resolve(data);
} };
// This in-process fixture implements only the extension hooks exercised below.
factory(probeApi as unknown as ExtensionAPI);
function context(cwd: string, session: string): ExtensionContext {
  return { cwd, model: { provider: "openai-codex", id: "gpt-5.6-luna" }, sessionManager: { getSessionFile: () => join(fixture, session + ".jsonl") }, getContextUsage: () => undefined, getSystemPrompt: () => "offline probe", signal: undefined, hasUI: false, ui: undefined,
    observeAsyncJobLifecycle(observer, options) {
      const key = options?.sourceToolCallId ?? "";
      const unsubscribe = manager.observeJobLifecycle(observer, { ownerId: "Main", sourceToolCallId: key });
      return () => { unsubscribe(); const n = (counts.get(key) ?? 0) + 1; counts.set(key, n); record("native-unsubscribe", { key, count: n }); disposals.get(key)?.resolve(n); };
    },
  };
}
function state(): OwnerRow[] {
  const code = `import sqlite3,json,sys\nc=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row\nprint(json.dumps([dict(r) for r in c.execute('SELECT task_id,state,logical_outcome,writer_ownership,executor_settled,cleanup_complete,lifecycle_sequence FROM worker_tasks ORDER BY task_id')]))\nc.close()`;
  return JSON.parse(execFileSync(python, ["-c", code, join(layout.home, "db/brain.sqlite")], { env, encoding: "utf8" }));
}
const owned: ChildProcessWithoutNullStreams[] = [];
async function scenario(key: string, cwd: string, cancelled: boolean) {
  const ctx = context(cwd, key);
  const disposer = deferred<number>(); disposals.set(key, disposer);
  const admission = await handlers.get("tool_call")!({ toolName: "task", toolCallId: key, input: { task: "offline owned writer", access_intent: "mutating", context_refs: [] } }, ctx);
  assert(admission?.input, JSON.stringify(admission));
  const task = /task_id=([^ ]+)/.exec(admission.input.task)![1];
  const initial = deferred<unknown>(); accepted.set(task, initial);
  const ready = deferred<unknown>(); const exited = deferred<number>();
  let writer!: ChildProcessWithoutNullStreams;
  const job = manager.register("task", key, async ({ signal, deferCleanup }: { signal: AbortSignal; deferCleanup(completion: Promise<void>): void }) => {
    writer = spawn(layout.base, ["-c", "import os,sys,json\nf=open('owned.txt','w'); f.write('start\\n'); f.flush(); print(json.dumps({'pid':os.getpid()}),flush=True)\nassert sys.stdin.readline().strip()=='release'\nf.write('end\\n'); f.close()"], { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    owned.push(writer);
    createInterface({ input: writer.stdout }).once("line", line => { const data = JSON.parse(line); assert.equal(data.pid, writer.pid); record("writer-ready", { key, pid: writer.pid }); ready.resolve(data); });
    writer.once("error", error => { throw error; });
    writer.once("exit", code => { assert.notEqual(code, null); record("writer-exit", { key, pid: writer.pid, code }); exited.resolve(code!); });
    deferCleanup(exited.promise.then(code => { assert.equal(code, 0); }));
    if (cancelled) await new Promise<void>(r => signal.addEventListener("abort", () => r(), { once: true }));
    else await exited.promise;
    return "owned writer finished";
  }, { ownerId: "Main", agentId: key, sourceToolCallId: key, sourceIndex: 0, cleanupTracked: true, requireLifecycleAcknowledgement: true });
  await deadline(ready.promise, key + " writer ready"); await deadline(initial.promise, key + " initial receipt");
  if (cancelled) {
    const cancellation = deferred<unknown>(); accepted.set(task, cancellation);
    assert(manager.cancel(job, { ownerId: "Main" }));
    await deadline(cancellation.promise, "cancellation receipt");
    await manager.getJob(job)?.promise;
  }
  await handlers.get("session_shutdown")!({ reason: "offline-observer-disconnect" }, ctx);
  assert.equal(writer.exitCode, null);
  record("shutdown-active-writer", { key, task, pid: writer.pid, state: state() });
  return { key, task, writer, exited, disposer, ctx, job };
}
try {
  const cases = await Promise.all([scenario("unknown", layout.a, false), scenario("cancelled", layout.b, true)]);
  await deadline(Promise.all(cases.map(c => c.disposer.promise)), "real 30 second observer expiry");
  const expired = state();
  for (const c of cases) {
    assert.equal(c.writer.exitCode, null); assert.equal(counts.get(c.key), 1);
    const row = expired.find(r => r.task_id === c.task)!;
    assert.notEqual(row.writer_ownership, "released");
    assert.equal(row.logical_outcome, c.key === "unknown" ? null : "cancelled");
    const denied = await handlers.get("tool_call")!({ toolName: "task", toolCallId: c.key + "-contender", input: { task: "must refuse", access_intent: "mutating" } }, c.ctx);
    assert.equal(denied?.block, true);
    record("expired-active-writer-protected", { key: c.key, row, denied });
  }
  const cleanup = cases.map(c => {
    const done = deferred<AsyncJobLifecycleObservation>();
    const unsubscribe = manager.observeJobLifecycle((observation: AsyncJobLifecycleObservation) => { if (observation.cleanupComplete) done.resolve(observation); return true; }, { ownerId: "Main", sourceToolCallId: c.key });
    c.writer.stdin.end("release\n");
    return deadline(done.promise, "native cleanup completion").then(observation => { unsubscribe(); return observation; });
  });
  const settled = await Promise.all(cleanup); await Promise.all(cases.map(c => c.exited.promise));
  const after = state();
  for (const c of cases) { assert.notEqual(after.find(r => r.task_id === c.task)!.writer_ownership, "released"); assert.deepEqual(readFileSync(join(c.key === "unknown" ? layout.a : layout.b, "owned.txt"), "utf8").split(/\r?\n/), ["start", "end", ""]); }
  assert.equal(await manager.dispose(), true);
  record("complete", { fixture, expired, after, nativeCleanup: settled, subscriptionsDisposedOnce: Object.fromEntries(counts), protectionRetainedWithoutReplay: true, providersUsed: 0 });
} catch (error) {
  record("failure", { fixture, error: String(error) });
  throw error;
} finally {
  for (const writer of owned) if (writer.exitCode === null) { const stopped = new Promise<void>(r => writer.once("exit", () => r())); writer.kill(); await deadline(stopped, "owned process failure teardown"); }
}
