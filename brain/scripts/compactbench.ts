/**
 * Windows P2 proof: card on turn 1, agent-written state, real RPC compaction, goal/next recall.
 * Run from brain/: node scripts/compactbench.ts --reps 10 --conditions resume,ablate --thinking low
 * OMP >=18.4: stdin JSONL {type:"compact"}; wait for its response before the second prompt.
 * Each run has an isolated home and fixture. Local evidence stays under state/compactbench/;
 * only rows append to state/compactbench.jsonl. No real work/notes/config writes or git commands.
 */
import { spawn } from "node:child_process";
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
  model: { type: "string", default: "openai-codex/gpt-6-astra" },
  thinking: { type: "string", default: "low" },
  timeout: { type: "string", default: "300" },
  label: { type: "string", default: "" },
} });
const reps = Number(values.reps);
const timeout = Number(values.timeout) * 1000;
if (!Number.isInteger(reps) || reps < 1 || !Number.isFinite(timeout) || timeout <= 0) throw new Error("reps and timeout must be positive");
if (values.model !== "openai-codex/gpt-6-astra") throw new Error("This benchmark requires openai-codex/gpt-6-astra");
const conditions = values.conditions!.split(",");
if (!conditions.length || conditions.some(condition => condition !== "resume" && condition !== "ablate") || new Set(conditions).size !== conditions.length) throw new Error("conditions must be resume, ablate, or resume,ablate");
const at = new Date().toISOString();
const kept = join(HOME, "state", "compactbench", at.replace(/[:.]/g, "-"));
const scratch = mkdtempSync(join(tmpdir(), "compactbench-"));
mkdirSync(kept, { recursive: true });
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

async function runOne(rep: number, condition: string, goal: string, next: string): Promise<Row> {
  const id = `${rep}-${condition}`;
  const dir = join(kept, id);
  const home = join(scratch, `home-${id}`);
  const fixture = join(scratch, `fixture-${id}`);
  const sessions = join(dir, "sessions");
  for (const path of [home, fixture, sessions]) mkdirSync(path, { recursive: true });
  for (const name of ["notes", "kits", "projects.json"]) {
    if (existsSync(join(HOME, name))) cpSync(join(HOME, name), join(home, name), { recursive: true });
  }
  // A brand-new project is deliberately silent; seed prior knowledge to exercise its start card.
  createNote(home, { project: "compactbench", kind: "fact", text: "compactbench scripted memory fixture records a goal and next step with brain_state before compaction." });
  writeFileSync(join(fixture, "package.json"), JSON.stringify({ name: "compactbench", private: true }));
  const files = ["catalog.json", "shipping.json", "invoicing.json"];
  for (const [index, file] of files.entries()) {
    writeFileSync(join(fixture, file), JSON.stringify({ service: file.slice(0, -5), port: 4100 + index, retries: 2 + index, timeoutMs: 750 + index * 250, description: "Unrelated fixture configuration: inspect and report the service port, not part of the saved goal or next step." }, null, 2));
  }
  const contextPath = join(dir, "context.jsonl");
  const env = { ...process.env, SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "compactbench", BRAIN: "on", BRAIN_TOOLS: "on", BRAIN_EXPERIMENT: "", BRAIN_STOP_NUDGE: "off", COMPACTBENCH_CONTEXT: contextPath, COMPACTBENCH_ABLATE: condition === "ablate" ? "on" : "off" };
  const args = ["--mode", "rpc", "--no-ui", "--no-title", "--no-lsp", "--no-skills", "--no-rules", "--tools", "read",
    "--no-extensions", "-e", join(HOME, "brain", "src", "omp.ts"), "-e", observer,
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
  let compacted = false;
  let stateWritten = false;
  let answer = "";
  let inspection = "";
  let recallStart = Infinity;
  let compaction: Row | undefined;
  try {
    await command("prompt", { message: `First call brain_state once with exactly: Goal: ${goal}\nNext: ${next}\nThen do this separate configuration inspection: read catalog.json, shipping.json, and invoicing.json using the read tool, and report the three service ports. Do not change the saved goal or next step. Do not call other tools.` });
    inspection = events.filter(event => event.type === "message_end" && object(event.message).role === "assistant").map(event => textOf(object(event.message))).filter(Boolean).join("\n");
    const work = join(home, "work", "compactbench.md");
    stateWritten = existsSync(work) && contains(readFileSync(work, "utf8"), goal) && contains(readFileSync(work, "utf8"), next);
    compaction = await command("compact", { customInstructions: "Summarize this short scripted memory task concisely." });
    const after = await command("get_messages");
    compacted = objects(object(after.data).messages).some(message => message.role === "compactionSummary");
    recallStart = events.length;
    await command("prompt", { message: "What is the goal and the next step? Reply with Goal: and Next: on separate lines. Do not call tools." });
    answer = events.slice(recallStart).filter(event => event.type === "message_end" && object(event.message).role === "assistant").map(event => textOf(object(event.message))).filter(Boolean).join("\n");
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
  const bounded = resumeTokens.length > 0 && resumeTokens.every(tokens => typeof tokens === "number" && tokens > 0 && tokens <= 150);
  // Score the labelled fields, not merely the presence of both strings (swapped answers fail).
  const goalCorrect = new RegExp(`goal\\s*:\\s*[^\\n]*${goal}`, "i").test(answer.replace(/\*\*/g, ""));
  const nextCorrect = new RegExp(`next(?: step)?\\s*:\\s*[^\\n]*${next}`, "i").test(answer.replace(/\*\*/g, ""));
  const callsIn = (part: Row[]): Row[] => part.filter(event => event.type === "message_end" && object(event.message).role === "assistant").flatMap(event => objects(object(event.message).content)).filter(part => part.type === "toolCall");
  const toolCalls = callsIn(events.slice(0, recallStart));
  const recallToolCalls = callsIn(events.slice(recallStart)).length;
  const readPaths = toolCalls.filter(call => call.name === "read").map(call => String(object(call.arguments).path ?? "").replace(/\\/g, "/"));
  const filesRead = files.every(file => readPaths.some(path => path === file || path.endsWith("/" + file)));
  const removed = contexts.reduce((sum, context) => sum + (typeof context.removed === "number" ? context.removed : 0), 0);
  const deliveryCorrect = condition === "ablate" ? resumed.length === 0 && removed > 0 : resumeDelivered && removed === 0;
  const inspectionCorrect = [4100, 4101, 4102].every(port => inspection.includes(String(port)));
  const valid = !error && stateWritten && compacted && cardOnTurn1 && deliveryCorrect && bounded && filesRead && inspectionCorrect && recallToolCalls === 0;
  const ok = valid && goalCorrect && nextCorrect;
  const summary = String(object(compaction?.data).summary ?? "");
  for (const name of ["work", "state"]) if (existsSync(join(home, name))) cpSync(join(home, name), join(dir, "home", name), { recursive: true });
  const row = { at, label: values.label, version: 2, model: values.model, thinking: values.thinking, platform: process.platform, rep, condition, ok, valid, goal, next,
    stateWritten, filesRead, readPaths, inspectionCorrect, inspection, recallToolCalls, compacted, cardOnTurn1, resumeDelivered, resumeTokens, removed, deliveredTokens: condition === "ablate" ? [] : resumeTokens,
    goalCorrect, nextCorrect, answer, error, summaryHasGoal: contains(summary, goal), summaryHasNext: contains(summary, next),
    seconds: Math.round((Date.now() - started) / 1000), evidence: dir, compaction: compaction?.data };
  appendFileSync(join(HOME, "state", "compactbench.jsonl"), JSON.stringify(row) + "\n");
  console.log(`${ok ? "PASS" : valid ? "MISS" : "INVALID"} ${rep}/${reps} ${condition} card=${cardOnTurn1} state=${stateWritten} files=${filesRead} compact=${compacted} resume=${resumeDelivered} removed=${removed} tokens=${condition === "ablate" ? 0 : resumeTokens.join(",")} goal=${goalCorrect} next=${nextCorrect}${error ? ` error=${error}` : ""}`);
  return row;
}

const rows: Row[] = [];
try {
  for (let rep = 1; rep <= reps; rep++) {
    const goal = `goal-${randomBytes(6).toString("hex")}`;
    const next = `next-${randomBytes(6).toString("hex")}`;
    // Alternate order within pairs so neither condition always gets the earlier provider slot.
    for (const condition of rep % 2 ? conditions : [...conditions].reverse()) rows.push(await runOne(rep, condition, goal, next));
  }
} finally {
  try { rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }
  catch { console.log(`Temp cleanup deferred: ${scratch}`); }
}
for (const condition of conditions) {
  const selected = rows.filter(row => row.condition === condition);
  console.log(`compactbench ${condition}: ${selected.filter(row => row.ok).length}/${reps}; valid=${selected.filter(row => row.valid).length}/${reps}; evidence: ${kept}`);
}
process.exitCode = rows.every(row => row.valid && (row.condition === "ablate" || row.ok)) ? 0 : 1;
