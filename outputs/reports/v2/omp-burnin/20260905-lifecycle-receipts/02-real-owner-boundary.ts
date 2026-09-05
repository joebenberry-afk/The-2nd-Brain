import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Finite offline regression probe, not a replacement executor or scope lock.
const [brain, python, host] = process.argv.slice(2);
assert(brain && python && host, "brain root, Python executable and host root required");
const { AsyncJobManager } = await import(`${host}/packages/coding-agent/src/async/job-manager.ts`);
const scratch = await mkdtemp(join(tmpdir(), "brain-lifecycle-primitive-"));
const home = join(scratch, "home");
const scope = join(scratch, "workspace");
const env: Record<string, string | undefined> = { ...process.env, SECOND_BRAIN_HOME: home, PI_CODING_AGENT_DIR: join(scratch, "host") };
delete env.PYTHONHOME;
delete env.PYTHONPATH;
const py = async (body: string, ...args: string[]) => {
  const p = Bun.spawn([python, "-c", `import sys\nsys.path.insert(0,sys.argv[1]+'/src')\n${body}`, brain, ...args], { env, stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, code] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text(), p.exited]);
  assert.equal(code, 0, stderr);
  return JSON.parse(stdout);
};
const setup = await py(`import json\nfrom pathlib import Path\nimport pytest\nsys.path.insert(0,sys.argv[1]+'/tests')\nfrom conftest import make_brain\nfrom second_brain import worker_protocol,build_identity\nh=Path(sys.argv[2]);h.mkdir(parents=True);Path(sys.argv[3]).mkdir()\nwith pytest.MonkeyPatch.context() as m: make_brain(h,m)\nprint(json.dumps({'source_tree_sha256':build_identity.source_tree_fingerprint(Path(sys.argv[1])),'module':str(Path(worker_protocol.__file__).relative_to(Path(sys.argv[1])))}))`, home, scope);
const admit = (task: string) => py(`import json\nfrom second_brain.omp_adapter import handle_request\np={'operation':'worker_context','host_session_id':'primitive-parent','role':'driver','provider':'offline','model':'no-provider','worker_role':'worker','task_id':sys.argv[3],'task':'Write the same disposable resource','scope':'shared output file','cwd':sys.argv[4],'project_id':'primitive-project','context_refs':[]}\nprint(json.dumps(handle_request(sys.argv[2],p)))`, home, task, scope);
const waitFor = async (condition: () => Promise<boolean>, description: string) => {
  const deadline = performance.now() + 10000;
  while (!(await condition())) {
    assert(performance.now() < deadline, `deadline waiting for ${description}`);
    await Bun.sleep(5);
  }
};
const writer = `import os,sys,time\nfrom pathlib import Path\nr=Path(sys.argv[1]);name=sys.argv[2];end=time.monotonic()+20\n(r/(name+'.ready')).write_text('ready')\nwhile time.monotonic()<end and not (r/(name+'.release')).exists():\n with (r/'shared.txt').open('a') as f: f.write(name+'\\n');f.flush()\n if (r/(name+'.cancel')).exists(): (r/(name+'.cancel-seen')).write_text('cancel observed; cleanup pending')\n time.sleep(0.005)\n(r/(name+'.closed')).write_text('writer exited loop')\n`;
let deliveries = 0;
const manager = new AsyncJobManager({ retentionMs: 0, onJobComplete: () => { deliveries++; } });
const children: Array<ReturnType<typeof Bun.spawn>> = [];
const obligations: Array<Promise<void>> = [];
let firstSettled = false;
let secondSettled = false;
const start = (name: string, onExit: () => void) => {
  const id = manager.register("task", name, async ({ signal }: { signal: AbortSignal }) => {
    const p = Bun.spawn([python, "-c", writer, scope, name], { env, stdout: "ignore", stderr: "pipe" });
    children.push(p);
    const cancel = () => { void writeFile(join(scope, `${name}.cancel`), "accepted"); };
    signal.addEventListener("abort", cancel, { once: true });
    try { assert.equal(await p.exited, 0); onExit(); return "offline writer exited"; }
    finally { signal.removeEventListener("abort", cancel); }
  }, { id: "NativeJob", ownerId: "Owner", agentId: name });
  const job = manager.getJob(id);
  assert(job);
  obligations.push(job.promise);
  return id;
};
const started = performance.now();
const cpu = process.cpuUsage();
let result: Record<string, unknown>;
try {
  const firstAdmission = await admit("writer-one");
  assert.equal(firstAdmission.status, "prepared");
  const first = start("WriterOne", () => { firstSettled = true; });
  await waitFor(() => Bun.file(join(scope, "WriterOne.ready")).exists(), "first real writer ready");
  const cancelStarted = performance.now();
  assert.equal(manager.cancel(first, { ownerId: "Owner" }), true);
  const cancelMs = performance.now() - cancelStarted;
  await waitFor(() => Bun.file(join(scope, "WriterOne.cancel-seen")).exists(), "real writer observing cancellation while draining");
  manager.evictCompletedJobs({ ownerId: "Owner" });
  assert.equal(manager.getJob(first), undefined);
  const claimedOwnerSettlement = await manager.waitForOwnerJobs("Owner", { timeoutMs: 50 });
  const realWriterStillRunning = !firstSettled;
  assert(realWriterStillRunning);
  const secondAdmission = await admit("writer-two");
  assert.equal(secondAdmission.status, "prepared");
  const second = start("WriterTwo", () => { secondSettled = true; });
  await waitFor(async () => {
    const lines = (await readFile(join(scope, "shared.txt"), "utf8")).split(/\r?\n/);
    return lines.includes("WriterOne") && lines.includes("WriterTwo");
  }, "both admitted writers writing the same real file");
  const concurrentWriters = !firstSettled && !secondSettled;
  assert(concurrentWriters);
  manager.cancel(second, { ownerId: "Owner" });
  await Promise.all([writeFile(join(scope, "WriterOne.release"), "release"), writeFile(join(scope, "WriterTwo.release"), "release")]);
  await Promise.all(obligations);
  await manager.drainDeliveries();
  assert.equal(deliveries, 0);
  const state = await py(`import json,sqlite3\nfrom pathlib import Path\nc=sqlite3.connect((Path(sys.argv[2])/'db/brain.sqlite').as_uri()+'?mode=ro',uri=True)\nprint(json.dumps({'workers':c.execute('SELECT task_id,state FROM worker_tasks ORDER BY task_id').fetchall(),'credit_events':c.execute('SELECT COUNT(*) FROM credit_events').fetchone()[0],'worker_columns':[r[1] for r in c.execute('PRAGMA table_info(worker_tasks)')],'meta_columns':[r[1] for r in c.execute('PRAGMA table_info(worker_task_meta)')]}))`, home);
  result = { verdict: "PRIMITIVE_ABSENT", source: setup, host_base: "e874b613654fd493b2bcb45c832e68f8d1a9a23e", brain_base: "e9fc61cb623699cb982be4466d053944e2f8426a", firstAdmission: firstAdmission.status, secondAdmission: secondAdmission.status, nativeIds: [first, second], childIds: ["WriterOne", "WriterTwo"], acceptedCancellation: true, visibleRowEvicted: true, claimedOwnerSettlement, realWriterStillRunningAtClaim: realWriterStillRunning, concurrentWritersOnSameFile: concurrentWriters, actualCleanupObserved: firstSettled && secondSettled, automaticCancellationDeliveries: deliveries, providerCalls: 0, productionUsage: null, state, overhead: { cancel_ms: cancelMs, total_ms: performance.now() - started, cpu_microseconds: process.cpuUsage(cpu), disposable_output_bytes: (await stat(join(scope, "shared.txt"))).size }, scope: "Actual manager and Brain worker_context/SQLite; two real directly owned Python file writers. Native TaskTool, supported extension observer, resource admission/fencing and arbitrary descendants are NOT proven. No test-only mutex or release attestation is substituted." };
} finally {
  await Promise.all([writeFile(join(scope, "WriterOne.release"), "release"), writeFile(join(scope, "WriterTwo.release"), "release")]);
  await Promise.all(children.map(p => p.exited));
  await manager.dispose();
  await rm(scratch, { recursive: true, force: true });
}
console.log(JSON.stringify(result));
if (process.argv.includes("--require-retained-obligation")) {
  assert.equal(result.claimedOwnerSettlement, false, "eviction must not fabricate execution settlement");
}
if (process.argv.includes("--require-scope-admission")) {
  assert.equal(result.concurrentWritersOnSameFile, false, "unknown cleanup must block a conflicting admitted writer");
}
