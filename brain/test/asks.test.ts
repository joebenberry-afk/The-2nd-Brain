import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { collectAsks, formatWeek, MAX_WEEKS, parseAsks, weeklyAsks, type Ask } from "../src/asks.ts";

const roots: string[] = [];
afterEach(() => { while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true }); });

const t = (minute: number, second = 0): string => new Date(Date.UTC(2026, 9, 5, 10, minute, second)).toISOString();
const jsonl = (...entries: object[]): string[] => entries.map(e => JSON.stringify(e));

const ompUser = (at: string, attribution = "user") => ({ type: "message", timestamp: at, message: { role: "user", attribution, content: [{ type: "text", text: "do it" }] } });
const ompAssistant = (at: string, usage?: object) => ({ type: "message", timestamp: at, message: { role: "assistant", content: [], stopReason: "toolUse", ...(usage ? { usage } : {}) } });
const ompResult = (at: string) => ({ type: "message", timestamp: at, message: { role: "toolResult", content: [] } });

it("OMP: counts every model request of a tool-call loop up to the next prompt, and ignores injected messages", () => {
  const asks = parseAsks(jsonl(
    { type: "session", timestamp: t(0), cwd: "/x" },
    ompUser(t(0, 10)),
    { type: "custom_message", customType: "brain.card", timestamp: t(0, 11), content: "card" },
    ompAssistant(t(0, 20)), ompResult(t(0, 25)), ompAssistant(t(0, 40)), ompResult(t(0, 45)), ompAssistant(t(1, 10)),
    { type: "custom_message", customType: "async-result", timestamp: t(2), content: "job done" },
    ompAssistant(t(2, 10)),
    ompUser(t(5)), // a prompt with no model request is dropped
    ompUser(t(6)),
    ompAssistant(t(6, 30)),
    ompUser(t(9), "agent"), // injected by an agent, not the owner: stays in the open span
    ompAssistant(t(9, 30)),
  ), "omp");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[4, 120], [2, 210]]);
});

it("an idle gap over 5 minutes ends the ask: later turns are a background wake-up and count for nothing", () => {
  const asks = parseAsks(jsonl(
    ompUser(t(0)),
    ompAssistant(t(0, 30)), ompResult(t(1)), ompAssistant(t(1, 30)),
    ompAssistant(t(21, 30)), ompResult(t(22)), ompAssistant(t(22, 30)), ompAssistant(t(23)),
  ), "omp");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[2, 90]]);
});

const ccUser = (at: string, content: unknown, extra: object = {}) => ({ type: "user", isSidechain: false, timestamp: at, message: { role: "user", content }, ...extra });
const ccAssistant = (at: string, id: string, extra: object = {}, usage?: object) => ({ type: "assistant", isSidechain: false, timestamp: at, message: { id, role: "assistant", model: "claude-opus-5-5", content: [{ type: "text", text: "x" }], ...(usage ? { usage } : {}) }, ...extra });
const ccToolResult = (at: string) => ccUser(at, [{ type: "tool_result", tool_use_id: "t1", content: "out" }]);

it("Claude Code: one request spans several content-block entries; tool results, meta, sidechain and harness prompts never split or inflate an ask", () => {
  const asks = parseAsks(jsonl(
    ccUser(t(0), "fix the bug", { origin: { kind: "human" } }),
    ccAssistant(t(0, 5), "m1"), ccAssistant(t(0, 6), "m1"), ccAssistant(t(0, 7), "m1"), // thinking + text + tool_use of one request
    ccToolResult(t(0, 20)),
    ccAssistant(t(0, 30), "m2"),
    ccAssistant(t(0, 40), "side", { isSidechain: true }), // subagent work inside the parent file
    ccUser(t(0, 50), [{ type: "text", text: "[Image: source: x.png]" }], { isMeta: true }),
    ccUser(t(0, 55), "<task-notification>done</task-notification>", { origin: { kind: "task-notification" } }),
    ccUser(t(1), [{ type: "text", text: "<command-name>/compact</command-name>" }]),
    ccAssistant(t(1, 5), "err", { message: { id: "err", role: "assistant", model: "<synthetic>", content: [] } }),
    ccAssistant(t(1, 30), "m3"),
    ccUser(t(3), "second request"),
    ccAssistant(t(3, 30), "m4"),
    ccUser(t(4), "scripted", { entrypoint: "sdk-py" }), // headless harness run, not the owner
    ccAssistant(t(4, 30), "m5"),
  ), "claude");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[3, 90], [2, 90]]);
});

it("sums each request's host usage once per ask and drops a partial price", () => {
  const ompUsage = (input: number, output: number, cacheRead: number, cacheWrite: number, cost: number) => ({
    input, output, cacheRead, cacheWrite, totalTokens: input + output + cacheRead + cacheWrite, cost: { total: cost },
  });
  const asks = parseAsks(jsonl(
    ompUser(t(0)),
    ompAssistant(t(0, 5), ompUsage(10, 2, 3, 4, 0.25)),
    ompAssistant(t(0, 10), ompUsage(20, 5, 6, 7, 0.5)),
    // OMP also writes session-level usage elsewhere; it must not become another turn.
    { type: "model_usage", timestamp: t(0, 15), usage: { input: 999, output: 999 } },
  ), "omp");
  expect(asks).toHaveLength(1);
  expect(asks[0]!.usage).toEqual({ requests: 2, input: 30, output: 7, cacheRead: 9, cacheWrite: 11, cost: 0.75 });

  const claudeUsage = (input: number, output: number, cacheRead: number, cacheWrite: number) => ({
    input_tokens: input, output_tokens: output, cache_read_input_tokens: cacheRead, cache_creation_input_tokens: cacheWrite,
  });
  const claude = parseAsks(jsonl(
    ccUser(t(0), "fix the bug", { origin: { kind: "human" } }),
    ccAssistant(t(0, 5), "m1", {}, claudeUsage(1, 2, 10, 20)),
    ccAssistant(t(0, 6), "m1", {}, claudeUsage(1, 2, 10, 20)), // thinking + text of the same request
    ccAssistant(t(0, 10), "m2", {}, claudeUsage(3, 4, 30, 40)),
    ccAssistant(t(0, 15), "m3"), // an aborted request: counters are absent, so no price is claimed
  ), "claude");
  expect(claude).toHaveLength(1);
  expect(claude[0]).toMatchObject({ turns: 3, usage: { requests: 2, input: 4, output: 6, cacheRead: 40, cacheWrite: 60 } });
  expect(claude[0]!.usage?.cost).toBeUndefined();
});

it("prints measured weekly input, cache, output and price; an unmeasured ask is marked", () => {
  const usage = { requests: 1, input: 1_000, output: 100, cacheRead: 3_000, cacheWrite: 1_000, cost: 0.42 };
  const withUsage: Ask = { at: Date.UTC(2026, 9, 5, 10), turns: 3, wallMs: 30_000, usage };
  const noUsage: Ask = { at: Date.UTC(2026, 9, 5, 11), turns: 5, wallMs: 60_000 };
  const [row] = weeklyAsks([withUsage, noUsage], 1, new Date(Date.UTC(2026, 9, 6)));
  expect(row!.usage).toEqual({ asks: 1, input: 1_000, output: 100, cacheRead: 3_000, cacheWrite: 1_000, cost: 0.42, costAsks: 1 });
  expect(formatWeek(row!)).toBe("2026-10-05 · 2 asks · turns median 4 (p75 5) · wall median 0.8 min · 1/2 measured: 5k in (60% cached) · 100 out · $0.42");
});

it("collects main sessions of the project only, never subagent transcripts, and reports weekly medians", () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-asks-"));
  roots.push(dir);
  const write = (path: string, header: object, ...entries: object[]): void => {
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, jsonl(header, ...entries).join("\n") + "\n");
  };
  const ask = (start: number, turns: number, seconds: number): object[] => [
    ompUser(t(start)), ...Array.from({ length: turns }, (_, i) => ompAssistant(t(start, i === turns - 1 ? seconds : 1 + i))),
  ];
  write(join(dir, "omp", "proj", "main.jsonl"), { type: "session", cwd: "/work/mine" }, ...ask(0, 3, 30), ...ask(10, 7, 60), ...ask(20, 5, 30));
  write(join(dir, "omp", "proj", "main", "sub.jsonl"), { type: "session", cwd: "/work/mine" }, ...ask(30, 40, 59)); // subagent: deeper folder
  write(join(dir, "omp", "other", "main.jsonl"), { type: "session", cwd: "/work/theirs" }, ...ask(40, 9, 50));
  write(join(dir, "claude", "proj", "c.jsonl"), { type: "queue-operation", timestamp: t(0) }, ccUser(t(0), "hi", { cwd: "/work/mine" }), ccAssistant(t(0, 30), "a"));

  const asks = collectAsks({ omp: join(dir, "omp"), claude: join(dir, "claude") }, Date.UTC(2026, 9, 1), cwd => cwd === "/work/mine");
  expect(asks.map(a => a.turns).sort((a, b) => a - b)).toEqual([1, 3, 5, 7]);

  const rows = weeklyAsks(asks, 2, new Date(Date.UTC(2026, 9, 6)));
  expect(rows.map(r => r.week)).toEqual(["2026-09-28", "2026-10-05"]);
  expect(rows[0]).toMatchObject({ asks: 0 });
  expect(formatWeek(rows[0]!)).toBe("2026-09-28 · 0 asks");
  expect(formatWeek(rows[1]!)).toBe("2026-10-05 · 4 asks · turns median 4 (p75 5) · wall median 0.5 min");
});

// ---- scan cache ----

const DAY = 86_400_000;
const tmp = (): string => { const dir = mkdtempSync(join(tmpdir(), "brain-asks-")); roots.push(dir); return dir; };
const session = (path: string, header: object, ...entries: object[]): void => {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, jsonl(header, ...entries).join("\n") + "\n");
};
/** One OMP ask `daysAgo` days back (relative to now: the cache prunes by the real clock): `turns` requests, the last `seconds` after the prompt. */
const askAt = (daysAgo: number, minute: number, turns: number, seconds: number): object[] => {
  const start = Date.now() - daysAgo * DAY + minute * 60_000;
  const iso = (ms: number): string => new Date(ms).toISOString();
  return [ompUser(iso(start)), ...Array.from({ length: turns }, (_, i) => ompAssistant(iso(start + (i === turns - 1 ? seconds : 1 + i) * 1000)))];
};
const age = (path: string, days: number): void => { const at = new Date(Date.now() - days * DAY); utimesSync(path, at, at); };
const turnsOf = (asks: Ask[]): number[] => asks.map(a => a.turns).sort((a, b) => a - b);
type Stored = { v: number; files: Record<string, { cwd: string | null; asks: { turns: number }[] | null }> };
const readCache = (file: string): Stored => JSON.parse(readFileSync(file, "utf8")) as Stored;

it("cache: an unchanged transcript is served from the cache; an append or a same-size rewrite is parsed again", () => {
  const dir = tmp();
  const file = join(dir, "omp", "proj", "main.jsonl");
  const cache = join(dir, "state", "asks-cache.json");
  const scan = (): Ask[] => collectAsks({ omp: join(dir, "omp") }, 0, cwd => cwd === "/work/mine", cache);
  session(file, { type: "session", cwd: "/work/mine" }, ...askAt(1, 0, 3, 30));

  expect(scan().map(a => [a.turns, a.wallMs / 1000])).toEqual([[3, 30]]);
  const stored = readCache(cache);
  expect(Object.keys(stored.files)).toEqual([file]);
  expect(readFileSync(cache, "utf8")).not.toContain("do it"); // summaries only, no transcript text

  // Reuse: a doctored summary comes back as is while the file is unchanged.
  stored.files[file]!.asks![0]!.turns = 99;
  writeFileSync(cache, JSON.stringify(stored));
  expect(turnsOf(scan())).toEqual([99]);

  // An active transcript grows: size changes, the file is parsed again.
  appendFileSync(file, jsonl(...askAt(1, 10, 2, 20)).join("\n") + "\n");
  expect(turnsOf(scan())).toEqual([2, 3]);

  // Rewritten in place with the same size and mtime put back: ctime still moves.
  const before = statSync(file);
  writeFileSync(file, readFileSync(file, "utf8").replace("\"role\":\"assistant\"", "\"role\":\"assistxnt\""));
  utimesSync(file, before.atime, before.mtime);
  expect(statSync(file).size).toBe(before.size);
  expect(turnsOf(scan())).toEqual([2, 2]);
});

it("cache: a wider window parses the transcripts the narrow one skipped; a new scope parses only newly accepted ones", () => {
  const dir = tmp();
  const sessions = join(dir, "omp", "proj");
  const cache = join(dir, "state", "asks-cache.json");
  const mine = join(sessions, "mine.jsonl"), old = join(sessions, "old.jsonl"), theirs = join(sessions, "theirs.jsonl");
  session(mine, { type: "session", cwd: "/work/mine" }, ...askAt(1, 0, 2, 20));
  session(old, { type: "session", cwd: "/work/mine" }, ...askAt(21, 0, 4, 40));
  age(old, 21);
  session(theirs, { type: "session", cwd: "/work/theirs" }, ...askAt(1, 30, 5, 50));
  const scan = (days: number, accept: (cwd: string) => boolean): Ask[] => collectAsks({ omp: join(dir, "omp") }, Date.now() - days * DAY, accept, cache);
  const isMine = (cwd: string): boolean => cwd === "/work/mine";

  expect(turnsOf(scan(7, isMine))).toEqual([2]);
  expect(Object.keys(readCache(cache).files).sort()).toEqual([mine, theirs].sort()); // old is outside the window: not read
  expect(readCache(cache).files[theirs]).toMatchObject({ cwd: "/work/theirs", asks: null }); // another project: header only

  expect(turnsOf(scan(30, isMine))).toEqual([2, 4]); // wider window: the skipped transcript is read now
  expect(Object.keys(readCache(cache).files)).toHaveLength(3);

  expect(turnsOf(scan(7, () => true))).toEqual([2, 5]); // wider scope: the other project's file is parsed now
  expect(readCache(cache).files[theirs]!.asks).toHaveLength(1);

  // A project (re)registered between scans: accept is asked afresh, its answers are never stored.
  expect(turnsOf(scan(7, cwd => cwd === "/work/theirs"))).toEqual([5]);
  expect(turnsOf(scan(7, isMine))).toEqual([2]);
  expect(Object.keys(readCache(cache).files)).toHaveLength(3); // narrowing again keeps what was parsed
});

it("cache: forgets deleted and unsupported-age transcripts, ignores a corrupt, foreign or malformed cache, and survives an unwritable location", () => {
  const dir = tmp();
  const cache = join(dir, "state", "asks-cache.json");
  const live = join(dir, "omp", "proj", "live.jsonl"), gone = join(dir, "omp", "proj", "gone.jsonl"), ancient = join(dir, "omp", "proj", "ancient.jsonl");
  session(live, { type: "session", cwd: "/work/mine" }, ...askAt(1, 0, 2, 20));
  session(gone, { type: "session", cwd: "/work/mine" }, ...askAt(1, 10, 3, 30));
  session(ancient, { type: "session", cwd: "/work/mine" }, ...askAt(7 * (MAX_WEEKS + 8), 0, 6, 60));
  age(ancient, 7 * (MAX_WEEKS + 8));
  const scan = (file = cache): Ask[] => collectAsks({ omp: join(dir, "omp") }, 0, () => true, file);

  expect(turnsOf(scan())).toEqual([2, 3, 6]); // a caller may ask for more than the supported window: answered, not retained
  expect(Object.keys(readCache(cache).files).sort()).toEqual([gone, live].sort());
  rmSync(gone);
  expect(turnsOf(scan())).toEqual([2, 6]);
  expect(Object.keys(readCache(cache).files)).toEqual([live]);

  writeFileSync(cache, "{not json");
  expect(turnsOf(scan())).toEqual([2, 6]);
  expect(Object.keys(readCache(cache).files)).toEqual([live]); // rewritten valid

  const foreign = readCache(cache);
  foreign.v = foreign.v + 1;
  foreign.files[live]!.asks![0]!.turns = 99;
  writeFileSync(cache, JSON.stringify(foreign));
  expect(turnsOf(scan())).toEqual([2, 6]); // another cache version is not trusted

  const malformed = readCache(cache);
  malformed.files[live] = { cwd: 5 } as never;
  writeFileSync(cache, JSON.stringify(malformed));
  expect(turnsOf(scan())).toEqual([2, 6]);
  expect(readCache(cache).files[live]!.cwd).toBe("/work/mine");

  writeFileSync(join(dir, "blocker"), "");
  expect(turnsOf(scan(join(dir, "blocker", "cache.json")))).toEqual([2, 6]); // the cache cannot be written: the scan still answers
});

it("cache: a transcript with no cwd is remembered as such and contributes nothing", () => {
  const dir = tmp();
  const cache = join(dir, "state", "asks-cache.json");
  const file = join(dir, "omp", "proj", "headless.jsonl");
  session(file, { type: "session" }, ...askAt(1, 0, 2, 20));
  const scan = (): Ask[] => collectAsks({ omp: join(dir, "omp") }, 0, () => true, cache);
  expect(scan()).toEqual([]);
  expect(readCache(cache).files[file]).toMatchObject({ cwd: null, asks: [] });
  expect(scan()).toEqual([]);
});
