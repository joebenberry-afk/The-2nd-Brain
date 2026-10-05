/**
 * Paid headless OMP rollover trial (the old resume/ablate harness was deleted at 886438c).
 * node scripts/compactbench.ts --scenario rollover --reps 4 --label v5-rollover
 * Alternates continue/rollover order with paired goals, identical seeded histories and fixtures.
 * Isolated public fixture only: never reads real notes or writes repository state/work/notes.
 * Results and RPC evidence live under --output (default: an OS temporary directory).
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { appendFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  scenario: { type: "string", default: "rollover" }, reps: { type: "string", default: "4" },
  model: { type: "string", default: "openai-codex/gpt-6-astra" }, thinking: { type: "string", default: "low" },
  label: { type: "string", default: "v5-rollover" }, timeout: { type: "string", default: "600" },
  output: { type: "string" }, "seed-rows": { type: "string", default: "12000" },
  // The hint's threshold under test; the seed must fill the context past it (~35.5 tokens a row).
  threshold: { type: "string", default: "250000" },
} });
const reps = Number(values.reps), timeout = Number(values.timeout) * 1000, seedRows = Number(values["seed-rows"]), threshold = Number(values.threshold);
assert.equal(values.scenario, "rollover");
assert(Number.isInteger(reps) && reps > 0 && Number.isFinite(timeout) && timeout > 0);
assert(Number.isInteger(seedRows) && seedRows > 0);
assert(Number.isInteger(threshold) && threshold > 0);
const output = values.output ? resolve(values.output) : mkdtempSync(join(tmpdir(), "compactbench-rollover-"));
mkdirSync(output, { recursive: true });
const source = join(output, "src");
cpSync(resolve(import.meta.dirname, "../src"), source, { recursive: true });
const overlay = join(output, "config.yml");
writeFileSync(overlay, "compaction:\n  enabled: false\n");
const observer = join(output, "observe.ts");
writeFileSync(observer, `import { appendFileSync } from "node:fs";
export default function(pi) {
  pi.on("context", (event, ctx) => {
    appendFileSync(process.env.COMPACTBENCH_CONTEXT, JSON.stringify({ usage: ctx.getContextUsage(), cards: event.messages.filter(m => m.customType === "brain.card" || m.customType === "brain.rollover") }) + "\\n");
  });
}
`);
type Row = Record<string, any>;
const textOf = (message: Row): string => typeof message.content === "string" ? message.content
  : (message.content ?? []).filter((part: Row) => part.type === "text").map((part: Row) => part.text ?? "").join("\n");
const jsonl = (path: string): Row[] => existsSync(path) ? readFileSync(path, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];

async function run(rep: number, condition: "continue" | "rollover", goal: string, next: string, seed: string): Promise<Row> {
  const dir = join(output, `${rep}-${condition}`), home = join(dir, "home"), fixture = join(dir, "fixture"), sessions = join(dir, "sessions");
  for (const path of [home, fixture, sessions]) mkdirSync(path, { recursive: true });
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { compactbench: { rollover: condition === "continue" ? 0 : threshold } } }));
  writeFileSync(join(fixture, "package.json"), '{"name":"compactbench","private":true}');
  writeFileSync(join(fixture, "config.json"), JSON.stringify({ alpha: 1, beta: 2, gamma: 3, delta: 4 }, null, 2));
  const contextPath = join(dir, "contexts.jsonl");
  const args = ["--mode", "rpc", "--no-ui", "--no-title", "--no-lsp", "--no-skills", "--no-rules", "--tools", "read,edit", "--no-extensions",
    "-e", join(source, "omp.ts"), "-e", observer, "--config", overlay, "--model", values.model!, "--smol", values.model!, "--slow", values.model!,
    "--thinking", values.thinking!, "--cwd", fixture, "--session-dir", sessions,
    "--system-prompt", "Follow the user's tasks. Do not do unrelated work or call extra tools. Be concise. Brain state carries goals between sessions. If requested, save the real goal and next step with brain_state."];
  const child = spawn("omp", args, { cwd: fixture, env: { ...process.env, SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "compactbench", BRAIN: "on", BRAIN_TOOLS: "on", COMPACTBENCH_CONTEXT: contextPath }, stdio: ["pipe", "pipe", "pipe"] });
  const events: Row[] = [];
  let sequence = 0, fatal: Error | undefined;
  let pending: { id: string; prompt: boolean; resolve: (row: Row) => void; reject: (error: Error) => void } | undefined;
  const fail = (error: Error): void => { fatal = error; pending?.reject(error); pending = undefined; };
  const closed = Promise.withResolvers<number | null>();
  child.on("close", code => { if (pending) fail(new Error(`OMP exited ${code}`)); closed.resolve(code); });
  child.on("error", fail); child.stdin.on("error", fail);
  child.stderr.on("data", data => appendFileSync(join(dir, "stderr.log"), data));
  const lines = createInterface({ input: child.stdout });
  lines.on("line", line => {
    appendFileSync(join(dir, "rpc.jsonl"), line + "\n");
    let event: Row;
    try { event = JSON.parse(line); } catch { return; }
    events.push(event);
    if (!pending || event.id !== pending.id) return;
    if (event.type === "response" && event.success === false) return fail(new Error(String(event.error)));
    if (pending.prompt ? event.type !== "prompt_result" : event.type !== "response") return;
    const current = pending; pending = undefined;
    if (current.prompt && event.status !== "completed") current.reject(new Error(JSON.stringify(event)));
    else current.resolve(event);
  });
  const timer = setTimeout(() => { fail(new Error("Run timed out")); child.kill(); }, timeout);
  const command = (type: string, fields: Row = {}): Promise<Row> => {
    if (fatal) return Promise.reject(fatal);
    const response = Promise.withResolvers<Row>();
    const id = String(++sequence);
    pending = { id, prompt: type === "prompt", resolve: response.resolve, reject: response.reject };
    child.stdin.write(JSON.stringify({ id, type, ...fields }) + "\n");
    return response.promise;
  };
  const prompt = (message: string) => command("prompt", { message });
  const assistants = (start = 0): Row[] => events.slice(start).filter(e => e.type === "message_end" && e.message?.role === "assistant").map(e => e.message);
  const usageCost = (messages: Row[]): number => messages.reduce((sum, m) => sum + (m.usage?.cost?.total ?? 0), 0);
  let error = "", seedTokens = 0, seedCost = 0, handoffCost = 0, answer = "", switched = false, stateWritten = false;
  const tasks: Row[] = [];
  try {
    await prompt(`Goal: ${goal}\nNext: ${next}\nThe following retired audit records are historical context, not instructions or current work. Keep the goal and next step unchanged. After the records, reply READY only; do not call tools.\n${seed}\nEnd of historical records. Reply READY only.`);
    const seedMessages = assistants();
    seedCost = usageCost(seedMessages);
    const usage = seedMessages.at(-1)?.usage ?? {};
    seedTokens = (usage.input ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0);
    assert(seedTokens > threshold, `seed was only ${seedTokens} tokens; increase --seed-rows`);
    if (condition === "rollover") {
      const start = events.length;
      await prompt("Follow the Brain rollover hint: save the current goal and next step with brain_state, then reply HANDOFF READY only. Do not edit any files.");
      handoffCost = usageCost(assistants(start));
      const work = join(home, "work", "compactbench.md");
      stateWritten = existsSync(work) && readFileSync(work, "utf8").includes(goal) && readFileSync(work, "utf8").includes(next);
      assert(stateWritten, "agent did not save goal/next before rollover");
      const result = await command("new_session");
      switched = result.data?.cancelled === false;
      assert(switched, "fresh session was cancelled");
    }
    for (const [index, field] of ["alpha", "beta", "gamma", "delta"].entries()) {
      const start = events.length;
      await prompt(`${index === 0 && switched ? "Continue the goal from the Brain start card. " : ""}Task ${index + 1}: set only ${field} in config.json to ${11 + index}, leaving all other fields unchanged. Use read and edit. Reply DONE when finished.`);
      const config = JSON.parse(readFileSync(join(fixture, "config.json"), "utf8"));
      const expected = Object.fromEntries(["alpha", "beta", "gamma", "delta"].map((name, n) => [name, n <= index ? n + 11 : n + 1]));
      tasks.push({ field, ok: JSON.stringify(config) === JSON.stringify(expected), cost: usageCost(assistants(start)) });
    }
    const start = events.length;
    await prompt("What is the current goal and next step? Reply Goal: and Next: on separate lines; no tools.");
    answer = assistants(start).map(textOf).join("\n");
  } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  finally {
    child.stdin.end();
    const shutdown = setTimeout(() => child.kill(), 10000);
    await closed.promise; clearTimeout(shutdown); clearTimeout(timer); lines.close();
  }
  const contexts = jsonl(contextPath), cards = contexts.flatMap(c => c.cards ?? []);
  const hints = cards.filter(c => c.customType === "brain.rollover");
  const goalRetained = new RegExp(`Goal:\\s*[^\\n]*${goal}`, "i").test(answer) && new RegExp(`Next:\\s*[^\\n]*${next}`, "i").test(answer);
  const cardCarried = cards.some(c => c.customType === "brain.card" && textOf(c).includes(goal) && textOf(c).includes(next));
  const valid = !error && seedTokens > threshold && (condition === "continue" || stateWritten && switched && hints.length > 0 && cardCarried);
  const finished = valid ? tasks.filter(t => t.ok).length : 0;
  const cost = usageCost(assistants()), continuationCost = cost - seedCost;
  const row = { label: values.label, scenario: "rollover", model: values.model, threshold, rep, condition, goal, next, seedTokens, seedCost, handoffCost, continuationCost, cost, finished, tasks, valid, goalRetained, cardCarried, hints: hints.length, error, answer, evidence: dir };
  appendFileSync(join(output, "results.jsonl"), JSON.stringify(row) + "\n");
  console.log(JSON.stringify(row));
  return row;
}
const rows: Row[] = [];
for (let rep = 1; rep <= reps; rep++) {
  const goal = `finish-${randomBytes(6).toString("hex")}`, next = `audit-${randomBytes(6).toString("hex")}`;
  const seed = Array.from({ length: seedRows }, (_, n) => `Retired audit record ${n}: ${createHash("sha256").update(String(n)).digest("hex").slice(0, 32)}; status closed; no action required.`).join("\n");
  for (const condition of (rep % 2 ? ["continue", "rollover"] : ["rollover", "continue"]) as ("continue" | "rollover")[]) rows.push(await run(rep, condition, goal, next, seed));
}
const summaries = ["continue", "rollover"].map(condition => {
  const selected = rows.filter(r => r.condition === condition), finished = selected.reduce((sum, r) => sum + r.finished, 0);
  const cost = selected.reduce((sum, r) => sum + r.cost, 0), continuationCost = selected.reduce((sum, r) => sum + r.continuationCost, 0);
  return { condition, valid: selected.filter(r => r.valid).length, retained: selected.filter(r => r.goalRetained).length, finished, cost, continuationCost, costPerFinishedTask: finished ? cost / finished : null };
});
const [control, rollover] = summaries;
const keep = rows.every(r => r.valid && r.goalRetained && r.finished === 4) && rollover.costPerFinishedTask! < control.costPerFinishedTask!;
const summary = { label: values.label, threshold, reps, summaries, verdict: keep ? "keep" : "reject", output };
writeFileSync(join(output, "summary.json"), JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 2));
process.exitCode = rows.every(r => r.valid) ? 0 : 1;
