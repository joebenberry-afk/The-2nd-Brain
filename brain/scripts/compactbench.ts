/**
 * Compaction recall proof: card, agent-written state, real RPC compactions, goal/next recall.
 * Short: node scripts/compactbench.ts --reps 10 --conditions resume,ablate --thinking low
 * V5: node scripts/compactbench.ts --scenario long --reps 10 --conditions resume,ablate --label v5-long
 * Scoring regression: node scripts/compactbench.ts --self-test (no model calls).
 * Long runs freeze the extension at HEAD; three crowded turns change A to B after compaction 1.
 * Local evidence stays under state/compactbench/; rows append to state/compactbench.jsonl.
 * Only isolated homes/fixtures are modified, never real work/notes/config or Git state.
 */
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { appendFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { parseArgs } from "node:util";
import { createNote } from "../src/notes.ts";

const HOME = resolve(import.meta.dirname, "../..");
const { values } = parseArgs({ options: {
  reps: { type: "string", default: "10" },
  conditions: { type: "string", default: "resume" },
  scenario: { type: "string", default: "short" },
  "self-test": { type: "boolean", default: false },
  model: { type: "string", default: "openai-codex/gpt-6-astra" },
  thinking: { type: "string", default: "low" },
  timeout: { type: "string", default: "300" },
  label: { type: "string", default: "" },
} });
function scoreAnswer(answer: string, goal: string, next: string, oldGoal = "", oldNext = "") {
  const clean = answer.replace(/\*\*/g, "");
  const staleAnswered = Boolean(oldGoal && clean.toLowerCase().includes(oldGoal.toLowerCase()) || oldNext && clean.toLowerCase().includes(oldNext.toLowerCase()));
  return {
    goalCorrect: !staleAnswered && new RegExp(`goal\\s*:\\s*[^\\n]*${goal}`, "i").test(clean),
    nextCorrect: !staleAnswered && new RegExp(`next(?: step)?\\s*:\\s*[^\\n]*${next}`, "i").test(clean),
    staleAnswered,
  };
}
function filesWereRead(files: string[], paths: string[]): boolean {
  const normalized = paths.map(path => path.replace(/:(?:raw(?::\d+(?:-\d+)?)?|\d+(?:-\d+)?)$/, ""));
  return files.every(file => normalized.some(path => path === file || path.endsWith("/" + file)));
}
if (values["self-test"]) {
  const score = (answer: string) => scoreAnswer(answer, "goal-b", "next-b", "goal-a", "next-a");
  assert.deepEqual(score("Goal: goal-b\nNext: next-b"), { goalCorrect: true, nextCorrect: true, staleAnswered: false });
  assert.deepEqual(score("Goal: goal-a\nNext: next-a"), { goalCorrect: false, nextCorrect: false, staleAnswered: true });
  assert.deepEqual(score("Goal: next-b\nNext: goal-b"), { goalCorrect: false, nextCorrect: false, staleAnswered: false });
  assert.deepEqual(score("Goal: goal-a or goal-b\nNext: next-a or next-b"), { goalCorrect: false, nextCorrect: false, staleAnswered: true });
  assert.equal(filesWereRead(["catalog.json", "shipping.json", "invoicing.json"], ["catalog.json:22-119", "C:/fixture/shipping.json:raw", "invoicing.json:raw:1-120"]), true);
  assert.equal(filesWereRead(["catalog.json", "shipping.json"], ["catalog.json:raw"]), false);
  console.log("PASS compactbench scoring: current, stale, swapped, ambiguous; read selectors");
  process.exit(0);
}
const reps = Number(values.reps);
const timeout = Number(values.timeout) * 1000;
if (values.scenario !== "short" && values.scenario !== "long") throw new Error("scenario must be short or long");
const long = values.scenario === "long";
if (!Number.isInteger(reps) || reps < 1 || !Number.isFinite(timeout) || timeout <= 0) throw new Error("reps and timeout must be positive");
if (values.model !== "openai-codex/gpt-6-astra") throw new Error("This benchmark requires openai-codex/gpt-6-astra");
const conditions = values.conditions!.split(",");
if (!conditions.length || conditions.some(condition => condition !== "resume" && condition !== "ablate") || new Set(conditions).size !== conditions.length) throw new Error("conditions must be resume, ablate, or resume,ablate");
const at = new Date().toISOString();
const kept = join(HOME, "state", "compactbench", at.replace(/[:.]/g, "-"));
const scratch = mkdtempSync(join(tmpdir(), "compactbench-"));
mkdirSync(kept, { recursive: true });
let extension = join(HOME, "brain", "src", "omp.ts");
let revision = "working-tree";
if (long) {
  revision = execFileSync("git", ["rev-parse", "HEAD"], { cwd: HOME, encoding: "utf8" }).trim();
  const archive = join(scratch, "head.tar");
  execFileSync("git", ["archive", "--format=tar", "-o", archive, revision, "brain/src"], { cwd: HOME });
  execFileSync("tar", ["-xf", "head.tar"], { cwd: scratch });
  extension = join(scratch, "brain", "src", "omp.ts");
}
const overlay = join(scratch, "config.yml");
// Small transcripts still compact; use a GPT summary rather than provider-native or image compaction.
writeFileSync(overlay, "compaction:\n  enabled: false\n  keepRecentTokens: 0\n  methodOrder: [soft]\n");
const observer = join(scratch, "observe.ts");
// Runs after Brain: record precisely what the model receives; ablation removes only resume cards.
writeFileSync(observer, `import { appendFileSync } from "node:fs";
type Message = { role?: string; customType?: string; details?: { resume?: boolean } };
export default function(pi: { on(name: string, handler: (event: { messages: Message[] }) => unknown): void }) {
  pi.on("context", (event) => {
    const compacted = event.messages.some(message => message.role === "compactionSummary");
    const messages = process.env.COMPACTBENCH_ABLATE === "on" && compacted
      ? event.messages.filter(message => !(message.customType === "brain.card" && message.details?.resume))
      : event.messages;
    appendFileSync(process.env.COMPACTBENCH_CONTEXT!, JSON.stringify({ messages, removed: event.messages.length - messages.length }) + "\\n");
    return { messages };
  });
}
`);

type Row = Record<string, unknown>;
const object = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const objects = (value: unknown): Row[] => Array.isArray(value) ? value.map(object) : [];
const jsonl = (path: string): Row[] => existsSync(path)
  ? readFileSync(path, "utf8").split("\n").filter(Boolean).map(line => object(JSON.parse(line))) : [];
const textOf = (message: Row): string => typeof message.content === "string" ? message.content
  : objects(message.content).filter(part => part.type === "text").map(part => typeof part.text === "string" ? part.text : "").join("\n");
const contains = (text: string, token: string): boolean => text.toLowerCase().includes(token.toLowerCase());

async function runOne(rep: number, condition: string, goal: string, next: string, oldGoal = "", oldNext = ""): Promise<Row> {
  const id = `${rep}-${condition}`;
  const dir = join(kept, id);
  const home = join(scratch, `home-${id}`);
  const fixture = join(scratch, `fixture-${id}`);
  const sessions = join(dir, "sessions");
  for (const path of [home, fixture, sessions]) mkdirSync(path, { recursive: true });
  for (const name of ["notes", "projects.json"]) {
    if (existsSync(join(HOME, name))) cpSync(join(HOME, name), join(home, name), { recursive: true });
  }
  // A brand-new project is deliberately silent; seed prior knowledge to exercise its start card.
  createNote(home, { project: "compactbench", kind: "fact", text: "compactbench scripted memory fixture records a goal and next step with brain_state before compaction." });
  writeFileSync(join(fixture, "package.json"), JSON.stringify({ name: "compactbench", private: true }));
  const files = ["catalog.json", "shipping.json", "invoicing.json", ...(long ? ["search.json", "warehouse.json", "notifications.json"] : [])];
  for (const [index, file] of files.entries()) {
    writeFileSync(join(fixture, file), JSON.stringify({ service: file.slice(0, -5), port: 4100 + index, retries: 2 + index, timeoutMs: 750 + index * 250, description: "Unrelated fixture configuration: inspect and report the service port, not part of the saved goal or next step.",
      ...(long ? { routes: Array.from({ length: 16 }, (_, route) => ({ path: `/api/${file.slice(0, -5)}/resource-${route}`, method: route % 2 ? "POST" : "GET", timeoutMs: 200 + route * 75, owner: `team-${index}-${route % 4}`, cacheSeconds: route * 10 })) } : {}),
    }, null, 2));
  }
  const contextPath = join(dir, "context.jsonl");
  const env = { ...process.env, SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "compactbench", BRAIN: "on", BRAIN_TOOLS: "on", BRAIN_EXPERIMENT: "", COMPACTBENCH_CONTEXT: contextPath, COMPACTBENCH_ABLATE: condition === "ablate" ? "on" : "off" };
  const args = ["--mode", "rpc", "--no-ui", "--no-title", "--no-lsp", "--no-skills", "--no-rules", "--tools", long ? "read,edit" : "read",
    "--no-extensions", "-e", extension, "-e", observer,
    "--config", overlay, "--model", values.model!, "--smol", values.model!, "--slow", values.model!,
    "--thinking", values.thinking!, "--cwd", fixture, "--session-dir", sessions,
    "--system-prompt", "Follow the user's scripted memory task. Use brain_state when requested. Be concise. Do not perform unrelated work."];
  const child = spawn("omp", args, { cwd: fixture, env, stdio: ["pipe", "pipe", "pipe"] });
  const started = Date.now();
  const events: Row[] = [];
  let sequence = 0;
  let fatal: Error | undefined;
  let pending: { id: string; prompt: boolean; resolve: (row: Row) => void; reject: (error: Error) => void } | undefined;
  const fail = (error: Error): void => { fatal = error; pending?.reject(error); pending = undefined; };
  const closed = Promise.withResolvers<number | null>();
  child.on("close", code => {
    if (pending) fail(new Error(`OMP exited ${code}`));
    closed.resolve(code);
  });
  child.on("error", fail);
  child.stdin.on("error", fail);
  child.stderr.on("data", data => appendFileSync(join(dir, "stderr.log"), data));
  const lines = createInterface({ input: child.stdout });
  lines.on("line", line => {
    appendFileSync(join(dir, "rpc.jsonl"), line + "\n");
    let event: Row;
    try { event = object(JSON.parse(line)); } catch { return; }
    events.push(event);
    if (!pending || event.id !== pending.id) return;
    if (event.type === "response" && event.success === false) return fail(new Error(String(event.error)));
    if (pending.prompt ? event.type !== "prompt_result" : event.type !== "response") return;
    const current = pending;
    pending = undefined;
    if (current.prompt && event.status !== "completed") current.reject(new Error(JSON.stringify(event)));
    else current.resolve(event);
  });
  const timer = setTimeout(() => { fail(new Error(`Run exceeded ${timeout / 1000}s`)); child.kill(); }, timeout);
  const command = (type: string, fields: Row = {}): Promise<Row> => {
    if (fatal) return Promise.reject(fatal);
    const response = Promise.withResolvers<Row>();
    const id = String(++sequence);
    pending = { id, prompt: type === "prompt", resolve: response.resolve, reject: response.reject };
    child.stdin.write(JSON.stringify({ id, type, ...fields }) + "\n");
    return response.promise;
  };
  let error = "";
  let answer = "";
  let recallStart = Infinity;
  const turns: Row[] = [];
  const compactions: Row[] = [];
  const deliveries: boolean[] = [];
  const callsIn = (part: Row[]): Row[] => part.filter(event => event.type === "message_end" && object(event.message).role === "assistant").flatMap(event => objects(object(event.message).content)).filter(part => part.type === "toolCall");
  const assistantText = (part: Row[]): string => part.filter(event => event.type === "message_end" && object(event.message).role === "assistant").map(event => textOf(object(event.message))).filter(Boolean).join("\n");
  const prompt = async (message: string, expectedGoal = "", expectedNext = ""): Promise<void> => {
    const start = jsonl(contextPath).length;
    await command("prompt", { message });
    if (!expectedGoal) return;
    const context = jsonl(contextPath)[start];
    const cards = objects(context?.messages).filter(message => message.customType === "brain.card" && object(message.details).resume);
    deliveries.push(condition === "ablate" ? cards.length === 0 && Number(context?.removed) > 0
      : cards.some(card => contains(textOf(card), expectedGoal) && contains(textOf(card), expectedNext)) && context?.removed === 0);
  };
  try {
    const work = join(home, "work", "compactbench.md");
    for (let turn = 1; turn <= (long ? 3 : 1); turn++) {
      const currentGoal = long && turn === 1 ? oldGoal : goal;
      const currentNext = long && turn === 1 ? oldNext : next;
      const save = `Call brain_state once with exactly: Goal: ${currentGoal}\nNext: ${currentNext}\n`;
      const inspect = `Read every one of these files with the read tool: ${files.join(", ")}. Report each service's port, retry count, timeout, and (if present) its highest route timeout and all route owners. `;
      const edit = turn > 1 ? `Use the edit tool to change only the top-level retries in ${turn === 2 ? "shipping.json from 3 to 4" : "catalog.json from 2 to 3"}. ` : "";
      const message = turn === 1 ? save + inspect + "Do not change the saved goal or next step. Do not call other tools."
        : turn === 2 ? inspect + edit + "The project goal now CHANGES; replace the previous goal and next step. " + save + "Do not call other tools."
        : inspect + edit + "The saved goal and next step are unchanged. Do not call brain_state or other tools.";
      const start = events.length;
      await prompt(message, turn === 1 ? "" : turn === 2 ? oldGoal : goal, turn === 2 ? oldNext : next);
      const calls = callsIn(events.slice(start));
      const readPaths = calls.filter(call => call.name === "read").map(call => String(object(call.arguments).path ?? "").replace(/\\/g, "/"));
      const inspection = assistantText(events.slice(start));
      const saved = existsSync(work) ? readFileSync(work, "utf8") : "";
      const editedFile = turn === 2 ? "shipping.json" : "catalog.json";
      const fixtureEdited = turn === 1 || calls.some(call => call.name === "edit") && object(JSON.parse(readFileSync(join(fixture, editedFile), "utf8"))).retries === (turn === 2 ? 4 : 3);
      turns.push({ turn, stateWritten: contains(saved, currentGoal) && contains(saved, currentNext) && (turn === 1 || !contains(saved, oldGoal) && !contains(saved, oldNext)),
        stateCalls: calls.filter(call => call.name === "brain_state").length, fixtureEdited,
        filesRead: filesWereRead(files, readPaths), readPaths, inspection,
        inspectionCorrect: files.every((_, index) => inspection.includes(String(4100 + index))) });
      const compaction = await command("compact", { customInstructions: long ? "Summarize this session concisely for continued work." : "Summarize this short scripted memory task concisely." });
      const after = await command("get_messages");
      const summary = String(object(compaction.data).summary ?? "");
      compactions.push({ turn, compacted: objects(object(after.data).messages).some(message => message.role === "compactionSummary"),
        summaryHasGoal: contains(summary, goal), summaryHasNext: contains(summary, next), summaryContainsB: contains(summary, goal) && contains(summary, next), data: compaction.data });
    }
    recallStart = events.length;
    await prompt("What is the current goal and the next step? Reply with Goal: and Next: on separate lines. Do not call tools.", goal, next);
    answer = assistantText(events.slice(recallStart));
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
  } finally {
    child.stdin.end();
    const shutdown = setTimeout(() => child.kill(), 10000);
    await closed.promise;
    clearTimeout(shutdown);
    clearTimeout(timer);
    lines.close();
  }
  const contexts = jsonl(contextPath);
  const firstMessages = objects(contexts[0]?.messages);
  const cardOnTurn1 = firstMessages.some(message => message.customType === "brain.card" && !object(message.details).resume);
  const resumed = contexts.flatMap(context => {
    const messages = objects(context.messages);
    const lastSummary = messages.findLastIndex(message => message.role === "compactionSummary");
    return lastSummary < 0 ? [] : messages.slice(lastSummary + 1).filter(message => message.customType === "brain.card" && object(message.details).resume);
  });
  const resumeDelivered = resumed.some(message => contains(textOf(message), goal) && contains(textOf(message), next));
  const telemetry = jsonl(join(home, "state", "telemetry.jsonl"));
  const resumeRows = telemetry.filter(row => row.kind === "resume");
  const resumeTokens = resumeRows.map(row => row.tokens);
  const bounded = resumeTokens.length === (long ? 3 : 1) && resumeTokens.every(tokens => typeof tokens === "number" && tokens > 0 && tokens <= 150);
  const { goalCorrect, nextCorrect, staleAnswered } = scoreAnswer(answer, goal, next, oldGoal, oldNext);
  const recallToolCalls = callsIn(events.slice(recallStart)).length;
  const stateWritten = turns.length === (long ? 3 : 1) && turns.every(turn => turn.stateWritten && turn.stateCalls === (turn.turn === 3 ? 0 : 1));
  const compacted = compactions.length === (long ? 3 : 1) && compactions.every(row => row.compacted);
  const filesRead = turns.every(turn => turn.filesRead);
  const readPaths = turns.flatMap(turn => turn.readPaths);
  const inspection = turns.map(turn => turn.inspection).join("\n");
  const removed = contexts.reduce((sum, context) => sum + (typeof context.removed === "number" ? context.removed : 0), 0);
  const deliveryCorrect = deliveries.length === (long ? 3 : 1) && deliveries.every(Boolean) && (condition === "ablate" ? resumed.length === 0 && removed > 0 : resumeDelivered && removed === 0);
  const inspectionCorrect = turns.every(turn => turn.inspectionCorrect);
  const fixtureEdited = turns.every(turn => turn.fixtureEdited);
  const valid = !error && stateWritten && compacted && cardOnTurn1 && deliveryCorrect && bounded && filesRead && inspectionCorrect && fixtureEdited && recallToolCalls === 0;
  const ok = valid && goalCorrect && nextCorrect;
  const finalSummary = compactions.at(-1);
  for (const name of ["work", "state"]) if (existsSync(join(home, name))) cpSync(join(home, name), join(dir, "home", name), { recursive: true });
  cpSync(fixture, join(dir, "fixture"), { recursive: true });
  const row = { at, label: values.label, version: 3, scenario: values.scenario, revision, model: values.model, thinking: values.thinking, platform: process.platform, rep, condition, ok, valid, goal, next, oldGoal, oldNext,
    stateWritten, filesRead, readPaths, inspectionCorrect, inspection, fixtureEdited, turns, deliveries, recallToolCalls, compacted, cardOnTurn1, resumeDelivered, resumeTokens, removed, deliveredTokens: condition === "ablate" ? [] : resumeTokens,
    goalCorrect, nextCorrect, staleAnswered, answer, error, summaryHasGoal: finalSummary?.summaryHasGoal ?? false, summaryHasNext: finalSummary?.summaryHasNext ?? false, finalSummaryContainedB: finalSummary?.summaryContainsB ?? false,
    seconds: Math.round((Date.now() - started) / 1000), evidence: dir, compactions, compaction: finalSummary?.data };
  appendFileSync(join(HOME, "state", "compactbench.jsonl"), JSON.stringify(row) + "\n");
  console.log(`${ok ? "PASS" : valid ? "MISS" : "INVALID"} ${rep}/${reps} ${condition} card=${cardOnTurn1} state=${stateWritten} files=${filesRead} compact=${compacted} resume=${resumeDelivered} removed=${removed} tokens=${condition === "ablate" ? 0 : resumeTokens.join(",")} goal=${goalCorrect} next=${nextCorrect}${error ? ` error=${error}` : ""}`);
  return row;
}

const rows: Row[] = [];
try {
  for (let rep = 1; rep <= reps; rep++) {
    const goal = `goal-${long ? "b-" : ""}${randomBytes(6).toString("hex")}`;
    const next = `next-${long ? "b-" : ""}${randomBytes(6).toString("hex")}`;
    const oldGoal = long ? `goal-a-${randomBytes(6).toString("hex")}` : "";
    const oldNext = long ? `next-a-${randomBytes(6).toString("hex")}` : "";
    // Alternate order within pairs so neither condition always gets the earlier provider slot.
    for (const condition of rep % 2 ? conditions : [...conditions].reverse()) rows.push(await runOne(rep, condition, goal, next, oldGoal, oldNext));
  }
} finally {
  try { rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }
  catch { console.log(`Temp cleanup deferred: ${scratch}`); }
}
for (const condition of conditions) {
  const selected = rows.filter(row => row.condition === condition);
  console.log(`compactbench ${condition}: ${selected.filter(row => row.ok).length}/${reps}; valid=${selected.filter(row => row.valid).length}/${reps}; evidence: ${kept}`);
}
if (long) {
  console.log("condition | goal B correct | next B correct | stale A answered | final summary contained B | resume tokens delivered/generated (total)");
  for (const condition of conditions) {
    const selected = rows.filter(row => row.condition === condition && row.valid);
    const count = (key: string) => selected.filter(row => row[key]).length;
    const tokens = (key: string) => selected.flatMap(row => row[key] as number[]).reduce((sum, n) => sum + n, 0);
    console.log(`${condition} | ${count("goalCorrect")}/${reps} | ${count("nextCorrect")}/${reps} | ${count("staleAnswered")}/${reps} | ${count("finalSummaryContainedB")}/${reps} | ${tokens("deliveredTokens")}/${tokens("resumeTokens")}`);
  }
  const controlled = reps >= 10 && conditions.includes("resume") && conditions.includes("ablate") && rows.every(row => row.valid);
  const perfect = rows.every(row => row.goalCorrect && row.nextCorrect && !row.staleAnswered);
  console.log(!controlled ? "V5 §3.5: inconclusive; requires valid 10+10 same-batch controls."
    : perfect ? "V5 §3.5: no observed recall benefit from resume; trim/remove post-compaction resume in P4, keep the start card."
    : "V5 §3.5: recall differs or misses occurred; inspect paired evidence before a trim decision.");
}
process.exitCode = rows.every(row => row.valid && (row.condition === "ablate" || row.ok)) ? 0 : 1;
