import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { judgeScorer, judgedAnswer, JUDGE_THRESHOLD, onJevScale, PHRASE_FLOOR, recallJudge, TORA_JUDGE_BAR, TORA_PHRASE_FLOOR, type Judge, type ToraRecall } from "../src/judge.ts";
import type { Note } from "../src/notes.ts";
import { answerWithHits } from "../src/search.ts";
import { logUse, stats } from "../src/telemetry.ts";
import { TORA_ADD, TORA_FLOOR, toraScorer, type ToraScorer } from "../src/tora.ts";

const project = { id: "test", tags: [], root: null };
function note(id: string, over: Partial<Note> = {}): Note {
  return { id, kind: "note", project: "test", private: false, at: "2026-09-28", source: "agent", tags: [], errors: [], evidence: [], tested: false, body: "Quartz migration guidance", path: "", ...over };
}
const roots: string[] = [];
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
/** BM25 ranks it on "migration", but the lexical answer drops it: "quartz" carries more of the query. */
const gated = (id: string, over: Partial<Note> = {}) => note(id, { body: `${id}: migration of schema versions`, ...over });
const QUERY = "quartz migration";
/** Only "migration" occurs in any note, so no note passes the lexical gate. */
const NO_HIT = "zebra migration";

/** Scores by id (anything unlisted 0.1) and records what it was sent. */
function fakeTora(scores: Record<string, number>) {
  const pools: string[][] = [];
  const scorer: ToraScorer = async (_query, pool) => {
    pools.push(pool.map(n => n.id));
    return { scores: new Map(pool.map(n => [n.id, scores[n.id] ?? 0.1])), ms: 5 };
  };
  return { scorer, pools };
}
/** Jev with fixed probabilities (unlisted 0.1); records the candidate ids of each call. */
function fakeJudge(p: Record<string, number>) {
  const calls: string[][] = [];
  const judge: Judge = async (_q, candidates) => { calls.push(candidates.map(c => c.id)); return new Map(candidates.map(c => [c.id, p[c.id] ?? 0.1])); };
  return { judge, calls };
}

it("Tora absent, failing or throwing leaves the answer identical to the no-Tora path", async () => {
  const notes = [note("lex"), gated("sem")];
  const jev = { lex: 0.9, sem: 0.95 };
  const plain = await judgedAnswer(notes, QUERY, { project }, fakeJudge(jev).judge);
  expect(plain.ids).toEqual(["lex"]);
  const gone: ToraScorer = async () => undefined;
  const broken: ToraScorer = async () => { throw new Error("boom"); };
  for (const tora of [undefined, gone, broken]) expect(await judgedAnswer(notes, QUERY, { project }, fakeJudge(jev).judge, tora)).toEqual(plain);
});

it("re-checks what BM25 ranked but the lexical answer dropped: at the floor it joins the same Jev request and shows only if Jev keeps it", async () => {
  const notes = [note("lex"), gated("a"), gated("b")];
  expect(answerWithHits(notes, QUERY, { project }).ids).toEqual(["lex"]);
  const { scorer, pools } = fakeTora({ a: 0.9, b: TORA_FLOOR - 0.01 });
  const kept = fakeJudge({ lex: 0.9, a: JUDGE_THRESHOLD });
  const result = await judgedAnswer(notes, QUERY, { project }, kept.judge, scorer);
  expect(pools).toEqual([["a", "b"]]);
  expect(kept.calls).toEqual([["lex", "a"]]);
  expect(result).toMatchObject({ ids: ["lex", "a"], hits: 2, judged: true, dropped: 0 });
  expect(result.text.split("\n")[1]).toContain("a [note] a: migration of schema versions");
  expect(result.tora).toEqual({ ms: 5, c: [["a", 0.9, JUDGE_THRESHOLD, 1], ["b", TORA_FLOOR - 0.01, null, null]] });
  const dropped = await judgedAnswer(notes, QUERY, { project }, fakeJudge({ lex: 0.9, a: JUDGE_THRESHOLD - 0.001 }).judge, scorer);
  expect(dropped.ids).toEqual(["lex"]);
  expect(dropped.tora?.c[0]).toEqual(["a", 0.9, JUDGE_THRESHOLD - 0.001, 0]);
});

it("never shows Tora a note BM25 did not rank, nor a private, retired or other-project one, whatever its cosine", async () => {
  const notes = [note("lex"), note("only", { body: "only about schema versions" }), gated("hidden", { private: true }), gated("old", { retired: "2026-09-28" }), gated("away", { project: "other" }), gated("ok")];
  const { scorer, pools } = fakeTora({ only: 0.99, hidden: 0.99, old: 0.98, away: 0.97, ok: 0.9 });
  const jev = fakeJudge({ lex: 0.9, only: 1, hidden: 1, old: 1, away: 1, ok: 0.9 });
  const result = await judgedAnswer(notes, QUERY, { project }, jev.judge, scorer);
  expect(pools).toEqual([["ok"]]);
  expect(jev.calls).toEqual([["lex", "ok"]]);
  expect(result.ids).toEqual(["lex", "ok"]);
});

it("local recall judges gated BM25 candidates directly without /score, preserving privacy, scope, cap and bar", async () => {
  const { env, dir } = sessions();
  session(dir, process.pid, { port: 1300 });
  const notes = [gated("a"), gated("b"), gated("c"), gated("hidden", { private: true }), gated("old", { retired: "2026-09-28" }), gated("away", { project: "other" }), note("unranked", { body: "schema versions only" })];
  const fetched = stubFetch({ scores: { a: 0.999, b: 0.998, c: 1 } });
  const result = await judgedAnswer(notes, NO_HIT, { project }, recallJudge({ ...env, BRAIN_JUDGE: "tora" }), undefined, true);
  expect(fetched).toHaveBeenCalledTimes(1);
  expect(String(fetched.mock.calls[0]![0])).toMatch(/\/judge$/);
  expect(JSON.parse(String(fetched.mock.calls[0]![1]!.body)).notes.map((n: { id: string }) => n.id)).toEqual(["a", "b"]);
  expect(result.ids).toEqual(["a"]);
  expect(result.recall?.local).toMatchObject([{ route: "/judge", outcome: "ok" }]);
  expect(result.tora).toBeUndefined();
});

it("sends at most TORA_ADD, best cosine first, and orders kept ones by Jev probability; no BM25 rank left means no Tora call", async () => {
  expect(TORA_ADD).toBe(2);
  const notes = [gated("a"), gated("b"), gated("c")];
  expect(answerWithHits(notes, NO_HIT, { project }).hits).toBe(0);
  const { scorer, pools } = fakeTora({ a: 0.8, b: 0.95, c: 0.9 });
  const jev = fakeJudge({ a: 0.99, b: 0.85, c: 0.95 });
  const result = await judgedAnswer(notes, NO_HIT, { project }, jev.judge, scorer);
  expect(pools).toEqual([["a", "b", "c"]]);
  expect(jev.calls).toEqual([["b", "c"]]);
  expect(result.ids).toEqual(["c", "b"]);
  // BM25's top three are the lexical answer: nothing is left for Tora to re-check.
  const full = [note("l0"), note("l1"), note("l2"), gated("extra")];
  const late = fakeTora({ extra: 0.99 });
  const capped = await judgedAnswer(full, QUERY, { project }, fakeJudge({ l0: 1, l1: 1, l2: 1, extra: 1 }).judge, late.scorer);
  expect(capped.ids).toEqual(["l0", "l1", "l2"]);
  expect(late.pools).toEqual([]);
});

it("lexical empty: a kept Tora candidate is the answer; none at the floor means no Jev call and the lexical result", async () => {
  const notes = [gated("sem"), gated("other")];
  const lexical = await judgedAnswer(notes, NO_HIT, { project }, fakeJudge({}).judge);
  expect(lexical.hits).toBe(0);
  const jev = fakeJudge({ sem: 0.9 });
  const result = await judgedAnswer(notes, NO_HIT, { project }, jev.judge, fakeTora({ sem: 0.8 }).scorer);
  expect(jev.calls).toEqual([["sem"]]);
  expect(result).toMatchObject({ ids: ["sem"], hits: 1, judged: true });
  expect(result.text).toContain("sem [note]");
  const none = fakeJudge({});
  const below = await judgedAnswer(notes, NO_HIT, { project }, none.judge, fakeTora({ sem: TORA_FLOOR - 0.01 }).scorer);
  expect(none.calls).toEqual([]);
  const { tora, ...answer } = below;
  expect(answer).toEqual(lexical);
  expect([...tora!.c].sort()).toEqual([["other", 0.1, null, null], ["sem", TORA_FLOOR - 0.01, null, null]]);
  // A Tora candidate Jev rejects leaves the usual no-match answer.
  const rejected = await judgedAnswer(notes, NO_HIT, { project }, fakeJudge({ sem: 0.2 }).judge, fakeTora({ sem: 0.8 }).scorer);
  expect(rejected).toMatchObject({ ids: [], hits: 0, text: lexical.text });
});

function docFixture() {
  const base = mkdtempSync(join(tmpdir(), "brain-tora-doc-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(join(root, "docs"), { recursive: true });
  writeFileSync(join(root, "docs", "LOOP.md"), "# Plan\n\n## Quartz migration\nOrder the quartz steps by schema version.\n\n## Other\nUnrelated.\n");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md"] } } }));
  return { opts: { project: { id: "repo", tags: [], root }, home } };
}

it("a lexical doc-excerpt answer is unchanged and checked as before; a kept Tora note is appended after it", async () => {
  const { opts } = docFixture();
  const query = "quartz migration steps";
  const notes = [gated("sem", { project: "repo" })];
  const plain = await judgedAnswer(notes, query, opts, fakeJudge({ "doc:docs/LOOP.md": 0.9 }).judge);
  expect(plain.ids).toEqual(["doc:docs/LOOP.md"]);
  const jev = fakeJudge({ sem: 0.9, "doc:docs/LOOP.md": 0.9 });
  const result = await judgedAnswer(notes, query, opts, jev.judge, fakeTora({ sem: 0.9 }).scorer);
  expect(jev.calls).toEqual([["sem"], ["doc:docs/LOOP.md"]]);
  expect(result.ids).toEqual(["doc:docs/LOOP.md", "sem"]);
  expect(result.text.split("\n")[0]).toBe(plain.text);
  expect(result.text.split("\n")[1]).toContain("sem [note]");
  expect(result).toMatchObject({ hits: 2, judged: true });
  // Jev drops the doc: the note stands alone. Jev drops the note: today's doc answer is untouched.
  expect((await judgedAnswer(notes, query, opts, fakeJudge({ sem: 0.9, "doc:docs/LOOP.md": 0.1 }).judge, fakeTora({ sem: 0.9 }).scorer)).ids).toEqual(["sem"]);
  const noteDropped = await judgedAnswer(notes, query, opts, fakeJudge({ sem: 0.1, "doc:docs/LOOP.md": 0.9 }).judge, fakeTora({ sem: 0.9 }).scorer);
  expect(noteDropped).toMatchObject({ ids: ["doc:docs/LOOP.md"], text: plain.text });
});

it("stats count recalls Tora scored, candidates Jev judged and kept; an entry of another shape counts for nothing", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-tora-stats-"));
  roots.push(home);
  expect(stats(home).tora).toEqual({ recalls: 0, scored: 0, judged: 0, kept: 0 });
  const row = (c: ToraRecall["c"]) => logUse(home, { kind: "recall", project: "test", tokens: 1, ms: 1, tora: { ms: 5, c } });
  row([["a", 0.9, 0.85, 1], ["b", 0.72, 0.4, 0], ["c", 0.5, null, null]]);
  row([]);
  // A row from the build with the shadow skip floor: [id, cosine, p, "l" | "t", kept].
  row([["old", 0.8, 0.9, "t", 1]] as unknown as ToraRecall["c"]);
  expect(stats(home).tora).toEqual({ recalls: 3, scored: 3, judged: 2, kept: 1 });
});

function session(dir: string, pid: number, over: Record<string, unknown>): void {
  writeFileSync(join(dir, `${pid}.json`), JSON.stringify({ port: 1, token: "tok", pid, host_pid: null, started: "2026-10-11T05:00:00Z", ...over }));
}
function sessions() {
  const base = mkdtempSync(join(tmpdir(), "brain-tora-"));
  roots.push(base);
  const dir = join(base, "tora", "sessions");
  mkdirSync(dir, { recursive: true });
  return { env: { LOCALAPPDATA: base }, dir };
}
const POOL = [{ id: "a", text: "alpha" }, { id: "b", text: "beta" }];
function stubFetch(body: unknown, status = 200) {
  const fetched = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(typeof body === "string" ? body : JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetched);
  return fetched;
}

it("discovery: skips dead pids, prefers this host's session, then the newest, and sends the bearer token", async () => {
  const { env, dir } = sessions();
  session(dir, 2 ** 30, { port: 1111, token: "dead", started: "2026-10-11T09:00:00Z" });
  session(dir, process.pid, { port: 2222, token: "newest", started: "2026-10-11T08:00:00Z" });
  session(dir, process.ppid, { port: 3333, token: "older", started: "2026-10-11T07:00:00Z" });
  const fetched = stubFetch({ scores: { a: 0.8, b: 0.7 }, ms: 3 });
  const scored = await toraScorer(env)!("q", POOL);
  expect(scored?.scores).toEqual(new Map([["a", 0.8], ["b", 0.7]]));
  expect(String(fetched.mock.calls[0]![0])).toBe("http://127.0.0.1:2222/score");
  expect((fetched.mock.calls[0]![1]!.headers as Record<string, string>).authorization).toBe("Bearer newest");
  // With a session of this process's host, it wins over a newer one.
  session(dir, process.ppid, { port: 4444, token: "own", host_pid: process.pid, started: "2026-10-11T01:00:00Z" });
  const own = stubFetch({ scores: { a: 0.8, b: 0.7 }, ms: 3 });
  await toraScorer(env)!("q", POOL);
  expect(String(own.mock.calls[0]![0])).toContain(":4444/");
});

it("discovery: only dead sessions, no directory or BRAIN_TORA=off mean no scorer, and BRAIN_JUDGE=jev gates judging while the card keeps Tora", async () => {
  const { env, dir } = sessions();
  session(dir, 2 ** 30, {});
  const fetched = stubFetch({ scores: { a: 1, b: 1 }, ms: 1 });
  expect(toraScorer(env)).toBeUndefined();
  expect(toraScorer({ LOCALAPPDATA: join(env.LOCALAPPDATA, "missing") })).toBeUndefined();
  session(dir, process.pid, {});
  expect(toraScorer({ ...env, BRAIN_TORA: "off" })).toBeUndefined();
  expect(judgeScorer({ ...env, BRAIN_JUDGE: "jev" })).toBeUndefined();
  expect(judgeScorer({ ...env, BRAIN_JUDGE: "off" })).toBeUndefined();
  expect(toraScorer({ ...env, BRAIN_JUDGE: "jev" })).toBeDefined();
  expect(toraScorer(env)).toBeDefined();
  expect(fetched).not.toHaveBeenCalled();
});

it("a failed, non-200 or malformed Tora response is undefined and never leaks the token", async () => {
  const { env, dir } = sessions();
  const bad: [unknown, number?][] = [
    [{ scores: { a: 0.8, b: 0.7 } }, 401],
    ["not json"],
    [{ cut: 0.76 }],
    [{ scores: { a: 0.8 } }],
    [{ scores: { a: 0.8, b: "0.7" } }],
    [{ scores: { a: 0.8, b: 1e999 } }],
  ];
  for (const [i, [body, status]] of bad.entries()) {
    session(dir, process.pid, { token: "secret-token", port: 1000 + i });
    const fetched = stubFetch(body, status);
    const scorer = toraScorer(env)!;
    expect(await scorer("q", POOL)).toBeUndefined();
    expect(fetched).toHaveBeenCalledTimes(1);
    expect(scorer.attempts?.[0]?.outcome).toBe(i === 0 ? "http" : "malformed");
  }
  const log = vi.spyOn(console, "error");
  for (const [i, code] of ["ECONNREFUSED", "ECONNRESET"].entries()) {
    session(dir, process.pid, { token: "secret-token", port: 1100 + i });
    const fetched = vi.fn(async () => { throw new Error("connect Bearer secret-token", { cause: { code } }); });
    vi.stubGlobal("fetch", fetched);
    const scorer = toraScorer(env)!;
    expect(await scorer("q", POOL)).toBeUndefined();
    expect(fetched).toHaveBeenCalledTimes(1);
    expect(scorer.attempts?.[0]?.outcome).toBe(i === 0 ? "refused" : "transport");
  }
  session(dir, process.pid, { port: 1200 });
  const fetched = stubFetch({ scores: { a: 1.2, b: 0.5 } });
  const judge = recallJudge({ ...env, BRAIN_JUDGE: "tora" })!;
  expect(await judge("q", POOL)).toBeUndefined();
  expect(fetched).toHaveBeenCalledTimes(1);
  expect(judge.attempts?.[0]?.outcome).toBe("malformed");
  expect(log).not.toHaveBeenCalled();
});

it("Tora's reranker scores land on Jev's bars: its bar is the judge threshold, its phrase floor the phrase floor, order kept", () => {
  expect(onJevScale(TORA_JUDGE_BAR)).toBeCloseTo(JUDGE_THRESHOLD, 9);
  expect(onJevScale(TORA_PHRASE_FLOOR)).toBeCloseTo(PHRASE_FLOOR, 9);
  expect(onJevScale(TORA_JUDGE_BAR + 0.0001)).toBeGreaterThan(JUDGE_THRESHOLD);
  expect(onJevScale(TORA_JUDGE_BAR - 0.0001)).toBeLessThan(JUDGE_THRESHOLD);
  const raw = [0, 1e-6, 0.2, 0.5, 0.9, 0.99, 0.998, 0.999, 0.99999, 1];
  const mapped = raw.map(onJevScale);
  expect(mapped.every((p, i) => p >= 0 && p <= 1 && (i === 0 || p > mapped[i - 1]!))).toBe(true);
});

it("recall judge: Tora's /judge first and Jev never called; Jev only when Tora gives no verdict; BRAIN_JUDGE picks or forbids either", async () => {
  const { env, dir } = sessions();
  session(dir, process.pid, { port: 5555, token: "tok" });
  const paid = { ...env, TYPESAFE_API_KEY: "synthetic-test-credential", TYPESAFE_BASE_URL: "https://judge.invalid" };
  const calls: string[] = [];
  const respond = (toraStatus: number) => vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
    calls.push(String(url));
    if (String(url).endsWith("/judge")) return new Response(JSON.stringify({ scores: { a: 0.9995, b: 0.2 } }), { status: toraStatus });
    return new Response(JSON.stringify({ answers: { rel_0: { noul: 0.9 }, rel_1: { noul: 0.1 } } }), { status: 200 });
  }));
  respond(200);
  const local = await recallJudge(paid)!("q", POOL);
  expect(calls).toEqual(["http://127.0.0.1:5555/judge"]);
  expect(local?.by).toBe("tora");
  expect(local!.get("a")!).toBeGreaterThan(JUDGE_THRESHOLD);
  expect(local!.get("b")!).toBeLessThan(PHRASE_FLOOR);
  calls.length = 0; respond(503);
  const fallback = await recallJudge(paid)!("q2", POOL);
  expect(calls).toEqual(["http://127.0.0.1:5555/judge", "https://judge.invalid/v1/systemone"]);
  expect(fallback?.by).toBe("jev");
  expect(fallback?.get("a")).toBe(0.9);
  calls.length = 0;
  expect(await recallJudge({ ...paid, BRAIN_JUDGE: "tora" })!("q3", POOL)).toBeUndefined();
  // The preceding failed /judge route is briefly cooled down; tora-only still never pays.
  expect(calls).toEqual([]);
  calls.length = 0; respond(200);
  expect((await recallJudge({ ...paid, BRAIN_JUDGE: "jev" })!("q4", POOL))?.by).toBe("jev");
  expect(calls).toEqual(["https://judge.invalid/v1/systemone"]);
  expect(recallJudge({ ...paid, BRAIN_JUDGE: "off" })).toBeUndefined();
  // No live Tora and no key: no judge, so recall stays synchronous and lexical.
  expect(recallJudge({ LOCALAPPDATA: join(env.LOCALAPPDATA, "missing") })).toBeUndefined();
});

it("stats count judged recalls by the judge that answered", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-judges-"));
  roots.push(home);
  for (const judge of ["tora", "tora", "jev", undefined] as const) logUse(home, { kind: "recall", project: "test", tokens: 1, ms: 1, judged: judge !== undefined, judge });
  expect(stats(home).judges).toEqual({ tora: 2, jev: 1 });
});
