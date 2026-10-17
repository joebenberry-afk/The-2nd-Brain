/** Local-only measurements; never print or persist note bodies, queries, or private paths. */
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { cpus, tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { loadNotes, formatNote, type Note } from "../src/notes.ts";
import { renderCard } from "../src/card.ts";
import { resolveProject } from "../src/project.ts";
import { answer, recall } from "../src/search.ts";
import { findFix, renderFix } from "../src/capture.ts";
import { writeWork } from "../src/work.ts";
import extension from "../src/omp.ts";
import { estimateTokens, findHome, PACKAGE_HOME, writeAtomic } from "../src/util.ts";

interface Row { name: string; count: number; metrics: Record<string, number>; }
interface Report { at: string; runtime: string; cpu: string; samples: number; rows: Row[]; }
const samples = 30;
const home = findHome();
assert(home, "No Brain home found");
const output = join(home, "state", "perf.json");
const previous: Report | undefined = existsSync(output) ? JSON.parse(readFileSync(output, "utf8")) as Report : undefined;
const scratch = mkdtempSync(join(tmpdir(), "brain-perf-"));

function bench(metrics: Record<string, number>, name: string, fn: () => unknown): void {
  for (let i = 0; i < 5; i++) fn();
  const times: number[] = [];
  for (let i = 0; i < samples; i++) {
    const start = performance.now();
    fn();
    times.push(performance.now() - start);
  }
  times.sort((a, b) => a - b);
  metrics[`${name}.medianMs`] = times[Math.floor(samples / 2)]!;
  metrics[`${name}.p95Ms`] = times[Math.ceil(samples * 0.95) - 1]!;
}

function synthetic(count: number): string {
  const target = join(scratch, String(count));
  mkdirSync(join(target, "notes", "perf"), { recursive: true });
  const topics = ["typescript", "python", "database", "network", "compaction", "authentication", "deploy", "testing", "storage", "rendering", "queue", "compiler"];
  const actions = ["invalidate", "retry", "isolate", "validate", "batch", "serialize", "cache", "cancel", "stream", "recover", "migrate"];
  const objects = ["session", "worker", "transaction", "socket", "schema", "request", "index", "buffer", "connection", "artifact", "cursor", "listener", "process"];
  for (let i = 0; i < count; i++) {
    const topic = topics[i % topics.length]!;
    const action = actions[Math.floor(i / topics.length) % actions.length]!;
    const object = objects[Math.floor(i / (topics.length * actions.length)) % objects.length]!;
    const id = `n-${i.toString(16).padStart(10, "0")}`;
    const note: Note = {
      id, kind: i % 7 === 0 ? "gotcha" : i % 3 === 0 ? "procedure" : "fact", project: "perf", private: false,
      at: "2026-01-01T00:00:00Z", source: "agent", tags: [topic, object],
      errors: i % 7 === 0 ? [`perf failure ${i}`] : [], evidence: [], tested: i % 7 === 0,
      body: `${topic}: ${action} the ${object} in component ${i}\nUse ${action} before releasing the ${object}. ${i % 4 === 0 ? "Keep a bounded cache for repeated lookups." : "Preserve ownership until the operation completes."} Limit ${i % 97 + 1} concurrent operations. ${i % 11 === 0 ? "An uncommon deadlock needs explicit rollback." : "Verify the result before returning."}`,
      path: join(target, "notes", "perf", `${id}.md`),
    };
    writeFileSync(note.path, formatNote(note));
  }
  writeWork(target, "perf", "Goal: benchmark varied memory retrieval.\nNext: compare latency and token budgets.");
  return target;
}

function measure(name: string, target: string, expected?: number): Row {
  const metrics: Record<string, number> = {};
  const start = performance.now();
  const loaded = loadNotes(target);
  metrics["loadNotes.firstMs"] = performance.now() - start;
  assert.equal(loaded.errors.length, 0, "Corpus contains invalid notes");
  const notes = loaded.notes;
  if (expected !== undefined) assert.equal(notes.length, expected);
  const env = { ...process.env, SECOND_BRAIN_HOME: target, ...(expected ? { BRAIN_PROJECT: "perf" } : {}) };
  const project = resolveProject(target, PACKAGE_HOME, env);
  const query = (expected ? ["typescript session", "database transaction"] : ["OMP", "compaction", "TypeScript", "session"])
    .find((value) => recall(notes, value, { project }).length >= 3) ?? "session";
  const card = renderCard(target, notes, project, { tools: true });
  const recalled = answer(notes, query, { project, home: target });
  const error = notes.flatMap((note) => note.tested && !note.retired ? note.errors : [])
    .find((value) => !value.startsWith("re:") && findFix(notes, value, project));
  const fix = error ? findFix(notes, error, project) : null;
  for (const [key, text] of Object.entries({ card, recall: recalled, fix: fix ? renderFix(fix) : "" })) {
    metrics[`${key}.tokens`] = estimateTokens(text);
  }
  metrics["recall.lines"] = recalled.split("\n").length;
  metrics["fix.available"] = fix ? 1 : 0;
  assert(metrics["card.tokens"]! <= 400 && metrics["fix.tokens"]! <= 80);
  assert(metrics["recall.lines"]! <= 3);
  bench(metrics, "loadNotes.warm", () => loadNotes(target));
  bench(metrics, "card", () => renderCard(target, loadNotes(target).notes, project, { tools: true }));
  bench(metrics, "recall", () => answer(loadNotes(target).notes, query, { project, home: target }));

  // The real home is read directly above. Hook writes go to a local snapshot, not real telemetry/work.
  const hookHome = join(scratch, `hook-${name}`);
  mkdirSync(hookHome, { recursive: true });
  for (const path of ["notes", "work", "projects.json"]) {
    if (existsSync(join(target, path))) cpSync(join(target, path), join(hookHome, path), { recursive: true });
  }
  const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
  extension({ on: (event, handler) => { handlers.set(event, handler); } }, { ...env, SECOND_BRAIN_HOME: hookHome });
  const failure = { toolName: "bash", input: { command: "perf-example" }, isError: true, content: [{ type: "text", text: error ?? "perf unmatched failure" }] };
  const ctx = { cwd: PACKAGE_HOME, sessionManager: { getSessionId: () => "perf" } };
  const handler = handlers.get("tool_result");
  assert(handler, "Missing failed-tool hook");
  const result = handler(failure, ctx) as { content?: { text?: string }[] } | undefined;
  if (fix) assert.equal(result?.content?.at(-1)?.text, `\n${renderFix(fix)}`);
  bench(metrics, "failedToolResult.snapshot", () => handler(failure, ctx));
  return { name, count: notes.length, metrics };
}

/** Every sample starts Node: warmed in-process loops above cannot measure CLI startup. */
function startup(): Row {
  const target = join(scratch, "startup");
  mkdirSync(join(target, "notes"), { recursive: true });
  const emptyHosts = join(target, "empty-hosts");
  mkdirSync(emptyHosts);
  const env: NodeJS.ProcessEnv = { ...process.env, SECOND_BRAIN_HOME: target, PI_CODING_AGENT_DIR: emptyHosts, CLAUDE_CONFIG_DIR: emptyHosts };
  delete env.BRAIN_ARGV;
  const metrics: Record<string, number> = {};
  const cli = join(PACKAGE_HOME, "brain", "bin", "brain.mjs");
  const run = (args: string[], payload = ""): void => {
    const child = spawnSync(process.execPath, args, { env, cwd: target, input: payload, encoding: "utf8", windowsHide: true, timeout: 30_000 });
    assert.ifError(child.error);
    assert.equal(child.status, 0, child.stderr);
  };
  bench(metrics, "node", () => run(["-e", ""]));
  for (const [name, payload] of [
    ["hook.noop", {}],
    ["hook.success", { hook_event_name: "PostToolUse", session_id: "perf-success", cwd: target, tool_name: "Bash", tool_input: { command: "true" }, tool_response: { stdout: "", stderr: "", exit_code: 0 } }],
    ["hook.failure", { hook_event_name: "PostToolUseFailure", session_id: "perf-failure", cwd: target, tool_name: "Bash", tool_input: { command: "false" }, error: "perf unmatched failure" }],
  ] as const) bench(metrics, name, () => run([cli, "hook", "claude-code", "--home", target], JSON.stringify(payload)));
  for (const command of ["stats", "check"]) bench(metrics, command, () => run([cli, command, "--home", target]));
  return { name: "fresh-process", count: 0, metrics };
}

try {
  const report: Report = {
    at: new Date().toISOString(), runtime: `${process.release.name} ${process.version}`, cpu: cpus()[0]?.model ?? "unknown", samples,
    rows: [startup(), measure("real", home), ...[1000, 5000].map((count) => measure(`synthetic-${count}`, synthetic(count), count))],
  };
  writeAtomic(output, JSON.stringify(report, null, 2) + "\n");
  console.log(`Performance: ${report.runtime}; ${samples} measured samples after 5 warmups; milliseconds, estimated tokens (ceil(chars/4)).`);
  console.log(previous ? `Delta against ${previous.at} (absolute change).` : "No previous run; deltas unavailable.");
  for (const row of report.rows) {
    console.log(`${row.name}: ${row.count} notes`);
    const before = previous?.rows.find((value) => value.name === row.name);
    for (const [key, value] of Object.entries(row.metrics)) {
      const old = before?.metrics[key];
      const delta = old === undefined ? "" : ` (${value >= old ? "+" : ""}${(value - old).toFixed(3)})`;
      console.log(`  ${key}: ${Number(value.toFixed(3))}${delta}`);
    }
  }
  console.log("Saved local aggregate metrics to state/perf.json; removed temporary corpora.");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
