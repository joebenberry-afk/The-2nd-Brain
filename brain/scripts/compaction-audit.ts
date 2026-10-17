#!/usr/bin/env node
/**
 * E0 compaction audit: what survives each compaction the hosts already recorded, and what the
 * agent does next. Offline and read-only; no model calls.
 *
 * Inputs: every main-session transcript the hosts keep (OMP, Claude Code, Codex; see
 * scripts/transcripts.ts).
 *
 *   node scripts/compaction-audit.ts [--days 30] [--hosts omp,claude,codex] [--output dir] [--samples] [--self-test]
 *
 * Visible after a compaction means the summary plus the verbatim context the host carries past it.
 *  - Opaque summaries (OpenAI-native, Codex) are encrypted, so their retention is a lower bound.
 *  - OMP snapcompact returns the old transcript as images of its text, so its retention is an
 *    upper bound.
 *
 * Probes are cumulative, taken from the owner's own prompts before each compaction. They are
 * deterministic; no judge is involved.
 *  - **constraints:** prompt sentences with a rule cue (never, always, don't, must, avoid…).
 *    - gist: at least 60% of their content-word stems are visible.
 *    - verbatim: the whole sentence is visible.
 *  - **values:** paths, URLs, hashes, flags, backticked names and long numbers the owner typed.
 *    Retained when visible verbatim; paths and URLs need only their last segment.
 *  - **ask:** the session's first prompt, retained when 50% of its content stems are visible.
 *  - **files:** files the agent edited, retained when the basename is visible.
 *
 * Behaviour compares the 30 tool calls after a compaction with the 30 before it.
 *  - Re-reads: the share of reads of a file the session had already read.
 *  - Repeat failures: commands that failed earlier and fail again.
 *  - Codex: not measured, because its shell reads and exit codes are not parsed.
 *
 * Delivered: whether Brain context arrived after the compaction. That is a card in a tool result,
 * a brain message, or a SessionStart additionalContext.
 *
 * Writes `compactions.jsonl` (one row per compaction) to `--output`, by default a new OS temp dir,
 * and prints a host × summary visibility × depth table.
 * Sessions with no owner prompt are harness runs and are skipped: Claude Code SDK entrypoints,
 * `codex exec`.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { parseArgs } from "node:util";
import { hasCompaction, parseSession, sessionFiles, sessionRoots } from "./transcripts.ts";
import type { Compaction, Host, Session } from "./transcripts.ts";

const WINDOW = 30;
const HOSTS: Host[] = ["omp", "claude", "codex"];

/** A pasted document is not the owner instructing: such prompts give no constraint or value probes. */
const PASTE_CHARS = 6000;
const PASTE_RULES = 8;

const CUE = /\b(?:never|always|don['’]t|do not|must|mustn['’]t|should not|shouldn['’]t|avoid|prefer|make sure|from now on|no longer|stop using)\b/i;
const STOP = new Set(("that this with from have will your what when then them they there were been into also just like make sure " +
  "should would could about after before every each which while because does dont never always must avoid prefer only than more " +
  "most some such very much many here where these those other being their please want need using used").split(" "));

/** Content-word stems: lower-cased words of four or more letters, stop words dropped, cut to six characters. */
export function stems(text: string): string[] {
  return [...new Set((text.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu) ?? []).filter((word) => !STOP.has(word)).map((word) => word.slice(0, 6)))];
}

const flat = (text: string): string => text.toLowerCase().replace(/\s+/g, " ").trim();

/** Prose the owner wrote, without fenced code, tagged blocks and quotes. */
function prose(prompt: string): string {
  return prompt.replace(/`{3}[\s\S]*?(?:`{3}|$)|~{3}[\s\S]*?(?:~{3}|$)/g, "")
    .replace(/<([\w-]+)(?:\s[^>]*)?>[\s\S]*?<\/\1>/g, "")
    .replace(/^\s*>.*$/gm, "");
}

export function constraintsOf(prompt: string): string[] {
  if (prompt.length > PASTE_CHARS) return [];
  // Sentences end at punctuation, blank lines and list items; a hard-wrapped line continues its sentence.
  const found = prose(prompt).split(/(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*+#]|\d+[.)])\s)/)
    .map((sentence) => sentence.replace(/^\s*(?:[-*+]|#+|\d+[.)])\s+/, "").replace(/\s+/g, " ").trim())
    .filter((sentence) => sentence.length >= 15 && sentence.length <= 300 && CUE.test(sentence) && !/\?\s*$/.test(sentence));
  return found.length > PASTE_RULES ? [] : found;
}

/** Value probes as lower-cased keys: a path or URL keeps its last segment, which a summary is likeliest to name. */
export function valuesOf(prompt: string): string[] {
  if (prompt.length > PASTE_CHARS) return [];
  const text = prompt.replace(/`{3}[\s\S]*?(?:`{3}|$)/g, "");
  const out = new Set<string>();
  const last = (path: string): string => path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? "";
  for (const match of text.matchAll(/https?:\/\/[^\s)>\]"'`]+/g)) out.add(last(match[0].replace(/[.,;:]+$/, "")));
  const noUrls = text.replace(/https?:\/\/\S+/g, " ");
  for (const match of noUrls.matchAll(/(?:[A-Za-z]:[\\/]|~[\\/]|\.{1,2}[\\/])[^\s"'`<>|*?]+|\b[\w.-]+(?:[\\/][\w.-]+)+\.\w{1,6}\b/g)) out.add(last(match[0].replace(/[.,;:]+$/, "")));
  for (const [, name = ""] of noUrls.matchAll(/`([^`\n]{3,60})`/g)) out.add(name.trim());
  for (const match of noUrls.matchAll(/(?<![\w-])--[a-z][\w-]{2,}/gi)) out.add(match[0]);
  for (const match of noUrls.matchAll(/\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/gi)) out.add(match[0]);
  for (const match of noUrls.matchAll(/\b\d{3,}(?:\.\d+)?\b/g)) if (!/^(?:19|20)\d\d$/.test(match[0])) out.add(match[0]);
  return [...out].map((value) => value.toLowerCase()).filter((value) => value.length >= 3);
}

const share = (words: string[], visible: Set<string>): number =>
  words.length ? words.filter((word) => visible.has(word)).length / words.length : 0;

export type Row = {
  host: Host; session: string; project: string; at: string; depth: number;
  method: string; visibility: Compaction["visibility"]; tokensBefore: number | null; tokensAfter: number | null;
  summaryChars: number; carriedChars: number;
  constraints: { n: number; gist: number; verbatim: number };
  values: { n: number; kept: number };
  files: { n: number; kept: number };
  ask: boolean | null;
  behaviour: { readsPre: number; rereadsPre: number; readsPost: number; rereadsPost: number; failuresPost: number; repeatFailures: number; callsPost: number } | null;
  delivered: "card" | "lean" | "none" | "n/a";
  missed?: { constraints: string[]; values: string[] };
};

/** One row per compaction in a session, or none when the session has no owner prompt (a harness run). */
export function audit(session: Session, samples = false): Row[] {
  const events = session.events;
  if (!events.some((event) => event.kind === "prompt")) return [];
  const errors = new Map<string, boolean>();
  for (const event of events) if (event.kind === "result") errors.set(event.id, event.error);
  // Calls in order, so windows are index ranges. A re-read in a window is a read of a file the
  // session first read before the window began: paging through a file inside the window is not one.
  const calls: { read: string | null; failKey: string | null }[] = [];
  const firstRead = new Map<string, number>();
  const callIndexAt: number[] = [];
  events.forEach((event) => {
    callIndexAt.push(calls.length);
    if (event.kind !== "call") return;
    if (event.read !== null && !firstRead.has(event.read)) firstRead.set(event.read, calls.length);
    const key = event.command ? `$ ${event.command.replace(/\s+/g, " ").trim()}` : event.read ? `read ${event.read}` : `${event.tool} ${event.edits.join(",")}`;
    calls.push({ read: event.read, failKey: errors.get(event.id) ? key : null });
  });
  const reads = (from: number, to: number): { reads: number; rereads: number } => {
    const window = calls.slice(from, to).filter((call) => call.read !== null);
    return { reads: window.length, rereads: window.filter((call) => call.read !== null && (firstRead.get(call.read) ?? from) < from).length };
  };
  const compactionIdx = events.flatMap((event, index) => (event.kind === "compaction" ? [index] : []));
  const rows: Row[] = [];
  const constraints: string[] = [];
  const values = new Set<string>();
  const edited = new Set<string>();
  let ask: string[] | null = null;
  let depth = 0;
  events.forEach((event, index) => {
    if (event.kind === "prompt") {
      ask ??= stems(prose(event.text).slice(0, 600));
      for (const sentence of constraintsOf(event.text)) if (!constraints.some((seen) => flat(seen) === flat(sentence))) constraints.push(sentence);
      for (const value of valuesOf(event.text)) values.add(value);
      return;
    }
    if (event.kind === "call") {
      for (const key of event.edits) edited.add(key);
      return;
    }
    if (event.kind !== "compaction") return;
    depth += 1;
    const { compaction } = event;
    const text = `${compaction.summary}\n${compaction.carried}`;
    const lower = text.toLowerCase();
    const visibleFlat = flat(text);
    const visible = new Set(stems(text));
    const gist = constraints.filter((sentence) => {
      const words = stems(sentence);
      return words.length >= 3 ? share(words, visible) >= 0.6 : visibleFlat.includes(flat(sentence));
    });
    const verbatim = constraints.filter((sentence) => visibleFlat.includes(flat(sentence).replace(/[.!]+$/, "")));
    const keptValues = [...values].filter((value) => lower.includes(value));
    const files = [...edited].map((key) => basename(key));
    const next = compactionIdx.find((at) => at > index) ?? events.length;
    const from = callIndexAt[index] ?? calls.length;
    const to = Math.min(from + WINDOW, callIndexAt[next] ?? calls.length);
    const pre = reads(Math.max(0, from - WINDOW), from);
    const post = reads(from, to);
    const failedBefore = new Set(calls.slice(0, from).flatMap((call) => (call.failKey ? [call.failKey] : [])));
    const failedAfter = calls.slice(from, to).flatMap((call) => (call.failKey ? [call.failKey] : []));
    let delivered: Row["delivered"] = session.host === "codex" ? "n/a" : "none";
    for (const later of events.slice(index + 1, Math.min(next, index + 60))) {
      const card = (later.kind === "inject" || later.kind === "result") && later.card;
      if (card) { delivered = "card"; break; }
      if (later.kind === "inject" && /Work lean:/.test(later.text)) delivered = "lean";
    }
    rows.push({
      host: session.host, session: basename(session.file), project: basename(session.cwd || "?"), at: new Date(event.at).toISOString(), depth,
      method: compaction.method, visibility: compaction.visibility, tokensBefore: compaction.tokensBefore, tokensAfter: compaction.tokensAfter,
      summaryChars: compaction.summary.length, carriedChars: compaction.carried.length,
      constraints: { n: constraints.length, gist: gist.length, verbatim: verbatim.length },
      values: { n: values.size, kept: keptValues.length },
      files: { n: files.length, kept: files.filter((file) => lower.includes(file)).length },
      ask: ask && ask.length >= 3 ? share(ask, visible) >= 0.5 : null,
      behaviour: session.host === "codex" ? null : {
        readsPre: pre.reads, rereadsPre: pre.rereads, readsPost: post.reads, rereadsPost: post.rereads,
        failuresPost: failedAfter.length, repeatFailures: new Set(failedAfter.filter((key) => failedBefore.has(key))).size,
        callsPost: to - from,
      },
      delivered,
      ...(samples ? { missed: {
        constraints: constraints.filter((sentence) => !gist.includes(sentence)).slice(0, 3).map((sentence) => sentence.slice(0, 120)),
        values: [...values].filter((value) => !keptValues.includes(value)).slice(0, 5),
      } } : {}),
    });
  });
  return rows;
}

const BUCKETS = ["1", "2", "3-4", "5-9", "10+"];
const bucket = (depth: number): string => (depth >= 10 ? "10+" : depth >= 5 ? "5-9" : depth >= 3 ? "3-4" : String(depth));
const pct = (part: number, whole: number): string => (whole ? `${((100 * part) / whole).toFixed(0)}%` : "-");

/** Pooled (micro) rates per host × visibility × depth bucket: every probe counts once. */
export function table(rows: Row[]): string {
  const groups = new Map<string, Row[]>();
  const sorted = [...rows].sort((a, b) => a.host.localeCompare(b.host) || a.visibility.localeCompare(b.visibility)
    || BUCKETS.indexOf(bucket(a.depth)) - BUCKETS.indexOf(bucket(b.depth)));
  for (const row of sorted) {
    const key = `${row.host}\t${row.visibility}\t${bucket(row.depth)}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  const lines = ["host\tsummary\tdepth\tn\tvisible chars p50\tconstraints gist/verbatim\tvalues\tfiles\task\treread pre→post\tpost fails (repeats)\tbrain card/lean"];
  for (const [key, group] of groups) {
    const sum = (pick: (row: Row) => number): number => group.reduce((total, row) => total + pick(row), 0);
    const sizes = group.map((row) => row.summaryChars + row.carriedChars).sort((a, b) => a - b);
    const asks = group.filter((row) => row.ask !== null);
    const measured = group.filter((row) => row.behaviour !== null);
    const behaviour = (pick: (b: NonNullable<Row["behaviour"]>) => number): number => measured.reduce((total, row) => total + (row.behaviour ? pick(row.behaviour) : 0), 0);
    const deliverable = group.filter((row) => row.delivered !== "n/a");
    lines.push([
      key, group.length, sizes[Math.floor(sizes.length / 2)],
      `${pct(sum((row) => row.constraints.gist), sum((row) => row.constraints.n))}/${pct(sum((row) => row.constraints.verbatim), sum((row) => row.constraints.n))} of ${sum((row) => row.constraints.n)}`,
      `${pct(sum((row) => row.values.kept), sum((row) => row.values.n))} of ${sum((row) => row.values.n)}`,
      `${pct(sum((row) => row.files.kept), sum((row) => row.files.n))} of ${sum((row) => row.files.n)}`,
      pct(asks.filter((row) => row.ask).length, asks.length),
      measured.length ? `${pct(behaviour((b) => b.rereadsPre), behaviour((b) => b.readsPre))}→${pct(behaviour((b) => b.rereadsPost), behaviour((b) => b.readsPost))}` : "n/a",
      measured.length ? `${(behaviour((b) => b.failuresPost) / measured.length).toFixed(2)} (${(behaviour((b) => b.repeatFailures) / measured.length).toFixed(2)})` : "n/a",
      deliverable.length ? `${pct(deliverable.filter((row) => row.delivered === "card").length, deliverable.length)}/${pct(deliverable.filter((row) => row.delivered === "lean").length, deliverable.length)}` : "n/a",
    ].join("\t"));
  }
  return lines.join("\n");
}

async function selfTest(): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), "compaction-audit-test-"));
  const write = (name: string, rows: object[]): string => {
    const file = join(dir, name);
    writeFileSync(file, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    return file;
  };
  const failures: string[] = [];
  const expect = (label: string, actual: unknown, wanted: unknown): void => {
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) failures.push(`${label}: got ${JSON.stringify(actual)}, want ${JSON.stringify(wanted)}`);
  };
  try {
    const t = (s: number): string => new Date(Date.UTC(2026, 9, 1, 0, 0, s)).toISOString();
    const omp = write("omp.jsonl", [
      { type: "session", id: "s", cwd: "C:/w", timestamp: t(0) },
      { type: "message", id: "u1", timestamp: t(1), message: { role: "user", content: [{ type: "text", text: "Fix the tokenizer bug in src/parse.ts. Never edit anything inside vendor/lib.txt because upstream owns it. Staging uses port 47213." }] } },
      { type: "message", id: "a1", timestamp: t(2), message: { role: "assistant", content: [{ type: "toolCall", id: "t1", name: "read", arguments: { path: "src/parse.ts:1-40" } }] } },
      { type: "message", id: "r1", timestamp: t(3), message: { role: "toolResult", toolCallId: "t1", content: [{ type: "text", text: "code" }], isError: false } },
      { type: "message", id: "a2", timestamp: t(4), message: { role: "assistant", content: [{ type: "toolCall", id: "t2", name: "edit", arguments: { input: "[src/parse.ts#AB12]\nPUT 1.=1:\n+x" } }] } },
      { type: "message", id: "r2", timestamp: t(5), message: { role: "toolResult", toolCallId: "t2", content: [{ type: "text", text: "ok" }], isError: false } },
      { type: "message", id: "a3", timestamp: t(6), message: { role: "assistant", content: [{ type: "text", text: "Edited parse.ts" }] } },
      { type: "compaction", id: "c1", timestamp: t(7), summary: "Goal: fix the tokenizer bug. Rule: never edit vendor files; upstream owns them.", firstKeptEntryId: "a3", tokensBefore: 120000, tokensAfter: 9000, method: "soft" },
      { type: "message", id: "a4", timestamp: t(8), message: { role: "assistant", content: [{ type: "toolCall", id: "t3", name: "read", arguments: { path: "C:/w/src/parse.ts" } }] } },
      { type: "message", id: "r3", timestamp: t(9), message: { role: "toolResult", toolCallId: "t3", content: [{ type: "text", text: "code\n\nBrain · demo — what prior sessions learned; the repo wins on conflict" }], isError: false } },
    ]);
    const claude = write("claude.jsonl", [
      { type: "user", uuid: "u1", cwd: "C:/w", timestamp: t(1), message: { role: "user", content: "Always run the unit tests with --runInBand before committing anything." } },
      { type: "assistant", uuid: "a1", timestamp: t(2), message: { role: "assistant", content: [{ type: "tool_use", id: "x1", name: "Bash", input: { command: "npm test  --runInBand" } }] } },
      { type: "user", uuid: "r1", timestamp: t(3), message: { role: "user", content: [{ type: "tool_result", tool_use_id: "x1", is_error: true, content: "fail" }] } },
      { type: "system", subtype: "compact_boundary", uuid: "b1", timestamp: t(4), compactMetadata: { trigger: "auto", preTokens: 150000, postTokens: 5000, preservedMessages: { uuids: ["r1"] } } },
      { type: "user", uuid: "s1", timestamp: t(5), isCompactSummary: true, message: { role: "user", content: "This session is being continued from a previous conversation. The user asked to run tests." } },
      { type: "attachment", uuid: "h1", timestamp: t(6), attachment: { type: "hook_additional_context", hookName: "SessionStart", content: ["Brain · demo — what prior sessions learned; the repo wins on conflict"] } },
      { type: "assistant", uuid: "a2", timestamp: t(7), message: { role: "assistant", content: [{ type: "tool_use", id: "x2", name: "Bash", input: { command: "npm test --runInBand" } }] } },
      { type: "user", uuid: "r2", timestamp: t(8), message: { role: "user", content: [{ type: "tool_result", tool_use_id: "x2", is_error: true, content: "fail" }] } },
    ]);
    const prompt = "Never push to main directly; open a pull request from the feature branch instead.";
    const codex = write("codex.jsonl", [
      { timestamp: t(0), type: "session_meta", payload: { originator: "codex-tui", cwd: "C:/w" } },
      { timestamp: t(1), type: "response_item", payload: { type: "message", role: "user", content: [{ type: "input_text", text: "<environment_context>cwd</environment_context>" }] } },
      { timestamp: t(2), type: "response_item", payload: { type: "message", role: "user", content: [{ type: "input_text", text: prompt }] } },
      { timestamp: t(3), type: "event_msg", payload: { type: "token_count", info: { last_token_usage: { total_tokens: 200000 } } } },
      { timestamp: t(4), type: "compacted", payload: { message: "", replacement_history: [{ type: "message", role: "user", content: [{ type: "input_text", text: prompt }] }, { type: "compaction", encrypted_content: "x" }] } },
    ]);
    const harness = write("codex-exec.jsonl", [{ timestamp: t(0), type: "session_meta", payload: { originator: "codex_exec", source: "exec", cwd: "C:/w" } }]);

    const one = async (host: Host, file: string, samples: boolean): Promise<Row> => {
      const session = await parseSession(host, file);
      const found = session ? audit(session, samples) : [];
      if (found.length !== 1 || !found[0]) throw new Error(`${host} fixture: expected one compaction row, got ${found.length}`);
      return found[0];
    };
    const o = await one("omp", omp, true);
    expect("omp visibility", o.visibility, "text");
    expect("omp constraint kept as gist, not verbatim", o.constraints, { n: 1, gist: 1, verbatim: 0 });
    expect("omp values: parse.ts kept; lib.txt and 47213 lost", { n: o.values.n, kept: o.values.kept, missed: o.missed?.values }, { n: 3, kept: 1, missed: ["lib.txt", "47213"] });
    expect("omp edited file kept", o.files, { n: 1, kept: 1 });
    expect("omp re-read after the compaction", [o.behaviour?.readsPost, o.behaviour?.rereadsPost], [1, 1]);
    expect("omp card in the next tool result", o.delivered, "card");

    const c = await one("claude", claude, true);
    expect("claude constraint lost", c.constraints, { n: 1, gist: 0, verbatim: 0 });
    expect("claude flag lost", c.values, { n: 1, kept: 0 });
    expect("claude same failing command, whitespace-insensitive", c.behaviour?.repeatFailures, 1);
    expect("claude SessionStart card", c.delivered, "card");
    expect("claude preserved message carried", c.carriedChars > 0, true);

    const x = await one("codex", codex, false);
    expect("codex opaque summary, verbatim user message", [x.visibility, x.constraints, x.tokensBefore], ["opaque", { n: 1, gist: 1, verbatim: 1 }, 200000]);
    expect("codex behaviour not measured", [x.behaviour, x.delivered], [null, "n/a"]);
    expect("codex exec run skipped", await parseSession("codex", harness), null);

    const rule = "Never edit the vendored files here. ";
    expect("more than eight rules in one prompt is a pasted document", [constraintsOf(rule.repeat(8)).length, constraintsOf(rule.repeat(9)).length], [8, 0]);
    expect("a hard-wrapped rule is one sentence", constraintsOf("Do not perform an architectural\nrewrite of the parser.\n- always keep the API"), ["Do not perform an architectural rewrite of the parser.", "always keep the API"]);
    expect("questions are not constraints", constraintsOf("Should we never cache this?"), []);
    expect("years are not values", valuesOf("Shipped in 2026 with build 4417 and --dry-run"), ["--dry-run", "4417"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  if (failures.length) throw new Error(`self-test failed:\n${failures.join("\n")}`);
  process.stdout.write("self-test ok\n");
}

async function main(): Promise<void> {
  const { values: opts } = parseArgs({
    options: {
      days: { type: "string", default: "30" },
      hosts: { type: "string", default: HOSTS.join(",") },
      output: { type: "string" },
      samples: { type: "boolean", default: false },
      "self-test": { type: "boolean", default: false },
    },
  });
  if (opts["self-test"]) return selfTest();
  const days = Number(opts.days);
  if (!Number.isFinite(days) || days < 0) throw new Error("--days must be a number >= 0 (0 = all history)");
  const hosts = opts.hosts.split(",").map((host) => host.trim()).filter((host): host is Host => (HOSTS as string[]).includes(host));
  const since = days ? Date.now() - days * 86_400_000 : 0;
  const roots = sessionRoots();
  const out = opts.output ?? mkdtempSync(join(tmpdir(), "compaction-audit-"));
  mkdirSync(out, { recursive: true });
  const rows: Row[] = [];
  const started = Date.now();
  for (const host of hosts) {
    const files = sessionFiles(host, roots[host], since);
    let compacted = 0;
    let harness = 0;
    for (const file of files) {
      if (!hasCompaction(host, file)) continue;
      compacted += 1;
      const session = await parseSession(host, file);
      const found = session ? audit(session, opts.samples) : [];
      if (!found.length) harness += 1;
      rows.push(...found);
    }
    process.stderr.write(`${host}: ${files.length} sessions, ${compacted} with a compaction, ${harness} skipped (no owner prompt)\n`);
  }
  writeFileSync(join(out, "compactions.jsonl"), rows.map((row) => JSON.stringify(row)).join("\n") + (rows.length ? "\n" : ""));
  process.stdout.write(`${table(rows)}\n\n${rows.length} compactions in ${((Date.now() - started) / 1000).toFixed(1)} s → ${join(out, "compactions.jsonl")}\n`);
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
