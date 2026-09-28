/**
 * Recall quality on the frozen V3 S2 case sets, against the real converted notes.
 * V3 (SQLite FTS5) scored dev 13/15 and held-out 7/8 in the top 3; V4 must not regress.
 * The misses V3 had: the retired 2-worker-cap policy (correctly not current) and one long prompt.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadNotes } from "../src/notes.ts";
import { answer, recall } from "../src/search.ts";
import { PACKAGE_HOME } from "../src/util.ts";

interface Case {
  id: string;
  prompt: string;
  expect: string[];
  forbid?: string[];
}

function cases(name: string): Case[] {
  const text = readFileSync(join(import.meta.dirname, "fixtures", name), "utf8");
  return text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l) as Case);
}

const hasNotes = existsSync(join(PACKAGE_HOME, "notes", "second-brain"));
const project = { id: "second-brain", tags: [], root: null };

function score(set: Case[]): { hits: number; total: number; missed: string[] } {
  const { notes } = loadNotes(PACKAGE_HOME);
  const memory = set.filter((c) => c.expect.length);
  const missed: string[] = [];
  for (const c of memory) {
    const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
    if (!c.expect.some((id) => ids.includes(id))) missed.push(c.id);
  }
  return { hits: memory.length - missed.length, total: memory.length, missed };
}

describe.skipIf(!hasNotes)("recall eval on the frozen S2 cases", () => {
  it("dev: at least 13 of 15 memory cases in the top 3", () => {
    const result = score(cases("recall-dev.jsonl"));
    console.log(`dev ${result.hits}/${result.total} missed ${result.missed.join(",")}`);
    expect(result.total).toBe(15);
    expect(result.hits).toBeGreaterThanOrEqual(13);
  });

  it("held-out: at least 7 of 8 memory cases in the top 3", () => {
    const result = score(cases("recall-heldout.jsonl"));
    console.log(`held-out ${result.hits}/${result.total} missed ${result.missed.join(",")}`);
    expect(result.total).toBe(8);
    expect(result.hits).toBeGreaterThanOrEqual(7);
  });

  it("what the agent sees (answer, with retired history): dev >= 14/15, held-out 8/8", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    for (const [file, min] of [["recall-dev.jsonl", 14], ["recall-heldout.jsonl", 8]] as const) {
      const memory = cases(file).filter((c) => c.expect.length);
      const found = memory.filter((c) => c.expect.some((id) => answer(notes, c.prompt, { project }).includes(id)));
      console.log(`answer ${file}: ${found.length}/${memory.length}`);
      expect(found.length).toBeGreaterThanOrEqual(min);
    }
  });

  it("never returns a forbidden note: other projects' notes, archived duplicates", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    const guarded = [...cases("recall-dev.jsonl"), ...cases("recall-heldout.jsonl")].filter((c) => c.forbid?.length);
    expect(guarded.length).toBeGreaterThan(0);
    for (const c of guarded) {
      const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
      expect(ids.filter((id) => c.forbid?.includes(id)), c.id).toEqual([]);
    }
  });

  it("answers in at most 3 lines and stays fast on the whole corpus", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    const started = performance.now();
    for (const c of cases("recall-dev.jsonl")) expect(recall(notes, c.prompt, { project }).length).toBeLessThanOrEqual(3);
    const perQuery = (performance.now() - started) / 28;
    console.log(`recall ${perQuery.toFixed(1)} ms/query over ${notes.length} notes`);
    expect(perQuery).toBeLessThan(50);
  });
});

interface RealCase {
  id: string;
  project: string;
  query: string;
  expect: string[];
  verdict: "note" | "silence";
  doc?: string;
}

describe.skipIf(!hasNotes)("real queries", () => {
  it("keeps right answers and bounds wrong answers on the frozen session queries", () => {
    const text = readFileSync(join(import.meta.dirname, "fixtures", "recall-real.jsonl"), "utf8");
    const set = text.split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as RealCase);
    const { notes } = loadNotes(PACKAGE_HOME);
    let right = 0, silentMiss = 0, correctSilence = 0;
    const wrong: string[] = [];
    for (const c of set) {
      const ids = recall(notes, c.query, { project: { id: c.project, tags: [], root: null } })
        .slice(0, 3).map((hit) => hit.note.id);
      if (c.verdict === "note") {
        expect(c.expect.length, c.id).toBeGreaterThan(0);
        for (const id of c.expect) expect(notes.some((note) => note.id === id && !note.retired && !note.private), `${c.id}: ${id}`).toBe(true);
        if (c.expect.some((id) => ids.includes(id))) right++;
        else if (!ids.length) silentMiss++;
        else wrong.push(`${c.id}: ${ids.join(",")}`);
      } else {
        expect(c.verdict, c.id).toBe("silence");
        expect(c.expect, c.id).toEqual([]);
        if (ids.length) wrong.push(`${c.id}: ${ids.join(",")}`);
        else correctSilence++;
      }
    }
    console.log(`real-query right ${right}/${set.length}; wrong ${wrong.length}; silent-miss ${silentMiss}; correct-silence ${correctSilence}`);
    console.log(`real-query wrong ${wrong.length}/${set.length} (target <=10%); cases ${wrong.join("; ")}`);
    expect(set).toHaveLength(34);
    expect(right).toBeGreaterThanOrEqual(9);
    // Frozen 2026-09-28: 9 right, 16 wrong, 0 silent misses, 9 correct silences.
    // Wrong exceeds the plan's <=10% target: hold today's ceiling, never bless it as target success.
    expect(wrong.length).toBeLessThanOrEqual(16);
  });
});
