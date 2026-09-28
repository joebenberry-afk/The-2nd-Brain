/**
 * Agent benchmark: the same small coding tasks run by headless OMP agents with the Brain off, on,
 * or on with experiments (BRAIN_EXPERIMENT), scored from the agents' own session files.
 *
 *   node scripts/agentbench.ts [--conditions off,on] [--tasks rename,fix,find,scaffold,jsonstdin,learn] [--reps 2]
 *                              [--concurrency 4] [--model openai-codex/gpt-6-astra] [--label text]
 *
 * A condition is `off`, `on`, or `on+<experiment>[+<experiment>]`; a `@<preset>` part adds an OMP
 * settings overlay (PI_CONFIG_FILES) from SETTINGS below, with or without the Brain (`off+@x`). Each run gets a fresh copy of a
 * small fixture project; each condition gets its own copy of the Brain home (notes,
 * projects, telemetry), so conditions never see each other's sessions. Results append to
 * state/agentbench.jsonl; the summary compares every condition with its best earlier run on the
 * same task set. Costs real model usage: meant for GPT models, run deliberately.
 * `--tasks learn --conditions off,on --reps 6` runs A/B session pairs (default condition: on):
 * fresh workspaces, one isolated Brain home per pair, no handoff except persisted Brain memory.
 * Notes and their later card/recall/fix exposure, plus B-only metrics, are retained in each row.
 * v5-nudge rejected: +11.9% A+B tokens, +4.2% cost vs same-batch control; control wrote notes 6/6.
 */
import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync, appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { execFileSync } from "node:child_process";
import { createNote, loadNotes } from "../src/notes.ts";
import assert from "node:assert/strict";
import { renderCard } from "../src/card.ts";

const PACKAGE = resolve(import.meta.dirname, "..");
/** Bump when existing fixtures/tasks change; additive tasks already have a distinct taskSet. */
const FIXTURE_VERSION = 3;

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
    conditions: { type: "string" },
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
  // Deploy targets are colours; which one is staging lives only in the Brain (the memory task).
  "scripts/deploy.mjs": "import { writeFileSync } from \"node:fs\";\nconst i = process.argv.indexOf(\"--target\");\nconst target = process.argv[i + 1];\nif (i < 0 || ![\"blue\", \"green\", \"amber\"].includes(target)) {\n  console.error(\"usage: node scripts/deploy.mjs --target <blue|green|amber>\");\n  process.exit(2);\n}\nwriteFileSync(`.deployed-${target}`, new Date().toISOString());\nconsole.log(`deployed to ${target}`);\n",
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
  empty?: boolean;
  fixture?: Record<string, string>;
  verify(dir: string, answer: string): boolean;
}

// The contract belongs to the host, not the repo. Reading/diagnosing it is allowed, editing it is not.
const LEARN_RUNNER = `import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
if (process.argv.includes("--diagnose")) {
  console.log("BENCHAPP-E17: this host's cart test channel is amber; set BENCHAPP_CHANNEL=amber when running npm test.");
  process.exit(0);
}
if (process.env.BENCHAPP_CHANNEL !== "amber") {
  console.error("BENCHAPP-E17: host contract mismatch. The host runner supports --diagnose.");
  process.exit(17);
}
const result = spawnSync(process.execPath, ["--test", "test/cart.test.ts"], { stdio: "inherit" });
if (result.status === 0) writeFileSync(process.env.BENCHAPP_RECEIPT, "passed");
process.exit(result.status ?? 1);
`;
const LEARN_FIXTURE = {
  ...FIXTURE,
  "package.json": JSON.stringify({ name: "benchapp-learn", type: "module", private: true, scripts: { test: "node scripts/check.mjs" } }, null, 2) + "\n",
  "scripts/check.mjs": 'import { pathToFileURL } from "node:url";\nawait import(pathToFileURL(process.env.BENCHAPP_RUNNER).href);\n',
};

const TASKS: Record<string, Task> = {
  learn: {
    fixture: LEARN_FIXTURE,
    prompt: "Fix the cart discount calculation and demonstrate a passing npm test. Do not edit tests, package scripts, or the host-managed runner; you may inspect and diagnose the host environment. Keep the source fix small.",
    verify: (dir) => ["test/cart.test.ts", "package.json", "scripts/check.mjs"].every((p) => read(dir, p) === LEARN_FIXTURE[p as keyof typeof LEARN_FIXTURE]) && testsPass(dir),
  },
  scaffold: {
    empty: true,
    prompt: "Create a small Node TypeScript CLI named wordcount in this empty directory. Running `node bin/wordcount.mjs <file>` must print just the number of whitespace-separated words in that UTF-8 file (zero for empty/whitespace-only input). Include a test at test/wordcount.test.ts and a non-watch `npm test` script, then run it and demonstrate the CLI. Keep it small; stop once it works.",
    verify: (dir) => {
      try {
        if (!existsSync(join(dir, "test/wordcount.test.ts"))) return false;
        execFileSync(process.platform === "win32" ? "cmd.exe" : "npm", process.platform === "win32" ? ["/d", "/s", "/c", "npm test"] : ["test"], { cwd: dir, stdio: "ignore", timeout: 60_000 });
        const input = join(dir, ".agentbench-wordcount.txt");
        for (const [text, expected] of [[" hello\tworld\n café  ", "3"], [" \t\n", "0"]] as const) {
          writeFileSync(input, text);
          const actual = execFileSync(process.execPath, ["bin/wordcount.mjs", input], { cwd: dir, encoding: "utf8", timeout: 10_000 });
          if (actual.trim() !== expected) return false;
        }
        return true;
      } catch {
        return false;
      }
    },
  },
  jsonstdin: {
    empty: true,
    prompt: "Create a small Node TypeScript CLI named jsonsum in this empty directory. Running `node bin/jsonsum.mjs` must read one JSON array of finite numbers from stdin and print just their sum (zero for an empty array). Malformed JSON, non-arrays, and non-number array entries must produce a nonzero exit code, a diagnostic on stderr, and no stdout. Include tests at test/jsonsum.test.ts covering valid and failing input and a non-watch `npm test` script, then run it and demonstrate the CLI. Keep it small; stop once it works.",
    verify: (dir) => {
      try {
        if (!existsSync(join(dir, "test/jsonsum.test.ts"))) return false;
        execFileSync(process.platform === "win32" ? "cmd.exe" : "npm", process.platform === "win32" ? ["/d", "/s", "/c", "npm test"] : ["test"], { cwd: dir, stdio: "ignore", timeout: 60_000 });
        for (const [input, expected] of [["[3, -2, 0.5]\n", "1.5"], ["[]", "0"]] as const) {
          const actual = execFileSync(process.execPath, ["bin/jsonsum.mjs"], { cwd: dir, input, encoding: "utf8", timeout: 10_000 });
          if (actual.trim() !== expected) return false;
        }
        for (const input of ["[", "{}", '[1, "2"]', "[null]", "[1e400]"]) {
          try {
            execFileSync(process.execPath, ["bin/jsonsum.mjs"], { cwd: dir, input, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: 10_000 });
            return false;
          } catch (error) {
            const result = error as { status?: number | null; stdout?: string; stderr?: string };
            if (typeof result.status !== "number" || result.status === 0 || result.stdout?.trim() || !result.stderr?.trim()) return false;
          }
        }
        return true;
      } catch {
        return false;
      }
    },
  },
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
  deploy: {
    prompt: "Deploy this app to staging.",
    verify: (dir) => existsSync(join(dir, ".deployed-amber")) && !existsSync(join(dir, ".deployed-blue")) && !existsSync(join(dir, ".deployed-green")),
  },
  recallq: {
    prompt: "Deploy this app to staging.",
    verify: (dir) => read(dir, "scripts/deploy.mjs") === FIXTURE["scripts/deploy.mjs"] && existsSync(join(dir, ".deployed-amber")) && !existsSync(join(dir, ".deployed-blue")) && !existsSync(join(dir, ".deployed-green")),
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
  session?: "A" | "B";
}

interface RecallCall {
  query: string;
  words: number;
  question: boolean;
  judged: boolean;
  dropped: number;
  ids: string[];
  neededReturned: boolean;
}

interface SessionRow extends Run, Score {
  id: string;
  ok: boolean;
  infra: boolean;
  exit: number | null;
  seconds: number;
  recall?: { neededId: string; calls: RecallCall[]; neededReturned: boolean; wrongNotes: number };
}

const conditions = (values.conditions ?? (values.tasks === "learn" ? "on" : "off,on")).split(",").map((c) => c.trim()).filter(Boolean);
const taskNames = values.tasks!.split(",").map((t) => t.trim()).filter((t) => TASKS[t]);
const reps = Number(values.reps);
if (taskNames.includes("learn") && (taskNames.length !== 1 || !conditions.length || conditions.some((c) => !["off", "on"].includes(c)))) throw new Error("learn runs alone with off/on conditions");
const scratch = mkdtempSync(join(tmpdir(), "agentbench-"));
/** Session files stay (local, never committed) so the next experiment can study where turns went. */
const kept = join(HOME, "state", "agentbench", new Date().toISOString().replace(/[:.]/g, "-"));

/** One Brain home per condition: the real notes, projects and telemetry, nothing shared. */
const homes = new Map<string, string>();
const neededIds = new Map<string, string>();
if (taskNames.includes("recallq")) {
  assert.equal(taskNames.length, 1, "recallq runs alone with fresh per-run homes");
  assert(conditions.every(c => c === "on" || c.startsWith("on+")), "recallq requires Brain-enabled conditions");
  assert(!/staging|production/i.test(Object.values(FIXTURE).join("\n")), "fixture must not disclose environment mapping");
}
for (const condition of conditions) {
  if (condition === "off") continue;
  const home = join(scratch, `home-${condition.replace(/[^a-z0-9]+/gi, "_")}`);
  mkdirSync(join(home, "state"), { recursive: true });
  if (taskNames.includes("recallq")) {
    const project = { id: "benchapp-recallq", tags: [], root: null };
    const needed = createNote(home, { project: project.id, kind: "fact", text: "Environment routing: staging is amber, production is blue; green is retired.\nRun: node scripts/deploy.mjs --target amber" });
    neededIds.set(condition, needed.id);
    for (const detail of [
      "release receipts belong in the incident archive",
      "the release owner reviews the smoke report",
      "keep the cart dashboard open during rollout",
      "record the release timestamp in the team log",
      "monitor request latency after rollout",
      "keep the previous build receipt for rollback",
      "notify the support channel after completion",
      "attach the checkout smoke result to the ticket",
    ]) createNote(home, { project: project.id, kind: "procedure", text: `Deploy this app to staging: ${detail}.` });
    const card = renderCard(home, loadNotes(home).notes, project, { tools: true, prompt: TASKS.recallq!.prompt });
    assert.equal((card.match(/\(n-[a-f0-9]+\)/g) ?? []).length, 5, "preflight must show five decoys");
    assert(!card.includes(needed.id) && !card.includes("amber"), "needed fact must be absent from start card");
    mkdirSync(kept, { recursive: true });
    writeFileSync(join(kept, `preflight-${condition}.txt`), card + "\n");
    console.log(`recallq preflight ${condition}: 9 notes, 5 card decoys, needed ${needed.id} excluded; fixture has no environment mapping`);
  } else {
    for (const path of ["notes", "projects.json"]) if (existsSync(join(HOME, path))) cpSync(join(HOME, path), join(home, path), { recursive: true });
    if (existsSync(join(HOME, "state", "telemetry.jsonl"))) cpSync(join(HOME, "state", "telemetry.jsonl"), join(home, "state", "telemetry.jsonl"));
    createNote(home, { project: "benchapp", kind: "fact", text: "benchapp deploy targets: staging is amber, production is blue (green is retired)\nRun: node scripts/deploy.mjs --target amber" });
  }
  homes.set(condition, home);
}
if (reps === 0) {
  rmSync(scratch, { recursive: true, force: true });
  console.log(`No runs requested: tasks ${taskNames.join(",")} · conditions ${conditions.join(",")}`);
  process.exit(0);
}

function runOne(run: Run, pairHome?: string): Promise<SessionRow> {
  const id = `${run.task}-${run.condition.replace(/[^a-z0-9]+/gi, "_")}-${run.rep}${run.session ? `-${run.session}` : ""}`;
  const ws = join(scratch, "ws", id);
  mkdirSync(ws, { recursive: true });
  for (const [path, text] of Object.entries(TASKS[run.task]!.empty ? {} : TASKS[run.task]!.fixture ?? FIXTURE)) {
    mkdirSync(join(ws, path, ".."), { recursive: true });
    writeFileSync(join(ws, path), text);
  }
  const sessions = join(kept, id);
  mkdirSync(sessions, { recursive: true });
  if (run.task === "recallq") {
    pairHome = join(sessions, "brain-home");
    cpSync(homes.get(run.condition)!, pairHome, { recursive: true });
  }
  const [mode, ...parts] = run.condition.split("+");
  const experiments = parts.filter((part) => !part.startsWith("@"));
  const presets = parts.filter((part) => part.startsWith("@")).map((part) => part.slice(1));
  // Fresh empty-directory projects must not inherit another repetition's working state or notes.
  const project = TASKS[run.task]!.empty ? id : run.task === "learn" ? "benchapp-learn" : run.task === "recallq" ? "benchapp-recallq" : "benchapp";
  const env: NodeJS.ProcessEnv = { ...process.env, BRAIN: mode === "off" ? "off" : "on", BRAIN_PROJECT: project, BRAIN_EXPERIMENT: experiments.join(",") };
  const runner = join(sessions, "host-runner.mjs");
  const receipt = join(sessions, "test-passed.txt");
  if (run.task === "learn") {
    writeFileSync(runner, LEARN_RUNNER);
    env.BENCHAPP_RUNNER = runner;
    env.BENCHAPP_RECEIPT = receipt;
    delete env.BENCHAPP_CHANNEL;
  }
  if (presets.length) {
    const overlay = join(scratch, `settings-${id}.yml`);
    writeFileSync(overlay, presets.map((name) => SETTINGS[name] ?? "").join(""));
    env.PI_CONFIG_FILES = overlay;
  }
  if (mode !== "off" || pairHome) {
    env.SECOND_BRAIN_HOME = pairHome ?? homes.get(run.condition)!;
    if (run.task === "learn") {
      const path = join(env.SECOND_BRAIN_HOME, "projects.json");
      const registry = existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : {};
      registry.projects ??= {};
      registry.projects[project] = { tags: ["node", "typescript"] };
      writeFileSync(path, JSON.stringify(registry, null, 2) + "\n");
    }
  }
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
      // A dead network or provider says nothing about the task: such runs are left out of scores.
      const infra = code !== 0 && /ERR_TLS|ECONNRESET|ETIMEDOUT|ENOTFOUND|fetch failed|socket hang up|\b429\b|\b5\d\d\b|rate limit|quota/i.test(out.slice(-2000));
      const ok = code === 0 && TASKS[run.task]!.verify(ws, answer) && (run.task !== "learn" || (existsSync(receipt) && readFileSync(runner, "utf8") === LEARN_RUNNER));
      writeFileSync(join(sessions, "output.txt"), out);
      const row: SessionRow = { ...run, id, ok, infra, exit: code, seconds: Math.round((Date.now() - started) / 1000), ...s, answer: answer.slice(0, 300) };
      if (run.task === "recallq") {
        const neededId = neededIds.get(run.condition)!;
        const path = join(pairHome!, "state", "telemetry.jsonl");
        const uses: { kind: string; query?: string; judged?: boolean; dropped?: number; ids?: string[] }[] = existsSync(path) ? readFileSync(path, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
        const calls = uses.filter(use => use.kind === "recall").map(use => {
          const query = use.query ?? "";
          const ids = use.ids ?? [];
          return { query, words: query.trim().split(/\s+/).filter(Boolean).length, question: query.trimEnd().endsWith("?"), judged: use.judged === true, dropped: use.dropped ?? 0, ids, neededReturned: ids.includes(neededId) };
        });
        row.recall = { neededId, calls, neededReturned: calls.some(call => call.neededReturned), wrongNotes: calls.reduce((sum, call) => sum + call.ids.filter(id => id !== neededId).length, 0) };
        writeFileSync(join(sessions, "recall.json"), JSON.stringify(row.recall, null, 2) + "\n");
      }
      console.log(`${infra ? "INFRA" : ok ? "PASS" : "FAIL"} ${id} ${row.seconds}s turns=${s.turns} tokens=${s.input + s.cacheRead + s.cacheWrite + s.output} $${s.cost.toFixed(3)}`);
      done(row);
    });
  });
}

/** A and B never share files/session history; only their private Brain home survives. */
async function runLearnPair(run: Run) {
  const home = join(scratch, `pair-${run.condition.replace(/[^a-z0-9]+/gi, "_")}-${run.rep}`);
  if (run.condition === "off") mkdirSync(home, { recursive: true });
  else cpSync(homes.get(run.condition)!, home, { recursive: true });
  const before = new Set(loadNotes(home).notes.map((n) => n.id));
  const telemetryPath = join(home, "state", "telemetry.jsonl");
  const telemetry = (): { kind: string; id?: string; ids?: string[] }[] => existsSync(telemetryPath) ? readFileSync(telemetryPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [];
  const a = await runOne({ ...run, session: "A" }, home);
  const notes = loadNotes(home).notes.filter((n) => !before.has(n.id)).map((n) => ({ id: n.id, text: n.body }));
  const afterA = telemetry();
  // Snapshot exactly what B can inherit, before B can add/change anything.
  cpSync(home, join(kept, a.id, "brain-after-A"), { recursive: true });
  const b = await runOne({ ...run, session: "B" }, home);
  const bUses = telemetry().slice(afterA.length);
  const surfaced: { id: string; via: string }[] = [];
  for (const note of notes) {
    for (const via of ["recall", "fix"]) if (bUses.some((u) => u.kind === via && (u.id === note.id || u.ids?.includes(note.id)))) surfaced.push({ id: note.id, via });
    for (const file of readdirSync(join(kept, b.id)).filter((f) => f.endsWith(".jsonl"))) {
      const entries = readFileSync(join(kept, b.id, file), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
      if (entries.some((e) => e.type === "custom_message" && e.customType === "brain.card" && String(e.content).includes(note.id))) {
        surfaced.push({ id: note.id, via: "card" });
        break;
      }
    }
  }
  cpSync(home, join(kept, b.id, "brain-after-B"), { recursive: true });
  const pair = { ...a, ...run, session: undefined, id: a.id.slice(0, -2), ok: a.ok && b.ok, infra: a.infra || b.infra, a, b, notes, surfaced };
  for (const key of ["seconds", "turns", "input", "cacheRead", "cacheWrite", "output", "cost", "toolCalls", "toolResultTokens", "failedTools"] as const) pair[key] = a[key] + b[key];
  writeFileSync(join(kept, pair.id + ".json"), JSON.stringify(pair, null, 2) + "\n");
  return pair;
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
const rows = await pool(runs, Number(values.concurrency), (run) => run.task === "learn" ? runLearnPair(run) : runOne(run));

// ---------------------------------------------------------------- summary vs best earlier run

const at = new Date().toISOString();
const taskSet = `v${FIXTURE_VERSION}:${taskNames.join(",")}`;
mkdirSync(join(HOME, "state"), { recursive: true });
for (const row of rows) appendFileSync(RESULTS, JSON.stringify({ at, label: values.label, model: values.model, taskSet, ...row }) + "\n");

type Row = { infra?: boolean; at: string; condition: string; taskSet: string; model: string; ok: boolean; cost: number; turns: number; input: number; cacheRead: number; cacheWrite: number; output: number; toolResultTokens: number };
const summarize = (all: Row[]) => {
  const rs = all.filter((r) => !r.infra);
  const n = rs.length || 1;
  const mean = (f: (r: Row) => number) => rs.reduce((s, r) => s + f(r), 0) / n;
  return { runs: rs.length, pass: rs.filter((r) => r.ok).length, cost: mean((r) => r.cost), turns: mean((r) => r.turns), tokens: mean((r) => r.input + r.cacheRead + r.cacheWrite + r.output), uncached: mean((r) => r.input), output: mean((r) => r.output), toolResult: mean((r) => r.toolResultTokens) };
};
const history: Row[] = readFileSync(RESULTS, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)).filter((r: Row) => !r.infra);
const infraRuns = rows.filter((r) => (r as { infra?: boolean }).infra).length;
if (infraRuns) console.log(`\n${infraRuns} run(s) hit network/provider errors and are left out of the scores; rerun for a full sample.`);
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
if (taskNames.includes("recallq")) {
  const metrics = conditions.map(condition => {
    const rs = rows.filter(row => row.condition === condition && !row.infra);
    const calls = rs.flatMap(row => row.recall?.calls ?? []);
    return { condition, ...summarize(rs as unknown as Row[]), recallCalls: calls.length / (rs.length || 1), questions: calls.filter(call => call.question).length / (calls.length || 1), needed: rs.filter(row => row.recall?.neededReturned).length / (rs.length || 1), wrongNotes: rs.reduce((sum, row) => sum + (row.recall?.wrongNotes ?? 0), 0) };
  });
  console.log("\nrecallq: condition | pass | $/run | tokens/run | turns | recalls/run | queries ending ? | needed returned/run | wrong-note returns (total)");
  for (const r of metrics) console.log(`${r.condition} | ${r.pass}/${r.runs} | ${r.cost.toFixed(4)} | ${Math.round(r.tokens)} | ${r.turns.toFixed(2)} | ${r.recallCalls.toFixed(2)} | ${(100 * r.questions).toFixed(1)}% | ${(100 * r.needed).toFixed(1)}% | ${r.wrongNotes}`);
  // v5-question rejected: a "phrase one question" tool description left queries unchanged (0% ended
  // with "?"), needed note returned 8/8 in both arms, +20% tokens, +4% cost.
}
if (taskNames.includes("learn")) {
  const pairs = rows.filter((r): r is Awaited<ReturnType<typeof runLearnPair>> => "b" in r && !r.infra);
  const learning = conditions.map((condition) => {
    const rs = pairs.filter((r) => r.condition === condition);
    const n = rs.length || 1;
    const mean = (f: (r: typeof rs[number]) => number) => rs.reduce((sum, r) => sum + f(r), 0) / n;
    return { condition, n: rs.length, notes: rs.reduce((sum, r) => sum + r.notes.length, 0), wrote: rs.filter((r) => r.notes.length).length,
      saw: rs.filter((r) => r.surfaced.length).length,
      landed: rs.reduce((sum, r) => sum + new Set(r.surfaced.filter((s) => s.via !== "card").map((s) => s.id)).size, 0),
      bTokens: mean((r) => r.b.input + r.b.cacheRead + r.b.cacheWrite + r.b.output), bCost: mean((r) => r.b.cost), bTurns: mean((r) => r.b.turns), bTools: mean((r) => r.b.toolCalls),
      pass: rs.filter((r) => r.ok).length, bPass: rs.filter((r) => r.b.ok).length,
      tokens: mean((r) => r.input + r.cacheRead + r.cacheWrite + r.output), cost: mean((r) => r.cost) };
  });
  console.log("\nlearn (means per B / pair; landed excludes card-only exposure):");
  console.log("condition       A notes (pairs)  B saw  landed  B tokens  B cost  B turns  B tools  B pass  pair pass  A+B tokens  A+B cost");
  for (const r of [...learning].sort((a, b) => a.cost - b.cost)) console.log(`${r.condition.padEnd(15)} ${r.notes} (${r.wrote}/${r.n})          ${r.saw}/${r.n}    ${r.landed}       ${Math.round(r.bTokens)}   ${r.bCost.toFixed(3)}   ${r.bTurns.toFixed(1)}     ${r.bTools.toFixed(1)}     ${r.bPass}/${r.n}     ${r.pass}/${r.n}        ${Math.round(r.tokens)}    ${r.cost.toFixed(3)}`);
}
console.log(`raw rows: ${RESULTS} · sessions: ${kept}`);
// A lingering child process can hold a file on Windows: cleanup must never lose the report.
try {
  rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
} catch {
  console.log(`left temp files in ${scratch}`);
}
