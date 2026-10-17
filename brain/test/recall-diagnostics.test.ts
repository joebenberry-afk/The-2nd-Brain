import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { judgedAnswer, recallFor, recallJudge } from "../src/judge.ts";
import type { Note } from "../src/notes.ts";
import { toraScorer } from "../src/tora.ts";

const roots: string[] = [];
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const project = { id: "demo", tags: [], root: null };
const note: Note = { id: "n-public", project: "demo", private: false, body: "Quartz migration guidance", kind: "note", at: "2026-10-01", source: "user", tags: [], errors: [], evidence: [], tested: false, path: "" };
function environment() {
  const home = mkdtempSync(join(tmpdir(), "brain-recall-deadline-")); roots.push(home);
  const dir = join(home, "tora", "sessions"); mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${process.pid}.json`), JSON.stringify({ pid: process.pid, port: 12345, token: home, started: new Date().toISOString() }));
  return { LOCALAPPDATA: home, BRAIN_JUDGE: "tora" };
}

it("caps an unresponsive local judge and cools down only that session route", async () => {
  const env = environment();
  // Platform AbortSignal.timeout uses Node's internal clock, not Vitest's fake timers.
  const fetcher = vi.fn(async (_url: unknown, init: RequestInit) => {
    const { promise, reject } = Promise.withResolvers<Response>();
    init.signal!.addEventListener("abort", () => reject(init.signal!.reason), { once: true });
    return promise;
  });
  vi.stubGlobal("fetch", fetcher);
  const started = performance.now();
  const first = await judgedAnswer([note], "quartz migration", { project }, recallJudge(env), undefined, true);
  const elapsed = performance.now() - started;
  expect(elapsed).toBeGreaterThan(700); expect(elapsed).toBeLessThan(1400);
  expect(first.ids).toEqual([note.id]); expect(first.judged).toBe(false);
  expect(first.recall?.local).toMatchObject([{ route: "/judge", outcome: "timeout" }]);
  const second = await judgedAnswer([note], "quartz migration", { project }, recallJudge(env), undefined, true);
  expect(second.recall?.local).toMatchObject([{ outcome: "cooldown" }]); expect(fetcher).toHaveBeenCalledTimes(1);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ scores: { [note.id]: 1 } }))));
  expect(await toraScorer(env)!("quartz", [{ id: note.id, text: note.body }])).toBeDefined();
  const next = environment();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ scores: { [note.id]: 1 } }))));
  expect((await judgedAnswer([note], "quartz migration", { project }, recallJudge(next), undefined, true)).judged).toBe(true);
});

it("records scope and corpus changes without private content or ids", async () => {
  const privateNote = { ...note, id: "private-id", private: true, body: "private-sensitive-text" };
  const first = await judgedAnswer([note, privateNote], "quartz", { project }, undefined, undefined, true);
  const edited = await judgedAnswer([{ ...note, body: note.body + " updated" }, privateNote], "quartz", { project, all: true }, undefined, undefined, true);
  const tagged = await judgedAnswer([note], "quartz", { project: { ...project, tags: ["new"] } }, undefined, undefined, true);
  expect(first.recall?.corpus).not.toBe(edited.recall?.corpus);
  expect(first.recall?.scope).not.toBe(tagged.recall?.scope);
  expect(edited.recall?.all).toBe(true);
  expect(JSON.stringify(first.recall)).not.toMatch(/private-id|private-sensitive-text|Quartz/);
});

it("records lexical rejection ids while keeping verdict failure asymmetric", async () => {
  const rejected = await judgedAnswer([note], "quartz migration", { project }, async () => new Map([[note.id, 0]]), undefined, true);
  expect(rejected.recall?.stages).toContainEqual([note.id, "judge-drop"]);
  expect(rejected.ids).toEqual([]);
  const failed = await judgedAnswer([note], "quartz migration", { project }, async () => undefined, undefined, true);
  expect(failed.ids).toEqual([note.id]);
});

it("a shortened or exhausted shared deadline never cools down the next recall", async () => {
  const env = environment();
  let clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  const timeout = vi.spyOn(AbortSignal, "timeout");
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("/score")) {
      clock += 790;
      return new Response(JSON.stringify({ scores: { [note.id]: 0.9 } }));
    }
    throw new DOMException("synthetic timeout", "TimeoutError");
  });
  vi.stubGlobal("fetch", fetcher);
  const first = recallJudge(env)!;
  await first.scorer!("q", [{ id: note.id, text: note.body }]);
  expect(await first("q", [{ id: note.id, text: note.body }])).toBeUndefined();
  expect(timeout.mock.calls.map(([ms]) => ms)).toEqual([800, 10]);
  clock += 20;
  await first("q", [{ id: note.id, text: note.body }]);
  expect(first.attempts?.at(-1)).toEqual({ route: "/judge", outcome: "timeout", ms: 0 });
  const healthy = vi.fn(async () => new Response(JSON.stringify({ scores: { [note.id]: 1 } })));
  vi.stubGlobal("fetch", healthy);
  expect((await recallJudge(env)!("q", [{ id: note.id, text: note.body }]))?.by).toBe("tora");
  expect(healthy).toHaveBeenCalledTimes(1);
});

it("shared recall wiring reports missing sessions only when local judging is enabled", async () => {
  const env = environment();
  const absent = { ...env, LOCALAPPDATA: join(env.LOCALAPPDATA, "absent") };
  const result = await recallFor([note], "quartz migration", { project }, absent);
  expect(result.ids).toEqual([note.id]);
  expect(result.recall?.local).toEqual([{ route: "/judge", outcome: "no-session", ms: 0 }]);
  for (const override of [{ BRAIN_TORA: "off" }, { BRAIN_JUDGE: "off" }, { BRAIN_JUDGE: "jev" }]) {
    expect((await recallFor([note], "quartz migration", { project }, { ...absent, ...override })).recall?.local).toEqual([]);
  }
});
