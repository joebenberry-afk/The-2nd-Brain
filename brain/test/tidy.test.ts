import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cardIds, renderCard } from "../src/card.ts";
import { main, type Io } from "../src/cli.ts";
import { JUDGE_THRESHOLD, typesafePairJudge, type PairJudge } from "../src/judge.ts";
import { createNote, loadNotes, saveNote, type Note } from "../src/notes.ts";
import { logUse, noteUsage } from "../src/telemetry.ts";
import { noteHint, similarPairs, tidyReport } from "../src/tidy.ts";
import { brainTools } from "../src/tools.ts";

const project = { id: "demo", tags: ["node"], root: null };
const roots: string[] = [];
function home(): string {
  const root = mkdtempSync(join(tmpdir(), "brain-tidy-"));
  roots.push(root);
  writeFileSync(join(root, "projects.json"), JSON.stringify({ projects: { demo: { tags: ["node"] } } }));
  return root;
}
function note(id: string, body = "Quartz migration uses numbered steps", over: Partial<Note> = {}): Note {
  return { id, body, kind: "note", project: "demo", private: false, at: new Date().toISOString(), source: "agent", tags: [], errors: [], evidence: [], tested: false, path: "", ...over };
}
async function cli(root: string, args: string[], env: NodeJS.ProcessEnv = {}): Promise<string> {
  const out: string[] = [];
  const errors: string[] = [];
  const io: Io = { cwd: root, env: { SECOND_BRAIN_HOME: root, BRAIN_PROJECT: "demo", ...env }, stdin: () => "", out: text => out.push(text), err: text => errors.push(text) };
  expect(await main(args, io)).toBe(0);
  expect(errors).toEqual([]);
  return out.join("\n");
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

const semantic: PairJudge = async pairs => new Map(pairs.map(({ id, a, b }) => [id, { same: a.includes("backup") && b.includes("backup") ? JUDGE_THRESHOLD : 0, contradicts: (a.includes("ascending") && b.includes("descending")) || (b.includes("ascending") && a.includes("descending")) ? JUDGE_THRESHOLD : 0 }]));

it("reports duplicate and contradictory pairs older-first without changing notes", async () => {
  const root = home();
  const notes = [note("new-order", "Quartz migration uses descending order", { at: "2026-09-02" }), note("old-order", "Quartz migration uses ascending order", { at: "2026-09-01" }), note("old-backup", "Database backup before schema deployment", { at: "2026-09-01" }), note("new-backup", "Database backup before schema deployment always", { at: "2026-09-02" })];
  for (const n of notes) saveNote(root, n);
  const paths = loadNotes(root).notes.map(n => n.path);
  const before = paths.map(path => readFileSync(path, "utf8"));
  const report = await tidyReport(root, notes, project, { judge: semantic });
  expect(report.contradictions.map(({ a, b }) => [a.id, b.id])).toEqual([["old-order", "new-order"]]);
  expect(report.duplicates.map(({ a, b }) => [a.id, b.id])).toEqual([["old-backup", "new-backup"]]);
  expect(report.similar).toEqual([]);
  expect(paths.map(path => readFileSync(path, "utf8"))).toEqual(before);
});

it("without a judge returns lexical pairs and excludes retired, linked and unrelated scopes", async () => {
  const root = home();
  const a = note("a"), b = note("b");
  const notes = [a, b, note("retired", a.body, { retired: "2026-01-01" }), note("elsewhere", a.body, { project: "other" })];
  expect((await tidyReport(root, notes, project)).similar.map(({ a, b }) => [a.id, b.id])).toEqual([["a", "b"]]);
  expect(similarPairs([a, { ...b, replaces: a.id }], 20)).toEqual([]);
  expect(similarPairs([a, { ...b, replacedBy: a.id }], 20)).toEqual([]);
  expect(similarPairs([a, b], 0)).toEqual([]);
  expect(similarPairs([note("global-a", a.body, { project: "global", tags: ["node"] }), note("global-b", a.body, { project: "global", tags: ["python"] })], 20)).toEqual([]);
});

it("unused includes old never-used notes including tested fixes, but excludes recent use and young notes", async () => {
  const root = home();
  const notes = [note("unused", "Unused durable advice", { at: "2000-01-01" }), note("recalled", "Recalled durable advice", { at: "2000-01-01" }), note("fix", "Known unused fix", { at: "2000-01-01", tested: true, errors: ["failure"] }), note("fired", "Known used fix", { at: "2000-01-01", tested: true, errors: ["failure"] }), note("young")];
  logUse(root, { kind: "recall", project: "demo", tokens: 0, ms: 0, query: "advice", ids: ["recalled"] });
  logUse(root, { kind: "fix", project: "demo", tokens: 0, ms: 0, id: "fired" });
  logUse(root, { kind: "card", project: "demo", tokens: 0, ms: 0, ids: ["unused"] }, new Date("2000-01-01"));
  expect((await tidyReport(root, notes, project)).unused.map(n => n.id)).toEqual(["unused", "fix"]);
});

it("hints prioritize contradictions and fail silently for missing, failing or invalid judges", async () => {
  const root = home();
  const old = note("old", "Quartz migration uses ascending order");
  const fresh = note("fresh", "Quartz migration uses descending order");
  expect(await noteHint(root, fresh, [old, fresh], semantic)).toBe(" (contradicts old: if it replaces it, brain retire old --by fresh)");
  expect(await noteHint(root, note("new-backup", "Database backup before schema deployment"), [note("old-backup", "Database backup before schema deployment always")], semantic)).toBe(" (same as old-backup: brain retire new-backup if redundant)");
  for (const judge of [undefined, async () => undefined, async () => { throw new Error("offline"); }, async () => new Map()]) expect(await noteHint(root, fresh, [old], judge)).toBe("");
});

it("private text never reaches either semantic entry point and hints use only three visible candidates", async () => {
  const root = home();
  const seen: { a: string; b: string }[] = [];
  const judge: PairJudge = async pairs => {
    seen.push(...pairs);
    return new Map(pairs.map(p => [p.id, { same: 0.1, contradicts: 0.1 }]));
  };
  const secret = note("private", "Quartz migration private secret", { private: true });
  const fresh = note("fresh");
  const candidates = [secret, ...Array.from({ length: 5 }, (_, i) => note("visible-" + i)), note("other", fresh.body, { project: "other" }), note("retired", fresh.body, { retired: "2026-01-01" })];
  expect(await noteHint(root, secret, candidates, judge)).toBe("");
  expect(seen).toEqual([]);
  expect(await noteHint(root, fresh, candidates, judge)).toBe("");
  expect(seen).toHaveLength(3);
  expect(seen.every(p => !p.a.includes("secret") && !p.b.includes("secret"))).toBe(true);
  seen.length = 0;
  const report = await tidyReport(root, [fresh, secret, note("public")], project, { judge });
  expect(seen).toHaveLength(1);
  expect(report.similar).toHaveLength(2);
  expect(seen.every(p => !p.a.includes("secret") && !p.b.includes("secret"))).toBe(true);
});

it("pair judge batches two noul questions per pair, scrubs text and caches validated scores", async () => {
  const requests: { url: unknown; init: RequestInit; body: { state: { pairs: { a: string; b: string }[] }; questions: Record<string, { type: string }>; model: string } }[] = [];
  const fetch = vi.fn(async (url: unknown, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    requests.push({ url, init, body });
    return new Response(JSON.stringify({ answers: Object.fromEntries(Object.keys(body.questions).map(key => [key, { noul: key.startsWith("same_") ? 0.8 : 0.2 }])) }));
  });
  vi.stubGlobal("fetch", fetch);
  const judge = typesafePairJudge({ TYPESAFE_API_KEY: "synthetic-pair-test", TYPESAFE_BASE_URL: "https://pair-test.invalid" })!;
  const pairs = Array.from({ length: 21 }, (_, i) => ({ id: "shape-" + i, a: "unique shape quartz " + i + " password=syntheticCredential123", b: "unique shape quartz second " + i }));
  const result = await judge(pairs);
  expect(result?.size).toBe(21);
  expect(result?.get("shape-20")).toEqual({ same: 0.8, contradicts: 0.2 });
  expect(requests.map(r => r.body.state.pairs.length)).toEqual([20, 1]);
  expect(requests.map(r => Object.keys(r.body.questions).length)).toEqual([40, 2]);
  expect(requests[0]?.url).toBe("https://pair-test.invalid/v1/systemone");
  expect(requests[0]?.init.headers).toMatchObject({ Authorization: "Bearer synthetic-pair-test" });
  expect(requests[0]?.init.signal).toBeInstanceOf(AbortSignal);
  expect(requests[0]?.body.model).toBe("jev-latest");
  expect(Object.values(requests[0]!.body.questions).every(q => q.type === "noul")).toBe(true);
  expect(JSON.stringify(requests)).not.toContain("syntheticCredential123");
  expect(await judge(pairs)).toEqual(result);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(typesafePairJudge({})).toBeUndefined();
  expect(typesafePairJudge({ TYPESAFE_API_KEY: "synthetic", BRAIN_JUDGE: "off" })).toBeUndefined();
});

it("pair judge fails open for HTTP, transport, parse and malformed probabilities", async () => {
  const responses = [async () => new Response("no", { status: 500 }), async () => { throw new Error("offline"); }, async () => new Response("invalid json"), async () => new Response(JSON.stringify({ answers: { same_0: { noul: 1 }, contradicts_0: { noul: 1.1 } } })), async () => new Response(JSON.stringify({ answers: { same_0: { noul: 1 } } }))];
  for (const [i, response] of responses.entries()) {
    vi.stubGlobal("fetch", response);
    expect(await typesafePairJudge({ TYPESAFE_API_KEY: "synthetic-fail" })!([{ id: "failure-" + i, a: "Unique fail quartz " + i, b: "Other unique fail " + i }])).toBeUndefined();
  }
});

it("cardIds counts ordinary and recurring rendered notes, not omitted notes or working-state pointers", () => {
  const root = home();
  const now = new Date();
  const fix = note("n-fix", "Install quartz runtime", { tested: true, errors: ["runtime mismatch"], project: "global" });
  const ordinary = note("n-ordinary", "Use numbered migration steps");
  const tooLong = note("n-omitted", "long ".repeat(400));
  for (const session of ["a", "b", "c"]) logUse(root, { kind: "fix", project: "demo", id: fix.id, session, tokens: 0, ms: 0 }, now);
  const card = renderCard(root, [fix, ordinary, tooLong], project, { now });
  expect(card).toContain("3×");
  expect(cardIds(card)).toEqual([fix.id, ordinary.id]);
  expect(cardIds(card + "\nGoal: work (not-a-note)\n" + card)).toEqual([fix.id, ordinary.id]);
});

it("noteUsage separates recalled, opened, carded and fired across rotated and current logs", () => {
  const root = home();
  const now = new Date("2026-10-04T00:00:00Z");
  mkdirSync(join(root, "state"), { recursive: true });
  writeFileSync(join(root, "state", "telemetry.1.jsonl"), JSON.stringify({ at: "2026-10-01T00:00:00Z", kind: "recall", query: "quartz advice", ids: ["n-used", "doc:PLAN.md"] }) + "\ninvalid\n");
  logUse(root, { kind: "recall", project: "demo", query: "[N-USED].", ids: ["n-used"], tokens: 0, ms: 0 }, now);
  logUse(root, { kind: "card", project: "demo", ids: ["n-used", "n-used"], tokens: 0, ms: 0 }, now);
  logUse(root, { kind: "fix", project: "demo", id: "n-used", tokens: 0, ms: 0 }, now);
  logUse(root, { kind: "recall", project: "demo", ids: ["too-old"], tokens: 0, ms: 0 }, new Date("2020-01-01"));
  logUse(root, { kind: "recall", project: "demo", ids: ["future"], tokens: 0, ms: 0 }, new Date("2030-01-01"));
  expect([...noteUsage(root, 30, now).notes]).toEqual([["n-used", { recalled: 1, opened: 1, carded: 1, fired: 1, last: "2026-10-04T00:00:00Z" }]]);
  expect(noteUsage(join(root, "missing"), 30, now).notes.size).toBe(0);
});

it("CLI tidy suggests the right retire direction, shows lexical fallback, and never writes notes", async () => {
  const root = home();
  const old = createNote(root, { project: "demo", text: "Unique CLI quartz migration ascending" });
  saveNote(root, { ...old, at: "2000-01-01" });
  const fresh = createNote(root, { project: "demo", text: "Unique CLI quartz migration descending" });
  const backup = createNote(root, { project: "demo", text: "Unique CLI database backup deployment" });
  saveNote(root, { ...backup, at: "2000-01-01" });
  const newBackup = createNote(root, { project: "demo", text: "Unique CLI database backup deployment always" });
  const paths = loadNotes(root).notes.map(n => n.path);
  const before = paths.map(path => readFileSync(path, "utf8"));
  vi.stubGlobal("fetch", async (_url: unknown, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    const answers: Record<string, { noul: number }> = {};
    for (const [i, pair] of (body.state.pairs as { a: string; b: string }[]).entries()) {
      answers["same_" + i] = { noul: pair.a.includes("backup") && pair.b.includes("backup") ? 0.9 : 0.1 };
      answers["contradicts_" + i] = { noul: pair.a.includes("ascending") && pair.b.includes("descending") ? 0.9 : 0.1 };
    }
    return new Response(JSON.stringify({ answers }));
  });
  const judged = await cli(root, ["tidy"], { TYPESAFE_API_KEY: "synthetic-tidy-cli" });
  expect(judged).toContain("Contradictions");
  expect(judged).toContain(`brain retire ${old.id} --by ${fresh.id}`);
  expect(judged).toContain("Duplicates");
  expect(judged).toContain(`brain retire ${backup.id} --by ${newBackup.id}`);
  expect(await cli(root, ["tidy"])).toContain("Similar (no judge)");
  expect(paths.map(path => readFileSync(path, "utf8"))).toEqual(before);
  expect(await cli(home(), ["tidy"])).toBe("nothing to tidy");
});

it("CLI and tool create replies append hints, but upgrades, private notes and subagents do not judge", async () => {
  const root = home();
  const old = createNote(root, { project: "demo", text: "Unique writehint quartz migration ascending" });
  const fetch = vi.fn(async () => new Response(JSON.stringify({ answers: { same_0: { noul: 0.1 }, contradicts_0: { noul: 0.9 } } })));
  vi.stubGlobal("fetch", fetch);
  const env = { BRAIN_PROJECT: "demo", TYPESAFE_API_KEY: "synthetic-writehint" };
  expect(await cli(root, ["note", "Unique writehint quartz migration descending"], env)).toContain(`contradicts ${old.id}`);
  fetch.mockClear();
  expect(await cli(root, ["note", "Unique writehint quartz migration descending"], env)).toContain("already noted");
  expect(await cli(root, ["note", "Unique writehint quartz private migration", "--private"], env)).not.toContain("contradicts");
  expect(fetch).not.toHaveBeenCalled();
  const tool = brainTools.find(t => t.name === "brain_note")!;
  const context = { home: root, cwd: root, env, sub: true, session: undefined };
  expect((await tool.run({ text: "Unique writehint quartz migration child" }, context)).text).not.toContain("contradicts");
  expect(fetch).not.toHaveBeenCalled();
  const toolRoot = home();
  const toolOld = createNote(toolRoot, { project: "demo", text: "Unique toolhint quartz migration ascending" });
  expect((await tool.run({ text: "Unique toolhint quartz migration descending" }, { ...context, home: toolRoot, cwd: toolRoot, sub: false })).text).toContain(`contradicts ${toolOld.id}`);
});

it("stats includes all-home active note usage and CLI cards record only shown ids", async () => {
  const root = home();
  const shown = createNote(root, { project: "demo", text: "Quartz card guidance" });
  createNote(root, { project: "other", text: "Other project advice" });
  const preview = await cli(root, ["card"]);
  expect(cardIds(preview)).toEqual([shown.id]);
  expect(noteUsage(root).notes.get(shown.id)?.carded).toBe(1);
  // Telemetry that reaches back past the window: the answer holds for all 30 days.
  logUse(root, { kind: "recall", project: "demo", ids: [], tokens: 0, ms: 0 }, new Date(Date.now() - 40 * 86_400_000));
  expect(await cli(root, ["stats", "--days", "30"])).toContain("notes used (30d): 1 of 2 active · never: 1 (brain tidy)");
});


it("tidy all expands project scope while tagged globals and usage windows keep their boundaries", async () => {
  const root = home();
  const notes = [note("old", "Local unrelated advice", { at: "2000-01-01" }), note("remote", "Remote unrelated advice", { at: "2000-01-01", project: "other" }), note("tagged", "Tagged unrelated advice", { at: "2000-01-01", project: "global", tags: ["python"] })];
  logUse(root, { kind: "recall", project: "demo", query: "advice", ids: ["old"], tokens: 0, ms: 0 }, new Date(Date.now() - 10 * 86_400_000));
  expect((await tidyReport(root, notes, project)).unused.map(n => n.id)).toEqual([]);
  expect((await tidyReport(root, notes, project, { all: true })).unused.map(n => n.id)).toEqual(["remote", "tagged"]);
  expect((await tidyReport(root, notes, project, { days: 7 })).unused.map(n => n.id)).toEqual(["old"]);
});

it("tidy preserves lexical suggestions when a judge throws, returns undefined or incomplete scores", async () => {
  const root = home();
  const notes = [note("left"), note("right")];
  const lexical = await tidyReport(root, notes, project);
  for (const judge of [async () => { throw new Error("offline"); }, async () => undefined, async () => new Map()]) {
    expect(await tidyReport(root, notes, project, { judge })).toEqual(lexical);
  }
});

describe("usage windows follow the telemetry that is retained", () => {
  const DAY = 86_400_000;
  const daysAgo = (days: number) => new Date(Date.now() - days * DAY);
  const day = (date: Date) => date.toISOString().slice(0, 10);
  const old = (id: string, over: Partial<Note> = {}) => note(id, `Unique ${id} advice`, { at: "2000-01-01", ...over });

  it("does not call a note unused for days the oldest retained row does not reach", async () => {
    const root = home();
    // Rotation kept ten days of rows: a note used 20 days ago is simply absent from them.
    const start = daysAgo(10);
    logUse(root, { kind: "recall", project: "demo", ids: ["used-lately"], tokens: 0, ms: 0 }, daysAgo(5));
    logUse(root, { kind: "card", project: "demo", ids: ["young"], tokens: 0, ms: 0 }, start);
    const notes = [old("never"), old("used-lately"), old("used-20-days-ago"), note("young")];
    const report = await tidyReport(root, notes, project);
    expect(report.unusedWindow).toContain("10d");
    expect(report.unusedWindow).toContain(day(start));
    expect(report.unusedWindow).not.toMatch(/^30d/);
    expect(report.unused.map(n => n.id)).toEqual(["never", "used-20-days-ago"]);
    // A window inside the covered days is answered as asked.
    expect((await tidyReport(root, notes, project, { days: 7 })).unusedWindow).toBe("7d");
  });

  it("holds for the full ask once the rows reach back past it, and judges nothing without rows", async () => {
    const covered = home();
    logUse(covered, { kind: "card", project: "demo", ids: ["other"], tokens: 0, ms: 0 }, daysAgo(40));
    expect((await tidyReport(covered, [old("never")], project)).unusedWindow).toBe("30d");
    const empty = home();
    const none = await tidyReport(empty, [old("never")], project);
    expect(none.unused).toEqual([]);
    expect(none.unusedWindow).toContain("no telemetry");
  });

  it("brain tidy and brain stats print the window the rows cover", async () => {
    const root = home();
    const start = daysAgo(10);
    const never = createNote(root, { project: "demo", text: "Unique CLI never used guidance" });
    saveNote(root, { ...never, at: "2000-01-01" });
    logUse(root, { kind: "card", project: "demo", ids: ["elsewhere"], tokens: 0, ms: 0 }, start);
    const tidy = await cli(root, ["tidy"]);
    expect(tidy).toContain(never.id);
    expect(tidy).toContain("10d");
    expect(tidy).toContain(day(start));
    expect(tidy).not.toContain("Unused 30d");
    const stats = (await cli(root, ["stats", "--days", "30"])).split("\n").find(line => line.startsWith("notes used"))!;
    expect(stats).toContain(day(start));
    expect(stats).toContain("never: 1");
  });
});
