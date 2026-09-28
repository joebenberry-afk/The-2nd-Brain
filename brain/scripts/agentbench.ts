/**
 * Agent benchmark: the same small coding tasks run by headless OMP agents with the Brain off, on,
 * or on with experiments (BRAIN_EXPERIMENT), scored from the agents' own session files.
 *
 *   node scripts/agentbench.ts [--conditions off,on] [--tasks rename,fix,find] [--reps 2]
 *                              [--concurrency 4] [--model openai-codex/gpt-6-astra] [--label text]
 *
 * A condition is `off`, `on`, or `on+<experiment>[+<experiment>]`; a `@<preset>` part adds an OMP
 * settings overlay (PI_CONFIG_FILES) from SETTINGS below, with or without the Brain (`off+@x`). Each run gets a fresh copy of a
 * small fixture project; each condition gets its own copy of the Brain home (notes, kits,
 * projects, telemetry), so conditions never see each other's sessions. Results append to
 * state/agentbench.jsonl; the summary compares every condition with its best earlier run on the
 * same task set. Costs real model usage: meant for GPT models, run deliberately.
 */
import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync, appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { execFileSync } from "node:child_process";

const PACKAGE = resolve(import.meta.dirname, "..");
/** Bump when the fixture or tasks change: results are only compared within one version. */
const FIXTURE_VERSION = 2;

/** Host settings overlays under test (keys and units: pi-coding-agent src/tools/settings.ts). */
const SETTINGS: Record<string, string> = {
  readlimit: "read:\n  defaultLimit: 150\n",
  grepctx: "grep:\n  contextBefore: 0\n  contextAfter: 1\n",
  spill: "tools:\n  artifactSpillThreshold: 10\n  artifactHeadBytes: 2\n  artifactTailBytes: 3\n  artifactTailLines: 100\n",
};
const HOME = resolve(PACKAGE, "..");
const RESULTS = join(HOME, "state", "agentbench.jsonl");

const { values } = parseArgs({
  options: {
    conditions: { type: "string", default: "off,on" },
    tasks: { type: "string", default: "rename,fix,find" },
    reps: { type: "string", default: "2" },
    concurrency: { type: "string", default: "4" },
    model: { type: "string", default: "openai-codex/gpt-6-astra" },
    thinking: { type: "string", default: "low" },
    label: { type: "string", default: "" },
    timeout: { type: "string", default: "420" },
  },
});

// ---------------------------------------------------------------- fixture project and tasks

const filler = (name: string, n: number): string =>
  Array.from({ length: n }, (_, i) => `/** Formats row ${i} of the ${name} table for display. */\nexport function ${name}Row${i}(value: number): string {\n  return \`${name}-${i}: \${value.toFixed(2)}\`;\n}\n`).join("\n");

const FIXTURE: Record<string, string> = {
  "package.json": JSON.stringify({ name: "benchapp", type: "module", private: true, scripts: { test: "node --test test/cart.test.ts" } }, null, 2) + "\n",
  "src/math.ts": "/** Adds two amounts in cents. */\nexport function add(a: number, b: number): number {\n  return a + b;\n}\n\nexport function clamp(x: number, lo: number, hi: number): number {\n  return Math.min(hi, Math.max(lo, x));\n}\n",
  "src/cart.ts": 'import { add, clamp } from "./math.ts";\n\nexport interface Item {\n  cents: number;\n  qty: number;\n}\n\nexport function total(items: Item[]): number {\n  return items.reduce((sum, item) => add(sum, item.cents * item.qty), 0);\n}\n\n/** Percent discount, 0-100. */\nexport function applyDiscount(cents: number, percent: number): number {\n  const p = clamp(percent, 0, 100);\n  return Math.round(cents - (cents * p) / 10);\n}\n',
  "src/config.ts": "/** Network settings. */\nexport const RETRY_LIMIT = 4;\nexport const TIMEOUT_MS = 2500;\nexport const REGION = \"eu-west\";\n",
  "src/report.ts": 'import { add } from "./math.ts";\n\nexport function grandTotal(a: number, b: number): number {\n  return add(a, b);\n}\n\n' + filler("report", 120),
  "src/legacy.ts": "// Old settings kept for the migration script; not used by the app.\nexport const OLD_RETRY_LIMIT = 9;\n\n" + filler("legacy", 90),
  "test/cart.test.ts": 'import { test } from "node:test";\nimport assert from "node:assert/strict";\nimport { applyDiscount, total } from "../src/cart.ts";\n\ntest("total", () => {\n  assert.equal(total([{ cents: 250, qty: 2 }, { cents: 100, qty: 1 }]), 600);\n});\n\ntest("discount", () => {\n  assert.equal(applyDiscount(1000, 10), 900);\n  assert.equal(applyDiscount(1000, 150), 0);\n});\n',
};

const read = (dir: string, path: string): string => readFileSync(join(dir, path), "utf8");
const testsPass = (dir: string): boolean => {
  try {
    execFileSync(process.execPath, ["--test", "test/cart.test.ts"], { cwd: dir, stdio: "ignore", timeout: 60_000 });
    return true;
  } catch {
    return false;
  }
};

interface Task {
  prompt: string;
  verify(dir: string, answer: string): boolean;
}

const TASKS: Record<string, Task> = {
  rename: {
    prompt: "Rename the function `add` in src/math.ts to `sum`, and update every place that uses it. Keep behaviour unchanged.",
    verify: (dir) => {
      const src = ["src/math.ts", "src/cart.ts", "src/report.ts"].map((p) => read(dir, p)).join("\n");
      return /function sum\(/.test(src) && !/\badd\b/.test(src) && testsPassIgnoringDiscount(dir);
    },
  },
  fix: {
    prompt: "`npm test` fails. Find the bug in the source and fix it. Do not change the tests.",
    verify: (dir) => read(dir, "test/cart.test.ts") === FIXTURE["test/cart.test.ts"] && testsPass(dir),
  },
  find: {
    prompt: "What retry limit and timeout does this app use, and which file defines them? Answer in one line.",
    verify: (_dir, answer) => /\b4\b/.test(answer) && /2500|2\.5\s*s/.test(answer) && /config\.ts/.test(answer) && !/\b9\b/.test(answer),
  },
  combo: {
    prompt: "Three things in this app: (1) rename the function `add` in src/math.ts to `sum` everywhere; (2) `npm test` fails, fix the bug in the source without changing the tests; (3) finally tell me in one line the retry limit and timeout and the file that defines them.",
    verify: (dir, answer) => {
      const src = ["src/math.ts", "src/cart.ts", "src/report.ts"].map((p) => read(dir, p)).join("\n");
      return /function sum\(/.test(src) && !/\badd\b/.test(src) && read(dir, "test/cart.test.ts") === FIXTURE["test/cart.test.ts"] && testsPass(dir)
        && /\b4\b/.test(answer) && /2500|2\.5\s*s/.test(answer) && /config\.ts/.test(answer);
    },
  },
};

/** The rename task must not break what already worked; the discount bug is the fix task's. */
function testsPassIgnoringDiscount(dir: string): boolean {
  try {
    execFileSync(process.execPath, ["--test", "--test-name-pattern=total", "test/cart.test.ts"], { cwd: dir, stdio: "ignore", timeout: 60_000 });
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- session-file scoring

interface Score {
  turns: number;
  input: number;
  cacheRead: number;
  cacheWrite: number;
  output: number;
  cost: number;
  toolCalls: number;
  toolResultTokens: number;
  failedTools: number;
  answer: string;
}

function score(sessionDir: string): Score {
  const s: Score = { turns: 0, input: 0, cacheRead: 0, cacheWrite: 0, output: 0, cost: 0, toolCalls: 0, toolResultTokens: 0, failedTools: 0, answer: "" };
  const files: string[] = [];
  const walk = (d: string): void => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) walk(p);
      else if (n.endsWith(".jsonl")) files.push(p);
    }
  };
  if (existsSync(sessionDir)) walk(sessionDir);
  for (const file of files) {
    for (const line of readFileSync(file, "utf8").split("\n")) {
      let e: { type?: string; message?: { role?: string; usage?: Record<string, number> & { cost?: { total?: number } }; content?: { type: string; text?: string }[]; isError?: boolean } };
      try {
        e = JSON.parse(line);
      } catch {
        continue;
      }
      const m = e.message;
      if (e.type !== "message" || !m) continue;
      if (m.role === "assistant" && m.usage) {
        s.turns += 1;
        s.input += m.usage.input ?? 0;
        s.cacheRead += m.usage.cacheRead ?? 0;
        s.cacheWrite += m.usage.cacheWrite ?? 0;
        s.output += m.usage.output ?? 0;
        s.cost += m.usage.cost?.total ?? 0;
        s.toolCalls += (m.content ?? []).filter((c) => c.type === "toolCall").length;
        const text = (m.content ?? []).filter((c) => c.type === "text").map((c) => c.text ?? "").join("").trim();
        if (text) s.answer = text;
      }
      if (m.role === "toolResult") {
        s.toolResultTokens += Math.ceil(JSON.stringify(m.content ?? []).length / 4);
        if (m.isError) s.failedTools += 1;
      }
    }
  }
  return s;
}

// ---------------------------------------------------------------- runs

interface Run {
  task: string;
  condition: string;
  rep: number;
}

const conditions = values.conditions!.split(",").map((c) => c.trim()).filter(Boolean);
const taskNames = values.tasks!.split(",").map((t) => t.trim()).filter((t) => TASKS[t]);
const reps = Number(values.reps);
const scratch = mkdtempSync(join(tmpdir(), "agentbench-"));
/** Session files stay (local, never committed) so the next experiment can study where turns went. */
const kept = join(HOME, "state", "agentbench", new Date().toISOString().replace(/[:.]/g, "-"));

/** One Brain home per condition: the real notes, kits, projects and telemetry, nothing shared. */
const homes = new Map<string, string>();
for (const condition of conditions) {
  if (condition === "off") continue;
  const home = join(scratch, `home-${condition.replace(/[^a-z0-9]+/gi, "_")}`);
  mkdirSync(join(home, "state"), { recursive: true });
  for (const path of ["notes", "kits", "projects.json"]) if (existsSync(join(HOME, path))) cpSync(join(HOME, path), join(home, path), { recursive: true });
  if (existsSync(join(HOME, "state", "telemetry.jsonl"))) cpSync(join(HOME, "state", "telemetry.jsonl"), join(home, "state", "telemetry.jsonl"));
  homes.set(condition, home);
}

function runOne(run: Run): Promise<Record<string, unknown>> {
  const id = `${run.task}-${run.condition.replace(/[^a-z0-9]+/gi, "_")}-${run.rep}`;
  const ws = join(scratch, "ws", id);
  for (const [path, text] of Object.entries(FIXTURE)) {
    mkdirSync(join(ws, path, ".."), { recursive: true });
    writeFileSync(join(ws, path), text);
  }
  const sessions = join(kept, id);
  mkdirSync(sessions, { recursive: true });
  const [mode, ...parts] = run.condition.split("+");
  const experiments = parts.filter((part) => !part.startsWith("@"));
  const presets = parts.filter((part) => part.startsWith("@")).map((part) => part.slice(1));
  const env: NodeJS.ProcessEnv = { ...process.env, BRAIN_PROJECT: "benchapp", BRAIN_EXPERIMENT: experiments.join(",") };
  if (presets.length) {
    const overlay = join(scratch, `settings-${id}.yml`);
    writeFileSync(overlay, presets.map((name) => SETTINGS[name] ?? "").join(""));
    env.PI_CONFIG_FILES = overlay;
  }
  if (mode === "off") env.BRAIN = "off";
  else env.SECOND_BRAIN_HOME = homes.get(run.condition)!;
  const args = ["-p", "--model", values.model!, "--thinking", values.thinking!, "--cwd", ws, "--session-dir", sessions, TASKS[run.task]!.prompt];
  const started = Date.now();
  return new Promise((done) => {
    const child = spawn("omp", args, { env, cwd: ws, stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    const timer = setTimeout(() => child.kill(), Number(values.timeout) * 1000);
    child.on("close", (code) => {
      clearTimeout(timer);
      const s = score(sessions);
      const answer = s.answer || out.trim().split("\n").slice(-3).join(" ");
      const ok = code === 0 && TASKS[run.task]!.verify(ws, answer);
      const row = { ...run, id, ok, exit: code, seconds: Math.round((Date.now() - started) / 1000), ...s, answer: answer.slice(0, 300) };
      console.log(`${ok ? "PASS" : "FAIL"} ${id} ${row.seconds}s turns=${s.turns} tokens=${s.input + s.cacheRead + s.cacheWrite + s.output} $${s.cost.toFixed(3)}`);
      done(row);
    });
  });
}

async function pool<T, R>(items: T[], n: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  let next = 0;
  await Promise.all(Array.from({ length: n }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]!);
    }
  }));
  return out;
}

// Interleave conditions so time-of-day and rate limits hit them alike.
const runs: Run[] = [];
for (let rep = 1; rep <= reps; rep++) for (const task of taskNames) for (const condition of conditions) runs.push({ task, condition, rep });
const rows = await pool(runs, Number(values.concurrency), runOne);

// ---------------------------------------------------------------- summary vs best earlier run

const at = new Date().toISOString();
const taskSet = `v${FIXTURE_VERSION}:${taskNames.join(",")}`;
mkdirSync(join(HOME, "state"), { recursive: true });
for (const row of rows) appendFileSync(RESULTS, JSON.stringify({ at, label: values.label, model: values.model, taskSet, ...row }) + "\n");

type Row = { at: string; condition: string; taskSet: string; model: string; ok: boolean; cost: number; turns: number; input: number; cacheRead: number; cacheWrite: number; output: number; toolResultTokens: number };
const summarize = (rs: Row[]) => {
  const n = rs.length || 1;
  const mean = (f: (r: Row) => number) => rs.reduce((s, r) => s + f(r), 0) / n;
  return { runs: rs.length, pass: rs.filter((r) => r.ok).length, cost: mean((r) => r.cost), turns: mean((r) => r.turns), tokens: mean((r) => r.input + r.cacheRead + r.cacheWrite + r.output), uncached: mean((r) => r.input), output: mean((r) => r.output), toolResult: mean((r) => r.toolResultTokens) };
};
const history: Row[] = readFileSync(RESULTS, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
console.log(`\nagentbench ${at} · ${values.model} · tasks ${taskSet} · ${reps} reps${values.label ? ` · ${values.label}` : ""}`);
// Batches drift ±5-10% (time of day, provider load): the same-batch control is the fair baseline.
const control = summarize(rows.filter((r) => r.condition === conditions[0]) as unknown as Row[]);
const pct = (a: number, b: number): string => `${a <= b ? "" : "+"}${Math.round((100 * (a - b)) / b)}%`;
console.log(`condition            pass   $/run   turns   tokens/run   uncached   output   tool-result   vs ${conditions[0]} (tokens, $)   vs best earlier ($)`);
for (const condition of conditions) {
  const now = summarize(rows.filter((r) => r.condition === condition) as unknown as Row[]);
  const earlier = new Map<string, Row[]>();
  for (const r of history) if (r.at !== at && r.taskSet === taskSet && r.model === values.model && r.condition === condition) earlier.set(r.at, [...(earlier.get(r.at) ?? []), r]);
  const best = [...earlier.values()].map(summarize).filter((s) => s.pass === s.runs).sort((a, b) => a.cost - b.cost)[0];
  // Cost, not tokens: uncached input costs ~10x a cache read, so fewer tokens can cost more.
  const vs = best ? `${now.cost < best.cost && now.pass === now.runs ? "BEAT" : "not beaten"} (${best.cost.toFixed(3)}, ${Math.round(best.tokens)} tokens)` : "first run";
  const rel = condition === conditions[0] ? "control" : `${pct(now.tokens, control.tokens)}, ${pct(now.cost, control.cost)}`;
  console.log(`${condition.padEnd(20)} ${`${now.pass}/${now.runs}`.padStart(4)}  ${now.cost.toFixed(3).padStart(6)}  ${now.turns.toFixed(1).padStart(6)}  ${Math.round(now.tokens).toString().padStart(11)}  ${Math.round(now.uncached).toString().padStart(9)}  ${Math.round(now.output).toString().padStart(7)}  ${Math.round(now.toolResult).toString().padStart(12)}   ${rel.padEnd(22)}  ${vs}`);
}
console.log(`raw rows: ${RESULTS} · sessions: ${kept}`);
rmSync(scratch, { recursive: true, force: true });
