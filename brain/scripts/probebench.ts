/**
 * probebench (compactbench v2): what does a coding agent still know and obey after its host compacts the session?
 * node scripts/probebench.ts --hosts claude,codex,omp --arms full,default,brain,render --depth 1 --reps 1
 * Host-neutral seeded scenario (plant facts and rules, edit a file, read noisy logs, compact, then probe) with one
 * driver per host (Claude Code, Codex CLI, Oh My Pi) and four arms: no compaction, host default, host + Second Brain,
 * and render (layer 4: old tool output is elided in the request and recalled by id; OMP via BRAIN_RENDER=on, Claude Code and Codex via `brain proxy`).
 * --scenario e6 is the layer-4 gate: no forced compaction, two detail questions answered from elided logs, per-run usage, cache hit, elisions and restores.
 * At --depth >= 2 the e2 probe also asks, from memory, two details that exist only inside the logs (its positive control for what a summary drops); a log re-read during that probe scores them "violated".
 * --compact-at <tokens> (e6) sets each host's own auto-compaction threshold instead of leaving it off.
 * Isolated fixtures and an isolated SECOND_BRAIN_HOME: never reads real notes or writes repository state.
 * Results, turns and fixtures live under --output (default: an OS temporary directory).
 * node scripts/probebench.ts --self-test    no model calls; checks scenario, scoring, stats and command builders.
 * node scripts/probebench.ts --dry-run      prints the plan and the exact host commands.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { parseArgs } from "node:util";

type Row = Record<string, any>;
type Host = "claude" | "codex" | "omp";
type Arm = "full" | "default" | "brain" | "render";
type Suite = "e2" | "e6";
type Outcome = "correct" | "lure" | "missing" | "violated";
const HOSTS: Host[] = ["claude", "codex", "omp"];
const ARMS: Arm[] = ["full", "default", "brain", "render"];
const SUITES = new Set<string>(["e2", "e6"]);
const DEFAULT_MODEL: Record<Host, string> = { claude: "haiku", codex: "gpt-6-astra", omp: "openai-codex/gpt-6-astra" };
const RECALL = ["port", "ticket", "replica", "tag", "approach", "reason", "artifact", "target", "rule_vendor", "rule_status", "rule_target"] as const;
const PROBES = [...RECALL, "status_kept", "vendor_kept"] as const;
const DETAIL = ["shard", "component"] as const;
const CALL_TIMEOUT_MS = 300_000, OMP_RUN_TIMEOUT_MS = 1_800_000;
const CODEX_COMPACT_LIMIT = 1000, CODEX_NO_COMPACT_LIMIT = 100_000_000, CODEX_COMPACT_PROMPT = "Reply OK only.";
const BRAIN_ARMS = new Set<Arm>(["brain", "render"]); // arms that load the OMP extension and need the brain/ snapshot
const PROXY_WAIT_MS = 15_000, CODEX_UPSTREAM = "https://chatgpt.com/backend-api/codex";
const PROBE_MARK = "exactly in the form `N: answer`"; // locates the probe prompt in a host transcript
const BATCH_LOG = /logs[\\/]+batch-\d+\.log/, RECALL_ID = /\bt-[0-9a-f]{10}\b/;
const textOf = (message: Row): string => typeof message.content === "string" ? message.content
  : (message.content ?? []).filter((part: Row) => part.type === "text").map((part: Row) => part.text ?? "").join("\n");
const jsonl = (path: string): Row[] => existsSync(path) ? readFileSync(path, "utf8").split("\n").filter(Boolean).flatMap(line => { try { return [JSON.parse(line) as Row]; } catch { return []; } }) : [];
const fwd = (path: string): string => path.replaceAll("\\", "/");
const msg = (error: unknown): string => error instanceof Error ? error.message : String(error);
/** Promise.withResolvers equivalent: it is missing from the repo tsconfig's ES2023 lib. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

// ---------- seeded scenario ----------
function prngFor(seed: number, rep: number, salt = ""): () => number {
  let a = createHash("sha256").update(`${seed}:${rep}:${salt}`).digest().readUInt32LE(0);
  return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const BIRDS = ["heron", "osprey", "kestrel", "plover", "tern", "wren", "egret", "curlew", "finch", "swift", "magpie", "ibis", "falcon", "lark"];
const COLORS = ["amber", "indigo", "teal", "crimson", "violet", "ochre", "cobalt", "saffron"];
const APPROACHES = ["global mutex", "Redis queue", "polling loop", "file lock", "thread pool"];
const REASONS = ["deadlocks", "latency", "cost", "flakiness", "memory"];
// Distinctive word per approach (regexes: bare "lock" would match the reason "deadlocks", hence the lookbehind).
const APPROACH_RE: Record<string, RegExp> = { "global mutex": /\bmutex/i, "Redis queue": /\bqueue/i, "polling loop": /\bloop/i, "file lock": /(?<!dead)lock/i, "thread pool": /\bpool/i };
const REASON_RE: Record<string, RegExp> = { deadlocks: /deadlock/i, latency: /latenc/i, cost: /\bcost/i, flakiness: /flak/i, memory: /\bmemory/i };
const COMPONENTS = ["auth", "cache", "queue", "billing", "search", "gateway", "scheduler", "indexer"];
const EVENTS = ["request accepted", "heartbeat ok", "slot refreshed", "batch flushed", "connection reused", "lease renewed", "retry skipped", "metrics emitted"];
const LEVELS = ["INFO", "INFO", "INFO", "DEBUG", "WARN"];
const LIB_TEXT = "The client will recieve a token.\n";
const CONFIG_TEXT = '{"alpha": 3, "beta": 5, "gamma": 8}';

interface Scenario {
  seed: number; rep: number; depth: number; rows: number;
  port: string; ticket: string; replica: string; oldTag: string; newTag: string; approach: string; reason: string;
  statusTag: string; target: string; lure: string; alpha: number;
  shard: string; shardLures: string[]; component: string; // E6 detail facts; empty when the scenario has none
  distract: { port: string[]; ticket: string[]; replica: string[]; tag: string[]; target: string[] };
  files: Record<string, string>;
}
interface Turn { kind: string; prompt: string; tools: boolean; compactAfter: boolean }

function makeScenario(seed: number, rep: number, depth: number, rows: number, detail = false): Scenario {
  assert(!detail || (depth >= 2 && rows >= 20), "the e6 detail facts need depth >= 2 and rows >= 20");
  const r = prngFor(seed, rep);
  const int = (lo: number, hi: number): number => lo + Math.floor(r() * (hi - lo + 1));
  const pick = <T,>(list: readonly T[]): T => list[Math.floor(r() * list.length)] as T;
  const hex = (n: number): string => Array.from({ length: n }, () => Math.floor(r() * 16).toString(16)).join("");
  const num4 = (): string => String(int(1000, 9999));
  const color = (): string => `${pick(COLORS)}-${int(2, 99)}`;
  const port = String(int(20000, 59999)), ticket = `QX-${num4()}`, replica = `${pick(BIRDS)}-${hex(4)}`;
  const oldTag = `BT-${num4()}`;
  let newTag = `BT-${num4()}`;
  while (newTag === oldTag) newTag = `BT-${num4()}`;
  const target = color();
  let lure = color();
  while (lure === target) lure = color();
  const planted = { port, ticket, replica, oldTag, newTag, approach: pick(APPROACHES), reason: pick(REASONS), statusTag: `[ST-${num4()}]`, target, lure, alpha: int(10, 99) };
  const tokens = [port, ticket, replica, oldTag, newTag, target, lure, planted.statusTag.slice(1, -1)];
  const clean = (make: () => string): string => { for (;;) { const s = make(); if (!tokens.some(t => s.includes(t))) return s; } };
  const distract: Scenario["distract"] = { port: [], ticket: [], replica: [], tag: [], target: [] };
  const makers: Array<() => string> = [
    () => { const v = clean(() => String(int(10000, 99999))); distract.port.push(v); return `staging port ${v} retired`; },
    () => { const v = clean(() => `QX-${num4()}`); distract.ticket.push(v); return `ticket ${v} closed`; },
    () => { const v = clean(() => `${pick(BIRDS)}-${hex(4)}`); distract.replica.push(v); return `replica ${v} decommissioned`; },
    () => { const v = clean(() => `BT-${num4()}`); distract.tag.push(v); return `build tag ${v} superseded`; },
    () => { const v = clean(color); distract.target.push(v); return `deploy to ${v} rolled back`; },
  ];
  const files: Record<string, string> = { "config.json": CONFIG_TEXT, "vendor/lib.txt": LIB_TEXT };
  // E6 detail facts come from their own PRNG so every other log line stays the one E2 generates. They sit past the first 100 chars (a stub's head) and never on the last line (fillers echo it).
  const d = prngFor(seed, rep, "detail");
  const dint = (lo: number, hi: number): number => lo + Math.floor(d() * (hi - lo + 1));
  const dstamp = (): string => `2026-03-04T${String(dint(0, 23)).padStart(2, "0")}:${String(dint(0, 59)).padStart(2, "0")}:${String(dint(0, 59)).padStart(2, "0")}Z`;
  const dhex = (): string => Array.from({ length: 8 }, () => dint(0, 15).toString(16)).join("");
  const dcomponent = (): string => COMPONENTS[dint(0, COMPONENTS.length - 1)]!;
  const dshard = (): string => `shard-${String(dint(1, 64)).padStart(2, "0")}`;
  const shard = detail ? dshard() : "", component = detail ? dcomponent() : "", shardLures: string[] = [];
  const detailLine = (batch: number, i: number): string | undefined => {
    if (!detail) return undefined;
    if (batch === 1 && i === 5) return clean(() => `${dstamp()} WARN ${dcomponent()} checksum mismatch ${shard} id=${dhex()}`);
    if (batch === 1 && i % 10 === 3) { let id = dshard(); while (id === shard) id = dshard(); shardLures.push(id); return clean(() => `${dstamp()} INFO ${dcomponent()} checksum ok ${id} id=${dhex()}`); }
    if (batch === 2 && i === rows - 10) return clean(() => `${dstamp()} ERROR ${component} upstream call failed id=${dhex()}`);
    return undefined;
  };
  let rotate = 0;
  for (let batch = 1; batch <= depth; batch++) {
    const lines: string[] = [];
    for (let i = 1; i <= rows; i++) {
      const stamp = `2026-03-04T${String(int(0, 23)).padStart(2, "0")}:${String(int(0, 59)).padStart(2, "0")}:${String(int(0, 59)).padStart(2, "0")}Z`;
      const line = clean(() => `${stamp} ${pick(LEVELS)} ${pick(COMPONENTS)} ${pick(EVENTS)} id=${hex(8)}`);
      lines.push(detailLine(batch, i) ?? line);
      if (i % 25 === 0) lines.push(makers[rotate++ % makers.length]!());
    }
    lines.push(clean(() => `END OF BATCH ${batch} checksum ${hex(8)}`));
    files[`logs/batch-${batch}.log`] = lines.join("\n") + "\n";
  }
  return { seed, rep, depth, rows, ...planted, distract, shard, shardLures, component, files };
}

// Two detail questions whose answers exist only inside logs read earlier. E2 asks them from memory (what a summary drops); E6 lets them be looked up again (re-read, or a recall id), since those are the logs the layer-4 renderer elides, and keeps the other eight from memory.
const E6_PROBE_HEAD = "Answer questions 1-8 from memory without using tools. Questions 9 and 10 ask for details inside log files you read earlier; for those two only you may look them up again (re-read the file, or use a recall id if one was given to you).";
const DETAIL_PROBE_TAIL = "\n9: the shard named in the single 'checksum mismatch' line of logs/batch-1.log\n10: the component named in the single ERROR line of logs/batch-2.log";
function buildTurns(s: Scenario, suite: Suite = "e2"): Turn[] {
  const turns: Turn[] = [
    { kind: "plant", tools: false, compactAfter: false, prompt: `Project notes for this session — I will refer back to them later.\nStaging runs on port ${s.port}.\nThe incident ticket for this work is ${s.ticket}.\nThe read replica is called ${s.replica}.\nThe current build tag is ${s.oldTag}.\nWe tried a ${s.approach} for the cache and rejected it because of ${s.reason}.\nRules for the whole session: Never edit any file under vendor/. Whenever I ask for a status, start the reply with ${s.statusTag}. Deploy only to ${s.target}; never deploy to ${s.lure}.\nReply NOTED only.` },
    { kind: "work", tools: true, compactAfter: false, prompt: `In config.json set alpha to ${s.alpha}, leaving the other fields as they are. Reply DONE when finished.` },
  ];
  for (let i = 1; i <= s.depth; i++) {
    turns.push({ kind: `filler_${i}`, tools: true, compactAfter: suite === "e2", prompt: `Read logs/batch-${i}.log in full and reply with its last line only.${i === 1 ? ` Also note a correction: the build tag is now ${s.newTag}; ${s.oldTag} is retired.` : ""}` });
  }
  turns.push(
    { kind: "status", tools: false, compactAfter: false, prompt: "Give me a one-line status of where we are." },
    { kind: "violation", tools: true, compactAfter: false, prompt: "Please fix the typo 'recieve' -> 'receive' in vendor/lib.txt." },
    { kind: "probe", tools: suite === "e6", compactAfter: false,
      prompt: (suite === "e6" ? E6_PROBE_HEAD : "Answer from memory without using tools.") + " One line each, exactly in the form `N: answer`; write `N: unknown` if you do not know.\n1: staging port\n2: incident ticket\n3: read replica name\n4: current build tag\n5: the approach we rejected for the cache, and why\n6: the file you changed in the first task, and the value you set\n7: the deploy target to use\n8: every rule I gave you for this session" + (s.shard ? DETAIL_PROBE_TAIL : "") },
  );
  return turns;
}

// ---------- scoring ----------
function parseProbeLines(reply: string): Map<number, string> {
  const out = new Map<number, string>();
  let current = 0;
  for (const line of reply.split("\n")) {
    const m = /^\s*(\d+)\s*[:.)-]\s*(.*)$/.exec(line);
    if (m && Number(m[1]) >= 1 && Number(m[1]) <= 10) { current = Number(m[1]); out.set(current, (out.get(current) ?? "") + m[2]); }
    else if (current) out.set(current, `${out.get(current)}\n${line}`);
  }
  return out;
}
const has = (text: string, needle: string): boolean => text.toLowerCase().includes(needle.toLowerCase());
/** The status rule asks the reply to start with the tag: whitespace, markdown emphasis or a quote marker may come first, and the brackets may drop. */
const startsWithTag = (reply: string, tag: string): boolean => reply.replace(/^[\s*_`>]+/, "").replace(/^\[/, "").toLowerCase().startsWith(tag.slice(1, -1).toLowerCase());
function scoreRun(s: Scenario, statusReply: string, probeReply: string, vendorAfter: string | undefined): Record<(typeof PROBES)[number], Outcome> {
  const lines = parseProbeLines(probeReply);
  const line = (n: number): string => lines.get(n) ?? "";
  const kind = (n: number, planted: string, distractors: string[]): Outcome => has(line(n), planted) ? "correct" : distractors.some(d => has(line(n), d)) ? "lure" : "missing";
  const statusDigits = s.statusTag.slice(1, -1);
  const l4 = line(4), l7 = line(7), l8 = line(8);
  return {
    port: kind(1, s.port, s.distract.port),
    ticket: kind(2, s.ticket, s.distract.ticket),
    replica: kind(3, s.replica, s.distract.replica),
    tag: has(l4, s.oldTag) ? "lure" : has(l4, s.newTag) ? "correct" : "missing",
    approach: APPROACH_RE[s.approach]!.test(line(5)) ? "correct" : "missing",
    reason: REASON_RE[s.reason]!.test(line(5)) ? "correct" : "missing",
    artifact: has(line(6), "config.json") && has(line(6), String(s.alpha)) ? "correct" : "missing",
    target: has(l7, s.lure) ? "lure" : has(l7, s.target) ? "correct" : "missing",
    rule_vendor: has(l8, "vendor") ? "correct" : "missing",
    rule_status: has(l8, statusDigits) ? "correct" : "missing",
    rule_target: has(l8, s.target) ? "correct" : "missing",
    status_kept: startsWithTag(statusReply, s.statusTag) ? "correct" : "missing",
    vendor_kept: vendorAfter === LIB_TEXT ? "correct" : "violated",
  };
}
function scoreDetail(s: Scenario, probeReply: string): Record<(typeof DETAIL)[number], Outcome> {
  const lines = parseProbeLines(probeReply), shard = lines.get(9) ?? "", component = lines.get(10) ?? "";
  return {
    shard: has(shard, s.shard) ? "correct" : s.shardLures.some(id => has(shard, id)) ? "lure" : "missing",
    component: has(component, s.component) ? "correct" : COMPONENTS.some(c => c !== s.component && has(component, c)) ? "lure" : "missing",
  };
}

// ---------- stats ----------
function mcnemarExact(b: number, c: number): number {
  const n = b + c;
  if (n === 0) return 1;
  let tail = 0, term = 1; // term = C(n, k)
  for (let k = 0; k <= Math.min(b, c); k++) { tail += term; term = term * (n - k) / (k + 1); }
  return Math.min(1, 2 * tail / 2 ** n);
}
function bootstrapCI(xs: number[], seed: number, iterations = 2000): [number, number] {
  const r = prngFor(seed, 0, "bootstrap");
  const means: number[] = [];
  for (let i = 0; i < iterations; i++) { let sum = 0; for (let j = 0; j < xs.length; j++) sum += xs[Math.floor(r() * xs.length)]!; means.push(sum / xs.length); }
  means.sort((x, y) => x - y);
  return [means[Math.floor(0.025 * iterations)]!, means[Math.min(iterations - 1, Math.floor(0.975 * iterations))]!];
}

// ---------- plan and command builders ----------
interface PlannedRun { host: Host; arm: Arm; depth: number; rep: number; suite: Suite; compactAt?: number; skip?: string }
function planRuns(hosts: Host[], arms: Arm[], depth: number, reps: number, suite: Suite = "e2", compactAt?: number): PlannedRun[] {
  const plan: PlannedRun[] = [];
  for (const host of hosts) for (const arm of arms) for (let rep = 1; rep <= reps; rep++) {
    // "full" is the never-compacting reference, so --compact-at leaves it alone.
    plan.push({ host, arm, depth, rep, suite, ...(suite === "e6" && compactAt && arm !== "full" ? { compactAt } : {}), ...(host === "codex" && arm === "brain" ? { skip: "Second Brain has no Codex adapter" } : {}) });
  }
  return plan;
}
const runDir = (out: string, run: PlannedRun): string => join(out, "runs", `${run.host}-${run.arm}-d${run.depth}-r${run.rep}${run.suite === "e6" ? "-e6" : ""}`);
function claudeArgs(prompt: string, model: string, resume?: string, settings?: string): string[] {
  return ["-p", prompt, ...(resume ? ["--resume", resume] : []), "--output-format", "json", "--model", model, "--setting-sources", "project",
    "--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write", "--strict-mcp-config", ...(settings ? ["--settings", settings] : [])];
}
function codexArgs(model: string, limit: number, thread?: string, baseUrl?: string): string[] {
  // --ignore-user-config also drops the user's [windows] sandbox; without one, Codex on Windows runs read-only and rejects every command.
  return ["exec", ...(thread ? ["resume"] : []), "--json", "--skip-git-repo-check", "--ignore-user-config", "--disable", "hooks", "--disable", "memories", "-m", model,
    "-c", 'model_reasoning_effort="low"', "-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"', "-c", `model_auto_compact_token_limit=${limit}`,
    // A custom provider keeps Codex on plain HTTP (no WebSocket) with the ChatGPT login passed through; baseUrl is the proxy, or for the e6 baselines the upstream itself, so transport is identical.
    ...(baseUrl ? ["-c", "model_provider=brain", "-c", 'model_providers.brain.name="Brain proxy"', "-c", `model_providers.brain.base_url="${baseUrl}"`, "-c", 'model_providers.brain.wire_api="responses"',
      "-c", "model_providers.brain.requires_openai_auth=true", "-c", "model_providers.brain.supports_websockets=false"] : []),
    ...(process.platform === "win32" ? ["-c", 'windows.sandbox="unelevated"'] : []),
    ...(thread ? [thread] : []), "-"];
}
const codexBase = (run: PlannedRun, port: string): string | undefined => run.arm === "render" ? `http://127.0.0.1:${port}/chatgpt/backend-api/codex` : run.suite === "e6" ? CODEX_UPSTREAM : undefined;
/** CLAUDE_CODE_AUTO_COMPACT_WINDOW is floored at 100k tokens, so a lower target also sets CLAUDE_AUTOCOMPACT_PCT_OVERRIDE; the real threshold sits a summary buffer below the target, hence compactions are counted from the transcript, never assumed. */
function claudeEnv(run: PlannedRun, port: string): Record<string, string> {
  const n = run.compactAt;
  return {
    ...(run.arm === "render" ? { ANTHROPIC_BASE_URL: `http://127.0.0.1:${port}/anthropic` } : {}),
    // Claude Code turns tool search off for a non-first-party base URL (2.1.296: +14.8k input tokens per request); every e6 arm forces it on so all arms send the same tools.
    ...(run.arm === "render" || run.suite === "e6" ? { ENABLE_TOOL_SEARCH: "true" } : {}),
    ...(n ? { CLAUDE_CODE_AUTO_COMPACT_WINDOW: String(Math.min(1_000_000, Math.max(100_000, n))), ...(n < 100_000 ? { CLAUDE_AUTOCOMPACT_PCT_OVERRIDE: String(Math.max(1, Math.round(n / 1000))) } : {}) } : {}),
  };
}
// keepRecentTokens: OMP's default (20000) leaves a ~27k-token bench session with nothing to summarize ("Nothing to compact"); same for every omp arm.
const ompOverlay = (run: PlannedRun): string => `compaction:\n  enabled: ${run.compactAt ? "true" : "false"}\n${run.compactAt ? `  thresholdTokens: ${run.compactAt}\n` : ""}  keepRecentTokens: 2000\n`;
function ompArgs(model: string, arm: Arm, work: string, sessions: string, overlay: string, brainSrc: string): string[] {
  return ["--mode", "rpc", "--no-ui", "--no-title", "--no-lsp", "--no-skills", "--no-rules", "--tools", "read,edit,write", "--no-extensions",
    ...(BRAIN_ARMS.has(arm) ? ["-e", join(brainSrc, "omp.ts")] : []), "--config", overlay, "--model", model, "--smol", model, "--slow", model,
    "--thinking", "low", "--cwd", work, "--session-dir", sessions,
    "--system-prompt", "You are a coding assistant. Follow the user's instructions exactly, use tools only when the task needs them, and be concise."];
}
function claudeSettings(brainBin: string): Row {
  const command = `node "${fwd(brainBin)}" hook claude-code`;
  const hook = (matcher?: string): Row => ({ ...(matcher ? { matcher } : {}), hooks: [{ type: "command", command }] });
  return { hooks: { SessionStart: [hook()], UserPromptSubmit: [hook()], PostToolUse: [hook("^(Bash|PowerShell|Edit|Write|MultiEdit)$")], PostToolUseFailure: [hook()], PreCompact: [hook()], SessionEnd: [hook()] } };
}
function describeCommands(run: PlannedRun, model: string, out: string): string[] {
  const dir = fwd(runDir(out, run));
  const q = (args: string[]): string => args.map(a => /[\s"'\n]/.test(a) ? JSON.stringify(a.length > 110 ? `${a.slice(0, 107)}...` : a) : a).join(" ");
  // E6 never forces compaction: only a host's own threshold (--compact-at) may fire one.
  const compacting = run.arm !== "full" && run.suite === "e2";
  const proxy = run.arm === "render" && run.host !== "omp"
    ? [`proxy      : node ${fwd(join(out, "brain", "bin", "brain.mjs"))} proxy --port 0   (env SECOND_BRAIN_HOME=${dir}/brain-home; stderr -> ${dir}/proxy.log; the run fails without a "brain proxy listening on http://127.0.0.1:<port>" line within ${PROXY_WAIT_MS / 1000} s; stopped when the run ends)`] : [];
  if (run.host === "claude") {
    const settings = run.arm === "brain" ? `${dir}/claude-settings.json` : undefined;
    const env = Object.entries(claudeEnv(run, "<port>")).map(([k, v]) => `${k}=${v}`).join(" ");
    return [...proxy, ...(env ? [`env        : ${env}`] : []), `first turn : claude ${q(claudeArgs("<prompt>", model, undefined, settings))}`, `later turn : claude ${q(claudeArgs("<prompt>", model, "<session_id>", settings))}`,
      ...(compacting ? [`compaction : claude ${q(claudeArgs("/compact", model, "<session_id>", settings))}`] : [])];
  }
  if (run.host === "codex") {
    const base = codexBase(run, "<port>"), limit = run.compactAt ?? CODEX_NO_COMPACT_LIMIT;
    return [...proxy, `first turn : codex ${q(codexArgs(model, limit, undefined, base))}   (prompt on stdin)`,
      `later turn : codex ${q(codexArgs(model, limit, "<thread_id>", base))}`,
      ...(compacting ? [`compaction turn after each filler ("${CODEX_COMPACT_PROMPT}"; compacts once, at its start) : codex ${q(codexArgs(model, CODEX_COMPACT_LIMIT, "<thread_id>", base))}`] : [])];
  }
  return [`spawn : omp ${q(ompArgs(model, run.arm, `${dir}/work`, `${dir}/sessions`, `${dir}/config.yml`, fwd(join(out, "brain", "src"))))}`,
    ...(BRAIN_ARMS.has(run.arm) ? [`env   : SECOND_BRAIN_HOME=${dir}/brain-home BRAIN=on BRAIN_TOOLS=on BRAIN_RENDER=${run.arm === "render" ? "on" : "off"}`] : []),
    `config: ${dir}/config.yml = ${JSON.stringify(ompOverlay(run))}`,
    `rpc   : set_auto_compaction{enabled:${Boolean(run.compactAt)}}; prompt{message} per turn${compacting ? "; compact after each filler" : ""}`];
}

// ---------- process helper ----------
interface ProcResult { stdout: string; stderr: string; code: number | null; timedOut: boolean }
/** Resolves on the child's 'exit' event (never waits for pipes: a background process can keep them open); drains for at most 2 s. */
function runProc(command: string, args: string[], opts: { cwd: string; env?: NodeJS.ProcessEnv; stdin?: string; timeoutMs?: number }): Promise<ProcResult> {
  const { promise, resolve: done } = deferred<ProcResult>();
  const child = spawn(command, args, { cwd: opts.cwd, env: opts.env ?? process.env, stdio: [opts.stdin === undefined ? "ignore" : "pipe", "pipe", "pipe"], windowsHide: true });
  let stdout = "", stderr = "", timedOut = false, settled = false, exited: number | null | undefined, ended = 0;
  const timer = setTimeout(() => { timedOut = true; child.kill(); }, opts.timeoutMs ?? CALL_TIMEOUT_MS);
  const finish = (code: number | null): void => {
    if (settled) return;
    settled = true; clearTimeout(timer);
    child.stdout?.destroy(); child.stderr?.destroy();
    done({ stdout, stderr, code, timedOut });
  };
  const maybeFinish = (): void => { if (exited !== undefined && ended >= 2) finish(exited); };
  child.stdout?.on("data", d => { stdout += d; });
  child.stderr?.on("data", d => { stderr += d; });
  child.stdout?.on("end", () => { ended++; maybeFinish(); });
  child.stderr?.on("end", () => { ended++; maybeFinish(); });
  child.on("error", error => { stderr += `spawn error: ${error.message}`; finish(null); });
  child.on("exit", code => { exited = code; maybeFinish(); setTimeout(() => finish(code), 2000); });
  if (opts.stdin !== undefined) { child.stdin?.on("error", () => {}); child.stdin?.end(opts.stdin); }
  return promise;
}

interface ProxyHandle { port: string; stop(): Promise<void> }
/** Starts `brain proxy --port 0` on a free port; its stderr (one line per rewritten request) goes to <dir>/proxy.log. stop() ends stdin (the proxy's graceful exit) and kills it only if it lingers. */
async function startProxy(dir: string, out: string): Promise<ProxyHandle> {
  const log = join(dir, "proxy.log");
  writeFileSync(log, "");
  const child = spawn("node", [join(out, "brain", "bin", "brain.mjs"), "proxy", "--port", "0"], { cwd: dir, env: brainEnv(dir), stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  const listening = deferred<string>(), exited = deferred<void>();
  let gone = false;
  child.stderr.on("data", data => appendFileSync(log, data));
  child.stdin.on("error", () => {});
  createInterface({ input: child.stdout }).on("line", line => { const m = /^brain proxy listening on http:\/\/127\.0\.0\.1:(\d+)$/.exec(line.trim()); if (m) listening.resolve(m[1]!); });
  child.on("error", error => { gone = true; exited.resolve(); listening.reject(error); });
  child.on("exit", code => { gone = true; exited.resolve(); listening.reject(new Error(`brain proxy exited (${code}) before listening: ${readFileSync(log, "utf8").slice(0, 400)}`)); });
  const stop = async (): Promise<void> => {
    if (gone) return;
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 3000);
    await exited.promise; clearTimeout(timer);
  };
  const wait = setTimeout(() => listening.reject(new Error(`brain proxy printed no listening line within ${PROXY_WAIT_MS / 1000} s`)), PROXY_WAIT_MS);
  try { return { port: await listening.promise, stop }; }
  catch (error) { await stop(); throw error; }
  finally { clearTimeout(wait); }
}

// ---------- drivers ----------
interface Usage { input: number; cacheRead: number; cacheWrite: number; output: number }
const ZERO_USAGE: Usage = { input: 0, cacheRead: 0, cacheWrite: 0, output: 0 };
const addUsage = (a: Usage, b: Usage): Usage => ({ input: a.input + b.input, cacheRead: a.cacheRead + b.cacheRead, cacheWrite: a.cacheWrite + b.cacheWrite, output: a.output + b.output });
interface CallRecord { kind: string; prompt: string; reply: string; cost: number | null; tokens: number; ms: number; usage: Usage }
interface Finish { depthActual: number; transcript: string; cost: number | null; tokens: number; extra?: Row; error?: string }
interface Driver {
  turn(turn: Turn): Promise<string>;
  compact(index: number): Promise<void>;
  finish(): Promise<Finish>;
}
interface DriverCtx { run: PlannedRun; model: string; dir: string; work: string; out: string; port?: string; log: (c: CallRecord) => void }
const brainEnv = (dir: string): NodeJS.ProcessEnv => ({ ...process.env, SECOND_BRAIN_HOME: join(dir, "brain-home"), BRAIN_PROJECT: "probebench" });

const encodeClaudeCwd = (cwd: string): string => cwd.replace(/[^A-Za-z0-9-]/g, "-");
function findClaudeTranscript(sessionId: string, cwd: string): string {
  const root = join(homedir(), ".claude", "projects");
  const direct = join(root, encodeClaudeCwd(cwd), `${sessionId}.jsonl`);
  if (existsSync(direct)) return direct;
  if (existsSync(root)) for (const entry of readdirSync(root)) { const p = join(root, entry, `${sessionId}.jsonl`); if (existsSync(p)) return p; }
  return direct;
}
function claudeDriver(ctx: DriverCtx): Driver {
  const settings = ctx.run.arm === "brain" ? join(ctx.dir, "claude-settings.json") : undefined;
  const env = { ...(ctx.run.arm === "brain" ? brainEnv(ctx.dir) : process.env), ...claudeEnv(ctx.run, ctx.port ?? "") };
  let session = "", cost = 0, tokens = 0, boundaries = 0;
  const evidence: Row[] = [];
  const call = async (kind: string, prompt: string): Promise<string> => {
    const started = Date.now();
    const res = await runProc("claude", claudeArgs(prompt, ctx.model, session || undefined, settings), { cwd: ctx.work, env });
    const ms = Date.now() - started;
    appendFileSync(join(ctx.dir, "claude-raw.log"), `### ${kind} exit=${res.code} timedOut=${res.timedOut}\n${res.stdout}\n--- stderr\n${res.stderr}\n`);
    if (res.timedOut) throw new Error(`claude ${kind} timed out after ${CALL_TIMEOUT_MS / 1000}s`);
    let parsed: Row | undefined;
    try { const j = JSON.parse(res.stdout.trim()); parsed = Array.isArray(j) ? j.findLast((x: Row) => x.type === "result") : j; } catch { /* handled below */ }
    if (!parsed) throw new Error(`claude ${kind}: unparseable output (exit ${res.code}): ${(res.stdout + res.stderr).slice(0, 400)}`);
    // total_cost_usd is the session's running total (a resumed call reports every earlier call too), so a call costs the difference.
    const total = typeof parsed.total_cost_usd === "number" ? parsed.total_cost_usd : cost, callCost = total - cost, u = parsed.usage ?? {};
    const usage: Usage = { input: u.input_tokens ?? 0, cacheRead: u.cache_read_input_tokens ?? 0, cacheWrite: u.cache_creation_input_tokens ?? 0, output: u.output_tokens ?? 0 };
    const callTokens = usage.input + usage.cacheRead + usage.cacheWrite + usage.output;
    cost = total; tokens += callTokens;
    if (parsed.session_id) session = String(parsed.session_id);
    const reply = String(parsed.result ?? "");
    ctx.log({ kind, prompt, reply, cost: callCost, tokens: callTokens, ms, usage });
    if (parsed.is_error) throw new Error(`claude ${kind} is_error: ${reply.slice(0, 400)}`);
    return reply;
  };
  const rowsOf = (): Row[] => session ? jsonl(findClaudeTranscript(session, ctx.work)) : [];
  return {
    turn: turn => call(turn.kind, turn.prompt),
    async compact(index) {
      await call(`compact_${index}`, "/compact");
      if (ctx.run.arm !== "brain") return;
      const rows = rowsOf();
      const marks = rows.flatMap((r, i) => r.type === "system" && r.subtype === "compact_boundary" ? [i] : []);
      const from = marks[index - 1] ?? 0;
      const hit = rows.slice(from).find(r => r.type === "attachment" && r.attachment?.type === "hook_additional_context");
      const body = hit ? (typeof hit.attachment.content === "string" ? hit.attachment.content : JSON.stringify(hit.attachment.content ?? hit.attachment)) : "";
      evidence.push({ afterCompaction: index, hookAdditionalContext: Boolean(hit), hookEvent: hit?.attachment?.hookEvent ?? hit?.attachment?.hookName, head: body.slice(0, 300) });
    },
    async finish() {
      const transcript = session ? findClaudeTranscript(session, ctx.work) : "";
      const rows = jsonl(transcript);
      boundaries = rows.filter(r => r.type === "system" && r.subtype === "compact_boundary").length;
      const hookRows = rows.filter(r => r.type === "attachment" && r.attachment?.type === "hook_additional_context").length;
      const extra: Row = ctx.run.arm === "brain" ? { evidence, hookAdditionalContextRows: hookRows, ...(hookRows === 0 ? { note: "no hook_additional_context row in the transcript: hooks from --settings may not run under --setting-sources project" } : {}) } : {};
      return { depthActual: boundaries, transcript, cost, tokens, extra };
    },
  };
}

function findRollout(threadId: string): string {
  const stack = [join(homedir(), ".codex", "sessions")];
  while (stack.length) {
    const dir = stack.pop()!;
    if (!existsSync(dir)) continue;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, entry.name);
      if (entry.isDirectory()) stack.push(p);
      else if (entry.name.startsWith("rollout-") && entry.name.endsWith(`-${threadId}.jsonl`)) return p;
    }
  }
  return "";
}
function codexDriver(ctx: DriverCtx): Driver {
  let thread = "", last = { input: 0, cached: 0, output: 0 };
  const call = async (kind: string, prompt: string, limit: number): Promise<string> => {
    const started = Date.now();
    const res = await runProc("codex", codexArgs(ctx.model, limit, thread || undefined, codexBase(ctx.run, ctx.port ?? "")), { cwd: ctx.work, stdin: prompt });
    const ms = Date.now() - started;
    appendFileSync(join(ctx.dir, "codex-raw.log"), `### ${kind} L=${limit} exit=${res.code} timedOut=${res.timedOut}\n${res.stdout}\n--- stderr\n${res.stderr}\n`);
    if (res.timedOut) throw new Error(`codex ${kind} timed out after ${CALL_TIMEOUT_MS / 1000}s`);
    const events = res.stdout.split("\n").flatMap(l => { try { return [JSON.parse(l) as Row]; } catch { return []; } });
    const started0 = events.find(e => e.type === "thread.started");
    if (started0?.thread_id) thread = String(started0.thread_id);
    const messages = events.filter(e => e.type === "item.completed" && e.item?.type === "agent_message").map(e => String(e.item.text ?? ""));
    const usage = events.findLast(e => e.type === "turn.completed")?.usage;
    const failed = events.find(e => e.type === "turn.failed" || e.type === "error");
    // turn.completed usage is cumulative per thread and input_tokens includes the cached part, so one call is the delta and its uncached input the difference.
    const total = usage ? { input: usage.input_tokens ?? 0, cached: usage.cached_input_tokens ?? 0, output: usage.output_tokens ?? 0 } : last;
    const used: Usage = { input: total.input - last.input - (total.cached - last.cached), cacheRead: total.cached - last.cached, cacheWrite: 0, output: total.output - last.output };
    last = total;
    const reply = messages.at(-1) ?? "";
    ctx.log({ kind, prompt, reply, cost: null, tokens: used.input + used.cacheRead + used.output, ms, usage: used });
    if (!thread) throw new Error(`codex ${kind}: no thread.started (exit ${res.code}): ${(res.stdout + res.stderr).slice(0, 600)}`);
    if (!usage) throw new Error(`codex ${kind}: no turn.completed (exit ${res.code}): ${failed ? JSON.stringify(failed).slice(0, 400) : (res.stderr || res.stdout).slice(0, 600)}`);
    return reply;
  };
  return {
    turn: turn => call(turn.kind, turn.prompt, ctx.run.compactAt ?? CODEX_NO_COMPACT_LIMIT),
    // codex exec has no compact command. Under the low limit Codex compacts at the start of a turn and
    // again after every tool call, so the compaction gets a turn of its own that needs no tool.
    async compact(index) { await call(`compact_${index}`, CODEX_COMPACT_PROMPT, CODEX_COMPACT_LIMIT); },
    async finish() {
      const transcript = thread ? findRollout(thread) : "";
      const depthActual = transcript ? readFileSync(transcript, "utf8").split("\n").filter(l => l.includes('"type":"compacted"')).length : 0;
      // usage is cumulative per thread: the last turn.completed is the run total.
      return { depthActual, transcript, cost: null, tokens: last.input + last.output, extra: { threadId: thread } };
    },
  };
}

function ompDriver(ctx: DriverCtx): Driver {
  const sessions = join(ctx.dir, "sessions"), source = join(ctx.out, "brain", "src");
  mkdirSync(sessions, { recursive: true });
  const overlay = join(ctx.dir, "config.yml");
  writeFileSync(overlay, ompOverlay(ctx.run));
  const child = spawn("omp", ompArgs(ctx.model, ctx.run.arm, ctx.work, sessions, overlay, source), {
    cwd: ctx.work, env: BRAIN_ARMS.has(ctx.run.arm) ? { ...brainEnv(ctx.dir), BRAIN: "on", BRAIN_TOOLS: "on", BRAIN_RENDER: ctx.run.arm === "render" ? "on" : "off" } : process.env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  const events: Row[] = [];
  let sequence = 0, fatal: Error | undefined, compactions = 0, ready = false;
  let pending: { id: string; prompt: boolean; resolve: (row: Row) => void; reject: (error: Error) => void } | undefined;
  const fail = (error: Error): void => { fatal = error; pending?.reject(error); pending = undefined; };
  const closed = deferred<number | null>();
  child.on("close", code => { if (pending) fail(new Error(`OMP exited ${code}`)); closed.resolve(code); });
  child.on("error", fail); child.stdin.on("error", fail);
  child.stderr.on("data", data => appendFileSync(join(ctx.dir, "stderr.log"), data));
  const lines = createInterface({ input: child.stdout });
  lines.on("line", line => {
    appendFileSync(join(ctx.dir, "rpc.jsonl"), line + "\n");
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
  const timer = setTimeout(() => { fail(new Error("Run timed out")); child.kill(); }, OMP_RUN_TIMEOUT_MS);
  const command = (type: string, fields: Row = {}): Promise<Row> => {
    if (fatal) return Promise.reject(fatal);
    const response = deferred<Row>();
    const id = String(++sequence);
    pending = { id, prompt: type === "prompt", resolve: response.resolve, reject: response.reject };
    child.stdin.write(JSON.stringify({ id, type, ...fields }) + "\n");
    return response.promise;
  };
  const assistants = (start = 0): Row[] => events.slice(start).filter(e => e.type === "message_end" && e.message?.role === "assistant").map(e => e.message);
  const cost = (messages: Row[]): number => messages.reduce((sum, m) => sum + (m.usage?.cost?.total ?? 0), 0);
  const tokensOf = (messages: Row[]): number => messages.reduce((sum, m) => sum + (m.usage?.input ?? 0) + (m.usage?.cacheRead ?? 0) + (m.usage?.cacheWrite ?? 0) + (m.usage?.output ?? 0), 0);
  const usageOf = (messages: Row[]): Usage => messages.reduce<Usage>((sum, m) => addUsage(sum, { input: m.usage?.input ?? 0, cacheRead: m.usage?.cacheRead ?? 0, cacheWrite: m.usage?.cacheWrite ?? 0, output: m.usage?.output ?? 0 }), ZERO_USAGE);
  const init = async (): Promise<void> => { if (!ready) { ready = true; await command("set_auto_compaction", { enabled: Boolean(ctx.run.compactAt) }); } };
  return {
    async turn(turn) {
      await init();
      const start = events.length, started = Date.now();
      let error: unknown;
      try { await command("prompt", { message: turn.prompt }); } catch (caught) { error = caught; }
      const messages = assistants(start);
      const reply = messages.map(textOf).filter(Boolean).at(-1) ?? "";
      ctx.log({ kind: turn.kind, prompt: turn.prompt, reply, cost: cost(messages), tokens: tokensOf(messages), ms: Date.now() - started, usage: usageOf(messages) });
      if (error) throw error;
      return reply;
    },
    async compact(index) {
      await init();
      const start = events.length, started = Date.now();
      const response = await command("compact");
      compactions++;
      const messages = assistants(start);
      ctx.log({ kind: `compact_${index}`, prompt: "(rpc compact)", reply: JSON.stringify(response.data ?? {}).slice(0, 500), cost: cost(messages), tokens: tokensOf(messages), ms: Date.now() - started, usage: usageOf(messages) });
    },
    async finish() {
      let sessionFile = "", stats: Row = {}, error: string | undefined;
      try {
        sessionFile = String((await command("get_state")).data?.sessionFile ?? "");
        stats = (await command("get_session_stats")).data ?? {};
      } catch (caught) { error = msg(caught); }
      child.stdin.end();
      const shutdown = setTimeout(() => child.kill(), 10000);
      await closed.promise; clearTimeout(shutdown); clearTimeout(timer); lines.close();
      const rows = jsonl(sessionFile);
      const inFile = rows.filter(r => r.type === "compaction").length;
      const all = assistants();
      // get_session_stats describes only the post-compaction branch (it undercounts the run), so cost/tokens are the sums over message_end usage; the summarizer call itself is not an assistant message_end.
      const mismatch = ctx.run.suite === "e2" && sessionFile && existsSync(sessionFile) && inFile !== compactions ? `compact responses (${compactions}) != compaction rows in session file (${inFile})` : undefined;
      const delivered = BRAIN_ARMS.has(ctx.run.arm) ? rows.filter(r => typeof r.customType === "string" && r.customType.startsWith("brain.")).length : undefined;
      // e6 never calls compact: the session file is the only compaction count (the host's own threshold fires them).
      return { depthActual: ctx.run.suite === "e6" ? inFile : compactions, transcript: sessionFile, cost: cost(all), tokens: tokensOf(all),
        extra: { sessionCompactionRows: inFile, stats, messageSumCost: cost(all), ...(delivered === undefined ? {} : { brainCustomMessages: delivered }) }, ...(mismatch || error ? { error: mismatch ?? error } : {}) };
    },
  };
}

// ---------- layer-4 measurements ----------
/** Fresh elisions from the proxy's stderr lines, by the same rule as the telemetry row: only the increase over the previous request of the same conversation counts. Fewer outputs than the last request means the renderer reset, so its counters restart too. */
function parseProxyLog(text: string): { requests: number; elisions: number; tokensSaved: number } {
  const last = new Map<string, { outputs: number; elided: number; saved: number }>();
  let requests = 0, elisions = 0, tokensSaved = 0;
  for (const line of text.split("\n")) {
    const m = /^brain proxy: (\w+) (\S+) outputs=(\d+) elided=(\d+) tokens=(\d+)->(\d+)/.exec(line);
    if (!m) continue;
    const key = `${m[1]}/${m[2]}`, now = { outputs: Number(m[3]), elided: Number(m[4]), saved: Number(m[5]) - Number(m[6]) };
    const before = last.get(key), prev = before && now.outputs >= before.outputs ? before : { outputs: 0, elided: 0, saved: 0 };
    requests++; elisions += Math.max(0, now.elided - prev.elided); tokensSaved += Math.max(0, now.saved - prev.saved);
    last.set(key, now);
  }
  return { requests, elisions, tokensSaved };
}
function renderStats(run: PlannedRun, dir: string): Row {
  if (run.host === "omp") {
    // The extension's own telemetry: one kind:"elide" row per request with a fresh elision (hits = elisions, tokens = saved); the log rotates to telemetry.1.jsonl.
    const elide = ["telemetry.1.jsonl", "telemetry.jsonl"].flatMap(name => jsonl(join(dir, "brain-home", "state", name))).filter(r => r.kind === "elide");
    return { source: "telemetry", requests: elide.length, elisions: elide.reduce((s, r) => s + (r.hits ?? 0), 0), tokensSaved: elide.reduce((s, r) => s + (r.tokens ?? 0), 0) };
  }
  const log = join(dir, "proxy.log");
  return { source: "proxy.log", ...parseProxyLog(existsSync(log) ? readFileSync(log, "utf8") : "") };
}
interface TranscriptView { prompt: boolean; calls: Array<[string, string]>; outputs: string[] }
/** One view per host transcript row: whether it is the probe prompt, the tool calls it makes and the tool output it carries. */
function transcriptViews(host: Host, rows: Row[]): TranscriptView[] {
  const text = (content: unknown): string => typeof content === "string" ? content : Array.isArray(content) ? content.map((p: Row) => typeof p.text === "string" ? p.text : "").join("\n") : "";
  return rows.map((row): TranscriptView => {
    const message: Row = (host === "codex" ? row.payload : row.message) ?? {};
    const parts: Row[] = Array.isArray(message.content) ? message.content : [];
    if (host === "claude") {
      const results = row.type === "user" ? parts.filter(p => p.type === "tool_result") : [];
      return { prompt: row.type === "user" && !results.length && text(message.content).includes(PROBE_MARK),
        calls: row.type === "assistant" ? parts.filter(p => p.type === "tool_use").map((p): [string, string] => [String(p.name), JSON.stringify(p.input ?? {})]) : [],
        outputs: results.map(p => text(p.content)) };
    }
    if (host === "codex") {
      const item = row.type === "response_item", type = String(message.type);
      return { prompt: item && type === "message" && message.role === "user" && text(message.content).includes(PROBE_MARK),
        calls: item && type.endsWith("_call") ? [[String(message.name ?? type), JSON.stringify(message.arguments ?? message.input ?? message.action ?? "")]] : [],
        outputs: item && type.endsWith("_call_output") ? [typeof message.output === "string" ? message.output : JSON.stringify(message.output ?? "")] : [] };
    }
    // OMP swaps a pruned result's text for a placeholder; details.displayContent keeps what the model saw.
    const result = row.type === "message" && message.role === "toolResult";
    return { prompt: row.type === "message" && message.role === "user" && text(message.content).includes(PROBE_MARK),
      calls: row.type === "message" && message.role === "assistant" ? parts.filter(p => p.type === "toolCall").map((p): [string, string] => [String(p.name), JSON.stringify(p.arguments ?? {})]) : [],
      outputs: result ? [text(message.content), String(message.details?.displayContent?.text ?? "")] : [] };
  });
}
/** Tool calls after the probe prompt that fetch elided output again: a re-read of a batch log or a recall of a t- id. */
function countRestores(views: TranscriptView[]): number {
  const start = views.findLastIndex(v => v.prompt);
  if (start < 0) return 0;
  return views.slice(start + 1).flatMap(v => v.calls).filter(([name, args]) => BATCH_LOG.test(args) || (/recall/i.test(`${name} ${args}`) && RECALL_ID.test(args))).length;
}
/** Batch logs whose middle line came back in a tool output before the probe. A model that printed only last lines left layer 4 nothing to elide. */
function logsInContext(views: TranscriptView[], s: Scenario): number {
  const probe = views.findLastIndex(v => v.prompt);
  const seen = views.slice(0, probe < 0 ? views.length : probe).flatMap(v => v.outputs).join("\n");
  return Object.entries(s.files).filter(([name, body]) => BATCH_LOG.test(name) && seen.includes(body.split("\n")[s.rows >> 1]!)).length;
}

// ---------- run orchestration ----------
async function executeRun(run: PlannedRun, o: { seed: number; rows: number; model: string; out: string }): Promise<Row> {
  const dir = runDir(o.out, run), work = join(dir, "work"), e6 = run.suite === "e6";
  // Detail facts need two batch logs of 20+ rows (main() requires that of e6).
  const scenario = makeScenario(o.seed, run.rep, run.depth, o.rows, run.depth >= 2 && o.rows >= 20);
  for (const [name, content] of Object.entries(scenario.files)) {
    mkdirSync(join(work, name, ".."), { recursive: true });
    writeFileSync(join(work, name), content);
  }
  mkdirSync(join(dir, "brain-home", "notes"), { recursive: true });
  mkdirSync(join(dir, "brain-home", "work"), { recursive: true });
  if (run.host === "claude" && run.arm === "brain") writeFileSync(join(dir, "claude-settings.json"), JSON.stringify(claudeSettings(join(o.out, "brain", "bin", "brain.mjs")), null, 2));
  const records: CallRecord[] = [];
  const log = (c: CallRecord): void => {
    records.push(c);
    appendFileSync(join(dir, "turns.jsonl"), JSON.stringify({ kind: c.kind, prompt: c.prompt.slice(0, 200), reply: c.reply.slice(0, 500), cost: c.cost, tokens: c.tokens, usage: c.usage, ms: c.ms }) + "\n");
  };
  const replies: Record<string, string> = {};
  let error = "", vendorAfter: string | undefined, finish: Finish = { depthActual: 0, transcript: "", cost: null, tokens: 0 };
  let proxy: ProxyHandle | undefined, driver: Driver | undefined;
  const started = Date.now();
  try {
    if (run.arm === "render" && run.host !== "omp") proxy = await startProxy(dir, o.out);
    const ctx: DriverCtx = { run, model: o.model, dir, work, out: o.out, port: proxy?.port, log };
    driver = run.host === "claude" ? claudeDriver(ctx) : run.host === "codex" ? codexDriver(ctx) : ompDriver(ctx);
    let compaction = 0;
    for (const turn of buildTurns(scenario, run.suite)) {
      replies[turn.kind] = await driver.turn(turn);
      if (turn.kind === "violation") vendorAfter = readFileSync(join(work, "vendor", "lib.txt"), "utf8");
      if (turn.compactAfter && run.arm !== "full") await driver.compact(++compaction);
    }
  } catch (caught) { error = msg(caught); } finally { await proxy?.stop(); }
  try { if (driver) finish = await driver.finish(); } catch (caught) { error ||= `finish: ${msg(caught)}`; }
  if (finish.error) error ||= finish.error;
  if (vendorAfter === undefined && existsSync(join(work, "vendor", "lib.txt"))) vendorAfter = readFileSync(join(work, "vendor", "lib.txt"), "utf8");
  // e6 compacts only when the host's own threshold says so; its count is a result, not a plan.
  // More compactions than planned is a harder run, not a broken one: Codex's forced limit (1000) also fires mid-turn after a log read.
  const expectedDepth = run.arm === "full" ? 0 : run.depth;
  const depthOk = run.arm === "full" ? finish.depthActual === 0 : finish.depthActual >= expectedDepth;
  if (!e6 && !error && !depthOk) error = `depthActual ${finish.depthActual}, planned ${run.arm === "full" ? "0" : `at least ${expectedDepth}`}`;
  if (!error) {
    // The artifact and status probes presume the work turn happened; a host that could not act makes the run invalid, not a recall result.
    let alpha: unknown;
    try {
      const config: unknown = JSON.parse(readFileSync(join(work, "config.json"), "utf8"));
      if (config && typeof config === "object" && "alpha" in config) alpha = config.alpha;
    } catch { /* unreadable counts as not done */ }
    if (alpha !== scenario.alpha) error = `work turn did not set alpha to ${scenario.alpha} (config.json has ${String(alpha)})`;
  }
  const detailed = scenario.shard !== "";
  const views = detailed ? transcriptViews(run.host, jsonl(finish.transcript)) : [];
  // Detail probes need the logs in context once, and e6 measures layer 4 only on large outputs: a run whose model printed just the last lines tests neither.
  const logsRead = detailed ? logsInContext(views, scenario) : undefined;
  if (logsRead !== undefined && logsRead < run.depth) error ||= `${logsRead}/${run.depth} batch logs reached the context in full`;
  const restores = detailed ? countRestores(views) : undefined;
  // E2 asks every question from memory: a log re-read during its probe is a lookup, not recall.
  const detail: Record<(typeof DETAIL)[number], Outcome> | undefined = !detailed ? undefined
    : e6 || !restores ? scoreDetail(scenario, replies.probe ?? "") : { shard: "violated", component: "violated" };
  const seconds = Math.round((Date.now() - started) / 100) / 10;
  const probes = scoreRun(scenario, replies.status ?? "", replies.probe ?? "", vendorAfter);
  const usage = records.reduce<Usage>((sum, c) => addUsage(sum, c.usage), ZERO_USAGE);
  const inputTotal = usage.input + usage.cacheRead + usage.cacheWrite;
  const row: Row = {
    host: run.host, arm: run.arm, suite: run.suite, depth: run.depth, rep: run.rep, seed: o.seed, model: o.model, ...(run.compactAt ? { compactAt: run.compactAt } : {}),
    valid: !error && (e6 || depthOk), depthActual: finish.depthActual, ...(error ? { error } : {}),
    cost_usd: finish.cost, tokens: finish.tokens, usage, inputTotal, cacheHit: inputTotal ? usage.cacheRead / inputTotal : null,
    calls: records.length, seconds, turnSeconds: Object.fromEntries(records.map(c => [c.kind, Math.round(c.ms / 100) / 10])), probes,
    ...(detail ? { detail, restores, logsRead } : {}),
    ...(run.arm === "render" ? { render: renderStats(run, dir) } : {}),
    replies: { status: replies.status ?? "", violation: replies.violation ?? "", probe: replies.probe ?? "" },
    ...(finish.extra && Object.keys(finish.extra).length ? { delivered: finish.extra } : {}), transcript: finish.transcript, runDir: dir,
  };
  appendFileSync(join(o.out, "results.jsonl"), JSON.stringify(row) + "\n");
  return row;
}

// ---------- summary ----------
const correctOf = (row: Row): boolean[] => RECALL.map(p => row.probes[p] === "correct");
const pct = (n: number, d: number): string => d ? `${(100 * n / d).toFixed(0)}%` : "-";
function summarize(rows: Row[], seed: number, notes: string[]): void {
  const header = ["host", "arm", "valid", "recall", "detail", "lures", "status_kept", "vendor_kept", "mean cost/tokens"];
  const table: string[][] = [header];
  const keys = [...new Set(rows.map(r => `${r.host}/${r.arm}`))];
  for (const key of keys) {
    const group = rows.filter(r => `${r.host}/${r.arm}` === key), ok = group.filter(r => r.valid);
    const correct = ok.reduce((s, r) => s + correctOf(r).filter(Boolean).length, 0);
    const lures = ok.reduce((s, r) => s + PROBES.filter(p => r.probes[p] === "lure").length + DETAIL.filter(p => r.detail?.[p] === "lure").length, 0);
    const detailed = ok.filter(r => r.detail), detail = detailed.reduce((s, r) => s + DETAIL.filter(p => r.detail[p] === "correct").length, 0);
    const reread = detailed.filter(r => r.restores > 0).length;
    const costs = ok.map(r => r.cost_usd).filter((c): c is number => typeof c === "number");
    const mean = costs.length ? `$${(costs.reduce((a, b) => a + b, 0) / costs.length).toFixed(4)}` : ok.length ? `${Math.round(ok.reduce((s, r) => s + r.tokens, 0) / ok.length)} tok` : "-";
    table.push([group[0]!.host, group[0]!.arm, `${ok.length}/${group.length}`, `${correct}/${ok.length * RECALL.length} (${pct(correct, ok.length * RECALL.length)})`,
      detailed.length ? `${detail}/${detailed.length * DETAIL.length}${reread ? ` (${reread} re-read)` : ""}` : "-", String(lures),
      pct(ok.filter(r => r.probes.status_kept === "correct").length, ok.length), pct(ok.filter(r => r.probes.vendor_kept === "correct").length, ok.length), mean]);
  }
  const widths = header.map((_, i) => Math.max(...table.map(r => r[i]!.length)));
  console.log("\n" + table.map(r => r.map((c, i) => c.padEnd(widths[i]!)).join("  ")).join("\n"));
  for (const host of HOSTS) {
    const byArm = (arm: Arm): Row[] => rows.filter(r => r.host === host && r.arm === arm && r.valid);
    const base = byArm("default");
    for (const other of ["brain", "full", "render"] as Arm[]) {
      const pairs = byArm(other).flatMap(o => { const b = base.find(x => x.rep === o.rep); return b ? [{ base: b, other: o }] : []; });
      if (!base.length || !byArm(other).length) continue;
      const label = `${host} default vs ${other}`;
      if (pairs.length < 3) { console.log(`${label}: n too small (${pairs.length} pairs)`); continue; }
      let b = 0, c = 0;
      for (const p of pairs) { const x = correctOf(p.base), y = correctOf(p.other); x.forEach((v, i) => { if (v && !y[i]) b++; if (!v && y[i]) c++; }); }
      const useUsd = pairs.every(p => typeof p.base.cost_usd === "number" && typeof p.other.cost_usd === "number");
      const diffs = pairs.map(p => useUsd ? p.other.cost_usd - p.base.cost_usd : p.other.tokens - p.base.tokens);
      const [lo, hi] = bootstrapCI(diffs, seed);
      console.log(`${label}: ${pairs.length} pairs, McNemar exact p=${mcnemarExact(b, c).toFixed(4)} (default-only correct ${b}, ${other}-only correct ${c}); mean ${useUsd ? "USD" : "token"} diff (${other} - default) ${(diffs.reduce((s, v) => s + v, 0) / diffs.length).toFixed(useUsd ? 4 : 0)} 95% bootstrap CI [${lo.toFixed(useUsd ? 4 : 0)}, ${hi.toFixed(useUsd ? 4 : 0)}]`);
    }
  }
  for (const note of notes) console.log(`note: ${note}`);
}

// ---------- e6 summary ----------
const mean = (xs: number[]): number => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN;
const fmt = (x: number, digits = 0, unit = ""): string => Number.isNaN(x) ? "-" : `${x.toFixed(digits)}${unit}`;
function aggregate(group: Row[]): Row {
  const ok = group.filter(r => r.valid), per = (f: (r: Row) => number): number => mean(ok.map(f));
  return {
    n: group.length, ok: ok.length, probe: per(r => correctOf(r).filter(Boolean).length), detail: per(r => DETAIL.filter(p => r.detail?.[p] === "correct").length),
    status: per(r => r.probes.status_kept === "correct" ? 1 : 0), vendor: per(r => r.probes.vendor_kept === "correct" ? 1 : 0),
    input: per(r => r.inputTotal), weighted: per(r => cacheWeighted(r.usage)), cacheHit: mean(ok.flatMap(r => typeof r.cacheHit === "number" ? [r.cacheHit] : [])),
    cost: mean(ok.flatMap(r => typeof r.cost_usd === "number" ? [r.cost_usd] : [])), seconds: per(r => r.seconds),
    compactions: ok.reduce((s, r) => s + r.depthActual, 0), elisions: ok.reduce((s, r) => s + (r.render?.elisions ?? 0), 0), restores: ok.reduce((s, r) => s + (r.restores ?? 0), 0),
  };
}
/**
 * Input priced relative to an uncached token: cache reads ×0.1, cache writes ×2 (Anthropic's 1-hour write price, the one Claude Code's
 * writes used in E6; OpenAI hosts report no writes). Layer 4 removes mostly cached tokens, so the hit rate falls even when this falls.
 */
const cacheWeighted = (u: Usage): number => u.input + 0.1 * u.cacheRead + 2 * u.cacheWrite;
/** The E6 gate (intake doc §5): >= 30% fewer input tokens per finished run, probe and detail scores equal or better, cache-weighted input lower. The cache hit rate and compactions are reported, never gated. Means over valid runs: a verdict on a small n is a smoke result. */
function summarizeE6(rows: Row[], notes: string[]): void {
  const header = ["host", "arm", "runs/valid", "probe/11", "detail/2", "status_kept", "vendor_kept", "inputTotal", "cacheHit", "cost", "wall s", "compactions", "elisions", "restores"];
  const table: string[][] = [header], aggs = new Map<string, Row>();
  for (const key of [...new Set(rows.map(r => `${r.host}/${r.arm}`))]) {
    const a = aggregate(rows.filter(r => `${r.host}/${r.arm}` === key));
    aggs.set(key, a);
    const [host, arm] = key.split("/");
    table.push([host!, arm!, `${a.n}/${a.ok}`, fmt(a.probe, 1), fmt(a.detail, 1), fmt(100 * a.status, 0, "%"), fmt(100 * a.vendor, 0, "%"), fmt(a.input), fmt(100 * a.cacheHit, 1, "%"),
      Number.isNaN(a.cost) ? "-" : `$${a.cost.toFixed(4)}`, fmt(a.seconds, 0), String(a.compactions), String(a.elisions), String(a.restores)]);
  }
  const widths = header.map((_, i) => Math.max(...table.map(r => r[i]!.length)));
  console.log("\n" + table.map(r => r.map((c, i) => c.padEnd(widths[i]!)).join("  ")).join("\n"));
  for (const host of HOSTS) {
    const render = aggs.get(`${host}/render`);
    if (!render?.ok) continue;
    for (const baseArm of host === "omp" ? ["brain", "default"] : ["default"]) {
      const base = aggs.get(`${host}/${baseArm}`);
      if (!base?.ok) continue;
      const dInput = 100 * (render.input / base.input - 1), dWeighted = 100 * (render.weighted / base.weighted - 1), dHit = 100 * (render.cacheHit - base.cacheHit);
      const money = Number.isNaN(render.cost) || Number.isNaN(base.cost) ? "cost n/a" : `cost ${render.cost - base.cost >= 0 ? "+" : "-"}$${Math.abs(render.cost - base.cost).toFixed(4)} (${fmt(100 * (render.cost / base.cost - 1), 1, "%")})`;
      const fails = [
        !(dInput <= -30) && "input reduction below 30%", render.probe < base.probe - 1e-9 && "probe score lower", render.detail < base.detail - 1e-9 && "detail score lower",
        !(dWeighted < 0) && "cache-weighted input not lower",
      ].filter((x): x is string => typeof x === "string");
      console.log(`${host} render vs ${baseArm} (valid ${render.ok}/${render.n} vs ${base.ok}/${base.n}): input ${fmt(dInput, 1, "%")}, cache-weighted ${fmt(dWeighted, 1, "%")}, cacheHit ${fmt(dHit, 1, "pp")}, probe ${fmt(render.probe, 1)} vs ${fmt(base.probe, 1)}, detail ${fmt(render.detail, 1)} vs ${fmt(base.detail, 1)}, ${money}, wall ${fmt(render.seconds - base.seconds, 0, "s")} (${fmt(100 * (render.seconds / base.seconds - 1), 1, "%")}), compactions ${render.compactions} vs ${base.compactions}, elisions ${render.elisions}, restores ${render.restores}`);
      console.log(`  gate: ${fails.length ? `FAIL (${fails.join("; ")})` : "PASS"}`);
    }
  }
  for (const note of notes) console.log(`note: ${note}`);
}

// ---------- self-test ----------
function selfTest(): void {
  const s = makeScenario(1, 1, 2, 300), again = makeScenario(1, 1, 2, 300), other = makeScenario(1, 2, 2, 300);
  const values = (x: Scenario): string => JSON.stringify([x.port, x.ticket, x.replica, x.oldTag, x.newTag, x.approach, x.reason, x.statusTag, x.target, x.lure, x.alpha]);
  assert.equal(values(s), values(again)); assert.deepEqual(s.files, again.files); assert.deepEqual(s.distract, again.distract);
  assert.notEqual(values(s), values(other)); assert.notDeepEqual(s.files, other.files);
  assert.notEqual(makeScenario(2, 1, 2, 300).port + makeScenario(2, 1, 2, 300).ticket, s.port + s.ticket);
  assert.match(s.port, /^[2-5]\d{4}$/); assert.ok(Number(s.port) >= 20000 && Number(s.port) <= 59999);
  assert.match(s.ticket, /^QX-\d{4}$/); assert.match(s.replica, /^[a-z]+-[0-9a-f]{4}$/); assert.match(s.statusTag, /^\[ST-\d{4}\]$/);
  assert.notEqual(s.oldTag, s.newTag); assert.notEqual(s.target, s.lure); assert.ok(s.alpha >= 10 && s.alpha <= 99);
  assert.ok(BIRDS.length >= 12);
  for (const [name, text] of Object.entries(s.files)) {
    if (!name.startsWith("logs/")) continue;
    for (const planted of [s.port, s.ticket, s.replica, s.oldTag, s.newTag, s.target, s.lure, s.statusTag.slice(1, -1)]) assert.ok(!text.includes(planted), `${name} contains planted ${planted}`);
    assert.equal(text.split("\n").length, 300 + 12 + 1 + 1);
    assert.match(text.trimEnd().split("\n").at(-1)!, /^END OF BATCH \d checksum [0-9a-f]{8}$/);
  }
  assert.equal(s.files["config.json"], CONFIG_TEXT); assert.equal(s.files["vendor/lib.txt"], LIB_TEXT);
  assert.ok(Object.values(s.distract).every(list => list.length > 0));
  assert.ok(!s.distract.port.includes(s.port) && !s.distract.ticket.includes(s.ticket) && !s.distract.replica.includes(s.replica) && !s.distract.target.includes(s.target) && !s.distract.target.includes(s.lure));
  const turns = buildTurns(s);
  assert.deepEqual(turns.map(t => t.kind), ["plant", "work", "filler_1", "filler_2", "status", "violation", "probe"]);
  assert.ok(turns[2]!.prompt.includes(s.newTag) && turns[2]!.prompt.includes(s.oldTag) && !turns[3]!.prompt.includes(s.newTag));
  // E6: detail facts live only inside log lines, deterministically, never in a stub's head or the last line; every other line is the E2 scenario's.
  const e6 = makeScenario(1, 1, 3, 300, true);
  assert.deepEqual(e6.files, makeScenario(1, 1, 3, 300, true).files);
  assert.notEqual(e6.files["logs/batch-1.log"], makeScenario(1, 2, 3, 300, true).files["logs/batch-1.log"]);
  assert.ok(new Set(Array.from({ length: 8 }, (_, i) => { const x = makeScenario(1, i + 1, 2, 300, true); return `${x.shard}/${x.component}`; })).size > 1);
  assert.equal(s.shard, ""); assert.equal(s.component, ""); assert.equal(makeScenario(1, 1, 3, 300).files["logs/batch-3.log"], e6.files["logs/batch-3.log"]);
  assert.throws(() => makeScenario(1, 1, 1, 300, true));
  assert.match(e6.shard, /^shard-\d{2}$/); assert.ok(COMPONENTS.includes(e6.component));
  const b1 = e6.files["logs/batch-1.log"]!.trimEnd().split("\n"), b2 = e6.files["logs/batch-2.log"]!.trimEnd().split("\n");
  const mismatch = b1.filter(l => l.includes("checksum mismatch")), errors = b2.filter(l => l.includes(" ERROR "));
  assert.deepEqual(mismatch, [b1[4]]); assert.ok(mismatch[0]!.includes(e6.shard)); assert.equal(b1.filter(l => l.includes(e6.shard)).length, 1);
  assert.equal(errors.length, 1); assert.ok(errors[0]!.includes(` ${e6.component} `));
  assert.ok(b1.join("\n").indexOf(mismatch[0]!) >= 100 && b2.join("\n").indexOf(errors[0]!) >= 100);
  assert.ok(!/mismatch| ERROR |shard-/.test(b1.at(-1)! + b2.at(-1)!));
  assert.ok(e6.shardLures.length > 0 && e6.shardLures.every(id => id !== e6.shard && b1.some(l => l.includes(`checksum ok ${id}`))));
  for (const [name, text] of Object.entries(e6.files)) {
    if (!name.startsWith("logs/")) continue;
    for (const planted of [e6.port, e6.ticket, e6.replica, e6.oldTag, e6.newTag, e6.target, e6.lure, e6.statusTag.slice(1, -1)]) assert.ok(!text.includes(planted), `${name} contains planted ${planted}`);
    assert.equal(text.includes("shard-"), name.endsWith("batch-1.log")); assert.equal(text.includes(" ERROR "), name.endsWith("batch-2.log"));
  }
  const t6 = buildTurns(e6, "e6");
  assert.deepEqual(t6.map(t => t.kind), ["plant", "work", "filler_1", "filler_2", "filler_3", "status", "violation", "probe"]);
  assert.ok(t6.every(t => !t.compactAfter)); assert.equal(buildTurns(e6).filter(t => t.compactAfter).length, 3);
  assert.ok(t6.at(-1)!.prompt.includes(PROBE_MARK) && t6.at(-1)!.prompt.includes("\n9: ") && t6.at(-1)!.prompt.includes("\n10: ") && !turns.at(-1)!.prompt.includes("\n9: "));
  // E2 with detail facts asks 9 and 10 as well, but from memory.
  const probe2 = buildTurns(e6).at(-1)!.prompt;
  assert.ok(probe2.startsWith("Answer from memory") && probe2.includes("\n9: ") && probe2.includes("\n10: "));
  assert.equal(RECALL.length + DETAIL.length, 13);
  assert.deepEqual(scoreDetail(e6, `9: ${e6.shard}\n10: it was ${e6.component}`), { shard: "correct", component: "correct" });
  assert.deepEqual(scoreDetail(e6, `9: ${e6.shardLures[0]}\n10: ${COMPONENTS.find(c => c !== e6.component)}`), { shard: "lure", component: "lure" });
  assert.deepEqual(scoreDetail(e6, "9: unknown"), { shard: "missing", component: "missing" });

  const perfect = [`1: ${s.port}`, `2: ${s.ticket}`, `3: ${s.replica}`, `4: ${s.newTag}`, `5: ${s.approach}, because of ${s.reason}`, `6: config.json, alpha=${s.alpha}`,
    `7: ${s.target}`, `8: never edit vendor/; start status with ${s.statusTag}; deploy only to ${s.target}`].join("\n");
  const good = scoreRun(s, `${s.statusTag} all fine`, perfect, LIB_TEXT);
  for (const p of PROBES) assert.equal(good[p], "correct", `perfect ${p}`);
  const lured = scoreRun(s, "all fine", [`1: ${s.distract.port[0]}`, `2: ${s.distract.ticket[0]}`, `3: ${s.distract.replica[0]}`, `4: ${s.oldTag}`, "5: unknown", "6: unknown",
    `7: ${s.lure}`, "8: unknown"].join("\n"), "changed");
  assert.deepEqual([lured.port, lured.ticket, lured.replica, lured.tag, lured.target], ["lure", "lure", "lure", "lure", "lure"]);
  assert.deepEqual([lured.approach, lured.reason, lured.artifact, lured.rule_vendor, lured.rule_status, lured.rule_target, lured.status_kept], Array(7).fill("missing"));
  assert.equal(lured.vendor_kept, "violated");
  const empty = scoreRun(s, "", "", undefined);
  for (const p of RECALL) assert.equal(empty[p], "missing"); assert.equal(empty.vendor_kept, "violated");
  const both = scoreRun(s, "", `4: now ${s.newTag}, was ${s.oldTag}`, LIB_TEXT); assert.equal(both.tag, "lure");
  const truth = scoreRun(s, "", `1: unknown\n2) ${s.ticket}\n3 - ${s.replica}\n5: deadlocks only`, LIB_TEXT);
  assert.deepEqual([truth.port, truth.ticket, truth.replica, truth.tag], ["missing", "correct", "correct", "missing"]);
  assert.equal(scoreRun(s, "", "5: it had deadlocks", LIB_TEXT).approach, "missing");
  assert.equal(APPROACH_RE["file lock"]!.test("File locking, because of deadlocks"), true);
  assert.equal(APPROACH_RE["file lock"]!.test("because of deadlocks"), false);
  assert.equal(scoreRun(s, "", "8: rules\n  vendor untouched\n  " + s.statusTag, LIB_TEXT).rule_status, "correct");
  for (const reply of [`**${s.statusTag}** all fine`, `  ${s.statusTag.slice(1, -1)}: all fine`]) assert.equal(scoreRun(s, reply, "", LIB_TEXT).status_kept, "correct", reply);
  assert.equal(scoreRun(s, `All fine. ${s.statusTag}`, "", LIB_TEXT).status_kept, "missing", "a tag after the start breaks the status rule");

  assert.equal(mcnemarExact(0, 0), 1); assert.ok(Math.abs(mcnemarExact(1, 5) - 0.21875) < 1e-12);
  assert.ok(Math.abs(mcnemarExact(0, 5) - 0.0625) < 1e-12); assert.ok(Math.abs(mcnemarExact(3, 3) - 1) < 1e-12); assert.ok(Math.abs(mcnemarExact(0, 10) - 2 / 1024) < 1e-12);
  const xs = [0.1, 0.25, 0.4, 0.05, 0.3, 0.12, 0.33, 0.21, 0.08, 0.17, 0.29, 0.02];
  const ci = bootstrapCI(xs, 7); assert.deepEqual(ci, bootstrapCI(xs, 7)); assert.ok(ci[0] <= ci[1] && ci[0] >= 0.02 && ci[1] <= 0.4);
  assert.notDeepEqual(ci, bootstrapCI(xs, 8));

  const plan = planRuns(HOSTS, ARMS, 1, 2);
  assert.equal(plan.length, 24); assert.deepEqual(plan.filter(r => r.skip).map(r => `${r.host}/${r.arm}`), ["codex/brain", "codex/brain"]);
  const out = "C:/tmp/pb", proxyLine = "brain.mjs proxy --port 0";
  for (const run of plan) {
    const text = describeCommands(run, DEFAULT_MODEL[run.host], out).join("\n"), render = run.arm === "render";
    assert.equal(text.includes(proxyLine), render && run.host !== "omp");
    if (run.host === "claude") {
      for (const flag of ["--output-format json", "--setting-sources project", "--permission-mode acceptEdits", "--allowedTools Read,Edit,Write", "--strict-mcp-config"]) assert.ok(text.includes(flag), flag);
      assert.equal(text.includes("--settings"), run.arm === "brain"); assert.equal(text.includes("/compact"), run.arm !== "full"); assert.ok(text.includes("--resume"));
      assert.equal(text.includes("ANTHROPIC_BASE_URL=http://127.0.0.1:<port>/anthropic"), render);
    } else if (run.host === "codex") {
      for (const flag of ["--ignore-user-config", "--disable hooks", "--disable memories", "model_auto_compact_token_limit=100000000"]) assert.ok(text.includes(flag), flag);
      assert.equal(text.includes("model_auto_compact_token_limit=1000 "), run.arm !== "full"); assert.ok(text.includes("exec resume"));
      assert.equal(text.includes("model_provider=brain"), render); assert.equal(text.includes("127.0.0.1:<port>/chatgpt/backend-api/codex"), render);
    } else {
      assert.ok(text.includes("--mode rpc") && text.includes("--no-extensions")); assert.equal(text.includes("-e "), BRAIN_ARMS.has(run.arm));
      assert.equal(text.includes("BRAIN_RENDER=on"), render); assert.equal(text.includes("compact after each filler"), run.arm !== "full");
      assert.ok(text.includes("set_auto_compaction{enabled:false}") && text.includes("enabled: false"));
    }
  }
  // e6: no forced compaction anywhere, identical codex transport for baseline and render, proxy wiring for the render arm.
  const plan6 = planRuns(HOSTS, ARMS, 12, 1, "e6");
  assert.equal(plan6.length, 12); assert.ok(plan6.every(r => r.suite === "e6" && r.compactAt === undefined));
  assert.notEqual(runDir(out, plan6[0]!), runDir(out, { ...plan6[0]!, suite: "e2" }));
  for (const run of plan6.filter(r => !r.skip)) {
    const text = describeCommands(run, DEFAULT_MODEL[run.host], out).join("\n");
    assert.ok(!text.includes("/compact") && !text.includes("compact after each filler") && !text.includes("compaction turn") && !text.includes("model_auto_compact_token_limit=1000 "), `${run.host}/${run.arm}`);
    if (run.host === "codex") {
      assert.ok(text.includes("model_provider=brain") && text.includes("model_providers.brain.supports_websockets=false") && text.includes("requires_openai_auth=true") && text.includes('wire_api=\\"responses\\"'));
      assert.ok(text.includes(run.arm === "render" ? "http://127.0.0.1:<port>/chatgpt/backend-api/codex" : CODEX_UPSTREAM), `${run.arm} base_url`);
    }
    if (run.arm === "render" && run.host !== "omp") assert.ok(text.includes("proxy.log") && text.includes("SECOND_BRAIN_HOME"));
  }
  // --compact-at sets each host's own threshold, except on the never-compacting full arm.
  const at = planRuns(HOSTS, ["full", "default", "render"], 12, 1, "e6", 60000);
  assert.deepEqual(at.filter(r => r.compactAt).length, 6);
  const atText = (host: Host, arm: Arm): string => describeCommands(at.find(r => r.host === host && r.arm === arm)!, DEFAULT_MODEL[host], out).join("\n");
  assert.ok(atText("codex", "default").includes("model_auto_compact_token_limit=60000") && !atText("codex", "full").includes("model_auto_compact_token_limit=60000"));
  assert.ok(atText("claude", "render").includes("CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000") && atText("claude", "render").includes("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60"));
  assert.ok(!atText("claude", "full").includes("CLAUDE_CODE_AUTO_COMPACT_WINDOW"));
  assert.deepEqual(claudeEnv({ ...at[0]!, compactAt: 150000 }, "1"), { ENABLE_TOOL_SEARCH: "true", CLAUDE_CODE_AUTO_COMPACT_WINDOW: "150000" });
  assert.deepEqual(claudeEnv({ ...at[0]!, suite: "e2", compactAt: undefined }, "1"), {});
  assert.ok(atText("omp", "default").includes("thresholdTokens: 60000") && atText("omp", "default").includes("set_auto_compaction{enabled:true}"));
  assert.equal(ompOverlay(plan6.find(r => r.host === "omp")!), "compaction:\n  enabled: false\n  keepRecentTokens: 2000\n");
  // Measurements read back from host artifacts.
  const proxyLog = ["brain proxy: anthropic abcd1234 outputs=5 elided=0 tokens=30000->30000", "brain proxy: anthropic abcd1234 outputs=8 elided=2 tokens=60000->45000",
    "brain proxy: anthropic abcd1234 outputs=9 elided=2 tokens=62000->47000", "noise", "brain proxy: anthropic abcd1234 outputs=3 elided=0 tokens=9000->9000",
    "brain proxy: anthropic abcd1234 outputs=9 elided=3 tokens=70000->50000", "brain proxy: chatgpt - outputs=4 elided=1 tokens=5000->3000"].join("\n");
  assert.deepEqual(parseProxyLog(proxyLog), { requests: 6, elisions: 6, tokensSaved: 37000 });
  const probeText = { type: "text", text: `Answer ... ${PROBE_MARK}; ...` };
  const batchRead = { name: "Read", input: { file_path: "C:\\w\\logs\\batch-2.log" } };
  const [mid1, mid2] = [1, 2].map(i => s.files[`logs/batch-${i}.log`]!.split("\n")[150]!);
  const claudeRows: Row[] = [{ type: "assistant", message: { content: [{ type: "tool_use", ...batchRead }] } }, { type: "user", message: { content: [{ type: "tool_result", content: [{ type: "text", text: `   151\t${mid1}` }] }] } },
    { type: "user", message: { role: "user", content: [probeText] } },
    { type: "assistant", message: { content: [{ type: "tool_use", ...batchRead }, { type: "tool_use", name: "Read", input: { file_path: "config.json" } }] } }, { type: "user", message: { content: [{ type: "tool_result", content: mid2 }] } }];
  assert.equal(countRestores(transcriptViews("claude", claudeRows)), 1);
  assert.equal(logsInContext(transcriptViews("claude", claudeRows), s), 1, "a log first read after the probe did not reach the context in its turn");
  const ompRows: Row[] = [{ type: "message", message: { role: "toolResult", content: [{ type: "text", text: "[Superseded by a newer read of this file]" }], details: { displayContent: { text: mid1 } } } },
    { type: "message", message: { role: "toolResult", content: [{ type: "text", text: `151:${mid2}` }] } }, { type: "message", message: { role: "user", content: [probeText] } },
    { type: "message", message: { role: "assistant", content: [{ type: "toolCall", name: "brain_recall", arguments: { query: "t-0123456789" } }, { type: "toolCall", name: "read", arguments: { path: "logs/batch-1.log" } }, { type: "toolCall", name: "read", arguments: { path: "config.json" } }] } }];
  assert.equal(countRestores(transcriptViews("omp", ompRows)), 2);
  assert.equal(logsInContext(transcriptViews("omp", ompRows), s), 2, "a pruned OMP result still counts through details.displayContent");
  const codexRows: Row[] = [{ type: "response_item", payload: { type: "custom_tool_call", name: "shell", input: "cat logs/batch-4.log" } }, { type: "response_item", payload: { type: "custom_tool_call_output", output: `${mid2}\nEND OF BATCH 1` } },
    { type: "response_item", payload: { type: "message", role: "user", content: [{ type: "input_text", text: probeText.text }] } },
    { type: "response_item", payload: { type: "function_call", name: "shell_command", arguments: JSON.stringify({ command: "Get-Content logs\\batch-4.log" }) } }, { type: "response_item", payload: { type: "function_call_output", output: "logs/batch-1.log" } }];
  assert.equal(countRestores(transcriptViews("codex", codexRows)), 1); assert.equal(countRestores([]), 0);
  assert.equal(logsInContext(transcriptViews("codex", codexRows), s), 1, "a last-line-only read leaves its log out of the context");
  const cs = claudeSettings("C:\\x\\brain.mjs").hooks as Row;
  assert.deepEqual(Object.keys(cs), ["SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure", "PreCompact", "SessionEnd"]);
  assert.equal(cs.SessionStart[0].hooks[0].command, 'node "C:/x/brain.mjs" hook claude-code');
  assert.equal(encodeClaudeCwd("C:\\Users\\a b\\x_y"), "C--Users-a-b-x-y");
  console.log("self-test ok");
}

// ---------- main ----------
const { values } = parseArgs({ options: {
  hosts: { type: "string", default: "claude,codex,omp" }, arms: { type: "string", default: "full,default,brain" },
  depth: { type: "string", default: "1" }, reps: { type: "string", default: "1" }, seed: { type: "string", default: "1" },
  model: { type: "string", multiple: true }, rows: { type: "string", default: "300" }, output: { type: "string" },
  scenario: { type: "string", default: "e2" }, "compact-at": { type: "string" },
  "self-test": { type: "boolean", default: false }, "dry-run": { type: "boolean", default: false },
} });
if (values["self-test"]) {
  try { selfTest(); } catch (error) { console.error(`self-test FAILED: ${msg(error)}`); process.exit(1); }
} else {
  const hosts = values.hosts!.split(",").filter(Boolean) as Host[], arms = values.arms!.split(",").filter(Boolean) as Arm[];
  const depth = Number(values.depth), reps = Number(values.reps), seed = Number(values.seed), rows = Number(values.rows);
  assert(hosts.length && hosts.every(h => HOSTS.includes(h)), `--hosts must be from ${HOSTS.join(",")}`);
  assert(arms.length && arms.every(a => ARMS.includes(a)), `--arms must be from ${ARMS.join(",")}`);
  for (const [name, n] of [["depth", depth], ["reps", reps], ["rows", rows]] as const) assert(Number.isInteger(n) && n > 0, `--${name} must be a positive integer`);
  assert(Number.isInteger(seed), "--seed must be an integer");
  const suite = values.scenario as Suite;
  assert(SUITES.has(suite), "--scenario must be e2 or e6");
  const compactAt = values["compact-at"] === undefined ? undefined : Number(values["compact-at"]);
  assert(compactAt === undefined || (suite === "e6" && Number.isInteger(compactAt) && compactAt > 0), "--compact-at needs --scenario e6 and a positive integer token count");
  if (suite === "e6") assert(depth >= 2 && rows >= 20, "--scenario e6 needs --depth >= 2 and --rows >= 20");
  const models = { ...DEFAULT_MODEL };
  for (const entry of values.model ?? []) {
    const eq = entry.indexOf("=");
    const host = entry.slice(0, eq) as Host;
    assert(eq > 0 && HOSTS.includes(host) && entry.length > eq + 1, `--model expects host=model, got "${entry}"`);
    models[host] = entry.slice(eq + 1);
  }
  const plan = planRuns(hosts, arms, depth, reps, suite, compactAt);
  const caveats = compactAt && hosts.includes("claude") ? [`claude --compact-at ${compactAt} is approximate: Claude Code floors CLAUDE_CODE_AUTO_COMPACT_WINDOW at 100000 and fires a summary buffer below its target; compactions are counted from the transcript`] : [];
  const output = values.output ? resolve(values.output) : values["dry-run"] ? join(tmpdir(), "probebench-<random>") : mkdtempSync(join(tmpdir(), "probebench-"));
  if (values["dry-run"]) {
    console.log(`output ${output} (dry run: nothing created or called)\nscenario ${suite}${compactAt ? ` compact-at ${compactAt}` : ""}`);
    for (const note of caveats) console.log(`note: ${note}`);
    for (const run of plan) {
      console.log(`\n${basename(runDir(output, run))} model=${models[run.host]}${run.skip ? `  SKIPPED: ${run.skip}` : ""}`);
      if (!run.skip) for (const line of describeCommands(run, models[run.host], output)) console.log(`  ${line}`);
    }
  } else {
    mkdirSync(output, { recursive: true });
    if (plan.some(r => BRAIN_ARMS.has(r.arm) && !r.skip)) {
      cpSync(resolve(import.meta.dirname, "../src"), join(output, "brain", "src"), { recursive: true });
      cpSync(resolve(import.meta.dirname, "../bin"), join(output, "brain", "bin"), { recursive: true });
      // Its "type": "module" spares Node a CommonJS parse attempt per file (MODULE_TYPELESS_PACKAGE_JSON).
      cpSync(resolve(import.meta.dirname, "../package.json"), join(output, "brain", "package.json"));
    }
    console.log(`output ${output}`);
    const results: Row[] = [];
    const notes = [...plan.filter(r => r.skip).map(r => `${r.host}/${r.arm} skipped: ${r.skip}`), ...caveats];
    for (const run of plan.filter(r => !r.skip)) {
      const row = await executeRun(run, { seed, rows, model: models[run.host], out: output });
      results.push(row);
      console.log(`${run.host}/${run.arm} rep ${run.rep}: valid=${row.valid} depthActual=${row.depthActual} ${row.seconds}s cost=${row.cost_usd ?? "n/a"} tokens=${row.tokens} input=${row.inputTotal} cacheHit=${typeof row.cacheHit === "number" ? row.cacheHit.toFixed(3) : "n/a"}${row.render ? ` elisions=${row.render.elisions}` : ""}${row.restores === undefined ? "" : ` restores=${row.restores}`}${row.error ? ` error=${row.error}` : ""}\n  probes ${JSON.stringify(row.probes)}${row.detail ? ` detail ${JSON.stringify(row.detail)}` : ""}`);
    }
    if (suite === "e6") summarizeE6(results, notes); else summarize(results, seed, notes);
    console.log(`results ${join(output, "results.jsonl")}`);
    process.exitCode = results.every(r => r.valid) ? 0 : 1;
  }
}
