import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { judgedAnswer, judgeText, JUDGE_THRESHOLD, JUDGE_TIMEOUT_MS, typesafeJudge, type Judge } from "../src/judge.ts";
import { answerWithHits } from "../src/search.ts";
import type { Note } from "../src/notes.ts";

const project = { id: "test", tags: [], root: null };
function note(id: string, over: Partial<Note> = {}): Note {
  return { id, kind: "note", project: "test", private: false, at: "2026-09-28", source: "agent", tags: [], errors: [], evidence: [], tested: false, body: "Quartz migration guidance", path: "", ...over };
}
const roots: string[] = [];
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const rejectAll: Judge = async (_query, candidates) => new Map(candidates.map(c => [c.id, 0.1]));

it("drops probabilities below the threshold, keeps the boundary, and does not backfill unjudged notes", async () => {
  const notes = [note("low"), note("boundary"), note("high"), note("unshown")];
  const lexical = answerWithHits(notes, "quartz migration", { project });
  expect(lexical.ids).toHaveLength(3);
  const judge: Judge = async (_query, candidates) => new Map(candidates.map((c, i) => [c.id, [JUDGE_THRESHOLD - 0.001, JUDGE_THRESHOLD, 1][i]!]));
  const result = await judgedAnswer(notes, "quartz migration", { project }, judge);
  expect(JUDGE_THRESHOLD).toBe(0.78);
  expect(result.ids).toEqual(lexical.ids.slice(1));
  expect(result).toMatchObject({ judged: true, dropped: 1, hits: 2 });
});

it("all dropped uses normal silence and cross-project hints", async () => {
  const notes = [note("local")];
  expect(await judgedAnswer(notes, "quartz migration", { project }, rejectAll)).toMatchObject({ text: "no match; note it once you learn it", ids: [], judged: true, dropped: 1 });
  notes.push(note("elsewhere", { project: "other" }));
  expect(await judgedAnswer(notes, "quartz migration", { project, tools: false }, rejectAll)).toMatchObject({ text: "no match here; 1 related in other projects (--all)", ids: [] });
  expect(await judgedAnswer([note("a"), note("b"), note("c"), note("d")], "quartz migration", { project }, rejectAll)).toMatchObject({ text: "no match; note it once you learn it", ids: [], dropped: 3 });
});

it("checks a plan-doc heading answer like a note (including after every note is dropped), but not the outline of a doc the query names", async () => {
  const base = mkdtempSync(join(tmpdir(), "brain-judge-doc-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(join(root, "docs"), { recursive: true });
  writeFileSync(join(root, "docs", "LOOP.md"), "# Plan\n\n## Quartz migration\nOrder the quartz steps by schema version.\n\n## Other\nUnrelated.\n");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md"] } } }));
  const repo = { id: "repo", tags: [], root };
  const seen: string[] = [];
  const scoring = (p: number): Judge => async (_q, candidates) => { seen.push(...candidates.map(c => c.text)); return new Map(candidates.map(c => [c.id, p])); };
  expect(await judgedAnswer([], "quartz migration steps", { project: repo, home }, scoring(0.9))).toMatchObject({ text: "docs/LOOP.md › Quartz migration (line 3)", judged: true, dropped: 0 });
  expect(seen.at(-1)).toBe("Quartz migration: Order the quartz steps by schema version.");
  expect(await judgedAnswer([], "quartz migration steps", { project: repo, home }, scoring(0.2))).toMatchObject({ text: "no match; note it once you learn it", ids: [], judged: true, dropped: 1 });
  // Every note dropped: the doc fallback that follows is checked too.
  expect(await judgedAnswer([note("n1", { project: "repo" })], "quartz migration steps", { project: repo, home }, scoring(0.2))).toMatchObject({ ids: [], dropped: 2 });
  seen.length = 0;
  expect(await judgedAnswer([], "LOOP.md", { project: repo, home }, scoring(0.1))).toMatchObject({ text: "docs/LOOP.md: Quartz migration · Other" });
  expect(seen).toEqual([]);
});

it.each([undefined, async () => undefined, async () => { throw new Error("unavailable"); }, async () => new Map<string, number>()])("failed or missing judge preserves the whole lexical answer", async judge => {
  const notes = [note("local")];
  expect(await judgedAnswer(notes, "quartz migration", { project }, judge)).toEqual({ ...answerWithHits(notes, "quartz migration", { project }), judged: false, dropped: 0 });
});

it("keeps private notes without sending them, including private-only answers", async () => {
  const notes = [note("public"), note("private", { private: true })];
  const judge = vi.fn(rejectAll);
  expect(await judgedAnswer(notes, "quartz migration", { project }, judge)).toMatchObject({ ids: ["private"], dropped: 1 });
  expect(judge.mock.calls[0]?.[1]).toEqual([{ id: "public", text: "Quartz migration guidance" }]);
  judge.mockClear();
  expect(await judgedAnswer(notes.slice(1), "quartz migration", { project }, judge)).toMatchObject({ ids: ["private"], judged: false });
  expect(judge).not.toHaveBeenCalled();
});

it("explicit note-id recalls are never judged", async () => {
  const notes = [note("local")]; const judge = vi.fn(rejectAll);
  expect(await judgedAnswer(notes, " local ", { project }, judge)).toEqual({ ...answerWithHits(notes, " local ", { project }), judged: false, dropped: 0 });
  expect(judge).not.toHaveBeenCalled();
});

it("does not resurrect a dropped retired note or its replacement", async () => {
  const notes = [note("old", { retired: "2026-09-28", replacedBy: "new" }), note("new", { body: "Different current advice" })];
  expect(answerWithHits(notes, "quartz migration", { project }).ids).toEqual(["new", "old"]);
  expect(await judgedAnswer(notes, "quartz migration", { project }, rejectAll)).toMatchObject({ ids: [], dropped: 2 });
});

it("collapses whitespace, cuts at 450 characters, then scrubs note text and the query", async () => {
  const original = note("safe", { body: "Quartz\n\t migration password=syntheticSecret123 " + "ordinary words ".repeat(50) });
  const text = judgeText(original);
  expect(text).toBe(("Quartz migration password=syntheticSecret123 " + "ordinary words ".repeat(50)).slice(0, 450).replace("syntheticSecret123", "***"));
  const judge = vi.fn(async (_query: string, candidates: { id: string; text: string }[]) => new Map(candidates.map(c => [c.id, 1])));
  await judgedAnswer([original], "quartz migration password=syntheticSecret123", { project }, judge);
  expect(judge.mock.calls[0]).toEqual(["quartz migration password=***", [{ id: "safe", text }]]);
});

it("uses the calibrated request and caches by query, note id and text across factory calls", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ answers: { rel_0: { noul: 0.75 }, rel_1: { noul: 0.2 } } }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const env = { TYPESAFE_API_KEY: "synthetic-test-credential", TYPESAFE_BASE_URL: "https://judge.invalid" };
  const candidates = [{ id: "request-a", text: "Candidate alpha" }, { id: "request-b", text: "Candidate beta" }];
  const judge = typesafeJudge(env)!;
  expect(await judge("request-shape", candidates)).toEqual(new Map([["request-a", 0.75], ["request-b", 0.2]]));
  const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("https://judge.invalid/v1/systemone");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ Authorization: "Bearer " + env.TYPESAFE_API_KEY, Accept: "application/json", "Content-Type": "application/json" });
  expect(JSON.parse(init.body as string)).toEqual({ state: { query: "request-shape" }, model: "jev-latest", questions: {
    rel_0: { type: "noul", instructions: "Is candidate c0 relevant to the query in the state? Candidate c0: Candidate alpha", criteria: { true: "The candidate addresses the subject the query asks about, or provides what it seeks", false: "The candidate is about a different subject, or only shares vocabulary with the query" } },
    rel_1: { type: "noul", instructions: "Is candidate c1 relevant to the query in the state? Candidate c1: Candidate beta", criteria: { true: "The candidate addresses the subject the query asks about, or provides what it seeks", false: "The candidate is about a different subject, or only shares vocabulary with the query" } },
  } });
  await typesafeJudge(env)!("request-shape", candidates);
  expect(fetch).toHaveBeenCalledTimes(1);
  await judge("changed-query", candidates);
  await judge("request-shape", [{ ...candidates[0]!, text: "Changed text" }]);
  await judge("request-shape", [{ ...candidates[0]!, id: "changed-id" }]);
  expect(fetch).toHaveBeenCalledTimes(4);
});

it("no key or opt-out never constructs a judge", () => {
  expect(typesafeJudge({})).toBeUndefined();
  expect(typesafeJudge({ TYPESAFE_API_KEY: "synthetic", BRAIN_JUDGE: "off" })).toBeUndefined();
});

it.each([{}, { answers: {} }, { answers: { rel_0: { noul: "0.9" } } }, { answers: { rel_0: { noul: -0.1 } } }, { answers: { rel_0: { noul: 1.1 } } }, { answers: { rel_0: { noul: 0.9 } } }])("invalid or incomplete responses fail the whole call without caching partial results", async body => {
  const fetch = vi.fn(async () => new Response(JSON.stringify(body)));
  vi.stubGlobal("fetch", fetch);
  const judge = typesafeJudge({ TYPESAFE_API_KEY: "synthetic" })!;
  const candidates = [{ id: "invalid-a", text: "alpha" }, { id: "invalid-b", text: "beta" }];
  expect(await judge("invalid-response", candidates)).toBeUndefined();
  expect(await judge("invalid-response", candidates)).toBeUndefined();
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each(["http", "parse", "throw", "abort"])("%s errors fail open without exposing the key", async mode => {
  const env = { TYPESAFE_API_KEY: "synthetic-secret-never-reported" };
  const timeout = vi.spyOn(AbortSignal, "timeout");
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    if (mode === "http") return new Response(env.TYPESAFE_API_KEY, { status: 503 });
    if (mode === "parse") return new Response("not json " + env.TYPESAFE_API_KEY);
    if (mode === "abort") {
      expect(init.signal).toBeInstanceOf(AbortSignal);
      throw new DOMException("Aborted " + env.TYPESAFE_API_KEY, "AbortError");
    }
    throw new Error(env.TYPESAFE_API_KEY);
  }));
  const notes = [note("errors")];
  expect(await judgedAnswer(notes, "quartz migration", { project }, typesafeJudge(env))).toEqual({ ...answerWithHits(notes, "quartz migration", { project }), judged: false, dropped: 0 });
  expect(timeout).toHaveBeenCalledWith(JUDGE_TIMEOUT_MS);
});

it("an abort signal settling a pending fetch preserves the lexical answer", async () => {
  const controller = new AbortController();
  vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
  vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal!.addEventListener("abort", () => reject(init.signal!.reason), { once: true });
  })));
  const notes = [note("timeout")];
  const pending = judgedAnswer(notes, "quartz migration", { project }, typesafeJudge({ TYPESAFE_API_KEY: "synthetic-timeout" }));
  controller.abort(new DOMException("Timed out", "TimeoutError"));
  expect(await pending).toEqual({ ...answerWithHits(notes, "quartz migration", { project }), judged: false, dropped: 0 });
});
