import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { judgedAnswer, type Judge } from "../src/judge.ts";
import { answerWithHits } from "../src/search.ts";
import type { Note } from "../src/notes.ts";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const home = mkdtempSync(join(tmpdir(), "brain-recall-gate-"));
  roots.push(home);
  mkdirSync(join(home, "docs"));
  writeFileSync(join(home, "docs/PLAN.md"), "## Quartz migration\nOrder the quartz migration steps.\n");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { test: { docs: ["docs/PLAN.md"] } } }));
  const project = { id: "test", tags: [], root: home };
  const note: Note = { id: "n-1234567890", project: "test", kind: "note", private: false, at: "2026-09-28", source: "agent", tags: [], errors: [], evidence: [], tested: false, body: "Quartz migration guidance", path: "" };
  return { home, project, note };
}

it.each([0.1, 0.9, undefined])("judges the conditional fallback in one request and preserves its verdict (%s)", async probability => {
  const { note, ...opts } = fixture();
  const judge = vi.fn<Judge>(async (_query, candidates) => new Map(candidates.flatMap(c => c.id.startsWith("doc:") ? probability === undefined ? [] : [[c.id, probability]] : [[c.id, 0.1]])));
  const result = await judgedAnswer([note], "quartz migration steps", opts, judge);
  expect(result.ids).toEqual(probability === 0.1 ? [] : ["doc:docs/PLAN.md"]);
  expect(result.dropped).toBe(probability === 0.1 ? 2 : 1);
  expect(judge).toHaveBeenCalledTimes(1);
});

it("never replaces a surviving note with the conditional document", async () => {
  const { note, ...opts } = fixture();
  const judge: Judge = async (_query, candidates) => new Map(candidates.map(c => [c.id, 0.9]));
  expect((await judgedAnswer([note], "quartz migration steps", opts, judge)).ids).toEqual([note.id]);
});

it("keeps lexical output on failed batches and sends no private note or unreachable fallback", async () => {
  const { note, ...opts } = fixture();
  const failed = vi.fn<Judge>(async () => undefined);
  expect(await judgedAnswer([note], "quartz migration steps", opts, failed)).toMatchObject(answerWithHits([note], "quartz migration steps", opts));
  const privateNote = { ...note, id: "private", private: true };
  const reject = vi.fn<Judge>(async (_query, candidates) => new Map(candidates.map(c => [c.id, 0.1])));
  expect((await judgedAnswer([note, privateNote], "quartz migration steps", opts, reject)).ids).toEqual(["private"]);
  expect(reject.mock.calls[0]![1].map(c => c.id)).toEqual([note.id]);
});
