import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { judgedAnswer, JUDGE_THRESHOLD, type Judge } from "../src/judge.ts";
import type { Note } from "../src/notes.ts";
import { logUse, stats, toraVerdict, TORA_EVIDENCE } from "../src/telemetry.ts";
import { TORA_ADD, TORA_FLOOR, TORA_TIMEOUT_MS, toraScorer, type ToraScorer } from "../src/tora.ts";

const project = { id: "test", tags: [], root: null };
function note(id: string, over: Partial<Note> = {}): Note {
  return { id, kind: "note", project: "test", private: false, at: "2026-09-28", source: "agent", tags: [], errors: [], evidence: [], tested: false, body: "Quartz migration guidance", path: "", ...over };
}
const roots: string[] = [];
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const sem = (id: string, over: Partial<Note> = {}) => note(id, { body: `${id} about schema versions`, ...over });
const QUERY = "quartz migration";

/** Scores by id (anything unlisted 0.1) and records what it was sent. */
function fakeTora(scores: Record<string, number>, cut = 0.76) {
  const pools: string[][] = [];
  const scorer: ToraScorer = async (_query, pool) => {
    pools.push(pool.map(n => n.id));
    return { scores: new Map(pool.map(n => [n.id, scores[n.id] ?? 0.1])), cut, ms: 5 };
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
  const notes = [note("lex"), sem("sem")];
  const jev = { lex: 0.9, sem: 0.95 };
  const plain = await judgedAnswer(notes, QUERY, { project }, fakeJudge(jev).judge);
  expect(plain.ids).toEqual(["lex"]);
  const gone: ToraScorer = async () => undefined;
  const broken: ToraScorer = async () => { throw new Error("boom"); };
  for (const tora of [undefined, gone, broken]) expect(await judgedAnswer(notes, QUERY, { project }, fakeJudge(jev).judge, tora)).toEqual(plain);
});

it("sends a Tora-found note to the same Jev request; it follows the lexical survivors only if Jev keeps it", async () => {
  const notes = [note("lex"), sem("sem")];
  const { scorer, pools } = fakeTora({ lex: 0.8, sem: 0.9 });
  const kept = fakeJudge({ lex: 0.9, sem: JUDGE_THRESHOLD });
  const result = await judgedAnswer(notes, QUERY, { project }, kept.judge, scorer);
  expect(kept.calls).toEqual([["lex", "sem"]]);
  expect(pools).toEqual([["lex", "sem"]]);
  expect(result).toMatchObject({ ids: ["lex", "sem"], hits: 2, judged: true, dropped: 0 });
  expect(result.text.split("\n")).toHaveLength(2);
  expect(result.text.split("\n")[1]).toContain("sem [note] sem about schema versions");
  expect(result.tora).toEqual({ ms: 5, cut: 0.76, floor: TORA_FLOOR, skip: false, enforced: false, c: [["lex", 0.8, 0.9, "l", 1], ["sem", 0.9, JUDGE_THRESHOLD, "t", 1]] });
  const dropped = await judgedAnswer(notes, QUERY, { project }, fakeJudge({ lex: 0.9, sem: JUDGE_THRESHOLD - 0.001 }).judge, scorer);
  expect(dropped.ids).toEqual(["lex"]);
  expect(dropped.text).not.toContain("sem");
});

it("adds at most TORA_ADD notes, best Tora score first, and orders kept ones by Jev probability within the line cap", async () => {
  expect(TORA_ADD).toBe(2);
  const notes = [note("lex"), sem("a"), sem("b"), sem("c"), sem("below")];
  const { scorer } = fakeTora({ lex: 0.8, a: 0.8, b: 0.95, c: 0.9, below: 0.75 });
  const jev = fakeJudge({ lex: 0.9, a: 0.99, b: 0.85, c: 0.95 });
  const result = await judgedAnswer(notes, QUERY, { project }, jev.judge, scorer);
  expect(jev.calls).toEqual([["lex", "b", "c"]]);
  expect(result.ids).toEqual(["lex", "c", "b"]);
  // Three lexical survivors leave no room: additions never exceed the usual cap.
  const full = Array.from({ length: 3 }, (_, i) => note(`l${i}`));
  const capped = await judgedAnswer([...full, sem("extra")], QUERY, { project }, fakeJudge({ l0: 1, l1: 1, l2: 1, extra: 1 }).judge, fakeTora({ extra: 0.9 }).scorer);
  expect(capped.ids).toEqual(["l0", "l1", "l2"]);
});

it("never sends or adds private, retired or other-project notes, even with the top scores", async () => {
  const notes = [note("lex"), sem("hidden", { private: true }), sem("old", { retired: "2026-09-28" }), sem("away", { project: "other" }), sem("ok")];
  const { scorer, pools } = fakeTora({ lex: 0.8, hidden: 0.99, old: 0.98, away: 0.97, ok: 0.9 });
  const jev = fakeJudge({ lex: 0.9, hidden: 1, old: 1, away: 1, ok: 0.9 });
  const result = await judgedAnswer(notes, QUERY, { project }, jev.judge, scorer);
  expect(pools).toEqual([["lex", "ok"]]);
  expect(jev.calls).toEqual([["lex", "ok"]]);
  expect(result.ids).toEqual(["lex", "ok"]);
});

it("lexical empty: a kept Tora addition is the answer; no addition means no Jev call and the lexical result", async () => {
  const notes = [sem("sem"), sem("other")];
  const query = "zebra crossing";
  const lexical = await judgedAnswer(notes, query, { project }, fakeJudge({}).judge);
  expect(lexical.hits).toBe(0);
  const jev = fakeJudge({ sem: 0.9 });
  const result = await judgedAnswer(notes, query, { project }, jev.judge, fakeTora({ sem: 0.8 }).scorer);
  expect(jev.calls).toEqual([["sem"]]);
  expect(result).toMatchObject({ ids: ["sem"], hits: 1, judged: true });
  expect(result.text).toContain("sem [note]");
  const none = fakeJudge({});
  expect(await judgedAnswer(notes, query, { project }, none.judge, fakeTora({ sem: 0.5 }).scorer)).toEqual(lexical);
  expect(none.calls).toEqual([]);
  // A Tora addition Jev rejects leaves the usual no-match answer.
  const rejected = await judgedAnswer(notes, query, { project }, fakeJudge({ sem: 0.2 }).judge, fakeTora({ sem: 0.8 }).scorer);
  expect(rejected).toMatchObject({ ids: [], hits: 0, text: lexical.text });
});

it("shadow mode logs that the floor would skip but still asks Jev and keeps the answer", async () => {
  const notes = [note("lex")];
  const plain = await judgedAnswer(notes, QUERY, { project }, fakeJudge({ lex: 0.9 }).judge);
  const jev = fakeJudge({ lex: 0.9 });
  const result = await judgedAnswer(notes, QUERY, { project }, jev.judge, fakeTora({ lex: TORA_FLOOR - 0.01 }).scorer);
  expect(jev.calls).toHaveLength(1);
  const { tora, ...answer } = result;
  expect(answer).toEqual(plain);
  expect(tora).toMatchObject({ skip: true, enforced: false, c: [["lex", TORA_FLOOR - 0.01, 0.9, "l", 1]] });
});

it("enforced floor skips Jev and drops the lexical candidates; one candidate at the floor sends it normally", async () => {
  const notes = [note("lex")];
  const low = fakeJudge({ lex: 0.9 });
  const skipped = await judgedAnswer(notes, QUERY, { project }, low.judge, fakeTora({ lex: 0.5 }).scorer, true);
  expect(low.calls).toEqual([]);
  expect(skipped).toMatchObject({ ids: [], hits: 0, dropped: 1, text: "no match; note it once you learn it" });
  expect(skipped).toMatchObject({ judged: false });
  expect(skipped.tora).toMatchObject({ skip: true, enforced: true, c: [["lex", 0.5, null, "l", null]] });
  const mixed = [note("lex"), note("near")];
  const jev = fakeJudge({ lex: 0.9, near: 0.9 });
  const result = await judgedAnswer(mixed, QUERY, { project }, jev.judge, fakeTora({ lex: 0.5, near: TORA_FLOOR }).scorer, true);
  expect(jev.calls).toEqual([["lex", "near"]]);
  expect(result).toMatchObject({ ids: ["lex", "near"], judged: true });
  expect(result.tora).toMatchObject({ skip: false });
});

it("enforced floor falls through to the doc branch like a Jev drop (Jev still checks the doc excerpt)", async () => {
  const base = mkdtempSync(join(tmpdir(), "brain-tora-doc-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(join(root, "docs"), { recursive: true });
  writeFileSync(join(root, "docs", "LOOP.md"), "# Plan\n\n## Quartz migration\nOrder the quartz steps by schema version.\n\n## Other\nUnrelated.\n");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md"] } } }));
  const jev = fakeJudge({ "doc:docs/LOOP.md": 0.9, n1: 0.9 });
  const result = await judgedAnswer([note("n1", { project: "repo" })], "quartz migration steps", { project: { id: "repo", tags: [], root }, home }, jev.judge, fakeTora({ n1: 0.5 }).scorer, true);
  expect(jev.calls).toEqual([["doc:docs/LOOP.md"]]);
  expect(result).toMatchObject({ ids: ["doc:docs/LOOP.md"], judged: true, dropped: 1 });
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
  const notes = [sem("sem", { project: "repo" })];
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

it("stats: a kept candidate in a would-skip recall is lost; ready only with enough scored kept candidates and none lost", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-tora-stats-"));
  roots.push(home);
  const empty = stats(home);
  expect(empty.tora).toEqual({ recalls: 0, added: 0, addedKept: 0, wouldSkip: 0, lost: 0, kept: 0, keptBelowFloor: 0 });
  expect(toraVerdict(empty.tora)).toBe(`skip floor: not ready (0/${TORA_EVIDENCE} Jev-kept candidates carry a Tora score)`);
  const row = (c: [string, number, number | null, "l" | "t", 0 | 1 | null][], skip = false) =>
    logUse(home, { kind: "recall", project: "test", tokens: 1, ms: 1, tora: { ms: 5, cut: 0.76, floor: TORA_FLOOR, skip, enforced: false, c } });
  for (let i = 0; i < TORA_EVIDENCE - 1; i++) row([["a", 0.8, 0.9, "l", 1]]);
  expect(toraVerdict(stats(home).tora)).toContain(`${TORA_EVIDENCE - 1}/${TORA_EVIDENCE}`);
  row([["t", 0.78, 0.85, "t", 1], ["d", 0.5, 0.2, "l", 0]]);
  const ready = stats(home).tora;
  expect(ready).toEqual({ recalls: TORA_EVIDENCE, added: 1, addedKept: 1, wouldSkip: 0, lost: 0, kept: TORA_EVIDENCE, keptBelowFloor: 0 });
  expect(toraVerdict(ready)).toBe("skip floor: ready");
  // Only the recorded decision counts: a 0.6 kept at the phrase floor is kept, a 0.9 flagged 0 is not, a null is neither.
  row([["x", 0.6, 0.6, "l", 1], ["y", 0.5, 0.9, "l", 0], ["z", 0.5, null, "l", null]], true);
  const lost = stats(home).tora;
  expect(lost).toMatchObject({ wouldSkip: 1, lost: 1, keptBelowFloor: 1, kept: TORA_EVIDENCE + 1 });
  expect(toraVerdict(lost)).toBe("skip floor: not ready (1 Jev-kept candidate inside would-skip recalls)");
});

it("records the answer's own keep decision per candidate, including the phrase floor", async () => {
  const notes = [note("phrase", { body: "The Witcher 3 5.0 keeps its render" }), note("words", { body: "Witcher mods need patch 3" })];
  const result = await judgedAnswer(notes, "witcher 3", { project }, fakeJudge({ phrase: 0.6, words: 0.6 }).judge, fakeTora({ phrase: 0.8, words: 0.8 }).scorer);
  expect(result.ids).toEqual(["phrase"]);
  expect([...result.tora!.c].sort()).toEqual([["phrase", 0.8, 0.6, "l", 1], ["words", 0.8, 0.6, "l", 0]]);
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
  const fetched = stubFetch({ scores: { a: 0.8, b: 0.7 }, cut: 0.76, ms: 3 });
  const scored = await toraScorer(env)!("q", POOL);
  expect(scored).toMatchObject({ scores: new Map([["a", 0.8], ["b", 0.7]]), cut: 0.76 });
  expect(String(fetched.mock.calls[0]![0])).toBe("http://127.0.0.1:2222/score");
  expect((fetched.mock.calls[0]![1]!.headers as Record<string, string>).authorization).toBe("Bearer newest");
  expect(TORA_TIMEOUT_MS).toBe(800);
  // With a session of this process's host, it wins over a newer one.
  session(dir, process.ppid, { port: 4444, token: "own", host_pid: process.pid, started: "2026-10-11T01:00:00Z" });
  const own = stubFetch({ scores: { a: 0.8, b: 0.7 }, cut: 0.76, ms: 3 });
  await toraScorer(env)!("q", POOL);
  expect(String(own.mock.calls[0]![0])).toContain(":4444/");
});

it("discovery: only dead sessions, no directory, or BRAIN_TORA=off mean no scorer call", async () => {
  const { env, dir } = sessions();
  session(dir, 2 ** 30, {});
  const fetched = stubFetch({ scores: { a: 1, b: 1 }, cut: 0.7, ms: 1 });
  expect(await toraScorer(env)!("q", POOL)).toBeUndefined();
  expect(await toraScorer({ LOCALAPPDATA: join(env.LOCALAPPDATA, "missing") })!("q", POOL)).toBeUndefined();
  session(dir, process.pid, {});
  expect(toraScorer({ ...env, BRAIN_TORA: "off" })).toBeUndefined();
  expect(fetched).not.toHaveBeenCalled();
});

it("a failed, non-200 or malformed Tora response is undefined and never leaks the token", async () => {
  const { env, dir } = sessions();
  session(dir, process.pid, { token: "secret-token" });
  const bad: [unknown, number?][] = [
    [{ scores: { a: 0.8, b: 0.7 }, cut: 0.76 }, 401],
    ["not json"],
    [{ scores: { a: 0.8 }, cut: 0.76 }],
    [{ scores: { a: 0.8, b: "0.7" }, cut: 0.76 }],
    [{ scores: { a: 0.8, b: 0.7 } }],
    [{ scores: { a: 0.8, b: 1e999 }, cut: 0.76 }],
    [{ scores: { a: 0.8, b: 0.7 }, cut: "x" }],
  ];
  for (const [body, status] of bad) {
    stubFetch(body, status);
    expect(await toraScorer(env)!("q", POOL)).toBeUndefined();
  }
  const log = vi.spyOn(console, "error");
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("connect ECONNREFUSED Bearer secret-token"); }));
  expect(await toraScorer(env)!("q", POOL)).toBeUndefined();
  expect(log).not.toHaveBeenCalled();
});
